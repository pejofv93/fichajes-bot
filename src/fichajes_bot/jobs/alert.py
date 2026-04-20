"""Job: alert — dispatch pending score-change events as Telegram alerts.

Reads eventos_pending WHERE tipo IN ('score_changed','hard_signal','new_rumor')
and not alerted, sends via AlertManager, marks alerted=1.

Usage:
    python -m fichajes_bot.jobs.alert
"""

from __future__ import annotations

import asyncio
import json
import os

from loguru import logger

from fichajes_bot.notifications.alert_manager import AlertManager
from fichajes_bot.notifications.telegram_sender import AsyncTelegramSender
from fichajes_bot.persistence.d1_client import D1Client
from fichajes_bot.persistence.repositories import MetricasRepository

_ALERT_EVENT_TYPES = ("score_changed", "hard_signal", "new_rumor")


async def run(**kwargs) -> dict[str, int]:
    logger.info("alert job starting")

    async with D1Client() as db:
        metrics = MetricasRepository(db)

        token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
        chat_id = os.environ.get("TELEGRAM_CHAT_ID", "")

        if not token or not chat_id:
            logger.warning("TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID not set — alert job skipped")
            await metrics.upsert("last_alert_run_at", "skipped_no_token")
            return {"generated": 0, "sent": 0, "deduped": 0, "errors": 0}

        # Fetch unalerted events
        events = await db.execute(
            """SELECT evento_id, tipo, payload, created_at
               FROM eventos_pending
               WHERE tipo IN ({placeholders})
                 AND procesado = 0
               ORDER BY created_at ASC
               LIMIT 200""".format(
                placeholders=",".join("?" * len(_ALERT_EVENT_TYPES))
            ),
            list(_ALERT_EVENT_TYPES),
        )

        if not events:
            logger.info("alert job: no pending events")
            await metrics.upsert("last_alert_run_at", "no_events")
            return {"generated": 0, "sent": 0, "deduped": 0, "errors": 0}

        logger.info(f"alert job: {len(events)} events to process")

        async with AsyncTelegramSender(token, chat_id) as sender:
            manager = AlertManager(db, sender)
            result = await manager.process_events_and_send(events)

        # Mark all processed events as alerted (procesado=1)
        event_ids = [e["evento_id"] for e in events]
        if event_ids:
            placeholders = ",".join("?" * len(event_ids))
            await db.execute(
                f"""UPDATE eventos_pending
                    SET procesado=1, procesado_at=datetime('now')
                    WHERE evento_id IN ({placeholders})""",
                event_ids,
            )

        await metrics.upsert("last_alert_run_at", _now_iso())
        await metrics.upsert("alerts_sent_this_run", str(result["sent"]), float(result["sent"]))

        logger.info(
            f"alert job done | generated={result['generated']} sent={result['sent']} "
            f"deduped={result['deduped']} errors={result['errors']}"
        )
        return result


def _now_iso() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Dispatch pending alerts to Telegram")
    parser.add_argument("--job", default="alert")
    parser.parse_args()
    asyncio.run(run())


if __name__ == "__main__":
    main()
