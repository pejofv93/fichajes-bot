"""RetractionHandler — detects and processes rumor retractions.

A retraction occurs when a journalist (or a different source) publishes content
that explicitly contradicts a previously positive rumor about the same player.

detect_retraction(nuevo_rumor):
  1. Check texto_fragmento for negation/cancellation keywords
  2. If found: look for prior positive rumors from the same player + journalist
  3. Mark those prior rumors as retractado=1
  4. Insert record in retractaciones table
  5. Enqueue 'retraction' event in eventos_pending (triggers urgent score recompute)

evaluate(jugador_id) → factor_retractacion in [0.4, 1.0]:
  0 retractions in 30d         → 1.0  (no penalisation)
  ≥1 tier-S retraction in 30d  → 0.6
  ≥2 any retraction in 30d     → 0.4
"""

from __future__ import annotations

import json
import re
import uuid
from typing import Optional

from loguru import logger

from fichajes_bot.persistence.d1_client import D1Client

FACTOR_NO_RETRACTION  = 1.00
FACTOR_ONE_TIER_S     = 0.60
FACTOR_TWO_OR_MORE    = 0.40

_RETRACTION_KEYWORDS = [
    # English
    "not happening", "won't happen", "no deal", "deal off", "deal collapsed",
    "no agreement", "cancelled", "canceled", "no transfer", "not true",
    "denies", "denied", "false report",
    # Spanish
    "no fichará", "no hay acuerdo", "descartado", "se cancela", "operación descartada",
    "no llegará", "no hay nada", "no hay ningún acuerdo", "completamente falso",
    "nunca hubo", "fuera del mercado", "descartado definitivamente",
    "no se producirá", "no es cierto", "mentira",
    # Italian/German (common in RM coverage)
    "non si farà", "affare saltato", "kein deal", "abgesagt",
]

_POSITIVE_TIPOS = ("FICHAJE", "RENOVACION", "CESION")


class RetractionHandler:
    """Detects and processes contradictions in the rumor stream."""

    def __init__(self, db: D1Client) -> None:
        self.db = db

    # ── Detection ─────────────────────────────────────────────────────────────

    async def detect_retraction(self, nuevo_rumor: dict) -> bool:
        """Check if nuevo_rumor contradicts previous rumors for the same player.

        Returns True if at least one prior rumor was retracted.
        """
        texto = (nuevo_rumor.get("texto_fragmento") or "").lower()
        if not self._has_retraction_keywords(texto):
            return False

        jugador_id = nuevo_rumor.get("jugador_id")
        periodista_id = nuevo_rumor.get("periodista_id")

        if not jugador_id:
            return False

        # If the new rumor itself has no periodista, try resolving from fuente
        if not periodista_id and nuevo_rumor.get("fuente_id"):
            rows = await self.db.execute(
                "SELECT periodista_id FROM fuentes WHERE fuente_id=? LIMIT 1",
                [nuevo_rumor["fuente_id"]],
            )
            if rows:
                periodista_id = rows[0].get("periodista_id")

        # Find positive prior rumors from same player (+ same journalist if known)
        if periodista_id:
            prior_rumors = await self.db.execute(
                """SELECT rumor_id, periodista_id, tipo_operacion, fecha_publicacion
                   FROM rumores
                   WHERE jugador_id = ?
                     AND periodista_id = ?
                     AND retractado = 0
                     AND tipo_operacion IN ('FICHAJE', 'RENOVACION', 'CESION')
                     AND rumor_id != ?
                   ORDER BY fecha_publicacion DESC""",
                [jugador_id, periodista_id, nuevo_rumor.get("rumor_id", "")],
            )
        else:
            # Broader: any positive rumor for this player in last 30 days
            prior_rumors = await self.db.execute(
                """SELECT rumor_id, periodista_id, tipo_operacion, fecha_publicacion
                   FROM rumores
                   WHERE jugador_id = ?
                     AND retractado = 0
                     AND tipo_operacion IN ('FICHAJE', 'RENOVACION', 'CESION')
                     AND fecha_publicacion >= datetime('now', '-30 days')
                     AND rumor_id != ?
                   ORDER BY fecha_publicacion DESC""",
                [jugador_id, nuevo_rumor.get("rumor_id", "")],
            )

        if not prior_rumors:
            return False

        retracted_any = False
        for prior in prior_rumors:
            await self._mark_retracted(
                prior_rumor_id=prior["rumor_id"],
                jugador_id=jugador_id,
                periodista_id=prior.get("periodista_id"),
                nuevo_rumor=nuevo_rumor,
            )
            retracted_any = True

        if retracted_any:
            # Enqueue urgent score recompute event
            await self.db.execute(
                """INSERT INTO eventos_pending (evento_id, tipo, payload)
                   VALUES (?,?,?)""",
                [
                    str(uuid.uuid4()),
                    "retraction",
                    json.dumps({
                        "jugador_id": jugador_id,
                        "urgente": True,
                        "retraction_rumor_id": nuevo_rumor.get("rumor_id"),
                    }),
                ],
            )
            logger.info(
                f"RetractionHandler: retraction detected for "
                f"jugador={jugador_id[:8]} "
                f"({len(prior_rumors)} prior rumores marked retractado)"
            )

        return retracted_any

    def _has_retraction_keywords(self, texto: str) -> bool:
        return any(kw in texto for kw in _RETRACTION_KEYWORDS)

    async def _mark_retracted(
        self,
        prior_rumor_id: str,
        jugador_id: str,
        periodista_id: Optional[str],
        nuevo_rumor: dict,
    ) -> None:
        """Mark a prior rumor as retracted and log the retraction."""
        await self.db.execute(
            """UPDATE rumores
               SET retractado = 1, retractado_at = datetime('now')
               WHERE rumor_id = ?""",
            [prior_rumor_id],
        )

        retractacion_id = str(uuid.uuid4())
        await self.db.execute(
            """INSERT OR IGNORE INTO retractaciones
               (retractacion_id, rumor_id, jugador_id, periodista_id,
                texto_retractacion, fuente_retractacion,
                fecha_retractacion, tipo, impacto_score, procesado, created_at)
               VALUES (?,?,?,?,?,?,datetime('now'),?,?,0,datetime('now'))""",
            [
                retractacion_id,
                prior_rumor_id,
                jugador_id,
                periodista_id,
                (nuevo_rumor.get("texto_fragmento") or "")[:400],
                nuevo_rumor.get("fuente_id") or nuevo_rumor.get("periodista_id"),
                "RETRACTACION_PERIODISTA",
                -0.30,
            ],
        )

    # ── Scoring factor ────────────────────────────────────────────────────────

    async def evaluate(self, jugador_id: str) -> float:
        """Return retraction penalisation factor for a player.

        Checks the last 30 days of retractaciones for this player.
        """
        rows = await self.db.execute(
            """SELECT r.retractacion_id, p.tier
               FROM retractaciones r
               LEFT JOIN periodistas p ON r.periodista_id = p.periodista_id
               WHERE r.jugador_id = ?
                 AND r.fecha_retractacion >= datetime('now', '-30 days')
               ORDER BY r.fecha_retractacion DESC""",
            [jugador_id],
        )

        if not rows:
            return FACTOR_NO_RETRACTION

        total = len(rows)
        tier_s_count = sum(1 for r in rows if r.get("tier") == "S")

        if total >= 2:
            logger.debug(
                f"RetractionHandler: {jugador_id[:8]} "
                f"{total} retractions → FACTOR_TWO_OR_MORE={FACTOR_TWO_OR_MORE}"
            )
            return FACTOR_TWO_OR_MORE

        if tier_s_count >= 1:
            logger.debug(
                f"RetractionHandler: {jugador_id[:8]} "
                f"{tier_s_count} tier-S retraction → FACTOR_ONE_TIER_S={FACTOR_ONE_TIER_S}"
            )
            return FACTOR_ONE_TIER_S

        # 1 retraction but not tier-S → mild penalty
        return 0.80
