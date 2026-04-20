"""Scoring modifiers — multipliers applied after combining base components.

Each modifier returns a factor in (0, ∞):
  > 1.0  → amplify score (positive signal)
  < 1.0  → reduce score (negative / uncertain signal)
  = 1.0  → neutral (no data or not yet implemented)

Session 6 activates: factor_economico, factor_substitucion, factor_temporal_modifier.
Session 7 activates: factor_sesgo, factor_globo_sonda, factor_retractacion.

Validator instances are cached per-run (keyed by db object id) to avoid
rebuilding the substitution graph or re-fetching modelo_economico for every player.
"""

from __future__ import annotations

from typing import Any

from loguru import logger

from fichajes_bot.persistence.d1_client import D1Client

# ── Per-run validator cache ───────────────────────────────────────────────────
# Refreshed automatically when a new D1Client instance is detected.

_run_cache: dict = {}   # {"db_id": int, "validators": {name: instance}}


def _validators_for(db: D1Client) -> dict:
    """Return (or create) cached validator instances for this run's db."""
    key = id(db)
    if _run_cache.get("db_id") != key:
        _run_cache.clear()
        from fichajes_bot.validators.economic import EconomicValidator
        from fichajes_bot.validators.substitution import SubstitutionEngine
        from fichajes_bot.validators.temporal import TemporalValidator
        _run_cache["db_id"] = key
        _run_cache["validators"] = {
            "economic":     EconomicValidator(db),
            "substitution": SubstitutionEngine(db),
            "temporal":     TemporalValidator(db),
        }
    return _run_cache["validators"]


# ── Individual modifier functions ─────────────────────────────────────────────


async def factor_economico(
    jugador_id: str,
    score_raw: float,
    db: D1Client,
) -> float:
    """Economic viability factor via EconomicValidator.

    Returns 1.0 if no economic model is available (neutral).
    """
    v = _validators_for(db)
    return await v["economic"].evaluate(jugador_id)


async def factor_substitucion(
    jugador_id: str,
    score_raw: float,
    db: D1Client,
) -> float:
    """Substitution-graph factor via SubstitutionEngine.

    Returns 1.0 (HUECO_NATURAL) if player or position data is missing.
    """
    v = _validators_for(db)
    return await v["substitution"].evaluate(jugador_id)


async def factor_temporal_modifier(
    jugador_id: str,
    rumores: list[dict[str, Any]],
    score_raw: float,
    db: D1Client,
) -> float:
    """Market-window timing factor via TemporalValidator.

    Uses the most recent rumor's text + the player's flags.
    Returns 1.0 only in neutral windows; may reduce score outside transfer windows.
    """
    v = _validators_for(db)
    temporal = v["temporal"]

    rumor = rumores[0] if rumores else {}

    # Fetch jugador flags for contract-expiry boost
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
    """Media bias correction factor. Implemented in Session 7."""
    return 1.0


async def factor_globo_sonda(
    rumores: list[dict[str, Any]],
    score_raw: float,
    db: D1Client,
) -> float:
    """Trial balloon detection factor. Implemented in Session 7."""
    return 1.0


async def factor_retractacion(
    jugador_id: str,
    rumores: list[dict[str, Any]],
    score_raw: float,
    db: D1Client,
) -> float:
    """Retraction factor. Implemented in Session 7."""
    return 1.0


# ── Orchestrator ──────────────────────────────────────────────────────────────


async def apply_modifiers(
    jugador_id: str,
    rumores: list[dict[str, Any]],
    score_raw: float,
    db: D1Client,
) -> tuple[float, dict[str, float]]:
    """Apply all modifiers and return (score_modified, factors_dict).

    The factors_dict is stored in jugadores.factores_actuales for transparency
    and surfaced in the /explain Telegram command.
    """
    f_econ    = await factor_economico(jugador_id, score_raw, db)
    f_subst   = await factor_substitucion(jugador_id, score_raw, db)
    f_temporal_mod = await factor_temporal_modifier(jugador_id, rumores, score_raw, db)
    f_sesgo   = await factor_sesgo(rumores, score_raw, db)
    f_globo   = await factor_globo_sonda(rumores, score_raw, db)
    f_retr    = await factor_retractacion(jugador_id, rumores, score_raw, db)

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
            f"apply_modifiers({jugador_id[:8]}): "
            f"{score_raw:.3f} × {combined:.3f} = {score_modified:.3f} "
            f"[econ={f_econ:.2f} subst={f_subst:.2f} temp={f_temporal_mod:.2f}]"
        )

    return score_modified, factors
