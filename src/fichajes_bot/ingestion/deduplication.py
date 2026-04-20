"""Deduplication helpers for the ingestion layer.

A rumor is considered a duplicate if its SHA-256 hash of
(url_canonico + titulo) already exists in rumores_raw.
All hash checks are batched into a single D1 query per run.
"""

from __future__ import annotations

from fichajes_bot.persistence.d1_client import D1Client
from fichajes_bot.utils.helpers import sha256_hash


def make_hash(url: str, titulo: str) -> str:
    """Canonical deduplication hash for a raw item."""
    return sha256_hash(url or "", (titulo or "")[:200])


async def filter_new(
    db: D1Client,
    items: list[dict],
) -> list[dict]:
    """Return only items whose hash does not yet exist in rumores_raw.

    Uses a single batch query regardless of list length.
    """
    if not items:
        return []

    hashes = [i["hash_dedup"] for i in items]
    if not hashes:
        return items

    placeholders = ",".join("?" * len(hashes))
    rows = await db.execute(
        f"SELECT hash_dedup FROM rumores_raw WHERE hash_dedup IN ({placeholders})",
        hashes,
    )
    existing: set[str] = {r["hash_dedup"] for r in rows}
    return [i for i in items if i["hash_dedup"] not in existing]
