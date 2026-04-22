"""Extraction pipeline: prefilter → language → lexicon+regex → Gemini fallback.

Pipeline steps:
  1. Prefilter — fast RM + transfer keyword check (no DB)
  2. Language detection — langdetect + heuristics
  3. Lexicon match — Aho-Corasick from DB entries (cached per instance)
  4. Regex extract — multi-language patterns
  5. Confidence compute — combine regex + lexicon
  6. If confidence >= THRESHOLD (0.60): accept without LLM
  7. Else: Gemini Flash extraction
  8. Fallback: if GeminiBudgetExceeded or Gemini disabled → accept regex result if any
  9. Persist: insert/update rumores + jugadores tables

Returns: dict with extraction result, or None if discarded.
"""

from __future__ import annotations

import json
import uuid
from typing import Any, Optional

from loguru import logger

from fichajes_bot.calibration.reliability_manager import ReliabilityManager
from fichajes_bot.extraction.confidence import THRESHOLD, compute_confidence, needs_llm
from fichajes_bot.extraction.gemini_client import GeminiBudgetExceeded, GeminiClient
from fichajes_bot.extraction.language_detect import detect as detect_language
from fichajes_bot.extraction.lexicon_matcher import LexiconMatcher
from fichajes_bot.extraction.prefilter import prefilter
from fichajes_bot.extraction.regex_extractor import RegexExtractor
from fichajes_bot.persistence.d1_client import D1Client
from fichajes_bot.utils.helpers import now_iso, slugify


class ExtractionPipeline:
    """One instance per job run. Lexicon is loaded once per instance."""

    def __init__(self, db: D1Client) -> None:
        self.db = db
        self._lexicon: Optional[LexiconMatcher] = None
        self._regex = RegexExtractor()
        self._gemini = GeminiClient(db)
        self._reliability: Optional[ReliabilityManager] = None
        self._retraction_handler = None
        self._hard_signal_detector = None
        self._last_reject_reason: str = ""

    async def get_reliability_manager(self) -> ReliabilityManager:
        """Lazy-initialised ReliabilityManager for use by downstream sessions."""
        if self._reliability is None:
            self._reliability = ReliabilityManager(self.db)
        return self._reliability

    # ── Lexicon (lazy, cached) ────────────────────────────────────────────────

    async def _get_lexicon(self) -> LexiconMatcher:
        if self._lexicon is not None:
            return self._lexicon
        entries = await self.db.execute(
            "SELECT frase, idioma, categoria, fase_rumor, tipo_operacion, "
            "peso_base, peso_aprendido FROM lexicon_entries"
        )
        m = LexiconMatcher()
        m.load_from_list(entries)
        self._lexicon = m
        return m

    # ── Main process ──────────────────────────────────────────────────────────

    async def process(self, raw: dict[str, Any]) -> Optional[dict[str, Any]]:
        """Process one raw rumor. Returns extraction dict or None."""
        rid = (raw.get("raw_id") or "?")[:8]
        fuente = raw.get("fuente_id", "?")

        text = (raw.get("texto_completo") or raw.get("titulo") or "").strip()
        if not text:
            logger.debug(f"[{rid}] SKIP empty_text fuente={fuente}")
            self._last_reject_reason = "empty_text"
            return None

        # ── Step 1: Prefilter ────────────────────────────────────────────────
        if not prefilter(text):
            logger.debug(f"[{rid}] SKIP prefilter fuente={fuente} title={raw.get('titulo','')[:60]!r}")
            self._last_reject_reason = "prefilter"
            return None

        logger.debug(f"[{rid}] PASS prefilter fuente={fuente}")

        # ── Step 2: Language ─────────────────────────────────────────────────
        idioma = raw.get("idioma_detectado") or detect_language(text)

        # ── Step 3: Lexicon ──────────────────────────────────────────────────
        lexicon = await self._get_lexicon()
        lex_matches = lexicon.match(text, idioma)
        lex_weight = lexicon.compute_weight(lex_matches)
        lex_tipo = lexicon.best_tipo(lex_matches)
        lex_fase = lexicon.best_fase(lex_matches)

        # ── Step 4: Regex ────────────────────────────────────────────────────
        regex_result = self._regex.extract(text, idioma)

        # ── Step 5: Confidence ───────────────────────────────────────────────
        conf = compute_confidence(
            regex_confianza=regex_result.confianza if regex_result else None,
            lexicon_weight=lex_weight,
            n_lexicon_matches=len(lex_matches),
            negation_found=regex_result.negation_found if regex_result else False,
        )

        # Determine tipo from best available signal
        tipo = (
            (regex_result.tipo_operacion if regex_result else None)
            or lex_tipo
        )

        logger.debug(
            f"[{rid}] conf={conf:.2f} tipo={tipo} "
            f"lex_matches={len(lex_matches)} regex={'OK' if regex_result else 'None'} "
            f"jugador={getattr(regex_result, 'jugador_nombre', None)!r}"
        )

        if not tipo and conf < 0.3:
            logger.debug(f"[{rid}] SKIP no_signal conf={conf:.2f} tipo=None")
            self._last_reject_reason = "no_signal"
            return None

        # ── Step 6: Accept regex without LLM ─────────────────────────────────
        if conf >= THRESHOLD and tipo:
            logger.info(f"[{rid}] ACCEPT regex conf={conf:.2f} tipo={tipo} jugador={getattr(regex_result, 'jugador_nombre', None)!r}")
            result = self._build_result(
                raw, regex_result, lex_matches, lex_weight, lex_fase,
                tipo, idioma, conf, "regex",
            )
            await self._persist(result)
            await self._post_process(result)
            return result

        # ── Step 7: Gemini fallback ───────────────────────────────────────────
        logger.debug(f"[{rid}] calling Gemini conf={conf:.2f} tipo={tipo}")
        gemini_result: Optional[dict] = None
        try:
            gemini_result = await self._gemini.extract(text, idioma)
        except GeminiBudgetExceeded as exc:
            logger.warning(f"Gemini budget exceeded: {exc}")
        except Exception as exc:
            logger.warning(f"Gemini unexpected error: {exc}")

        if gemini_result:
            logger.debug(f"[{rid}] Gemini → es_rm={gemini_result.get('es_real_madrid')} tipo={gemini_result.get('tipo_operacion')} jugador={gemini_result.get('jugador_nombre')!r}")

        if gemini_result and gemini_result.get("es_real_madrid"):
            logger.info(f"[{rid}] ACCEPT gemini jugador={gemini_result.get('jugador_nombre')!r}")
            result = self._build_from_gemini(raw, gemini_result, lex_weight, idioma)
            await self._persist(result)
            await self._post_process(result)
            return result

        # ── Step 8: Fallback — accept weak regex if tipo is known ─────────────
        if tipo and (regex_result or lex_tipo):
            logger.info(f"[{rid}] ACCEPT fallback conf={conf:.2f} tipo={tipo} jugador={getattr(regex_result, 'jugador_nombre', None)!r}")
            result = self._build_result(
                raw, regex_result, lex_matches, lex_weight, lex_fase,
                tipo, idioma, conf, "regex",
            )
            await self._persist(result)
            await self._post_process(result)
            return result

        logger.debug(f"[{rid}] SKIP no_extraction conf={conf:.2f} tipo={tipo} gemini={'no_rm' if gemini_result else 'None'}")
        self._last_reject_reason = "no_extraction"
        return None

    # ── Result builders ───────────────────────────────────────────────────────

    def _build_result(
        self,
        raw: dict,
        regex_result: Any,
        lex_matches: list[dict],
        lex_weight: float,
        lex_fase: Optional[int],
        tipo: str,
        idioma: str,
        confianza: float,
        extraido_con: str,
    ) -> dict[str, Any]:
        fase = (
            (regex_result.fase_rumor if regex_result else None)
            or lex_fase
            or 1
        )
        lexico = (
            (regex_result.lexico_detectado if regex_result else None)
            or (lex_matches[0]["frase"] if lex_matches else None)
        )
        jugador_nombre = regex_result.jugador_nombre if regex_result else None
        club_destino = regex_result.club_destino if regex_result else None

        return {
            "rumor_id": str(uuid.uuid4()),
            "raw_id": raw.get("raw_id"),
            "fuente_id": raw.get("fuente_id"),
            "tipo_operacion": tipo,
            "fase_rumor": fase,
            "lexico_detectado": lexico,
            "peso_lexico": round(lex_weight or confianza, 4),
            "confianza_extraccion": round(confianza, 4),
            "extraido_con": extraido_con,
            "idioma": idioma,
            "texto_fragmento": (raw.get("titulo") or "")[:300],
            "jugador_nombre": jugador_nombre,
            "club_destino": club_destino,
            "fecha_publicacion": raw.get("fecha_publicacion"),
        }

    def _build_from_gemini(
        self,
        raw: dict,
        gr: dict,
        lex_weight: float,
        idioma: str,
    ) -> dict[str, Any]:
        return {
            "rumor_id": str(uuid.uuid4()),
            "raw_id": raw.get("raw_id"),
            "fuente_id": raw.get("fuente_id"),
            "tipo_operacion": gr.get("tipo_operacion"),
            "fase_rumor": gr.get("fase_rumor") or 1,
            "lexico_detectado": gr.get("lexico_detectado"),
            "peso_lexico": round(max(float(gr.get("confianza") or 0), lex_weight), 4),
            "confianza_extraccion": round(float(gr.get("confianza") or 0.5), 4),
            "extraido_con": "gemini",
            "idioma": idioma,
            "texto_fragmento": (raw.get("titulo") or "")[:300],
            "jugador_nombre": gr.get("jugador_nombre"),
            "club_destino": gr.get("club_destino"),
            "fecha_publicacion": raw.get("fecha_publicacion"),
        }

    # ── Post-processing (Session 7 detectors) ────────────────────────────────

    async def _post_process(self, result: dict[str, Any]) -> None:
        """Run retraction detection and hard signal detection after extraction."""
        from fichajes_bot.detectors.retraction_handler import RetractionHandler
        from fichajes_bot.detectors.hard_signal_detector import HardSignalDetector

        if self._retraction_handler is None:
            self._retraction_handler = RetractionHandler(self.db)
        if self._hard_signal_detector is None:
            self._hard_signal_detector = HardSignalDetector(self.db)

        # Retraction detection — only if there's an identified player
        if result.get("jugador_id"):
            try:
                await self._retraction_handler.detect_retraction(result)
            except Exception as exc:
                logger.warning(f"RetractionHandler error: {exc}")

        # Hard signal detection — sync regex, then async persist if found
        tipo_señal = self._hard_signal_detector.detect(result)
        if tipo_señal:
            try:
                await self._hard_signal_detector.persist_signal(
                    rumor_id=result.get("rumor_id", ""),
                    jugador_id=result.get("jugador_id"),
                    tipo_señal=tipo_señal,
                )
            except Exception as exc:
                logger.warning(f"HardSignalDetector persist error: {exc}")

    # ── Persistence ───────────────────────────────────────────────────────────

    async def _persist(self, result: dict[str, Any]) -> None:
        """Insert rumor into DB and upsert jugador."""
        jugador_id = await self._upsert_jugador(result)
        result["jugador_id"] = jugador_id

        # Get periodista_id from fuente if available
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

        # Enqueue scoring event
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
        """Find or create a jugador by name. Returns jugador_id or None.

        Auto-creates only when confianza >= 0.6 — low-confidence extractions
        should not pollute the jugadores table with false positives.
        """
        nombre = result.get("jugador_nombre")
        if not nombre:
            return None

        sl = slugify(nombre)

        # Try exact slug match first
        rows = await self.db.execute(
            "SELECT jugador_id FROM jugadores WHERE slug=? LIMIT 1", [sl]
        )
        if rows:
            return rows[0]["jugador_id"]

        # Try fuzzy match via LIKE
        rows = await self.db.execute(
            "SELECT jugador_id FROM jugadores "
            "WHERE LOWER(nombre_canonico) LIKE LOWER(?) LIMIT 1",
            [f"%{nombre[:15]}%"],
        )
        if rows:
            return rows[0]["jugador_id"]

        # Only auto-create with sufficient extraction confidence
        conf = result.get("confianza_extraccion") or 0.0
        if conf < 0.6:
            logger.debug(
                f"_upsert_jugador: skip auto-create '{nombre}' "
                f"conf={conf:.2f} < 0.60"
            )
            return None

        # Detect entidad from title/fragment text
        texto = (result.get("texto_fragmento") or "").lower()
        entidad = (
            "castilla"
            if any(kw in texto for kw in ("castilla", "filial", "rm castilla", "real madrid castilla"))
            else "primer_equipo"
        )

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
            [jid, nombre, sl, tipo, entidad],
        )
        logger.info(
            f"Auto-created jugador: '{nombre}' tipo={tipo} entidad={entidad} "
            f"conf={conf:.2f} ({jid[:8]}…)"
        )
        return jid


from typing import Optional  # noqa: E402
