"""Web scraper using httpx + selectolax (no Playwright)."""

from __future__ import annotations

import asyncio
from typing import Any

import httpx
from loguru import logger

from fichajes_bot.persistence.d1_client import D1Client
from fichajes_bot.persistence.repositories import RumorRawRepository
from fichajes_bot.utils.helpers import sha256_hash


class WebScraper:
    HEADERS = {
        "User-Agent": "Mozilla/5.0 (compatible; fichajes-bot/3.1)",
        "Accept-Language": "es,en;q=0.9",
    }

    def __init__(self, db: D1Client) -> None:
        self.db = db
        self.repo = RumorRawRepository(db)

    async def scrape(self, source: dict[str, Any]) -> int:
        url = source.get("url")
        if not url:
            return 0

        rate_limit = source.get("rate_limit_seconds", 0)
        if rate_limit:
            await asyncio.sleep(float(rate_limit))

        try:
            async with httpx.AsyncClient(headers=self.HEADERS, timeout=15.0, follow_redirects=True) as client:
                resp = await client.get(url)
                resp.raise_for_status()
                html = resp.text
        except Exception as exc:
            logger.warning(f"Web scrape failed for {source['fuente_id']}: {exc}")
            raise

        title = ""
        text = ""
        try:
            from selectolax.parser import HTMLParser
            tree = HTMLParser(html)
            if tree.body:
                text = tree.body.text(separator="\n")
            title_node = tree.css_first("title")
            if title_node:
                title = title_node.text()
        except Exception as exc:
            logger.warning(f"selectolax parse failed for {source['fuente_id']}: {exc}")
            text = html[:5000]

        h = sha256_hash(url, html[:500])
        existing = await self.repo.hashes_exist_batch([h])
        if h in existing:
            return 0

        await self.repo.insert_batch([{
            "fuente_id": source["fuente_id"],
            "url_canonico": url,
            "titulo": title[:500] if title else None,
            "texto_completo": text[:8000],
            "html_crudo": html[:50000],
            "fecha_publicacion": None,
            "idioma_detectado": source.get("idioma", "es"),
            "hash_dedup": h,
        }])

        await self.db.execute(
            "UPDATE fuentes SET last_fetched_at=datetime('now'), consecutive_errors=0 WHERE fuente_id=?",
            [source["fuente_id"]],
        )
        return 1
