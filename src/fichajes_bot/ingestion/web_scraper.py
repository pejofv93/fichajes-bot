"""Web scraper — httpx + selectolax, no Playwright, per-domain rate limiting."""

from __future__ import annotations

import asyncio
import re
import time
from typing import Any
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser

import httpx
from loguru import logger

from fichajes_bot.ingestion.deduplication import filter_new, make_hash
from fichajes_bot.persistence.d1_client import D1Client
from fichajes_bot.persistence.repositories import RumorRawRepository

_UA = "fichajes-bot/3.1 (+https://github.com/pejofeve/fichajes-bot)"
_HEADERS = {
    "User-Agent": _UA,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "es,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
}

# Per-domain last-fetch timestamps (process-local)
_domain_last_fetch: dict[str, float] = {}

# Site-specific CSS selectors for structured extraction
_SITE_SELECTORS: dict[str, dict[str, str]] = {
    "transfermarkt.com": {
        "player_row": "table.items tbody tr",
        "player_name": "td.hauptlink a",
        "market_value": "td.rechts.hauptlink",
    },
    "capology.com": {
        "salary_row": "table tbody tr",
        "player_name": "td.name a",
        "salary": "td.number",
    },
    "laliga.com": {
        "limit_value": ".salary-limit__value, [data-testid='salary-limit']",
    },
    "realmadrid.com": {
        # .rm-news__list covers listing pages (SSR Angular); fallbacks for article pages
        "article_body": ".rm-news__list, .article-body, .news-content",
    },
    "rfef.es": {
        "team_row": "table.standings tbody tr",
        "team_name": "td.team a",
    },
}


def _domain(url: str) -> str:
    try:
        host = urlparse(url).netloc.lower()
        # Strip www.
        return host.removeprefix("www.")
    except Exception:
        return ""


async def _respect_rate_limit(url: str, rate_limit_seconds: float) -> None:
    """Sleep if we fetched this domain too recently."""
    if rate_limit_seconds <= 0:
        return
    dom = _domain(url)
    last = _domain_last_fetch.get(dom, 0.0)
    elapsed = time.monotonic() - last
    if elapsed < rate_limit_seconds:
        wait = rate_limit_seconds - elapsed
        logger.debug(f"Rate-limiting {dom}: sleeping {wait:.1f}s")
        await asyncio.sleep(wait)
    _domain_last_fetch[dom] = time.monotonic()


async def _check_robots(url: str) -> bool:
    """Return True if we are allowed to fetch `url` per robots.txt."""
    parsed = urlparse(url)
    robots_url = f"{parsed.scheme}://{parsed.netloc}/robots.txt"
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(robots_url, headers={"User-Agent": _UA})
            if resp.status_code != 200:
                return True  # No robots.txt → allowed
            rp = RobotFileParser()
            rp.parse(resp.text.splitlines())
            return rp.can_fetch("*", url)
    except Exception:
        return True  # On error, optimistically allow


def _extract_structured(html: str, url: str) -> tuple[str, str]:
    """Try site-specific extraction; fall back to generic body text."""
    dom = _domain(url)

    try:
        from selectolax.parser import HTMLParser  # type: ignore[import]
    except ImportError:
        return "", html[:5000]

    tree = HTMLParser(html)

    # Remove noise nodes
    for tag in ("script", "style", "nav", "footer", "header", "aside"):
        for node in tree.css(tag):
            node.decompose()

    title = ""
    title_node = tree.css_first("title")
    if title_node:
        title = title_node.text(strip=True)

    # Site-specific extraction
    selectors = next((v for k, v in _SITE_SELECTORS.items() if k in dom), {})

    if "player_row" in selectors:
        rows = tree.css(selectors["player_row"])
        parts: list[str] = []
        for row in rows[:50]:
            name_node = row.css_first(selectors.get("player_name", ""))
            val_node = row.css_first(selectors.get("market_value", selectors.get("salary", "")))
            name = name_node.text(strip=True) if name_node else ""
            val = val_node.text(strip=True) if val_node else ""
            if name:
                parts.append(f"{name}: {val}".strip(": "))
        text = "\n".join(parts)
    elif "limit_value" in selectors:
        node = tree.css_first(selectors["limit_value"])
        text = node.text(strip=True) if node else (tree.body.text(separator="\n") if tree.body else "")
    elif "article_body" in selectors:
        node = tree.css_first(selectors["article_body"])
        text = node.text(separator="\n", strip=True) if node else (tree.body.text(separator="\n") if tree.body else "")
    else:
        text = tree.body.text(separator="\n") if tree.body else ""

    return title, text[:8000]


class WebScraper:
    def __init__(self, db: D1Client) -> None:
        self.db = db
        self.repo = RumorRawRepository(db)

    async def scrape(self, source: dict[str, Any]) -> int:
        """Scrape a static HTML source. Returns 1 if new content ingested, else 0."""
        url = source.get("url")
        if not url:
            return 0

        rate_limit = float(source.get("rate_limit_seconds") or 0)
        await _respect_rate_limit(url, rate_limit)

        # Robots.txt check
        allowed = await _check_robots(url)
        if not allowed:
            logger.warning(f"Web {source['fuente_id']}: blocked by robots.txt — {url}")
            return 0

        try:
            async with httpx.AsyncClient(
                headers=_HEADERS, timeout=15.0, follow_redirects=True
            ) as client:
                resp = await client.get(url)
                resp.raise_for_status()
                html = resp.text
        except httpx.HTTPStatusError as exc:
            logger.warning(f"Web {source['fuente_id']}: HTTP {exc.response.status_code}")
            raise
        except Exception as exc:
            logger.warning(f"Web {source['fuente_id']}: fetch error — {exc}")
            raise

        title, text = _extract_structured(html, url)

        # Hash on URL + first 500 chars of body (changes when content changes)
        h = make_hash(url, html[:500])
        new_items = await filter_new(self.db, [{"hash_dedup": h}])
        if not new_items:
            logger.debug(f"Web {source['fuente_id']}: content unchanged")
            return 0

        await self.repo.insert_batch([{
            "fuente_id": source["fuente_id"],
            "url_canonico": url,
            "titulo": (title or "")[:500] or None,
            "texto_completo": text or None,
            "html_crudo": html[:50_000],
            "fecha_publicacion": None,
            "idioma_detectado": source.get("idioma", "es"),
            "hash_dedup": h,
        }])

        await self.db.execute(
            "UPDATE fuentes SET last_fetched_at=datetime('now'), consecutive_errors=0, "
            "updated_at=datetime('now') WHERE fuente_id=?",
            [source["fuente_id"]],
        )

        logger.info(f"Web {source['fuente_id']}: new snapshot ingested ({len(text)} chars)")
        return 1
