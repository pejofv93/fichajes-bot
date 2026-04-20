"""Scoring components — four base signals.

All functions are pure/async-pure: they receive data already fetched from D1.
They return floats in defined ranges for combination in score_base.py.

Components:
  1. consenso    → [-1, 1]   proportion of journalists aligned on tipo/club
  2. credibilidad → [0, 1]   reliability-weighted lexical strength
  3. fase_dominante → [1, 6] weighted dominant phase (higher = more advanced)
  4. factor_temporal → [0, 1] recency-based decay
"""

from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Any

from loguru import logger

# ── Temporal decay constants ─────────────────────────────────────────────────

_HALF_LIFE_DAYS = 14.0     # default; overridden by configs/temporal.yaml
_MIN_DECAY = 0.10
_LN2 = math.log(2)

# ── Phase signal values ───────────────────────────────────────────────────────

_PHASE_VALUE = {1: 0.10, 2: 0.20, 3: 0.35, 4: 0.55, 5: 0.80, 6: 0.98}


# ─────────────────────────────────────────────────────────────────────────────
# 1. CONSENSO
# ─────────────────────────────────────────────────────────────────────────────

def compute_consenso(rumores: list[dict[str, Any]]) -> float:
    """Agreement among journalists on tipo_operacion and club_destino.

    Counts non-retracted rumors grouped by (tipo_operacion, club_destino).
    Returns the dominance fraction minus a confusion penalty:
      - All agree (1 group):  → close to +1.0
      - Split 50/50:          → ~0.0
      - Contradictory signals:→ negative
    Range: [-1, 1]
    """
    active = [r for r in rumores if not r.get("retractado")]
    if not active:
        return 0.0

    n_total = len(active)

    # Group by (tipo_operacion, club_destino_normalized)
    groups: dict[tuple, int] = {}
    for r in active:
        tipo = r.get("tipo_operacion") or "UNKNOWN"
        club = (r.get("club_destino") or "").lower().strip() or "unknown"
        key = (tipo, club)
        groups[key] = groups.get(key, 0) + 1

    if not groups:
        return 0.0

    # Dominant group fraction
    max_count = max(groups.values())
    dominant_fraction = max_count / n_total

    # Penalty for multiple contradictory groups (entropy-like)
    n_groups = len(groups)
    confusion_penalty = (n_groups - 1) * 0.05  # each extra group = -0.05

    # Map dominant_fraction [0.5, 1.0] → consenso [0, 1], apply penalty
    consenso = (2 * dominant_fraction - 1.0) - confusion_penalty
    return max(-1.0, min(1.0, round(consenso, 4)))


# ─────────────────────────────────────────────────────────────────────────────
# 2. CREDIBILIDAD
# ─────────────────────────────────────────────────────────────────────────────

async def compute_credibilidad(
    rumores: list[dict[str, Any]],
    reliability_manager: Any,  # ReliabilityManager
) -> float:
    """Reliability-weighted lexical signal strength.

    For each rumor:
      - Fetch journalist reliability in context (club, tipo)
      - Weight = reliability * |peso_lexico|
    Returns weighted mean in [0, 1].
    """
    active = [r for r in rumores if not r.get("retractado")]
    if not active:
        return 0.0

    total_weight = 0.0
    weighted_signal = 0.0

    for r in active:
        periodista_id = r.get("periodista_id")
        if not periodista_id:
            # No journalist — use a default moderate reliability
            reliability = 0.50
        else:
            club = r.get("club_destino")
            tipo = r.get("tipo_operacion")
            est = await reliability_manager.get_reliability(
                periodista_id, context="rm", club=club, tipo=tipo
            )
            reliability = est.reliability

        peso_lexico = abs(float(r.get("peso_lexico") or 0.0))
        confianza = float(r.get("confianza_extraccion") or 0.0)

        # Signal = average of lexical weight and extraction confidence
        signal = (peso_lexico + confianza) / 2.0

        total_weight += reliability
        weighted_signal += reliability * signal

    if total_weight <= 0:
        return 0.0

    return min(1.0, round(weighted_signal / total_weight, 4))


# ─────────────────────────────────────────────────────────────────────────────
# 3. FASE DOMINANTE
# ─────────────────────────────────────────────────────────────────────────────

async def compute_fase_dominante(
    rumores: list[dict[str, Any]],
    reliability_manager: Any,
    half_life_days: float = _HALF_LIFE_DAYS,
) -> float:
    """Credibility × recency weighted phase (returns float in [1.0, 6.0]).

    High-credibility, recent, high-phase rumors dominate.
    A single Romano "here we go" (fase 6, credibility 0.92) beats 10 tier-B
    fase-2 rumors.
    """
    active = [r for r in rumores if not r.get("retractado") and r.get("fase_rumor")]
    if not active:
        return 1.0

    total_w = 0.0
    weighted_fase = 0.0

    for r in active:
        fase = int(r.get("fase_rumor") or 1)
        fase = max(1, min(6, fase))

        # Temporal weight
        t_weight = _temporal_weight(r.get("fecha_publicacion"), half_life_days)

        # Reliability weight
        periodista_id = r.get("periodista_id")
        if periodista_id:
            est = await reliability_manager.get_reliability(periodista_id, context="rm")
            r_weight = est.reliability
        else:
            r_weight = 0.40  # anonymous source, low weight

        w = t_weight * r_weight
        total_w += w
        weighted_fase += w * fase

    if total_w <= 0:
        return 1.0

    return round(weighted_fase / total_w, 3)


# ─────────────────────────────────────────────────────────────────────────────
# 4. FACTOR TEMPORAL
# ─────────────────────────────────────────────────────────────────────────────

def compute_factor_temporal(
    rumores: list[dict[str, Any]],
    half_life_days: float = _HALF_LIFE_DAYS,
    window_days: int = 60,
) -> float:
    """Aggregate recency factor for the rumor set.

    Returns the reliability-weighted average temporal decay across all active
    rumors. A single very recent rumor gives factor ≈ 1.0.
    """
    active = [r for r in rumores if not r.get("retractado")]
    if not active:
        return 0.0

    weights = [_temporal_weight(r.get("fecha_publicacion"), half_life_days) for r in active]
    if not any(w > 0 for w in weights):
        return 0.0

    # Average, but cap at 1.0 and floor at _MIN_DECAY
    avg = sum(weights) / len(weights)
    return round(max(_MIN_DECAY, min(1.0, avg)), 4)


# ─────────────────────────────────────────────────────────────────────────────
# Shared helpers
# ─────────────────────────────────────────────────────────────────────────────

def _temporal_weight(
    fecha_str: str | None,
    half_life_days: float = _HALF_LIFE_DAYS,
) -> float:
    """Exponential decay weight for a single rumor date.

    weight = max(MIN_DECAY, exp(-ln2 * dias / half_life))
    """
    if not fecha_str:
        return 0.50  # unknown date → medium weight

    try:
        dt = _parse_date(fecha_str)
        if dt is None:
            return 0.50

        now = datetime.now(timezone.utc)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)

        dias = max(0.0, (now - dt).total_seconds() / 86400.0)
        weight = math.exp(-_LN2 * dias / half_life_days)
        return max(_MIN_DECAY, min(1.0, weight))

    except Exception as exc:
        logger.debug(f"Temporal weight parse error for '{fecha_str}': {exc}")
        return 0.50


def _parse_date(fecha_str: str) -> datetime | None:
    """Parse a date string into a timezone-aware datetime."""
    s = fecha_str.strip()

    # Python 3.11+ fromisoformat handles +00:00 and Z
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        pass

    # RFC 2822 (RSS feeds): "Mon, 01 Jul 2024 10:00:00 +0000"
    import email.utils
    try:
        t = email.utils.parsedate_to_datetime(s)
        return t
    except Exception:
        pass

    # Fallback: strip to YYYY-MM-DD
    try:
        return datetime.strptime(s[:10], "%Y-%m-%d").replace(tzinfo=timezone.utc)
    except ValueError:
        pass

    return None


def compute_mean_credibility_from_rumores(
    rumores: list[dict[str, Any]],
) -> float:
    """Quick synchronous credibility estimate (uses confianza_extraccion only).

    Used by Kalman to set adaptive R without awaiting ReliabilityManager.
    """
    active = [r for r in rumores if not r.get("retractado")]
    if not active:
        return 0.50
    confianzas = [float(r.get("confianza_extraccion") or 0.5) for r in active]
    return round(sum(confianzas) / len(confianzas), 4)
