"""Prefilter: fast keyword check before regex/LLM extraction."""

from __future__ import annotations

import re

# Real Madrid keywords — any match passes the filter
_RM_KEYWORDS = [
    "real madrid", "realmadrid", "los blancos", "merengues",
    "bernabéu", "bernabeu", "florentino", "ancelotti",
    "real madrid cf", "rm ",
]

_PATTERN = re.compile(
    "|".join(re.escape(k) for k in _RM_KEYWORDS),
    re.IGNORECASE,
)


def prefilter(text: str) -> bool:
    """Return True if text likely contains Real Madrid transfer news."""
    return bool(_PATTERN.search(text))
