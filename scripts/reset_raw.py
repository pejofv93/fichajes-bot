#!/usr/bin/env python
"""Reset procesado=0 for rumores_raw from the last 30 days.

Allows the new simplified pipeline to re-process all recent items.

Usage:
    python scripts/reset_raw.py
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from loguru import logger
from fichajes_bot.persistence.d1_client import D1Client


_BAD_JUGADORES = ("Rashford", "Marcus Rashford", "Xabi Alonso")


async def run() -> None:
    async with D1Client() as db:
        await db.execute(
            """UPDATE rumores_raw
               SET procesado = 0,
                   descartado = 0,
                   motivo_descarte = NULL
               WHERE fecha_ingesta >= datetime('now', '-30 days')
                  OR fecha_publicacion >= datetime('now', '-30 days')"""
        )
        rows = await db.execute(
            """SELECT COUNT(*) AS n FROM rumores_raw
               WHERE procesado = 0"""
        )
        n = rows[0]["n"] if rows else "?"
        logger.info(f"Reset done — {n} rumores_raw now pending reprocessing")

        try:
            for nombre in _BAD_JUGADORES:
                safe = nombre.replace("'", "''")
                await db.execute(
                    f"DELETE FROM jugadores WHERE nombre_canonico = '{safe}'",
                    [],
                )
            logger.info(f"Deleted bad jugadores: {_BAD_JUGADORES}")
        except Exception as exc:
            logger.warning(f"DELETE jugadores failed (manual cleanup needed): {exc}")


def main() -> None:
    asyncio.run(run())


if __name__ == "__main__":
    main()
