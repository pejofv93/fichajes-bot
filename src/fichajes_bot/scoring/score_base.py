"""score_base — combine four components into a raw score via sigmoid.

Formula (from configs/scoring.yaml):
  z = scale * (w1*consenso + w2*credibilidad + w3*(fase/6) + w4*temporal - 0.5)
  score_raw = 1 / (1 + exp(-z))

Why sigmoid?
  - Natural [0, 1] output.
  - Gradient around 0.5 is steep (sensitive to changes in the relevant range).
  - Saturates gracefully near 0 and 1 (prevents runaway extrapolation).
"""

from __future__ import annotations

import math
from typing import NamedTuple

# ── Default weights (overridden by configs/scoring.yaml if loaded) ────────────

_W_CONSENSO = 0.30
_W_CREDIBILIDAD = 0.35
_W_FASE = 0.25
_W_TEMPORAL = 0.10
_SCALE = 6.0

# Phase normalisation: the raw phase [1..6] is first converted to a 0..1 signal
# using a lookup (from components._PHASE_VALUE) or a simple 1/6 linear map.
_PHASE_MAX = 6.0

_PHASE_VALUE = {1: 0.10, 2: 0.20, 3: 0.35, 4: 0.55, 5: 0.80, 6: 0.98}


class ScoreComponents(NamedTuple):
    """Immutable snapshot of all four scoring components."""
    consenso:     float   # [-1, 1]
    credibilidad: float   # [0, 1]
    fase:         float   # [1.0, 6.0]  (weighted average phase)
    temporal:     float   # [0, 1]


def phase_to_signal(fase: float) -> float:
    """Map a weighted phase (1–6) to a normalised [0, 1] signal."""
    # Interpolate between the two bracketing integer phases
    lo = max(1, min(5, int(fase)))
    hi = lo + 1
    frac = fase - lo
    v_lo = _PHASE_VALUE.get(lo, lo / 6.0)
    v_hi = _PHASE_VALUE.get(hi, hi / 6.0)
    return v_lo + frac * (v_hi - v_lo)


def combine_components(
    components: ScoreComponents,
    w_consenso: float = _W_CONSENSO,
    w_credibilidad: float = _W_CREDIBILIDAD,
    w_fase: float = _W_FASE,
    w_temporal: float = _W_TEMPORAL,
    scale: float = _SCALE,
) -> float:
    """Combine four components into score_raw ∈ [0, 1] using sigmoid.

    Args:
        components:     ScoreComponents namedtuple
        w_*:            Component weights (should sum to ~1.0)
        scale:          Controls sigmoid steepness

    Returns:
        score_raw ∈ [0.01, 0.99]
    """
    fase_signal = phase_to_signal(components.fase)

    # Normalise consenso from [-1, 1] to [0, 1] for combination
    consenso_01 = (components.consenso + 1.0) / 2.0

    z = scale * (
        w_consenso     * consenso_01
        + w_credibilidad * components.credibilidad
        + w_fase         * fase_signal
        + w_temporal     * components.temporal
        - 0.5
    )

    score_raw = _sigmoid(z)
    # Hard floor/cap to avoid DBZ or certainty artefacts
    return round(max(0.01, min(0.99, score_raw)), 6)


def _sigmoid(x: float) -> float:
    """Numerically stable sigmoid."""
    if x >= 0:
        return 1.0 / (1.0 + math.exp(-x))
    exp_x = math.exp(x)
    return exp_x / (1.0 + exp_x)


def explain_components(components: ScoreComponents) -> str:
    """Human-readable explanation for score_history.explicacion_humana."""
    score_raw = combine_components(components)
    fase_int = round(components.fase)
    fase_names = {1: "interés inicial", 2: "contactos", 3: "negociaciones",
                  4: "acuerdo personal", 5: "acuerdo clubs", 6: "confirmado"}
    fase_desc = fase_names.get(fase_int, f"fase {fase_int}")

    parts = []
    if components.consenso >= 0.7:
        parts.append(f"consenso alto ({components.consenso:.0%})")
    elif components.consenso < 0.0:
        parts.append(f"señales contradictorias (consenso {components.consenso:.0%})")

    if components.credibilidad >= 0.75:
        parts.append(f"fuentes fiables (cred. {components.credibilidad:.0%})")
    elif components.credibilidad < 0.4:
        parts.append(f"fuentes poco fiables (cred. {components.credibilidad:.0%})")

    parts.append(f"{fase_desc}")

    if components.temporal < 0.3:
        parts.append("rumores antiguos")
    elif components.temporal > 0.8:
        parts.append("rumores recientes")

    explanation = "; ".join(parts)
    return f"score_raw={score_raw:.2f} — {explanation}"
