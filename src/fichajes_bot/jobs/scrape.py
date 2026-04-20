"""Job: scrape RSS/Bluesky sources by tier."""

from __future__ import annotations

import asyncio
import sys

from loguru import logger

from fichajes_bot.persistence.d1_client import D1Client
from fichajes_bot.persistence.repositories import MetricasRepository


async def run(tier: str = "S") -> None:
    tiers = [t.strip() for t in tier.upper().split(",")]
    logger.info(f"scrape job starting | tiers={tiers}")

    async with D1Client() as db:
        metrics = MetricasRepository(db)

        rows = await db.execute(
            f"SELECT * FROM fuentes WHERE tier IN ({','.join('?' * len(tiers))}) AND is_disabled=0",
            tiers,
        )
        logger.info(f"Found {len(rows)} active sources for tiers {tiers}")

        total_ingested = 0
        for source in rows:
            try:
                from fichajes_bot.ingestion.resolver import SourceResolver
                resolver = SourceResolver(db)
                n = await resolver.scrape_source(source)
                total_ingested += n
                logger.info(f"  {source['fuente_id']}: {n} items")
            except Exception as exc:
                logger.warning(f"  {source['fuente_id']}: FAILED — {exc}")
                await db.execute(
                    "UPDATE fuentes SET consecutive_errors=consecutive_errors+1 WHERE fuente_id=?",
                    [source["fuente_id"]],
                )

        await metrics.upsert("rumores_ingested_this_run", str(total_ingested), float(total_ingested))
        await metrics.upsert("last_hot_loop_at", __import__("datetime").datetime.utcnow().isoformat())
        logger.info(f"scrape job done | total_ingested={total_ingested}")


def main() -> None:
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--tier", default="S")
    args = parser.parse_args()
    asyncio.run(run(args.tier))


if __name__ == "__main__":
    main()
