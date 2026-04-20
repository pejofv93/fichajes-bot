"""Job: generate and send the daily Variante B report via Telegram."""

from __future__ import annotations

import asyncio
import os
import uuid
from datetime import datetime

from loguru import logger

from fichajes_bot.notifications.daily_report import generate_daily_report
from fichajes_bot.notifications.telegram_sender import AsyncTelegramSender, split_message
from fichajes_bot.persistence.d1_client import D1Client


async def run() -> None:
    logger.info("daily_report job starting")

    bot_token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "")

    async with D1Client() as d1:
        report = await generate_daily_report(d1)

        chunks = split_message(report, max_len=4096)
        chunks_totales = len(chunks)
        chunks_enviados = 0

        async with AsyncTelegramSender(bot_token, chat_id) as sender:
            for idx, chunk in enumerate(chunks, start=1):
                ok = await sender.send_message(chunk)
                if ok:
                    chunks_enviados += 1
                    logger.info(f"daily_report: chunk {idx}/{chunks_totales} sent")
                else:
                    logger.error(
                        f"daily_report: chunk {idx}/{chunks_totales} FAILED — "
                        "continuing with remaining chunks"
                    )

        partial = chunks_enviados < chunks_totales
        log_id = str(uuid.uuid4())
        try:
            await d1.execute(
                """INSERT INTO alertas_log
                   (log_id, tipo_alerta, chunks_enviados, chunks_totales,
                    enviada_at, feedback_usuario)
                   VALUES (?, 'daily_report', ?, ?, CURRENT_TIMESTAMP, ?)""",
                [
                    log_id,
                    chunks_enviados,
                    chunks_totales,
                    f"partial={partial}",
                ],
            )
        except Exception as exc:
            logger.warning(f"daily_report: could not log to alertas_log: {exc}")

    logger.info(
        f"daily_report job done: {chunks_enviados}/{chunks_totales} chunks sent"
    )


def main() -> None:
    asyncio.run(run())


if __name__ == "__main__":
    main()
