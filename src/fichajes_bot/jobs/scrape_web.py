"""Job: scrape_web — fetch web_selectolax sources (cold-loop only).

Only scrapes sources with tipo='web_selectolax'. Respects polling_minutes
so that semanal sources (Capology, LaLiga) are not fetched every 4h.

Usage:
    python -m fichajes_bot.jobs.scrape_web
    python -m fichajes_bot.jobs.scrape_web --force  # ignore polling_minutes
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from loguru import logger

from fichajes_bot.ingestion.resolver import SourceResolver
from fichajes_bot.persistence.d1_client import D1Client
from fichajes_bot.persistence.repositories import MetricasRepository


async def run(force: bool = False) -> int:
    """Returns total new items ingested."""
    logger.info(f"scrape_web job | force={force}")

    async with D1Client() as db:
        metrics = MetricasRepository(db)
        resolver = SourceResolver(db)

        # Only web_selectolax sources that are due for a fetch
        if force:
            sources = await db.execute(
                "SELECT * FROM fuentes WHERE tipo='web_selectolax' AND is_disabled=0"
            )
        else:
            # Due = never fetched OR last_fetched_at is older than polling_minutes
            sources = await db.execute(
                """SELECT * FROM fuentes
                   WHERE tipo='web_selectolax' AND is_disabled=0
                   AND (
                     last_fetched_at IS NULL
                     OR datetime(last_fetched_at, '+' || polling_minutes || ' minutes') <= datetime('now')
                   )"""
            )

        if not sources:
            logger.info("No web sources due for fetch")
            return 0

        logger.info(f"Web scraping {len(sources)} sources")
        total_new = 0

        for source in sources:
            try:
                n = await resolver.scrape_source(source)
                total_new += n
                logger.info(f"  {source['fuente_id']}: +{n}")
            except Exception as exc:
                logger.warning(f"  {source['fuente_id']}: FAILED — {exc}")

        await metrics.upsert("last_cold_loop_at", datetime.now(timezone.utc).isoformat())
        await metrics.upsert(
            "web_items_ingested_this_run", str(total_new), float(total_new)
        )

        logger.info(f"scrape_web done | new={total_new}")
        return total_new


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Scrape web_selectolax sources")
    parser.add_argument(
        "--force", action="store_true", help="Ignore polling_minutes, fetch all"
    )
    args = parser.parse_args()
    asyncio.run(run(force=args.force))


if __name__ == "__main__":
    main()
