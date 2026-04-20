"""RSS scraper — feedparser + httpx, If-Modified-Since, periodista_id_filter."""

from __future__ import annotations

import json
from typing import Any

import feedparser
import httpx
from loguru import logger
from tenacity import retry, stop_after_attempt, wait_exponential

from fichajes_bot.ingestion.deduplication import filter_new, make_hash
from fichajes_bot.persistence.d1_client import D1Client
from fichajes_bot.persistence.repositories import RumorRawRepository

_UA = "fichajes-bot/3.1 (+https://github.com/pejofeve/fichajes-bot)"


class RssScraper:
    def __init__(self, db: D1Client) -> None:
        self.db = db
        self.repo = RumorRawRepository(db)

    @retry(stop=stop_after_attempt(2), wait=wait_exponential(multiplier=1, min=2, max=8))
    async def _fetch(
        self,
        url: str,
        etag: str | None,
        last_modified: str | None,
    ) -> tuple[Any | None, str | None, str | None]:
        """Fetch and parse feed. Returns (feed|None, etag, last_modified)."""
        headers: dict[str, str] = {"User-Agent": _UA}
        if etag:
            headers["If-None-Match"] = etag
        if last_modified:
            headers["If-Modified-Since"] = last_modified

        async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as client:
            resp = await client.get(url, headers=headers)

        if resp.status_code == 304:
            return None, etag, last_modified

        resp.raise_for_status()

        new_etag = resp.headers.get("ETag")
        new_modified = resp.headers.get("Last-Modified")
        feed = feedparser.parse(resp.text)
        return feed, new_etag, new_modified

    def _parse_filter(self, source: dict[str, Any]) -> list[str]:
        """Return list of periodista_ids to filter on (empty = no filter)."""
        raw = source.get("periodista_id_filter")
        if not raw:
            return []
        if isinstance(raw, list):
            return [str(x) for x in raw]
        # Stored as JSON string in D1
        try:
            parsed = json.loads(raw)
            return [str(x) for x in parsed] if isinstance(parsed, list) else []
        except Exception:
            return []

    async def scrape(self, source: dict[str, Any]) -> int:
        """Scrape one RSS source. Returns number of new items ingested."""
        url = source.get("url")
        if not url:
            return 0

        try:
            feed, new_etag, new_modified = await self._fetch(
                url,
                source.get("last_etag"),
                source.get("last_modified"),
            )
        except httpx.HTTPStatusError as exc:
            logger.warning(f"RSS {source['fuente_id']}: HTTP {exc.response.status_code} — {url}")
            raise
        except Exception as exc:
            logger.warning(f"RSS {source['fuente_id']}: fetch error — {exc}")
            raise

        if feed is None:
            logger.debug(f"RSS {source['fuente_id']}: 304 not modified")
            return 0

        if feed.bozo and not feed.entries:
            logger.warning(f"RSS {source['fuente_id']}: malformed feed — {feed.bozo_exception}")
            return 0

        periodista_filter = self._parse_filter(source)
        idioma = source.get("idioma", "es")

        items: list[dict[str, Any]] = []
        for entry in feed.entries:
            titulo = entry.get("title", "") or ""
            texto = entry.get("summary") or entry.get("description") or ""
            url_entry = entry.get("link", "") or ""
            fecha = entry.get("published", "") or entry.get("updated", "") or ""

            # Apply periodista_id_filter if configured
            if periodista_filter:
                tags = [t.get("term", "") for t in entry.get("tags", [])]
                author = entry.get("author", "").lower()
                # Match against filter list (best effort — RSS author fields vary)
                matched = any(
                    pid.lower().replace("-", " ") in author
                    or pid.lower() in " ".join(tags).lower()
                    for pid in periodista_filter
                )
                if not matched:
                    continue

            h = make_hash(url_entry, titulo)
            items.append({
                "fuente_id": source["fuente_id"],
                "url_canonico": url_entry[:2048] if url_entry else None,
                "titulo": titulo[:1000] if titulo else None,
                "texto_completo": texto[:5000] if texto else None,
                "html_crudo": None,
                "fecha_publicacion": fecha[:64] if fecha else None,
                "idioma_detectado": idioma,
                "hash_dedup": h,
            })

        if not items:
            logger.debug(f"RSS {source['fuente_id']}: 0 entries after filter")
            _update_fetched(self.db, source["fuente_id"], new_etag, new_modified)
            return 0

        new_items = await filter_new(self.db, items)

        if new_items:
            await self.repo.insert_batch(new_items)

        await _update_fetched(self.db, source["fuente_id"], new_etag, new_modified)

        logger.info(f"RSS {source['fuente_id']}: {len(new_items)} new / {len(items)} total")
        return len(new_items)


async def _update_fetched(
    db: D1Client, fuente_id: str, etag: str | None, modified: str | None
) -> None:
    await db.execute(
        "UPDATE fuentes SET last_fetched_at=datetime('now'), last_etag=?, last_modified=?, "
        "consecutive_errors=0, updated_at=datetime('now') WHERE fuente_id=?",
        [etag, modified, fuente_id],
    )
