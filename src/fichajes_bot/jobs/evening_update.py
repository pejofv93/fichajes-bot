"""Job: evening update — top 5 movimientos + alertas pendientes (20:00 CEST)."""

from __future__ import annotations

import asyncio
import os
import uuid
from datetime import date

from loguru import logger

from fichajes_bot.notifications.telegram_sender import AsyncTelegramSender
from fichajes_bot.persistence.d1_client import D1Client


async def _generate_evening_update(d1: D1Client) -> str:
    today = date.today()
    fecha_str = today.strftime("%d/%m/%Y")

    # Top 5 cambios del día por delta absoluto
    cambios = await d1.execute("""
        SELECT j.nombre_canonico, sh.delta, sh.razon_cambio, j.tipo_operacion_principal
        FROM score_history sh
        JOIN jugadores j ON sh.jugador_id = j.jugador_id
        WHERE date(sh.timestamp) = date('now')
        ORDER BY ABS(sh.delta) DESC LIMIT 5
    """)

    # Alertas pendientes de enviar (tipo no daily_report)
    try:
        alertas_pendientes = await d1.execute("""
            SELECT COUNT(*) as n FROM eventos_pending
            WHERE tipo != 'daily_report' AND procesado = 0
        """)
        n_pendientes = (alertas_pendientes[0].get("n") or 0) if alertas_pendientes else 0
    except Exception:
        n_pendientes = 0

    lines: list[str] = [
        f"🌆 *ACTUALIZACIÓN VESPERTINA — {fecha_str}*",
        "━━━━━━━━━━━━━━━━━━━━",
        "",
    ]

    if cambios:
        lines.append("📊 *Top movimientos del día:*")
        for r in cambios:
            delta = r.get("delta") or 0.0
            sign = "+" if delta >= 0 else ""
            pct_delta = f"{sign}{round(delta * 100)}%"
            nombre = r.get("nombre_canonico") or "?"
            razon = r.get("razon_cambio") or "?"
            tipo_em = "🏆" if r.get("tipo_operacion_principal") == "FICHAJE" else "📤"
            lines.append(f"{tipo_em} *{nombre}* {pct_delta} — {razon}")
    else:
        lines.append("_Sin movimientos significativos hoy_")

    lines.append("")

    if n_pendientes > 0:
        lines.append(f"⚠️ {n_pendientes} alertas pendientes de procesar")
    else:
        lines.append("✅ Sin alertas pendientes")

    lines.append("")
    lines.append("_Próximo informe completo mañana a las 08:00_")

    return "\n".join(lines)


async def run() -> None:
    logger.info("evening_update job starting")

    bot_token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "")

    async with D1Client() as d1:
        report = await _generate_evening_update(d1)

        chunks_enviados = 0
        chunks_totales = 1

        async with AsyncTelegramSender(bot_token, chat_id) as sender:
            ok = await sender.send_message(report)
            if ok:
                chunks_enviados = 1
            else:
                logger.error("evening_update: failed to send message")

        log_id = str(uuid.uuid4())
        try:
            await d1.execute(
                """INSERT INTO alertas_log
                   (log_id, tipo_alerta, chunks_enviados, chunks_totales,
                    enviada_at, feedback_usuario)
                   VALUES (?, 'evening_update', ?, ?, CURRENT_TIMESTAMP, NULL)""",
                [log_id, chunks_enviados, chunks_totales],
            )
        except Exception as exc:
            logger.warning(f"evening_update: could not log to alertas_log: {exc}")

    logger.info("evening_update job done")


def main() -> None:
    asyncio.run(run())


if __name__ == "__main__":
    main()
