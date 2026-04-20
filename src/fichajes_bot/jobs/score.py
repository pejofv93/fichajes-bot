"""Job: score — recompute scores for players with pending rumor events.

Usage:
    python -m fichajes_bot.jobs.score              # only players with pending events
    python -m fichajes_bot.jobs.score --full       # all players with rumores <48h

Modes:
  default:  processes jugadores referenced in eventos_pending tipo='new_rumor'
  --full:   processes all jugadores with any rumores in last 48h
            (used in cold-loop.yml for full re-scoring + substitution propagation)
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone

from loguru import logger

from fichajes_bot.calibration.reliability_manager import ReliabilityManager
from fichajes_bot.persistence.d1_client import D1Client
from fichajes_bot.persistence.repositories import MetricasRepository
from fichajes_bot.scoring.engine import recompute_score


async def run(full: bool = False, limit: int = 200) -> dict[str, int]:
    """Recompute scores. Returns {processed, updated, skipped, errors}."""
    logger.info(f"score job | full={full} limit={limit}")

    async with D1Client() as db:
        metrics = MetricasRepository(db)

        # ── Determine which jugadores to score ──────────────────────────────
        if full:
            jugador_ids = await _get_all_active_jugadores(db)
            logger.info(f"Full mode: {len(jugador_ids)} jugadores with recent rumores")
        else:
            jugador_ids = await _get_pending_event_jugadores(db)
            logger.info(f"Event mode: {len(jugador_ids)} jugadores with pending events")

        if not jugador_ids:
            logger.info("No jugadores to score")
            return {"processed": 0, "updated": 0, "skipped": 0, "errors": 0}

        # Cap to limit
        jugador_ids = jugador_ids[:limit]

        # Single ReliabilityManager instance — shared cache for the whole batch
        reliability_manager = ReliabilityManager(db)

        processed = updated = skipped = errors = 0

        for jugador_id in jugador_ids:
            try:
                result = await recompute_score(jugador_id, db, reliability_manager)
                if result is None:
                    skipped += 1
                else:
                    updated += 1
                processed += 1
            except Exception as exc:
                errors += 1
                logger.warning(f"score error for {jugador_id[:8]}: {exc}")

        # Mark pending events as processed
        if not full:
            await _mark_events_processed(db)
        else:
            # After full scoring, propagate substitution effects for newly classified outcomes
            await _run_substitution_propagation(db)

        # Record metrics
        now = datetime.now(timezone.utc).isoformat()
        await metrics.upsert("last_score_run_at", now)
        await metrics.upsert("score_updated_this_run", str(updated), float(updated))

        logger.info(
            f"score done | processed={processed} updated={updated} "
            f"skipped={skipped} errors={errors}"
        )

        return {"processed": processed, "updated": updated,
                "skipped": skipped, "errors": errors}


async def _get_pending_event_jugadores(db: D1Client) -> list[str]:
    """Jugadores referenced in unprocessed 'new_rumor' events."""
    rows = await db.execute(
        "SELECT payload FROM eventos_pending WHERE tipo='new_rumor' AND procesado=0"
    )
    ids: set[str] = set()
    for row in rows:
        try:
            payload = json.loads(row["payload"] or "{}")
            if jid := payload.get("jugador_id"):
                ids.add(jid)
        except Exception:
            pass
    return list(ids)


async def _get_all_active_jugadores(db: D1Client) -> list[str]:
    """All jugadores with at least one rumor in the last 48h."""
    rows = await db.execute(
        """SELECT DISTINCT jugador_id FROM rumores
           WHERE jugador_id IS NOT NULL
             AND retractado = 0
             AND (fecha_publicacion IS NULL
                  OR fecha_publicacion >= datetime('now', '-48 hours'))"""
    )
    return [r["jugador_id"] for r in rows]


async def _run_substitution_propagation(db: D1Client) -> None:
    """Propagate score changes for players with outcomes classified in the last 4h."""
    from fichajes_bot.validators.substitution import SubstitutionEngine

    engine = SubstitutionEngine(db)
    await engine.build_graph()

    # Signed players (FICHAJE confirmed) → reduce alternatives' scores
    signed = await db.execute(
        """SELECT DISTINCT r.jugador_id FROM rumores r
           JOIN jugadores j ON r.jugador_id = j.jugador_id
           WHERE r.outcome = 'CONFIRMADO'
             AND r.outcome_at >= datetime('now', '-4 hours')
             AND j.tipo_operacion_principal = 'FICHAJE'"""
    )
    for row in signed:
        await engine.propagate_on_signing(row["jugador_id"])
        logger.info(f"substitution propagation: signing {row['jugador_id'][:8]}")

    # Players who left (SALIDA confirmed) → boost candidates for that position
    sold = await db.execute(
        """SELECT DISTINCT r.jugador_id FROM rumores r
           JOIN jugadores j ON r.jugador_id = j.jugador_id
           WHERE r.outcome = 'CONFIRMADO'
             AND r.outcome_at >= datetime('now', '-4 hours')
             AND j.tipo_operacion_principal = 'SALIDA'"""
    )
    for row in sold:
        await engine.propagate_on_sale(row["jugador_id"])
        logger.info(f"substitution propagation: sale {row['jugador_id'][:8]}")

    if not signed and not sold:
        logger.debug("substitution propagation: no recent outcomes to propagate")


async def _mark_events_processed(db: D1Client) -> None:
    await db.execute(
        """UPDATE eventos_pending
           SET procesado=1, procesado_at=datetime('now')
           WHERE tipo='new_rumor' AND procesado=0"""
    )


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Recompute player scores with Kalman")
    parser.add_argument("--full", action="store_true",
                        help="Full recompute for all players with recent rumores")
    parser.add_argument("--limit", type=int, default=200,
                        help="Max players to process")
    args = parser.parse_args()

    asyncio.run(run(full=args.full, limit=args.limit))


if __name__ == "__main__":
    main()
