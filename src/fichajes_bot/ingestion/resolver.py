"""SourceResolver: routes a source config to the correct scraper."""

from __future__ import annotations

from typing import Any

from loguru import logger

from fichajes_bot.persistence.d1_client import D1Client


class SourceResolver:
    def __init__(self, db: D1Client) -> None:
        self.db = db

    async def scrape_source(self, source: dict[str, Any]) -> int:
        tipo = source.get("tipo", "")
        if tipo == "rss":
            from fichajes_bot.ingestion.rss_scraper import RssScraper
            scraper = RssScraper(self.db)
            return await scraper.scrape(source)
        elif tipo == "bluesky":
            from fichajes_bot.ingestion.bluesky_scraper import BlueskyScraper
            scraper = BlueskyScraper(self.db)
            return await scraper.scrape(source)
        elif tipo == "web_selectolax":
            from fichajes_bot.ingestion.web_scraper import WebScraper
            scraper = WebScraper(self.db)
            return await scraper.scrape(source)
        else:
            logger.warning(f"Unknown source type: {tipo}")
            return 0
