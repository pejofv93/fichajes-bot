"""Gemini 2.0 Flash Lite client.

Features:
  - SHA-256 cache in llm_cache table (TTL 7 days)
  - Daily budget counter: gemini_calls_YYYY-MM-DD  (auto-resets at midnight)
  - 4 s sleep before every real API call (respects 15 RPM free-tier limit)
  - GeminiBudgetExceeded raised when daily limit hit — caller must handle
  - Structured JSON response (response_mime_type)
"""

from __future__ import annotations

import asyncio
import json
import os
from datetime import date, datetime, timedelta, timezone
from typing import Any, Optional

from loguru import logger

from fichajes_bot.persistence.d1_client import D1Client
from fichajes_bot.utils.helpers import sha256_hash

GEMINI_DAILY_LIMIT = 1400   # leave 100 req margin over the 1500 free cap
GEMINI_RPM_SLEEP = 6.0      # seconds between real API calls (~10 RPM, avoids 429)
CACHE_TTL_DAYS = 7

_SIMPLE_PROMPT_TEMPLATE = """\
Football transfer news headline: '{titulo}'
Extract as JSON:
- player_name: full name of a real football player (null if not mentioned or if generic like 'target', 'star')
- operation_type: 'FICHAJE' if player joining Real Madrid, 'SALIDA' if player leaving Real Madrid, null if unclear
- confidence: float 0-1
- is_real_madrid: true/false
IMPORTANT: Do NOT extract coaches, managers or technical staff (e.g. Xabi Alonso, Carlo Ancelotti, Pep Guardiola, Jose Mourinho). Only extract outfield players or goalkeepers. Also do NOT extract players who are currently at Spanish rival clubs (Barcelona, Atletico Madrid) as loan players.
Return only valid JSON, no other text."""

_PROMPT_TEMPLATE = """\
You are a football transfer news analyst. Extract Real Madrid transfer information from the text below.

Text (language: {idioma}):
\"\"\"
{text}
\"\"\"

Respond ONLY with a single JSON object — no markdown, no explanation:
{{
  "es_real_madrid": true | false,
  "tipo_operacion": "FICHAJE" | "SALIDA" | "RENOVACION" | "CESION" | null,
  "jugador_nombre": "<name or null>",
  "club_destino": "<club or null>",
  "club_origen": "<club or null>",
  "fase_rumor": <1-6 or null>,
  "confianza": <0.0-1.0>,
  "lexico_detectado": "<key phrase or null>"
}}

Rules:
- es_real_madrid must be true for the result to be useful.
- jugador_nombre: extract ONLY a full proper name (first name + surname of a real person).
  If the article uses generic phrases like "Real Madrid target", "the player", "the star",
  "a forward", "Los Blancos target" instead of naming the player, return null.
- fase_rumor: 1=interest, 2=contacts, 3=negotiations, 4=personal agreement, 5=club agreement/medical, 6=confirmed.
- If unrelated to Real Madrid transfers: {{"es_real_madrid": false, "confianza": 0.0}}.
"""


class GeminiBudgetExceeded(Exception):
    pass


class GeminiClient:
    def __init__(self, db: D1Client) -> None:
        self.db = db
        # API key read lazily so tests can override via patch.dict after construction
        self._api_key: str = ""

    @property
    def _key(self) -> str:
        if self._api_key:
            return self._api_key
        return os.environ.get("GEMINI_API_KEY", "")

    # ── Budget management ─────────────────────────────────────────────────────

    def _today_key(self) -> str:
        return f"gemini_calls_{date.today().isoformat()}"

    async def get_daily_usage(self) -> int:
        rows = await self.db.execute(
            "SELECT value_num FROM metricas_sistema WHERE metric_name=? "
            "ORDER BY timestamp DESC LIMIT 1",
            [self._today_key()],
        )
        if rows and rows[0]["value_num"] is not None:
            return int(rows[0]["value_num"])
        return 0

    async def _increment_usage(self) -> None:
        import uuid
        current = await self.get_daily_usage()
        new_val = current + 1
        key = self._today_key()
        # Upsert by inserting a new row — latest row wins via ORDER BY timestamp DESC
        await self.db.execute(
            "INSERT INTO metricas_sistema (metric_id, metric_name, value, value_num, timestamp) "
            "VALUES (?,?,?,?,datetime('now'))",
            [str(uuid.uuid4()), key, str(new_val), float(new_val)],
        )
        # Also keep the legacy "gemini_calls_hoy" key for /status command
        await self.db.execute(
            "INSERT INTO metricas_sistema (metric_id, metric_name, value, value_num, timestamp) "
            "VALUES (?,?,?,?,datetime('now'))",
            [str(uuid.uuid4()), "gemini_calls_hoy", str(new_val), float(new_val)],
        )

    # ── Cache ─────────────────────────────────────────────────────────────────

    async def _cache_get(self, input_hash: str) -> Optional[dict]:
        rows = await self.db.execute(
            "SELECT response_json FROM llm_cache "
            "WHERE input_hash=? AND expires_at > datetime('now') LIMIT 1",
            [input_hash],
        )
        if not rows:
            return None
        try:
            return json.loads(rows[0]["response_json"])
        except Exception:
            return None

    async def _cache_set(self, input_hash: str, response: dict) -> None:
        expires = (datetime.now(timezone.utc) + timedelta(days=CACHE_TTL_DAYS)).isoformat()
        cache_id = sha256_hash(input_hash, "gemini-cache-v1")
        await self.db.execute(
            "INSERT OR REPLACE INTO llm_cache "
            "(cache_id, input_hash, modelo, response_json, created_at, expires_at) "
            "VALUES (?,?,?,?,datetime('now'),?)",
            [cache_id, input_hash, "gemini-2.0-flash-lite", json.dumps(response), expires],
        )

    # ── Main extract ─────────────────────────────────────────────────────────

    async def extract(self, text: str, idioma: str = "es") -> Optional[dict[str, Any]]:
        """Call Gemini to extract transfer info. Returns dict or None.

        Raises GeminiBudgetExceeded when daily limit is hit.
        """
        key = self._key
        if not key:
            logger.warning("GEMINI_API_KEY not set — skipping LLM extraction")
            return None
        logger.debug(f"Gemini key present len={len(key)} prefix={key[:4]!r}")

        # Canonical cache key: hash of first 2000 chars + language
        input_hash = sha256_hash(text[:2000], idioma)

        # Cache hit — free, no budget consumed
        cached = await self._cache_get(input_hash)
        if cached is not None:
            logger.debug(f"Gemini cache HIT | hash={input_hash[:12]}")
            return cached if cached.get("es_real_madrid") else None

        # Budget check
        usage = await self.get_daily_usage()
        if usage >= GEMINI_DAILY_LIMIT:
            raise GeminiBudgetExceeded(
                f"Daily Gemini budget exhausted: {usage}/{GEMINI_DAILY_LIMIT}"
            )

        # Rate-limit sleep (15 RPM = 1 call per 4s)
        await asyncio.sleep(GEMINI_RPM_SLEEP)

        logger.info(f"Gemini INPUT | {text[:120]!r}")

        # Real API call
        result = await self._call_api(text, idioma)

        logger.info(f"Gemini OUTPUT | {json.dumps(result, ensure_ascii=False)}")

        if result is None:
            return None

        # Cache result regardless of es_real_madrid (to avoid re-calling on same text)
        await self._cache_set(input_hash, result)
        await self._increment_usage()

        if not result.get("es_real_madrid"):
            return None

        return result

    async def _call_api(self, text: str, idioma: str) -> Optional[dict]:
        try:
            import google.generativeai as genai  # type: ignore[import]
        except ImportError:
            logger.warning("google-generativeai not installed")
            return None

        try:
            genai.configure(api_key=self._key)
            model = genai.GenerativeModel(
                "gemini-2.0-flash-lite",
                generation_config=genai.GenerationConfig(
                    response_mime_type="application/json",
                    temperature=0.1,
                    max_output_tokens=512,
                ),
            )
            prompt = _PROMPT_TEMPLATE.format(
                idioma=idioma,
                text=text[:3000].replace('"""', "'''"),
            )
            # Run sync call in executor to avoid blocking the event loop
            response = await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: model.generate_content(prompt),
            )
            return json.loads(response.text)

        except json.JSONDecodeError as exc:
            logger.warning(f"Gemini returned invalid JSON: {exc}")
            return None
        except Exception as exc:
            logger.warning(f"Gemini API error ({type(exc).__name__}): {exc}")
            return None


    async def extract_simple(self, titulo: str) -> Optional[dict[str, Any]]:
        """Call Gemini with simple title-only prompt. Returns dict or None.

        Raises GeminiBudgetExceeded when daily limit is hit.
        Uses fields: player_name, operation_type, confidence, is_real_madrid.
        """
        key = self._key
        if not key:
            logger.warning("GEMINI_API_KEY not set — skipping LLM extraction")
            return None

        input_hash = sha256_hash(titulo[:500], "simple-v2")

        cached = await self._cache_get(input_hash)
        if cached is not None:
            logger.debug(f"Gemini cache HIT | hash={input_hash[:12]}")
            return cached if cached.get("is_real_madrid") else None

        usage = await self.get_daily_usage()
        if usage >= GEMINI_DAILY_LIMIT:
            raise GeminiBudgetExceeded(
                f"Daily Gemini budget exhausted: {usage}/{GEMINI_DAILY_LIMIT}"
            )

        await asyncio.sleep(GEMINI_RPM_SLEEP)

        logger.info(f"Gemini INPUT | {titulo!r}")

        result = await self._call_simple_api(titulo)

        logger.info(f"Gemini OUTPUT | {json.dumps(result, ensure_ascii=False)}")

        if result is None:
            return None

        await self._cache_set(input_hash, result)
        await self._increment_usage()

        if not result.get("is_real_madrid"):
            return None

        return result

    async def _call_simple_api(self, titulo: str) -> Optional[dict]:
        try:
            import google.generativeai as genai  # type: ignore[import]
        except ImportError:
            logger.warning("google-generativeai not installed")
            return None

        try:
            genai.configure(api_key=self._key)
            model = genai.GenerativeModel(
                "gemini-2.0-flash-lite",
                generation_config=genai.GenerationConfig(
                    response_mime_type="application/json",
                    temperature=0.1,
                    max_output_tokens=200,
                ),
            )
            prompt = _SIMPLE_PROMPT_TEMPLATE.format(
                titulo=titulo.replace("'", "\\'")
            )
            response = await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: model.generate_content(prompt),
            )
            return json.loads(response.text)

        except json.JSONDecodeError as exc:
            logger.warning(f"Gemini simple returned invalid JSON: {exc}")
            return None
        except Exception as exc:
            logger.warning(f"Gemini simple API error ({type(exc).__name__}): {exc}")
            return None


from typing import Optional  # noqa: E402
