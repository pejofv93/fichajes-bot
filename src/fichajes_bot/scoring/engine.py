"""Scoring engine — orchestrates components → modifiers → Kalman → persist.

Entry point: recompute_score(jugador_id, db, reliability_manager)

Steps:
  1. Load rumores activos for jugador (last WINDOW_DAYS, non-retracted)
  2. Compute four components (components.py)
  3. Combine into score_raw (score_base.py)
  4. Apply modifiers (modifiers.py — hooks for Sessions 6-7)
  5. Kalman update → score_smoothed
  6. Persist: UPDATE jugadores + INSERT score_history
  7. Mark eventos_pending as processed
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any

from loguru import logger

from fichajes_bot.calibration.reliability_manager import ReliabilityManager
from fichajes_bot.persistence.d1_client import D1Client
from fichajes_bot.scoring.components import (
    compute_consenso,
    compute_credibilidad,
    compute_factor_temporal,
    compute_fase_dominante,
    compute_mean_credibility_from_rumores,
)
from fichajes_bot.scoring.kalman import KalmanFilter1D, KalmanState, state_from_db
from fichajes_bot.scoring.modifiers import apply_modifiers
from fichajes_bot.scoring.score_base import ScoreComponents, combine_components, explain_components

WINDOW_DAYS = 60       # only consider rumores from last N days
MIN_RUMORES = 1        # minimum rumores to compute a score

# Global Kalman instance (parameters can be overridden from configs/scoring.yaml)
_kalman = KalmanFilter1D()


async def recompute_score(
    jugador_id: str,
    db: D1Client,
    reliability_manager: ReliabilityManager,
) -> dict[str, Any] | None:
    """Recompute score for one jugador. Returns result dict or None if skipped.

    Result dict:
        score_raw, score_smoothed, delta, components, factors, razon, explicacion
    """
    # ── 1. Load rumores ──────────────────────────────────────────────────────
    rumores = await db.execute(
        """SELECT r.*, p.reliability_global
           FROM rumores r
           LEFT JOIN periodistas p ON r.periodista_id = p.periodista_id
           WHERE r.jugador_id = ?
             AND r.retractado = 0
             AND (r.fecha_publicacion IS NULL
                  OR r.fecha_publicacion >= datetime('now', ? || ' days'))
           ORDER BY r.fecha_publicacion DESC""",
        [jugador_id, f"-{WINDOW_DAYS}"],
    )

    if len(rumores) < MIN_RUMORES:
        logger.debug(f"score: skip {jugador_id[:8]} — {len(rumores)} rumores")
        return None

    # ── 2. Load current jugador state ────────────────────────────────────────
    rows = await db.execute(
        "SELECT * FROM jugadores WHERE jugador_id=? LIMIT 1", [jugador_id]
    )
    if not rows:
        logger.warning(f"score: jugador not found: {jugador_id}")
        return None

    jugador = rows[0]
    prev_smoothed = float(jugador.get("score_smoothed") or 0.0)
    kalman_state = state_from_db(
        jugador.get("score_smoothed"), jugador.get("kalman_P")
    )

    # ── 3. Detect hard signals ────────────────────────────────────────────────
    hard_signal = _detect_hard_signal(rumores)

    # ── 4. Compute components ─────────────────────────────────────────────────
    consenso = compute_consenso(rumores)
    credibilidad = await compute_credibilidad(rumores, reliability_manager)
    fase = await compute_fase_dominante(rumores, reliability_manager)
    temporal = compute_factor_temporal(rumores)

    components = ScoreComponents(
        consenso=consenso,
        credibilidad=credibilidad,
        fase=fase,
        temporal=temporal,
    )

    # ── 5. Combine → score_raw ────────────────────────────────────────────────
    score_raw = combine_components(components)

    # ── 6. Apply modifiers (hooks for Sessions 6-7) ───────────────────────────
    score_modified, factors = await apply_modifiers(jugador_id, rumores, score_raw, db)

    # Attach component details to factors dict for factores_actuales JSON
    factors.update({
        "consenso":          round(consenso, 4),
        "credibilidad":      round(credibilidad, 4),
        "fase_dominante":    round(fase, 3),
        "factor_temporal":   round(temporal, 4),
        "n_rumores":         len(rumores),
        "hard_signal":       hard_signal,
    })

    # ── 7. Kalman update → score_smoothed ─────────────────────────────────────
    cred_media = compute_mean_credibility_from_rumores(rumores)
    new_state = _kalman.update(
        state=kalman_state,
        observation=score_modified,
        credibilidad_media=cred_media,
        hard_signal=hard_signal,
    )
    score_smoothed = new_state.x

    # ── 8. Build explanation ──────────────────────────────────────────────────
    delta = round(score_smoothed - prev_smoothed, 6)
    razon = _build_razon(components, delta, hard_signal, len(rumores))
    explicacion = explain_components(components)

    # ── 9. Persist ────────────────────────────────────────────────────────────
    await _persist_score(
        db=db,
        jugador=jugador,
        score_raw=score_raw,
        score_smoothed=score_smoothed,
        kalman_P=new_state.P,
        factors=factors,
        fase_int=max(1, min(6, round(fase))),
        delta=delta,
        razon=razon,
        explicacion=explicacion,
    )

    logger.info(
        f"score: {jugador.get('nombre_canonico','?')[:20]} "
        f"raw={score_raw:.3f} smooth={score_smoothed:.3f} "
        f"Δ={delta:+.3f} fase={fase:.1f} cred={credibilidad:.2f}"
    )

    return {
        "jugador_id":     jugador_id,
        "score_raw":      score_raw,
        "score_smoothed": score_smoothed,
        "delta":          delta,
        "components":     components._asdict(),
        "factors":        factors,
        "razon":          razon,
        "explicacion":    explicacion,
    }


# ── Internal helpers ──────────────────────────────────────────────────────────

def _detect_hard_signal(rumores: list[dict]) -> bool:
    """Return True if any rumor represents a confirmed transfer / retraction."""
    for r in rumores:
        flags = json.loads(r.get("flags") or "[]") if isinstance(r.get("flags"), str) else []
        if "FICHAJE_OFICIAL" in flags or "RETRACTACION_OFICIAL" in flags:
            return True
        # Phase 6 from a high-credibility source is a hard signal
        if int(r.get("fase_rumor") or 0) == 6 and float(r.get("reliability_global") or 0) > 0.80:
            return True
    return False


def _build_razon(
    components: ScoreComponents,
    delta: float,
    hard_signal: bool,
    n_rumores: int,
) -> str:
    """Short machine-readable reason tag for score_history."""
    if hard_signal:
        return "HARD_SIGNAL"
    if delta > 0.10:
        return "SCORE_UP_SIGNIFICANT"
    if delta < -0.10:
        return "SCORE_DOWN_SIGNIFICANT"
    if components.fase >= 5:
        return "HIGH_PHASE_SIGNAL"
    if n_rumores >= 5:
        return "MULTI_SOURCE_CONSENSUS"
    return "ROUTINE_UPDATE"


async def _persist_score(
    db: D1Client,
    jugador: dict,
    score_raw: float,
    score_smoothed: float,
    kalman_P: float,
    factors: dict,
    fase_int: int,
    delta: float,
    razon: str,
    explicacion: str,
) -> None:
    jugador_id = jugador["jugador_id"]
    prev_smoothed = float(jugador.get("score_smoothed") or 0.0)

    # Update jugadores
    await db.execute(
        """UPDATE jugadores SET
             score_raw = ?,
             score_smoothed = ?,
             score_anterior = ?,
             kalman_P = ?,
             factores_actuales = ?,
             fase_dominante = ?,
             ultima_actualizacion_at = datetime('now')
           WHERE jugador_id = ?""",
        [
            round(score_raw, 6),
            round(score_smoothed, 6),
            round(prev_smoothed, 6),
            round(kalman_P, 6),
            json.dumps(factors),
            fase_int,
            jugador_id,
        ],
    )

    # Insert score_history
    await db.execute(
        """INSERT INTO score_history
           (history_id, jugador_id, score_anterior, score_nuevo, delta,
            razon_cambio, explicacion_humana, factores_snapshot, timestamp)
           VALUES (?,?,?,?,?,?,?,?,datetime('now'))""",
        [
            str(uuid.uuid4()),
            jugador_id,
            round(prev_smoothed, 6),
            round(score_smoothed, 6),
            round(delta, 6),
            razon,
            explicacion,
            json.dumps(factors),
        ],
    )
