"""Job: archive_to_json — stub implementation for Session 1."""

from __future__ import annotations

import asyncio
import argparse

from loguru import logger

from fichajes_bot.persistence.d1_client import D1Client


async def run(**kwargs) -> None:
    logger.info("archive_to_json job starting | kwargs={kwargs}")
    async with D1Client() as db:
        # TODO: implement in subsequent sessions
        pass
    logger.info("archive_to_json job done")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--full", action="store_true", default=False)
    parser.add_argument("--job", default="archive_to_json")
    parser.add_argument("--limit", type=int, default=100)
    args = parser.parse_args()
    asyncio.run(run(**vars(args)))


if __name__ == "__main__":
    main()
