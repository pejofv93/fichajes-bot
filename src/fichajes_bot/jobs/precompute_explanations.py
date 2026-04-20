"""Job: precompute_explanations — cache /explain for top 20 players.

Runs at end of cold-loop. Ensures /explain responds in <100ms for top 20.

Usage:
    python -m fichajes_bot.jobs.precompute_explanations
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

from loguru import logger

from fichajes_bot.notifications.explain_extended import generate_extended_explanation
from fichajes_bot.persistence.d1_client import D1Client
from fichajes_bot.persistence.repositories import MetricasRepository

CACHE_TTL_HOURS = 4
TOP_N = 20


async def run(_db: D1Client | None = None, **kwargs) -> dict[str, int]:
    """Cache /explain for top N players. Accepts optional db for testing."""
    logger.info(f"precompute_explanations: caching top {TOP_N} players")

    if _db is not None:
        return await _execute(_db)

    async with D1Client() as db:
        return await _execute(db)


async def _execute(db: D1Client) -> dict[str, int]:
    metrics = MetricasRepository(db)

    jugadores = await db.execute(
        """SELECT jugador_id FROM jugadores
           WHERE is_active = 1
           ORDER BY score_smoothed DESC
           LIMIT ?""",
        [TOP_N],
    )

    if not jugadores:
        logger.info("precompute_explanations: no active players found")
        return {"cached": 0, "errors": 0}

    cached = errors = 0
    now = datetime.now(timezone.utc)
    valido_hasta = (now + timedelta(hours=CACHE_TTL_HOURS)).strftime("%Y-%m-%d %H:%M:%S")

    for row in jugadores:
        jugador_id = row["jugador_id"]
        try:
            contenido = await generate_extended_explanation(jugador_id, db)

            await db.execute(
                """INSERT INTO explanation_cache
                       (jugador_id, contenido, generado_at, valido_hasta)
                   VALUES (?, ?, datetime('now'), ?)
                   ON CONFLICT(jugador_id) DO UPDATE SET
                       contenido = excluded.contenido,
                       generado_at = excluded.generado_at,
                       valido_hasta = excluded.valido_hasta""",
                [jugador_id, contenido, valido_hasta],
            )
            cached += 1
            logger.debug(f"precompute_explanations: cached {jugador_id[:8]}")

        except Exception as exc:
            errors += 1
            logger.error(f"precompute_explanations error for {jugador_id[:8]}: {exc}")

    await metrics.upsert("last_precompute_explanations_at", now.isoformat())
    logger.info(f"precompute_explanations done | cached={cached} errors={errors}")
    return {"cached": cached, "errors": errors}


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Pre-compute /explain cache for top players")
    parser.parse_args()
    asyncio.run(run())


if __name__ == "__main__":
    main()
