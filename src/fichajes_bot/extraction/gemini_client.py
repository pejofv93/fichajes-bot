"""Gemini Flash client with caching, budget management, and rate limiting."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
from datetime import datetime, timedelta, timezone
from typing import Any

from loguru import logger

from fichajes_bot.persistence.d1_client import D1Client
from fichajes_bot.utils.helpers import sha256_hash

GEMINI_DAILY_LIMIT = 1400
GEMINI_RPM_SLEEP = 4.0  # seconds between calls to respect 15 RPM

_EXTRACTION_PROMPT = """Analyze this text and extract Real Madrid transfer information.

Text: {text}

Respond ONLY with valid JSON:
{{
  "tipo_operacion": "FICHAJE" | "SALIDA" | "RENOVACION" | "CESION" | null,
  "jugador_nombre": string | null,
  "club_destino": string | null,
  "club_origen": string | null,
  "fase_rumor": 1-6 | null,
  "confianza": 0.0-1.0,
  "es_real_madrid": true | false,
  "lexico_detectado": string | null
}}

If not related to Real Madrid transfers, return {{"es_real_madrid": false, "confianza": 0.0}}.
"""


class GeminiBudgetExceeded(Exception):
    pass


class GeminiClient:
    def __init__(self, db: D1Client) -> None:
        self.db = db
        self._api_key = os.environ.get("GEMINI_API_KEY", "")

    async def _get_budget_today(self) -> int:
        rows = await self.db.execute(
            "SELECT value_num FROM metricas_sistema WHERE metric_name='gemini_calls_hoy' ORDER BY timestamp DESC LIMIT 1"
        )
        return int(rows[0]["value_num"]) if rows and rows[0]["value_num"] else 0

    async def _increment_budget(self) -> None:
        current = await self._get_budget_today()
        await self.db.execute(
            "INSERT INTO metricas_sistema (metric_id, metric_name, value, value_num) VALUES (?,?,?,?)",
            [sha256_hash("gemini_budget", str(datetime.now())), "gemini_calls_hoy", str(current + 1), float(current + 1)],
        )

    async def _check_cache(self, input_hash: str) -> dict | None:
        rows = await self.db.execute(
            "SELECT response_json FROM llm_cache WHERE input_hash=? AND expires_at > datetime('now') LIMIT 1",
            [input_hash],
        )
        if rows:
            try:
                return json.loads(rows[0]["response_json"])
            except Exception:
                return None
        return None

    async def _store_cache(self, input_hash: str, response: dict) -> None:
        expires = (datetime.now(timezone.utc) + timedelta(days=7)).isoformat()
        await self.db.execute(
            """INSERT OR REPLACE INTO llm_cache (cache_id, input_hash, modelo, response_json, created_at, expires_at)
               VALUES (?,?,?,?,datetime('now'),?)""",
            [sha256_hash(input_hash, "v1"), input_hash, "gemini-1.5-flash", json.dumps(response), expires],
        )

    async def extract(self, text: str, idioma: str = "es") -> dict[str, Any] | None:
        if not self._api_key:
            logger.warning("GEMINI_API_KEY not set")
            return None

        input_hash = sha256_hash(text[:2000], idioma)

        cached = await self._check_cache(input_hash)
        if cached:
            logger.debug("Gemini cache hit")
            return cached

        budget = await self._get_budget_today()
        if budget >= GEMINI_DAILY_LIMIT:
            raise GeminiBudgetExceeded(f"Gemini daily limit reached: {budget}/{GEMINI_DAILY_LIMIT}")

        await asyncio.sleep(GEMINI_RPM_SLEEP)

        try:
            import google.generativeai as genai
            genai.configure(api_key=self._api_key)
            model = genai.GenerativeModel(
                "gemini-1.5-flash",
                generation_config={"response_mime_type": "application/json"},
            )
            prompt = _EXTRACTION_PROMPT.format(text=text[:3000])
            response = await asyncio.get_event_loop().run_in_executor(
                None, lambda: model.generate_content(prompt)
            )
            result = json.loads(response.text)

            if not result.get("es_real_madrid"):
                return None

            await self._increment_budget()
            await self._store_cache(input_hash, result)
            return result

        except GeminiBudgetExceeded:
            raise
        except Exception as exc:
            logger.warning(f"Gemini API call failed: {exc}")
            return None
