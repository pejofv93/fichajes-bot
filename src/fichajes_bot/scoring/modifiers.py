"""Scoring modifiers — hooks for Sessions 6-7.

Each modifier is a multiplier in (0, ∞):
  > 1.0  → amplify score (positive signal)
  < 1.0  → reduce score (negative / uncertain signal)
  = 1.0  → neutral (no data or not yet implemented)

All functions currently return 1.0 (neutral). Sessions 6 and 7 will
fill in the real implementations without changing the engine interface.

The engine calls apply_modifiers() after combining components:
  score_modified = score_raw * factor_econ * factor_subst * factor_sesgo
                   * factor_globo_sonda * factor_retractacion
"""

from __future__ import annotations

from typing import Any

from loguru import logger

from fichajes_bot.persistence.d1_client import D1Client


async def factor_economico(
    jugador_id: str,
    score_raw: float,
    db: D1Client,
) -> float:
    """Economic viability factor.

    Session 6 will read modelo_economico and check:
      - If RM has transfer budget for the player's market value → neutral or boost
      - If no budget or FFP limit exceeded → reduce
    Currently: returns 1.0 (neutral).
    """
    return 1.0


async def factor_substitucion(
    jugador_id: str,
    score_raw: float,
    db: D1Client,
) -> float:
    """Substitution graph propagation factor.

    Session 6 will traverse substitution_graph:
      - If a highly-ranked substitute is confirmed → reduce scores of alternatives
      - If RM needs a specific position → boost candidates for that position
    Currently: returns 1.0 (neutral).
    """
    return 1.0


async def factor_sesgo(
    rumores: list[dict[str, Any]],
    score_raw: float,
    db: D1Client,
) -> float:
    """Media bias correction factor.

    Session 7 will:
      - Identify the main source for this rumor batch
      - Apply the bias factor from configs/bias.yaml
      - pro-rm sources: reduce fichaje probability
      - pro-barca sources: reduce salida probability for RM players
    Currently: returns 1.0 (neutral).
    """
    return 1.0


async def factor_globo_sonda(
    rumores: list[dict[str, Any]],
    score_raw: float,
    db: D1Client,
) -> float:
    """Trial balloon (globo sonda) detection factor.

    Session 7 will:
      - Check if rumores contain POSIBLE_GLOBO_SONDA flag
      - Run heuristics from configs/lexicon/trial_balloon.yaml
      - If likely trial balloon: reduce score by ~0.15
    Currently: returns 1.0 (neutral).
    """
    return 1.0


async def factor_retractacion(
    jugador_id: str,
    rumores: list[dict[str, Any]],
    score_raw: float,
    db: D1Client,
) -> float:
    """Retraction factor.

    Session 7 will:
      - Check retractaciones table for this jugador
      - Recent retraction from high-credibility source: strongly reduce score
      - Multiple retractions: force score near 0
    Currently: returns 1.0 (neutral).
    """
    return 1.0


async def apply_modifiers(
    jugador_id: str,
    rumores: list[dict[str, Any]],
    score_raw: float,
    db: D1Client,
) -> tuple[float, dict[str, float]]:
    """Apply all modifiers and return (score_modified, factors_dict).

    The factors_dict is stored in jugadores.factores_actuales for transparency.
    """
    f_econ  = await factor_economico(jugador_id, score_raw, db)
    f_subst = await factor_substitucion(jugador_id, score_raw, db)
    f_sesgo = await factor_sesgo(rumores, score_raw, db)
    f_globo = await factor_globo_sonda(rumores, score_raw, db)
    f_retr  = await factor_retractacion(jugador_id, rumores, score_raw, db)

    combined = f_econ * f_subst * f_sesgo * f_globo * f_retr
    score_modified = max(0.01, min(0.99, score_raw * combined))

    factors = {
        "factor_econ":  round(f_econ,  4),
        "factor_subst": round(f_subst, 4),
        "factor_sesgo": round(f_sesgo, 4),
        "factor_globo": round(f_globo, 4),
        "factor_retr":  round(f_retr,  4),
        "combined":     round(combined, 4),
    }

    if combined != 1.0:
        logger.debug(f"apply_modifiers({jugador_id[:8]}): {score_raw:.3f} × {combined:.3f} = {score_modified:.3f}")

    return score_modified, factors
