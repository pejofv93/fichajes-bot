"""Bluesky scraper using atproto."""

from __future__ import annotations

import os
from typing import Any

from loguru import logger

from fichajes_bot.persistence.d1_client import D1Client
from fichajes_bot.persistence.repositories import MetricasRepository, RumorRawRepository
from fichajes_bot.utils.helpers import sha256_hash


class BlueskyScraper:
    def __init__(self, db: D1Client) -> None:
        self.db = db
        self.repo = RumorRawRepository(db)

    async def scrape(self, source: dict[str, Any]) -> int:
        handle = source.get("bluesky_handle")
        if not handle:
            return 0

        bsky_handle = os.environ.get("BLUESKY_HANDLE", "")
        bsky_password = os.environ.get("BLUESKY_APP_PASSWORD", "")

        if not bsky_handle or not bsky_password:
            logger.warning("BLUESKY credentials not set, skipping Bluesky source")
            return 0

        try:
            from atproto import AsyncClient
        except ImportError:
            logger.warning("atproto not installed")
            return 0

        try:
            client = AsyncClient()
            await client.login(bsky_handle, bsky_password)

            cursor_rows = await self.db.execute(
                "SELECT value FROM metricas_sistema WHERE metric_name=? ORDER BY timestamp DESC LIMIT 1",
                [f"bluesky_cursor_{source['fuente_id']}"],
            )
            cursor = cursor_rows[0]["value"] if cursor_rows else None

            response = await client.get_author_feed(handle, limit=30, cursor=cursor)
            posts = response.feed

            items = []
            for post_view in posts:
                post = post_view.post
                text = getattr(post.record, "text", "")
                uri = post.uri
                created_at = getattr(post.record, "created_at", "")
                h = sha256_hash(uri, text[:200])
                items.append({
                    "fuente_id": source["fuente_id"],
                    "url_canonico": f"https://bsky.app/profile/{handle}/post/{uri.split('/')[-1]}",
                    "titulo": text[:200],
                    "texto_completo": text[:5000],
                    "html_crudo": None,
                    "fecha_publicacion": created_at,
                    "idioma_detectado": source.get("idioma", "en"),
                    "hash_dedup": h,
                })

            if items:
                existing = await self.repo.hashes_exist_batch([i["hash_dedup"] for i in items])
                new_items = [i for i in items if i["hash_dedup"] not in existing]
                if new_items:
                    await self.repo.insert_batch(new_items)

            new_cursor = getattr(response, "cursor", None)
            if new_cursor:
                metrics = MetricasRepository(self.db)
                await metrics.upsert(f"bluesky_cursor_{source['fuente_id']}", str(new_cursor))

            await self.db.execute(
                "UPDATE fuentes SET last_fetched_at=datetime('now'), consecutive_errors=0 WHERE fuente_id=?",
                [source["fuente_id"]],
            )
            logger.debug(f"Bluesky {source['fuente_id']}: {len(items)} posts fetched")
            return len(items)

        except Exception as exc:
            logger.warning(f"Bluesky scrape failed for {source['fuente_id']}: {exc}")
            raise
