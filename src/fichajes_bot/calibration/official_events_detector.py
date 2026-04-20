"""OfficialEventsDetector — converts hard-signal rumors into outcome records.

Logic
─────
A rumor carries a "hard signal" when:
  a) Its `flags` JSON array contains 'FICHAJE_OFICIAL' or 'SALIDA_OFICIAL', OR
  b) The `periodista_id` is 'marca-rm-oficial' (Real Madrid official communications), OR
  c) The `fuente_id` is 'realmadrid_noticias_rss' or 'realmadrid_oficial'

When such a rumor is found for a jugador that has no `outcome_clasificado` yet:
  1. Infer outcome type from the signal and rumor's tipo_operacion
  2. UPDATE jugadores: set outcome_clasificado + fecha_outcome + fuente_confirmacion
  3. INSERT into outcomes_historicos
  4. UPDATE rumores for this jugador: set outcome='CONFIRMADO' where tipo matches,
     set outcome='FALLIDO' for rumores that contradict (e.g. SALIDA rumors when outcome is FICHAJE)
  5. Idempotent: re-running on the same jugador is safe.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any

from loguru import logger

from fichajes_bot.persistence.d1_client import D1Client

# Periodistas and fuentes treated as "official RM sources"
_OFFICIAL_PERIODISTAS = {"marca-rm-oficial"}
_OFFICIAL_FUENTES = {"realmadrid_noticias_rss", "realmadrid_oficial", "realmadrid_canteras_rss"}

# Flags from HardSignalDetector that indicate a completed transfer
_FLAGS_FICHAJE = {"FICHAJE_OFICIAL"}
_FLAGS_SALIDA = {"SALIDA_OFICIAL"}


def _parse_flags(raw: Any) -> set[str]:
    if isinstance(raw, (list, set)):
        return set(raw)
    if isinstance(raw, str):
        try:
            return set(json.loads(raw))
        except Exception:
            return set()
    return set()


def _infer_outcome(flags: set[str], tipo_operacion: str | None) -> str | None:
    """Determine outcome_clasificado from signal type and rumor's tipo_operacion."""
    if flags & _FLAGS_FICHAJE:
        if tipo_operacion in ("FICHAJE", None):
            return "FICHAJE_EFECTIVO"
        if tipo_operacion == "RENOVACION":
            return "RENOVACION_EFECTIVA"
        if tipo_operacion == "CESION":
            return "CESION_EFECTIVA"
        return "FICHAJE_EFECTIVO"

    if flags & _FLAGS_SALIDA:
        if tipo_operacion == "CESION":
            return "CESION_EFECTIVA"
        return "SALIDA_EFECTIVA"

    # Official source with no explicit flag — use tipo_operacion
    if tipo_operacion == "FICHAJE":
        return "FICHAJE_EFECTIVO"
    if tipo_operacion == "SALIDA":
        return "SALIDA_EFECTIVA"
    if tipo_operacion == "RENOVACION":
        return "RENOVACION_EFECTIVA"
    if tipo_operacion == "CESION":
        return "CESION_EFECTIVA"
    return None


class OfficialEventsDetector:
    """Detect official transfer confirmations and update outcome records."""

    def __init__(self, db: D1Client) -> None:
        self.db = db

    async def scan_recent_rumors(self, window_days: int = 30) -> int:
        """Scan recent hard-signal rumors and create outcome records.

        Returns number of new outcomes created.
        """
        # Fetch rumores with hard-signal flags or official sources, no existing outcome
        candidate_rumors = await self.db.execute(
            """
            SELECT r.rumor_id, r.jugador_id, r.periodista_id, r.fuente_id,
                   r.tipo_operacion, r.flags, r.club_destino, r.fecha_publicacion,
                   j.outcome_clasificado, j.nombre_canonico
            FROM rumores r
            JOIN jugadores j ON r.jugador_id = j.jugador_id
            WHERE r.retractado = 0
              AND j.outcome_clasificado IS NULL
              AND r.fecha_publicacion >= datetime('now', ?)
            ORDER BY r.fecha_publicacion DESC
            """,
            [f"-{window_days} days"],
        )

        outcomes_created = 0

        for row in candidate_rumors:
            flags = _parse_flags(row.get("flags"))
            periodista_id = row.get("periodista_id") or ""
            fuente_id = row.get("fuente_id") or ""

            is_official = (
                bool(flags & (_FLAGS_FICHAJE | _FLAGS_SALIDA))
                or periodista_id in _OFFICIAL_PERIODISTAS
                or fuente_id in _OFFICIAL_FUENTES
            )

            if not is_official:
                continue

            outcome = _infer_outcome(flags, row.get("tipo_operacion"))
            if not outcome:
                continue

            jugador_id = row["jugador_id"]
            rumor_id = row["rumor_id"]
            fecha = row.get("fecha_publicacion") or datetime.now(timezone.utc).isoformat()
            nombre = row.get("nombre_canonico", "?")

            # Re-check idempotency (may have been set in a previous loop iteration)
            current = await self.db.execute(
                "SELECT outcome_clasificado FROM jugadores WHERE jugador_id=? LIMIT 1",
                [jugador_id],
            )
            if current and current[0].get("outcome_clasificado"):
                continue

            try:
                await self._create_outcome(
                    jugador_id=jugador_id,
                    outcome=outcome,
                    fecha=fecha,
                    club_destino=row.get("club_destino"),
                    fuente=periodista_id or fuente_id,
                    rumor_id_trigger=rumor_id,
                )
                outcomes_created += 1
                logger.info(
                    f"OfficialEventsDetector: {nombre} → {outcome} "
                    f"(trigger: {rumor_id[:8]})"
                )
            except Exception as exc:
                logger.error(
                    f"OfficialEventsDetector: failed to create outcome for "
                    f"jugador_id={jugador_id}: {exc}"
                )

        logger.info(f"OfficialEventsDetector: {outcomes_created} new outcomes created")
        return outcomes_created

    async def _create_outcome(
        self,
        jugador_id: str,
        outcome: str,
        fecha: str,
        club_destino: str | None,
        fuente: str,
        rumor_id_trigger: str | None,
    ) -> None:
        # 1. Update jugadores
        await self.db.execute(
            """UPDATE jugadores
               SET outcome_clasificado = ?,
                   fecha_outcome = ?,
                   fuente_confirmacion = ?,
                   ultima_actualizacion_at = datetime('now')
               WHERE jugador_id = ?""",
            [outcome, fecha, fuente, jugador_id],
        )

        # 2. Insert outcomes_historicos
        outcome_id = str(uuid.uuid4())
        await self.db.execute(
            """INSERT INTO outcomes_historicos
               (outcome_id, jugador_id, outcome_tipo, fecha,
                club_destino, fuente_confirmacion, rumor_id_trigger)
               VALUES (?,?,?,?,?,?,?)""",
            [outcome_id, jugador_id, outcome, fecha,
             club_destino, fuente, rumor_id_trigger],
        )

        # 3. Mark confirming rumors as CONFIRMADO, contradicting ones as FALLIDO
        outcome_tipo = _outcome_to_tipo(outcome)
        if outcome_tipo:
            await self.db.execute(
                """UPDATE rumores
                   SET outcome = 'CONFIRMADO', outcome_at = datetime('now')
                   WHERE jugador_id = ? AND tipo_operacion = ? AND retractado = 0""",
                [jugador_id, outcome_tipo],
            )
            await self.db.execute(
                """UPDATE rumores
                   SET outcome = 'FALLIDO', outcome_at = datetime('now')
                   WHERE jugador_id = ? AND tipo_operacion != ? AND retractado = 0
                     AND outcome IS NULL""",
                [jugador_id, outcome_tipo],
            )


def _outcome_to_tipo(outcome: str) -> str | None:
    mapping = {
        "FICHAJE_EFECTIVO": "FICHAJE",
        "SALIDA_EFECTIVA": "SALIDA",
        "RENOVACION_EFECTIVA": "RENOVACION",
        "CESION_EFECTIVA": "CESION",
    }
    return mapping.get(outcome)
