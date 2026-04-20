"""AlertManager — detect alert triggers and dispatch via Telegram."""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from loguru import logger

from fichajes_bot.notifications.alert_formatter import format_alert
from fichajes_bot.notifications.telegram_sender import AsyncTelegramSender
from fichajes_bot.persistence.d1_client import D1Client

# Thresholds
THRESHOLD_HIGH = 0.70
THRESHOLD_LOW = 0.40
TOP10_SIZE = 10
DEDUP_HOURS = 6
GLOBO_SONDA_MIN_PROB = 0.70


@dataclass
class Alert:
    alert_type: str
    jugador_id: str
    jugador: dict[str, Any]
    contexto: dict[str, Any] = field(default_factory=dict)


class AlertManager:
    def __init__(self, db: D1Client, telegram_sender: AsyncTelegramSender) -> None:
        self._db = db
        self._sender = telegram_sender

    # ── Public API ────────────────────────────────────────────────────────────

    def detect_alert_triggers(
        self,
        jugador_id: str,
        score_anterior: float,
        score_nuevo: float,
        factores_anteriores: dict[str, Any],
        factores_nuevos: dict[str, Any],
        hard_signals: list[dict[str, Any]],
        *,
        jugador: dict[str, Any] | None = None,
        ranking_anterior: int | None = None,
        ranking_nuevo: int | None = None,
        nuevo_periodista_tier_s: dict[str, Any] | None = None,
        rumores_previos_count: int = 0,
    ) -> list[Alert]:
        """Return list of Alert objects triggered by this score change."""
        alerts: list[Alert] = []
        j = jugador or {"jugador_id": jugador_id, "score_smoothed": score_nuevo}

        # a) Score crossing UP through 70%
        if score_anterior < THRESHOLD_HIGH <= score_nuevo:
            alerts.append(Alert(
                alert_type="ALERTA_ALTA",
                jugador_id=jugador_id,
                jugador=j,
                contexto={"score_anterior": score_anterior},
            ))

        # b) Score crossing DOWN through 40%
        if score_anterior >= THRESHOLD_LOW > score_nuevo:
            alerts.append(Alert(
                alert_type="CAIDA",
                jugador_id=jugador_id,
                jugador=j,
                contexto={"score_anterior": score_anterior},
            ))

        # c) Hard signals (fichaje_oficial / salida_oficial)
        for sig in hard_signals:
            tipo = sig.get("tipo", "")
            if tipo in ("fichaje_oficial", "salida_oficial"):
                alerts.append(Alert(
                    alert_type="OFICIAL",
                    jugador_id=jugador_id,
                    jugador=j,
                    contexto={"tipo_signal": tipo},
                ))
                break  # one OFICIAL per score update is enough

        # d) Retractación detected in tier-S
        flags_nuevos = factores_nuevos.get("flags", [])
        flags_anteriores = factores_anteriores.get("flags", [])
        if "RETRACTADO_TIER_S" in flags_nuevos and "RETRACTADO_TIER_S" not in flags_anteriores:
            alerts.append(Alert(
                alert_type="RETRACTADO",
                jugador_id=jugador_id,
                jugador=j,
                contexto={"periodista_nombre": factores_nuevos.get("retraction_periodista", "Fuente tier-S")},
            ))

        # e) Trial balloon detected (probabilidad >= 0.70)
        prob_globo = factores_nuevos.get("probabilidad_globo", 0.0)
        prob_globo_prev = factores_anteriores.get("probabilidad_globo", 0.0)
        if prob_globo >= GLOBO_SONDA_MIN_PROB and prob_globo_prev < GLOBO_SONDA_MIN_PROB:
            alerts.append(Alert(
                alert_type="GLOBO_SONDA",
                jugador_id=jugador_id,
                jugador=j,
                contexto={"probabilidad_globo": prob_globo},
            ))

        # f) New player enters top 10
        if (
            ranking_nuevo is not None
            and ranking_nuevo <= TOP10_SIZE
            and (ranking_anterior is None or ranking_anterior > TOP10_SIZE)
        ):
            alerts.append(Alert(
                alert_type="NUEVO_EN_TOP_10",
                jugador_id=jugador_id,
                jugador=j,
                contexto={"ranking_nuevo": ranking_nuevo, "ranking_anterior": ranking_anterior},
            ))

        # g) New tier-S journalist reports on player that already had rumors
        if nuevo_periodista_tier_s and rumores_previos_count > 0:
            alerts.append(Alert(
                alert_type="CORROBORACION",
                jugador_id=jugador_id,
                jugador=j,
                contexto={"periodista_nombre": nuevo_periodista_tier_s.get("nombre_completo", "Tier-S")},
            ))

        return alerts

    async def send_alert(self, alert: Alert) -> bool:
        """Format and send one alert. Returns True if sent successfully."""
        try:
            # Check global alertas_realtime flag
            flag_row = await self._db.execute(
                "SELECT estado FROM flags_sistema WHERE flag_name = 'alertas_realtime'"
            )
            if flag_row and flag_row[0].get("estado") == "OFF":
                logger.info(f"alertas_realtime=OFF, skipping {alert.alert_type} for {alert.jugador_id[:8]}")
                return False

            # Deduplication: has same alert_type + jugador_id been sent in last 6h?
            dedup_rows = await self._db.execute(
                """SELECT log_id FROM alertas_log
                   WHERE jugador_id = ? AND alert_type = ?
                     AND enviada_at >= datetime('now', ? )
                   LIMIT 1""",
                [alert.jugador_id, alert.alert_type, f"-{DEDUP_HOURS} hours"],
            )
            if dedup_rows:
                logger.info(
                    f"dedup: {alert.alert_type} for {alert.jugador_id[:8]} "
                    f"already sent in last {DEDUP_HOURS}h"
                )
                return False

            formatted = format_alert(alert.alert_type, alert.jugador, alert.contexto)
            full_text = f"{formatted.titulo}\n\n{formatted.cuerpo}"
            results = await self._sender.send_message_splitted(full_text)

            chunks_ok = sum(1 for r in results if r)
            chunks_total = len(results)
            sent_ok = chunks_ok > 0

            # Log to alertas_log
            await self._db.execute(
                """INSERT INTO alertas_log
                   (log_id, jugador_id, alert_type, tipo_alerta, mensaje_enviado,
                    score_snapshot, enviada_at, chunks_enviados, chunks_totales)
                   VALUES (?, ?, ?, ?, ?, ?, datetime('now'), ?, ?)""",
                [
                    str(uuid.uuid4()),
                    alert.jugador_id,
                    alert.alert_type,
                    alert.alert_type,
                    full_text[:2000],
                    alert.jugador.get("score_smoothed"),
                    chunks_ok,
                    chunks_total,
                ],
            )

            logger.info(
                f"alert sent: {alert.alert_type} for {alert.jugador_id[:8]} "
                f"chunks={chunks_ok}/{chunks_total}"
            )
            return sent_ok

        except Exception as exc:
            logger.error(f"alert send failed {alert.alert_type} {alert.jugador_id[:8]}: {exc}")
            return False

    async def process_events_and_send(self, events: list[dict[str, Any]]) -> dict[str, int]:
        """Process a list of eventos_pending rows and dispatch alerts.

        Returns {alerts_generated, alerts_sent, alerts_deduped, errors}.
        """
        generated = sent = deduped = errors = 0

        for event in events:
            try:
                payload = json.loads(event.get("payload") or "{}")
                jugador_id = payload.get("jugador_id")
                if not jugador_id:
                    continue

                # Fetch current jugador state
                rows = await self._db.execute(
                    "SELECT * FROM jugadores WHERE jugador_id = ?", [jugador_id]
                )
                if not rows:
                    continue
                jugador = rows[0]
                jugador["flags"] = json.loads(jugador.get("flags") or "[]")
                jugador["factores_actuales"] = json.loads(jugador.get("factores_actuales") or "{}")

                score_nuevo = jugador.get("score_smoothed", 0.0)
                score_anterior = payload.get("score_anterior", score_nuevo)
                factores_ant = payload.get("factores_anteriores", {})
                hard_signals = payload.get("hard_signals", [])

                alerts = self.detect_alert_triggers(
                    jugador_id=jugador_id,
                    score_anterior=score_anterior,
                    score_nuevo=score_nuevo,
                    factores_anteriores=factores_ant,
                    factores_nuevos=jugador["factores_actuales"],
                    hard_signals=hard_signals,
                    jugador=jugador,
                    ranking_anterior=payload.get("ranking_anterior"),
                    ranking_nuevo=payload.get("ranking_nuevo"),
                    nuevo_periodista_tier_s=payload.get("nuevo_periodista_tier_s"),
                    rumores_previos_count=payload.get("rumores_previos_count", 0),
                )

                generated += len(alerts)
                for alert in alerts:
                    ok = await self.send_alert(alert)
                    if ok:
                        sent += 1
                    else:
                        deduped += 1

            except Exception as exc:
                errors += 1
                logger.error(f"process_events error on event {event.get('evento_id', '?')}: {exc}")

        return {"generated": generated, "sent": sent, "deduped": deduped, "errors": errors}
