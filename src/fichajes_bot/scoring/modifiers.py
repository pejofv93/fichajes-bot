"""Scoring modifiers — multipliers applied after combining base components.

Each modifier returns a factor in (0, ∞):
  > 1.0  → amplify score (positive signal)
  < 1.0  → reduce score (negative / uncertain signal)
  = 1.0  → neutral (no data or not yet implemented)

Session 6 activates: factor_economico, factor_substitucion, factor_temporal_modifier.
Session 7 activates: factor_sesgo, factor_globo_sonda, factor_retractacion.

Validator/detector instances are cached per-run (keyed by db object id) so the
substitution graph and bias fuente cache are only built once per batch.
"""

from __future__ import annotations

from typing import Any

from loguru import logger

from fichajes_bot.persistence.d1_client import D1Client

# ── Per-run instance cache ────────────────────────────────────────────────────
# Cleared automatically when a new D1Client instance is detected.

_run_cache: dict = {}   # {"db_id": int, "validators": {...}}


def _validators_for(db: D1Client) -> dict:
    """Return (or create) cached validator/detector instances for this batch run."""
    key = id(db)
    if _run_cache.get("db_id") != key:
        _run_cache.clear()
        from fichajes_bot.validators.economic import EconomicValidator
        from fichajes_bot.validators.substitution import SubstitutionEngine
        from fichajes_bot.validators.temporal import TemporalValidator
        from fichajes_bot.detectors.bias_corrector import BiasCorrector
        from fichajes_bot.detectors.trial_balloon import TrialBalloonDetector
        from fichajes_bot.detectors.retraction_handler import RetractionHandler
        _run_cache["db_id"] = key
        _run_cache["validators"] = {
            "economic":     EconomicValidator(db),
            "substitution": SubstitutionEngine(db),
            "temporal":     TemporalValidator(db),
            "bias":         BiasCorrector(db),
            "trial_balloon": TrialBalloonDetector(db),
            "retraction":   RetractionHandler(db),
        }
    return _run_cache["validators"]


# ── Individual modifier functions ─────────────────────────────────────────────


async def factor_economico(
    jugador_id: str,
    score_raw: float,
    db: D1Client,
) -> float:
    """Economic viability factor via EconomicValidator. Returns 1.0 if no model."""
    v = _validators_for(db)
    return await v["economic"].evaluate(jugador_id)


async def factor_substitucion(
    jugador_id: str,
    score_raw: float,
    db: D1Client,
) -> float:
    """Substitution-graph factor. Returns 1.0 if player/position data is missing."""
    v = _validators_for(db)
    return await v["substitution"].evaluate(jugador_id)


async def factor_temporal_modifier(
    jugador_id: str,
    rumores: list[dict[str, Any]],
    score_raw: float,
    db: D1Client,
) -> float:
    """Market-window timing factor via TemporalValidator."""
    v = _validators_for(db)
    temporal = v["temporal"]
    rumor = rumores[0] if rumores else {}
    rows = await db.execute(
        "SELECT flags FROM jugadores WHERE jugador_id=? LIMIT 1",
        [jugador_id],
    )
    jugador = rows[0] if rows else {}
    return temporal.evaluate(rumor, jugador)


async def factor_sesgo(
    rumores: list[dict[str, Any]],
    score_raw: float,
    db: D1Client,
) -> float:
    """Media bias correction via BiasCorrector.

    Weighted mean across all active rumores (weight = peso_lexico).
    Returns 1.0 when no source information is available.
    """
    v = _validators_for(db)
    return await v["bias"].evaluate_batch(rumores)


async def factor_globo_sonda(
    rumores: list[dict[str, Any]],
    score_raw: float,
    db: D1Client,
) -> float:
    """Trial balloon detection via TrialBalloonDetector.

    If probabilidad_globo >= 0.50 → reduce score by 15%.
    If probabilidad_globo >= 0.75 → reduce score by 30%.
    """
    v = _validators_for(db)
    detector = v["trial_balloon"]

    # Use jugador_id from first rumor
    jugador_id = rumores[0].get("jugador_id") if rumores else None
    if not jugador_id:
        return 1.0

    prob, _ = await detector.evaluate(jugador_id, rumores)

    if prob >= 0.75:
        return 0.70
    if prob >= 0.50:
        return 0.85
    return 1.0


async def factor_retractacion(
    jugador_id: str,
    rumores: list[dict[str, Any]],
    score_raw: float,
    db: D1Client,
) -> float:
    """Retraction factor via RetractionHandler.

    Penalises players whose rumors have been retracted recently.
    """
    v = _validators_for(db)
    return await v["retraction"].evaluate(jugador_id)


# ── Orchestrator ──────────────────────────────────────────────────────────────


async def apply_modifiers(
    jugador_id: str,
    rumores: list[dict[str, Any]],
    score_raw: float,
    db: D1Client,
) -> tuple[float, dict[str, float]]:
    """Apply all six modifiers and return (score_modified, factors_dict).

    The factors_dict is stored in jugadores.factores_actuales for transparency
    and surfaced in the /explain Telegram command.
    """
    f_econ         = await factor_economico(jugador_id, score_raw, db)
    f_subst        = await factor_substitucion(jugador_id, score_raw, db)
    f_temporal_mod = await factor_temporal_modifier(jugador_id, rumores, score_raw, db)
    f_sesgo        = await factor_sesgo(rumores, score_raw, db)
    f_globo        = await factor_globo_sonda(rumores, score_raw, db)
    f_retr         = await factor_retractacion(jugador_id, rumores, score_raw, db)

    combined = f_econ * f_subst * f_temporal_mod * f_sesgo * f_globo * f_retr
    score_modified = max(0.01, min(0.99, score_raw * combined))

    factors: dict[str, float] = {
        "factor_econ":         round(f_econ, 4),
        "factor_subst":        round(f_subst, 4),
        "factor_temporal_mod": round(f_temporal_mod, 4),
        "factor_sesgo":        round(f_sesgo, 4),
        "factor_globo":        round(f_globo, 4),
        "factor_retr":         round(f_retr, 4),
        "combined":            round(combined, 4),
    }

    if combined != 1.0:
        logger.debug(
            f"apply_modifiers({jugador_id[:8]}): {score_raw:.3f} × {combined:.3f} = "
            f"{score_modified:.3f} [econ={f_econ:.2f} subst={f_subst:.2f} "
            f"temp={f_temporal_mod:.2f} sesgo={f_sesgo:.2f} "
            f"globo={f_globo:.2f} retr={f_retr:.2f}]"
        )

    return score_modified, factors
