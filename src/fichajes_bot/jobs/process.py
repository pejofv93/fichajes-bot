"""Job: process — run extraction pipeline on unprocessed rumores_raw.

Usage:
    python -m fichajes_bot.jobs.process --limit 100
    python -m fichajes_bot.jobs.process --limit 300   # cold-loop
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from loguru import logger

from fichajes_bot.extraction.pipeline import ExtractionPipeline
from fichajes_bot.persistence.d1_client import D1Client
from fichajes_bot.persistence.repositories import MetricasRepository, RumorRawRepository


async def run(limit: int = 100) -> dict[str, int]:
    """Process up to *limit* unprocessed raw rumors.

    Returns dict with counts: regex, gemini, discarded.
    """
    logger.info(f"process job | limit={limit}")

    async with D1Client() as db:
        raw_repo = RumorRawRepository(db)
        metrics = MetricasRepository(db)

        items = await raw_repo.get_unprocessed(limit)
        logger.info(f"Unprocessed raw rumors: {len(items)}")

        if not items:
            await metrics.upsert("rumores_procesados_hoy", "0", 0.0)
            await metrics.upsert("last_process_at", datetime.now(timezone.utc).isoformat())
            return {"regex": 0, "gemini": 0, "discarded": 0}

        # Single pipeline instance — lexicon loaded once for the whole batch
        pipeline = ExtractionPipeline(db)

        n_regex = n_gemini = n_discarded = 0

        for item in items:
            raw_id = item["raw_id"]
            try:
                result = await pipeline.process(item)

                if result is None:
                    await raw_repo.mark_processed(raw_id, descartado=True, motivo="no_match")
                    n_discarded += 1
                else:
                    await raw_repo.mark_processed(raw_id)
                    if result.get("extraido_con") == "gemini":
                        n_gemini += 1
                    else:
                        n_regex += 1

            except Exception as exc:
                logger.warning(f"process error for {raw_id}: {exc}")
                try:
                    await raw_repo.mark_processed(
                        raw_id, descartado=True, motivo=str(exc)[:200]
                    )
                except Exception:
                    pass
                n_discarded += 1

        # ── Metrics ───────────────────────────────────────────────────────────
        n_total = n_regex + n_gemini
        now = datetime.now(timezone.utc).isoformat()

        await metrics.upsert("rumores_procesados_hoy", str(n_total), float(n_total))
        await metrics.upsert("last_process_at", now)

        gemini_usage = await pipeline._gemini.get_daily_usage()
        await metrics.upsert("gemini_calls_hoy", str(gemini_usage), float(gemini_usage))

        # ── Immediate recompute for urgent hard-signal events ─────────────────
        n_urgent = await _process_urgent_events(db)
        if n_urgent:
            logger.info(f"process: {n_urgent} urgent events recomputed immediately")

        logger.info(
            f"process done | regex={n_regex} gemini={n_gemini} "
            f"discarded={n_discarded} total_extracted={n_total} urgent={n_urgent}"
        )

        return {"regex": n_regex, "gemini": n_gemini, "discarded": n_discarded}


async def _process_urgent_events(db) -> int:
    """Immediately recompute scores for jugadores with urgent hard-signal events."""
    from fichajes_bot.calibration.reliability_manager import ReliabilityManager
    from fichajes_bot.scoring.engine import recompute_score

    rows = await db.execute(
        """SELECT payload FROM eventos_pending
           WHERE tipo IN ('retraction', 'score_recompute_needed')
             AND procesado = 0
           ORDER BY created_at ASC""",
    )

    if not rows:
        return 0

    import json
    reliability_manager = ReliabilityManager(db)
    processed_ids: set[str] = set()
    count = 0

    for row in rows:
        try:
            payload = json.loads(row["payload"] or "{}")
            jid = payload.get("jugador_id")
            if jid and jid not in processed_ids:
                processed_ids.add(jid)
                await recompute_score(jid, db, reliability_manager)
                count += 1
        except Exception as exc:
            logger.warning(f"urgent recompute error: {exc}")

    # Mark all consumed
    await db.execute(
        """UPDATE eventos_pending
           SET procesado=1, procesado_at=datetime('now')
           WHERE tipo IN ('retraction', 'score_recompute_needed')
             AND procesado=0"""
    )
    return count


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Run extraction pipeline on raw rumors")
    parser.add_argument("--limit", type=int, default=100, help="Max items to process")
    args = parser.parse_args()

    asyncio.run(run(limit=args.limit))


if __name__ == "__main__":
    main()
