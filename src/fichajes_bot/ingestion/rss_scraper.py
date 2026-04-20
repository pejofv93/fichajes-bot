"""RSS scraper using feedparser + httpx."""

from __future__ import annotations

from typing import Any

import feedparser
import httpx
from loguru import logger
from tenacity import retry, stop_after_attempt, wait_exponential

from fichajes_bot.persistence.d1_client import D1Client
from fichajes_bot.persistence.repositories import RumorRawRepository
from fichajes_bot.utils.helpers import sha256_hash


class RssScraper:
    def __init__(self, db: D1Client) -> None:
        self.db = db
        self.repo = RumorRawRepository(db)

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(min=2, max=10))
    async def fetch_feed(
        self,
        url: str,
        etag: str | None = None,
        modified: str | None = None,
    ) -> tuple[Any, str | None, str | None]:
        headers: dict[str, str] = {
            "User-Agent": "fichajes-bot/3.1 (+https://github.com/fichajes-bot)"
        }
        if etag:
            headers["If-None-Match"] = etag
        if modified:
            headers["If-Modified-Since"] = modified

        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(url, headers=headers, follow_redirects=True)
            if resp.status_code == 304:
                return None, etag, modified
            resp.raise_for_status()
            content = resp.text
            new_etag = resp.headers.get("ETag")
            new_modified = resp.headers.get("Last-Modified")

        feed = feedparser.parse(content)
        return feed, new_etag, new_modified

    async def scrape(self, source: dict[str, Any]) -> int:
        url = source.get("url")
        if not url:
            return 0

        try:
            feed, new_etag, new_modified = await self.fetch_feed(
                url,
                source.get("last_etag"),
                source.get("last_modified"),
            )
        except Exception as exc:
            logger.warning(f"RSS fetch failed for {source['fuente_id']}: {exc}")
            raise

        if feed is None:
            logger.debug(f"RSS not modified: {source['fuente_id']}")
            return 0

        items = []
        for entry in feed.entries:
            titulo = entry.get("title", "")
            texto = entry.get("summary", entry.get("description", ""))
            url_entry = entry.get("link", "")
            fecha = entry.get("published", "")
            h = sha256_hash(url_entry, titulo)
            items.append({
                "fuente_id": source["fuente_id"],
                "url_canonico": url_entry,
                "titulo": titulo[:1000] if titulo else None,
                "texto_completo": texto[:5000] if texto else None,
                "html_crudo": None,
                "fecha_publicacion": fecha,
                "idioma_detectado": source.get("idioma", "es"),
                "hash_dedup": h,
            })

        if not items:
            return 0

        existing = await self.repo.hashes_exist_batch([i["hash_dedup"] for i in items])
        new_items = [i for i in items if i["hash_dedup"] not in existing]

        if new_items:
            await self.repo.insert_batch(new_items)

        await self.db.execute(
            "UPDATE fuentes SET last_fetched_at=datetime('now'), last_etag=?, last_modified=?, consecutive_errors=0 WHERE fuente_id=?",
            [new_etag, new_modified, source["fuente_id"]],
        )

        logger.debug(f"RSS {source['fuente_id']}: {len(new_items)} new / {len(items)} total")
        return len(new_items)
