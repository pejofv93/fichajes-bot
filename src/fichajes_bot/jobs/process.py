"""Job: process raw rumors through extraction pipeline."""

from __future__ import annotations

import asyncio

from loguru import logger

from fichajes_bot.persistence.d1_client import D1Client
from fichajes_bot.persistence.repositories import MetricasRepository, RumorRawRepository


async def run(limit: int = 100) -> None:
    logger.info(f"process job starting | limit={limit}")
    async with D1Client() as db:
        raw_repo = RumorRawRepository(db)
        metrics = MetricasRepository(db)

        items = await raw_repo.get_unprocessed(limit)
        logger.info(f"Found {len(items)} unprocessed raw rumors")

        n_regex = n_gemini = n_discarded = 0
        for item in items:
            try:
                from fichajes_bot.extraction.pipeline import ExtractionPipeline
                pipeline = ExtractionPipeline(db)
                result = await pipeline.process(item)
                if result is None:
                    await raw_repo.mark_processed(item["raw_id"], descartado=True, motivo="no_match")
                    n_discarded += 1
                else:
                    await raw_repo.mark_processed(item["raw_id"])
                    if result.get("extraido_con") == "gemini":
                        n_gemini += 1
                    else:
                        n_regex += 1
            except Exception as exc:
                logger.warning(f"process failed for {item['raw_id']}: {exc}")
                await raw_repo.mark_processed(item["raw_id"], descartado=True, motivo=str(exc))
                n_discarded += 1

        await metrics.upsert("rumores_procesados_hoy", str(n_regex + n_gemini))
        await metrics.upsert("gemini_calls_hoy", str(n_gemini), float(n_gemini))
        logger.info(f"process done | regex={n_regex} gemini={n_gemini} discarded={n_discarded}")


def main() -> None:
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=100)
    args = parser.parse_args()
    asyncio.run(run(args.limit))


if __name__ == "__main__":
    main()
