"""Job: calibrate — update journalist reliability + lexicon weights."""

from __future__ import annotations

import asyncio
import argparse

from loguru import logger

from fichajes_bot.calibration.calibrator import Calibrator
from fichajes_bot.calibration.reliability_manager import ReliabilityManager
from fichajes_bot.persistence.d1_client import D1Client


async def run(window_days: int = 90, **kwargs) -> None:
    logger.info(f"calibrate job starting | window_days={window_days}")
    async with D1Client() as db:
        rm = ReliabilityManager(db)
        calibrator = Calibrator(db, rm)

        journalist_updates = await calibrator.calibrate_journalists(
            window_days=window_days
        )
        lexicon_updates = await calibrator.calibrate_lexicon(
            window_days=window_days
        )

        logger.info(
            f"calibrate job done | "
            f"journalist_updates={sum(journalist_updates.values())} "
            f"lexicon_updates={lexicon_updates}"
        )


def main() -> None:
    parser = argparse.ArgumentParser(description="Calibrate journalist reliability and lexicon")
    parser.add_argument("--window-days", type=int, default=90,
                        help="Calibration window in days (default: 90)")
    args = parser.parse_args()
    asyncio.run(run(window_days=args.window_days))


if __name__ == "__main__":
    main()
