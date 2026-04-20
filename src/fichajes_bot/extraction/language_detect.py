"""Language detection — langdetect with script-based fallback.

Returns a 2-letter ISO code: 'es', 'en', 'it', 'de', 'fr'.
Unknown/unsupported languages fall back to 'es'.
"""

from __future__ import annotations

import re

_SUPPORTED = frozenset({"es", "en", "it", "de", "fr"})
_DEFAULT = "es"

# Fast heuristic patterns applied before langdetect for known phrases
_HEURISTICS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"\bhere\s+we\s+go\b|\bdone\s+deal\b|\bfee\s+agreed\b", re.I), "en"),
    (re.compile(r"\baquí\s+vamos\b|\bcontrato\s+firmado\b|\bacuerdo\s+cerrado\b", re.I), "es"),
    (re.compile(r"\baccordo\s+trovato\b|\bfumata\s+bianca\b|\bvisite\s+mediche\b", re.I), "it"),
    (re.compile(r"\beinigung\s+erzielt\b|\bdeal\s+perfekt\b|\bmedizincheck\b", re.I), "de"),
    (re.compile(r"\baccord\s+trouv[eé]\b|\bvisite\s+m[eé]dicale\b|\bdossier\s+boucl[eé]\b", re.I), "fr"),
]

# German-specific characters
_DE_CHARS = re.compile(r"[äöüÄÖÜß]")
# Italian-specific patterns
_IT_CHARS = re.compile(r"\b(della|dello|degli|delle|nella|nella|nell)\b", re.I)
# French-specific patterns
_FR_CHARS = re.compile(r"\b(les|des|une|dans|avec|pour)\b", re.I)


def detect(text: str, fallback: str = _DEFAULT) -> str:
    """Detect language of *text*. Returns 2-letter code."""
    if not text or len(text.strip()) < 10:
        return fallback

    # 1. Heuristic shortcuts (fastest path — no imports)
    sample = text[:500]
    for pattern, lang in _HEURISTICS:
        if pattern.search(sample):
            return lang

    # 2. Try langdetect
    try:
        from langdetect import detect as _ld_detect
        lang = _ld_detect(text[:1000])
        # langdetect returns e.g. "pt", "ca", "ro" — map to supported
        if lang in _SUPPORTED:
            return lang
        # Map close relatives
        _MAP = {"ca": "es", "gl": "es", "pt": "es", "nl": "de", "ro": "fr"}
        return _MAP.get(lang, fallback)
    except Exception:
        pass

    # 3. Character/word heuristics as last resort
    if _DE_CHARS.search(sample):
        return "de"
    if _IT_CHARS.search(sample):
        return "it"
    if _FR_CHARS.search(sample):
        return "fr"

    return fallback
