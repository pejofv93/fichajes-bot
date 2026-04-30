"""Extraction pipeline: prefilter → Gemini direct.

Steps:
  1. Prefilter — check text for Real Madrid identifiers (no DB)
  2. Gemini — send title with simple prompt, get player + operation
  3. If player_name != null AND confidence >= 0.5 AND is_real_madrid → persist
"""

from __future__ import annotations

import json
import re
import uuid
from typing import Any, Optional

from loguru import logger

from fichajes_bot.extraction.gemini_client import GeminiBudgetExceeded, GeminiClient
from fichajes_bot.persistence.d1_client import D1Client
from fichajes_bot.utils.helpers import slugify

_RM_RE = re.compile(
    r"real\s+madrid|los\s+blancos|\brm\b",
    re.IGNORECASE,
)


class ExtractionPipeline:
    """One instance per job run."""

    def __init__(self, db: D1Client) -> None:
        self.db = db
        self._gemini = GeminiClient(db)
        self._last_reject_reason: str = ""

    async def process(self, raw: dict[str, Any]) -> Optional[dict[str, Any]]:
        """Process one raw rumor. Returns extraction dict or None."""
        rid = (raw.get("raw_id") or "?")[:8]

        titulo = raw.get("titulo") or ""
        texto = raw.get("texto_completo") or ""
        text = f"{titulo} {texto}".strip()

        # Step 1: Prefilter
        if not _RM_RE.search(text):
            logger.debug(f"[{rid}] SKIP prefilter title={titulo[:60]!r}")
            self._last_reject_reason = "prefilter"
            return None

        # Step 2: Gemini direct on title
        gemini_result: Optional[dict] = None
        try:
            gemini_result = await self._gemini.extract_simple(titulo)
        except GeminiBudgetExceeded as exc:
            logger.warning(f"Gemini budget exceeded: {exc}")
            self._last_reject_reason = "budget_exceeded"
            return None
        except Exception as exc:
            logger.warning(f"Gemini error: {exc}")
            self._last_reject_reason = "gemini_error"
            return None

        if not gemini_result:
            logger.debug(f"[{rid}] SKIP no_gemini_result")
            self._last_reject_reason = "no_gemini_result"
            return None

        player_name = gemini_result.get("player_name")
        confidence = float(gemini_result.get("confidence") or 0)
        is_real_madrid = bool(gemini_result.get("is_real_madrid"))
        operation_type = gemini_result.get("operation_type")

        # Step 3: Accept or discard
        if not player_name or confidence < 0.5 or not is_real_madrid:
            logger.debug(
                f"[{rid}] SKIP player={player_name!r} conf={confidence:.2f} is_rm={is_real_madrid}"
            )
            self._last_reject_reason = "no_player" if not player_name else "low_confidence"
            return None

        result = {
            "rumor_id": str(uuid.uuid4()),
            "raw_id": raw.get("raw_id"),
            "fuente_id": raw.get("fuente_id"),
            "tipo_operacion": operation_type,
            "fase_rumor": 1,
            "lexico_detectado": None,
            "peso_lexico": round(confidence, 4),
            "confianza_extraccion": round(confidence, 4),
            "extraido_con": "gemini",
            "idioma": raw.get("idioma_detectado") or "es",
            "texto_fragmento": titulo[:300],
            "jugador_nombre": player_name,
            "club_destino": None,
            "fecha_publicacion": raw.get("fecha_publicacion"),
        }

        logger.info(
            f"[{rid}] ACCEPT player={player_name!r} tipo={operation_type} conf={confidence:.2f}"
        )
        await self._persist(result)
        return result

    async def _persist(self, result: dict[str, Any]) -> None:
        """Insert rumor into DB and upsert jugador."""
        jugador_id = await self._upsert_jugador(result)
        result["jugador_id"] = jugador_id

        periodista_id: Optional[str] = None
        if result.get("fuente_id"):
            rows = await self.db.execute(
                "SELECT periodista_id FROM fuentes WHERE fuente_id=?",
                [result["fuente_id"]],
            )
            if rows and rows[0].get("periodista_id"):
                periodista_id = rows[0]["periodista_id"]

        await self.db.execute(
            """INSERT OR IGNORE INTO rumores
               (rumor_id, raw_id, jugador_id, periodista_id, fuente_id,
                tipo_operacion, club_destino, fase_rumor,
                lexico_detectado, peso_lexico, confianza_extraccion,
                extraido_con, fecha_publicacion, idioma, texto_fragmento,
                created_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,datetime('now'))""",
            [
                result["rumor_id"],
                result.get("raw_id"),
                jugador_id,
                periodista_id,
                result.get("fuente_id"),
                result.get("tipo_operacion"),
                result.get("club_destino"),
                result.get("fase_rumor", 1),
                result.get("lexico_detectado"),
                result.get("peso_lexico", 0.0),
                result.get("confianza_extraccion", 0.0),
                result.get("extraido_con"),
                result.get("fecha_publicacion"),
                result.get("idioma"),
                result.get("texto_fragmento"),
            ],
        )

        await self.db.execute(
            "INSERT INTO eventos_pending (evento_id, tipo, payload) VALUES (?,?,?)",
            [
                str(uuid.uuid4()),
                "new_rumor",
                json.dumps({
                    "rumor_id": result["rumor_id"],
                    "jugador_id": jugador_id,
                }),
            ],
        )

    async def _upsert_jugador(self, result: dict[str, Any]) -> Optional[str]:
        """Find or create a jugador by name. Returns jugador_id or None."""
        nombre = result.get("jugador_nombre")
        if not nombre:
            return None

        sl = slugify(nombre)

        rows = await self.db.execute(
            "SELECT jugador_id FROM jugadores WHERE slug=? LIMIT 1", [sl]
        )
        if rows:
            return rows[0]["jugador_id"]

        rows = await self.db.execute(
            "SELECT jugador_id FROM jugadores "
            "WHERE LOWER(nombre_canonico) LIKE LOWER(?) LIMIT 1",
            [f"%{nombre[:15]}%"],
        )
        if rows:
            return rows[0]["jugador_id"]

        tipo = result.get("tipo_operacion") or "FICHAJE"
        jid = str(uuid.uuid4())
        await self.db.execute(
            """INSERT OR IGNORE INTO jugadores
               (jugador_id, nombre_canonico, slug, tipo_operacion_principal,
                entidad, score_raw, score_smoothed, kalman_P,
                flags, factores_actuales, n_rumores_total,
                primera_mencion_at, ultima_actualizacion_at,
                is_active, created_at)
               VALUES (?,?,?,?,?,0.01,0.01,1.0,'[]','{}',1,
                       datetime('now'),datetime('now'),1,datetime('now'))""",
            [jid, nombre, sl, tipo, "primer_equipo"],
        )
        logger.info(f"Auto-created jugador: '{nombre}' tipo={tipo} ({jid[:8]}…)")
        return jid
