"""Job: detect_official_events — stub implementation for Session 1."""

from __future__ import annotations

import asyncio
import argparse

from loguru import logger

from fichajes_bot.persistence.d1_client import D1Client


async def run(**kwargs) -> None:
    logger.info("detect_official_events job starting | kwargs={kwargs}")
    async with D1Client() as db:
        # TODO: implement in subsequent sessions
        pass
    logger.info("detect_official_events job done")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--full", action="store_true", default=False)
    parser.add_argument("--job", default="detect_official_events")
    parser.add_argument("--limit", type=int, default=100)
    args = parser.parse_args()
    asyncio.run(run(**vars(args)))


if __name__ == "__main__":
    main()
