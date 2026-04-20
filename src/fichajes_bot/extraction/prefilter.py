"""Two-stage fast prefilter: RM keyword AND transfer signal.

Stage 1 — Real Madrid mention (any language).
Stage 2 — At least one transfer signal word.

Both must pass. No DB access. Pure regex, sub-millisecond.
"""

from __future__ import annotations

import re

# ── Stage 1: Real Madrid identifiers ─────────────────────────────────────────
_RM_PATTERNS = [
    r"\breal\s+madrid\b",
    r"\brealmadrid\b",
    r"\blos\s+blancos\b",
    r"\bmerengues?\b",
    r"\bbern[aá]beu\b",
    r"\bflorentino\b",
    r"\bancelotti\b",
    r"\breal\s+madrid\s+cf\b",
    r"\bcasa\s+blanca\b",
    # Spanish shorthands: "el Madrid", "al Madrid", "del Madrid"
    r"\b(?:el|al|del)\s+madrid\b",
    r"\blos\s+merengues\b",
    # Abbreviations that appear in transfer news
    r"\bRM\b",
    r"\bRMCF\b",
]

_RM_RE = re.compile(
    "|".join(_RM_PATTERNS),
    re.IGNORECASE,
)

# ── Stage 2: Transfer signal words (multi-language) ───────────────────────────
# Deliberately broad — exact classification happens downstream.
_TRANSFER_PATTERNS = [
    # Spanish
    r"\bfich[ae]\b", r"\bfichari\w*\b", r"\bfichaje\b",
    r"\btraspaso\b", r"\btransfer\b",
    r"\bacuerdo\b", r"\bcontrato\b", r"\brenovaci[oó]n\b",
    r"\bsalida\b", r"\bcesi[oó]n\b", r"\bcedido\b",
    r"\brescisi[oó]n\b", r"\boferta\b", r"\bnegociaci\w*\b",
    r"\bm[eé]dico\b", r"\breconocimiento\b",
    r"\bincorporaci[oó]n\b", r"\bincorporar\w*\b",
    r"\brefuerzo\b", r"\bpresentaci[oó]n\b", r"\bpresenta\b",
    # English
    r"\bsign\w*\b", r"\bsigning\b", r"\btransfer\b",
    r"\bdeal\b", r"\bfee\b", r"\bagreement\b", r"\bcontract\b",
    r"\bloan\b", r"\bdeparture\b", r"\bmedical\b",
    r"\bhere\s+we\s+go\b", r"\bdone\s+deal\b",
    # Italian
    r"\baccordo\b", r"\btrattativa\b", r"\bcessione\b",
    r"\bvisite\s+mediche\b", r"\btrasferimento\b",
    r"\bvuole\b", r"\bacquisto\b",
    # German
    r"\bwechsel\b", r"\bvertrag\b",
    r"\beinigung\b", r"\babl[oö]se\b", r"\binteresse\b",
    r"\bmedizincheck\b", r"\bverpflichtung\b",
    # French
    r"\btransfert\b", r"\baccord\b", r"\bcontrat\b",
    r"\bc[eè]ssion\b", r"\bpr[eê]t\b",
    r"\bvisite\s+m[eé]dicale\b", r"\brecrutement\b",
]

_TRANSFER_RE = re.compile(
    "|".join(_TRANSFER_PATTERNS),
    re.IGNORECASE,
)

# ── Negation early-exit ───────────────────────────────────────────────────────
# If the ONLY mentions are explicit denials, skip to save LLM budget.
_DENIAL_RE = re.compile(
    r"\b(fake|hoax|bulo|falso|invented|inventado)\b",
    re.IGNORECASE,
)


def prefilter(text: str) -> bool:
    """Return True if text warrants extraction processing.

    Checks:
      1. Contains a Real Madrid identifier.
      2. Contains at least one transfer-domain word.
    """
    if not text or not text.strip():
        return False

    if not _RM_RE.search(text):
        return False

    if not _TRANSFER_RE.search(text):
        return False

    return True


def prefilter_debug(text: str) -> dict:
    """Return diagnostic dict — used in tests and logging."""
    rm_match = _RM_RE.search(text)
    tr_match = _TRANSFER_RE.search(text)
    return {
        "passes": bool(rm_match and tr_match),
        "rm_match": rm_match.group(0) if rm_match else None,
        "transfer_match": tr_match.group(0) if tr_match else None,
    }
