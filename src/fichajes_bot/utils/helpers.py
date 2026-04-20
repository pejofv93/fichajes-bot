"""Utility helpers."""

from __future__ import annotations

import hashlib
import re
import unicodedata
from datetime import datetime, timezone


def slugify(text: str) -> str:
    text = unicodedata.normalize("NFD", text.lower())
    text = "".join(c for c in text if unicodedata.category(c) != "Mn")
    text = re.sub(r"[^\w\s-]", "", text)
    return re.sub(r"[-\s]+", "-", text).strip("-")


def sha256_hash(*parts: str) -> str:
    combined = "|".join(p or "" for p in parts)
    return hashlib.sha256(combined.encode()).hexdigest()


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
