"""Extraction pipeline: prefilter → regex/lexicon → Gemini fallback."""

from __future__ import annotations

from typing import Any

from loguru import logger

from fichajes_bot.persistence.d1_client import D1Client


class ExtractionPipeline:
    def __init__(self, db: D1Client) -> None:
        self.db = db

    async def process(self, raw: dict[str, Any]) -> dict[str, Any] | None:
        """Process a raw rumor. Returns extracted rumor dict or None if discarded."""
        text = raw.get("texto_completo") or raw.get("titulo") or ""
        if not text.strip():
            return None

        # Phase 1: prefilter (RM keywords check)
        from fichajes_bot.extraction.prefilter import prefilter
        if not prefilter(text):
            return None

        # Phase 2: regex extractor
        from fichajes_bot.extraction.regex_extractor import RegexExtractor
        extractor = RegexExtractor()
        result = extractor.extract(text, raw.get("idioma_detectado", "es"))

        if result and result.get("confianza", 0) >= 0.6:
            result["extraido_con"] = "regex"
            result["raw_id"] = raw["raw_id"]
            return result

        # Phase 3: Gemini fallback for ambiguous content
        from fichajes_bot.extraction.gemini_client import GeminiClient
        try:
            gemini = GeminiClient(self.db)
            result = await gemini.extract(text, raw.get("idioma_detectado", "es"))
            if result:
                result["extraido_con"] = "gemini"
                result["raw_id"] = raw["raw_id"]
                return result
        except Exception as exc:
            logger.warning(f"Gemini extraction failed: {exc}")
            if result:
                result["extraido_con"] = "regex"
                result["raw_id"] = raw["raw_id"]
                return result

        return None
