"""Job: detect_official_events — scan hard-signal rumors and record outcomes."""

from __future__ import annotations

import asyncio
import argparse

from loguru import logger

from fichajes_bot.calibration.official_events_detector import OfficialEventsDetector
from fichajes_bot.persistence.d1_client import D1Client


async def run(window_days: int = 30, **kwargs) -> None:
    logger.info(f"detect_official_events job starting | window_days={window_days}")
    async with D1Client() as db:
        detector = OfficialEventsDetector(db)
        n = await detector.scan_recent_rumors(window_days=window_days)
        logger.info(f"detect_official_events job done | outcomes_created={n}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Detect official transfer events")
    parser.add_argument("--window-days", type=int, default=30,
                        help="Days to look back for hard-signal rumors (default: 30)")
    args = parser.parse_args()
    asyncio.run(run(window_days=args.window_days))


if __name__ == "__main__":
    main()
