"""Job: scrape — fetch RSS/Bluesky/web sources by tier.

Usage:
    python -m fichajes_bot.jobs.scrape --tier S
    python -m fichajes_bot.jobs.scrape --tier A,B,C
    python -m fichajes_bot.jobs.scrape --tier all
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from loguru import logger

from fichajes_bot.ingestion.resolver import SourceResolver
from fichajes_bot.persistence.d1_client import D1Client
from fichajes_bot.persistence.repositories import MetricasRepository


async def run(tier: str = "S") -> int:
    """Returns total number of new items ingested."""
    if tier.strip().lower() == "all":
        tiers = ["S", "A", "B", "C"]
    else:
        tiers = [t.strip().upper() for t in tier.split(",") if t.strip()]

    logger.info(f"scrape job | tiers={tiers}")

    async with D1Client() as db:
        metrics = MetricasRepository(db)
        resolver = SourceResolver(db)

        sources = await db.execute(
            f"SELECT * FROM fuentes WHERE tipo IN ('rss','bluesky') "
            f"AND tier IN ({','.join('?' * len(tiers))}) "
            f"AND is_disabled=0",
            tiers,
        )

        if not sources:
            logger.info("No active RSS/Bluesky sources found")
            return 0

        logger.info(f"Scraping {len(sources)} sources")
        total_new = 0
        sources_ok = 0
        sources_failed = 0

        for source in sources:
            try:
                n = await resolver.scrape_source(source)
                total_new += n
                sources_ok += 1
                logger.debug(f"  {source['fuente_id']}: +{n}")
            except Exception as exc:
                sources_failed += 1
                logger.warning(f"  {source['fuente_id']}: FAILED — {exc}")

        now = datetime.now(timezone.utc).isoformat()
        await metrics.upsert("last_hot_loop_at", now)
        await metrics.upsert(
            "rumores_ingested_this_run", str(total_new), float(total_new)
        )
        await metrics.upsert("sources_activas", str(sources_ok), float(sources_ok))
        if sources_failed:
            await metrics.upsert(
                "sources_degradadas", str(sources_failed), float(sources_failed)
            )

        logger.info(
            f"scrape done | new={total_new} ok={sources_ok} failed={sources_failed}"
        )
        return total_new


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Scrape RSS/Bluesky sources")
    parser.add_argument("--tier", default="S", help="Tiers to scrape: S, A,B,C, or all")
    args = parser.parse_args()
    asyncio.run(run(args.tier))


if __name__ == "__main__":
    main()
