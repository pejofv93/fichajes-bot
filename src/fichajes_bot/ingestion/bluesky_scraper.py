"""Bluesky scraper — atproto AsyncClient, cursor-based pagination, 15s timeout."""

from __future__ import annotations

import os
from typing import Any

from loguru import logger

from fichajes_bot.ingestion.deduplication import filter_new, make_hash
from fichajes_bot.persistence.d1_client import D1Client
from fichajes_bot.persistence.repositories import MetricasRepository, RumorRawRepository

_CURSOR_PREFIX = "bluesky_cursor_"
_FEED_LIMIT = 30  # posts per page


class BlueskyScraper:
    def __init__(self, db: D1Client) -> None:
        self.db = db
        self.repo = RumorRawRepository(db)
        self._metrics = MetricasRepository(db)
        self._client: Any = None  # atproto AsyncClient, lazy-initialised

    async def _get_client(self) -> Any:
        """Login once per scraper instance; reuse afterwards."""
        if self._client is not None:
            return self._client

        bsky_handle = os.environ.get("BLUESKY_HANDLE", "")
        bsky_password = os.environ.get("BLUESKY_APP_PASSWORD", "")

        if not bsky_handle or not bsky_password:
            raise RuntimeError("BLUESKY_HANDLE / BLUESKY_APP_PASSWORD not set")

        try:
            from atproto import AsyncClient
        except ImportError as exc:
            raise RuntimeError("atproto not installed — run: pip install atproto") from exc

        client = AsyncClient(timeout=15.0)
        await client.login(bsky_handle, bsky_password)
        self._client = client
        return client

    async def _load_cursor(self, fuente_id: str) -> str | None:
        row = await self._metrics.get_latest(f"{_CURSOR_PREFIX}{fuente_id}")
        return row["value"] if row else None

    async def _save_cursor(self, fuente_id: str, cursor: str) -> None:
        await self._metrics.upsert(f"{_CURSOR_PREFIX}{fuente_id}", cursor)

    async def scrape(self, source: dict[str, Any]) -> int:
        """Fetch new posts from a Bluesky handle. Returns count of new items ingested."""
        handle = source.get("bluesky_handle")
        if not handle:
            return 0

        try:
            client = await self._get_client()
        except RuntimeError as exc:
            logger.warning(f"Bluesky {source['fuente_id']}: cannot initialise client — {exc}")
            return 0

        cursor = await self._load_cursor(source["fuente_id"])

        try:
            response = await client.get_author_feed(
                handle,
                limit=_FEED_LIMIT,
                cursor=cursor,
            )
        except Exception as exc:
            logger.warning(f"Bluesky {source['fuente_id']}: get_author_feed failed — {exc}")
            raise  # bubble up so resolver can apply fallback

        posts = response.feed or []
        items: list[dict[str, Any]] = []

        for post_view in posts:
            post = post_view.post
            text: str = getattr(post.record, "text", "") or ""
            uri: str = post.uri or ""
            created_at: str = getattr(post.record, "created_at", "") or ""

            # Build canonical URL from AT-URI  (at://did/app.bsky.feed.post/rkey)
            rkey = uri.split("/")[-1] if uri else ""
            canonical_url = f"https://bsky.app/profile/{handle}/post/{rkey}" if rkey else ""

            h = make_hash(uri, text[:200])
            items.append({
                "fuente_id": source["fuente_id"],
                "url_canonico": canonical_url[:2048],
                "titulo": text[:200] if text else None,
                "texto_completo": text[:5000] if text else None,
                "html_crudo": None,
                "fecha_publicacion": created_at[:64] if created_at else None,
                "idioma_detectado": source.get("idioma", "en"),
                "hash_dedup": h,
            })

        new_items = await filter_new(self.db, items) if items else []

        if new_items:
            await self.repo.insert_batch(new_items)

        # Persist cursor so next run resumes from here
        new_cursor: str | None = getattr(response, "cursor", None)
        if new_cursor:
            await self._save_cursor(source["fuente_id"], new_cursor)

        await self.db.execute(
            "UPDATE fuentes SET last_fetched_at=datetime('now'), consecutive_errors=0, "
            "updated_at=datetime('now') WHERE fuente_id=?",
            [source["fuente_id"]],
        )

        logger.info(
            f"Bluesky {source['fuente_id']} (@{handle}): "
            f"{len(new_items)} new / {len(items)} fetched"
        )
        return len(new_items)
