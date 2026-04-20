"""SourceResolver — routes source → scraper, handles fallbacks and health.

Fallback chain:
  Bluesky error → try RSS of same periodista (if exists)
  RSS/Web error  → mark consecutive_errors++

Source health:
  consecutive_errors >= DISABLE_THRESHOLD → is_disabled=1 + enqueue admin alert
"""

from __future__ import annotations

from typing import Any

from loguru import logger

from fichajes_bot.persistence.d1_client import D1Client

DISABLE_THRESHOLD = 10  # errors before disabling a source


class SourceResolver:
    def __init__(self, db: D1Client) -> None:
        self.db = db

    async def scrape_source(self, source: dict[str, Any]) -> int:
        """Dispatch to the right scraper; apply fallback on Bluesky failure."""
        tipo = source.get("tipo", "")

        try:
            if tipo == "rss":
                return await self._run("rss", source)
            elif tipo == "bluesky":
                try:
                    return await self._run("bluesky", source)
                except Exception as exc:
                    logger.warning(
                        f"Bluesky {source['fuente_id']} failed ({exc}), "
                        "trying RSS fallback for same periodista"
                    )
                    await self._bump_errors(source["fuente_id"])
                    await self._check_disable(source)
                    fallback = await self._find_rss_fallback(source)
                    if fallback:
                        logger.info(f"  RSS fallback: {fallback['fuente_id']}")
                        return await self._run("rss", fallback)
                    return 0
            elif tipo == "web_selectolax":
                return await self._run("web", source)
            else:
                logger.warning(f"Unknown source type '{tipo}' for {source['fuente_id']}")
                return 0
        except Exception as exc:
            # For rss / web failures — bump errors here
            await self._bump_errors(source["fuente_id"])
            await self._check_disable(source)
            raise

    # ── internal ──────────────────────────────────────────────────────

    async def _run(self, kind: str, source: dict[str, Any]) -> int:
        if kind == "rss":
            from fichajes_bot.ingestion.rss_scraper import RssScraper
            return await RssScraper(self.db).scrape(source)
        elif kind == "bluesky":
            from fichajes_bot.ingestion.bluesky_scraper import BlueskyScraper
            return await BlueskyScraper(self.db).scrape(source)
        else:
            from fichajes_bot.ingestion.web_scraper import WebScraper
            return await WebScraper(self.db).scrape(source)

    async def _bump_errors(self, fuente_id: str) -> None:
        await self.db.execute(
            "UPDATE fuentes SET consecutive_errors=consecutive_errors+1, "
            "updated_at=datetime('now') WHERE fuente_id=?",
            [fuente_id],
        )

    async def _check_disable(self, source: dict[str, Any]) -> None:
        """Disable source if it has hit the error threshold."""
        fuente_id = source["fuente_id"]
        # Read current count from DB (already incremented by _bump_errors)
        rows = await self.db.execute(
            "SELECT consecutive_errors FROM fuentes WHERE fuente_id=?", [fuente_id]
        )
        if not rows:
            return
        errors = rows[0]["consecutive_errors"]
        if errors >= DISABLE_THRESHOLD:
            await self._disable_source(fuente_id)
            await self._enqueue_admin_alert(fuente_id, errors, "threshold reached")

    async def _disable_source(self, fuente_id: str) -> None:
        await self.db.execute(
            "UPDATE fuentes SET is_disabled=1, updated_at=datetime('now') WHERE fuente_id=?",
            [fuente_id],
        )
        logger.error(f"Source DISABLED after {DISABLE_THRESHOLD}+ errors: {fuente_id}")

    async def _enqueue_admin_alert(
        self, fuente_id: str, errors: int, last_error: str
    ) -> None:
        import json
        import uuid
        await self.db.execute(
            "INSERT INTO eventos_pending (evento_id, tipo, payload) VALUES (?,?,?)",
            [
                str(uuid.uuid4()),
                "source_disabled",
                json.dumps({
                    "fuente_id": fuente_id,
                    "errors": errors,
                    "last_error": last_error[:200],
                }),
            ],
        )

    async def _find_rss_fallback(self, bluesky_source: dict[str, Any]) -> dict | None:
        """Find an RSS source for the same periodista as a failed Bluesky source."""
        periodista_id = bluesky_source.get("periodista_id")
        if not periodista_id:
            return None
        rows = await self.db.execute(
            "SELECT * FROM fuentes WHERE tipo='rss' AND periodista_id=? AND is_disabled=0 LIMIT 1",
            [periodista_id],
        )
        return rows[0] if rows else None
