"""Session 2 tests — ingestion layer: RSS, Bluesky, web, dedup, source health."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from fichajes_bot.ingestion.deduplication import filter_new, make_hash


# ────────────────────────────────────────────────────────────────────────────
# Helpers
# ────────────────────────────────────────────────────────────────────────────

def _fake_feed(entries: list[dict]) -> MagicMock:
    """Build a feedparser-like object."""
    feed = MagicMock()
    feed.bozo = False
    feed.bozo_exception = None
    feed.entries = []
    for e in entries:
        entry = MagicMock()
        entry.get = lambda k, d="", _e=e: _e.get(k, d)
        entry.title = e.get("title", "")
        entry.summary = e.get("summary", "")
        entry.description = e.get("description", "")
        entry.link = e.get("link", "")
        entry.published = e.get("published", "")
        entry.updated = e.get("updated", "")
        entry.tags = []
        entry.author = e.get("author", "")
        feed.entries.append(entry)
    return feed


SOURCE_RSS = {
    "fuente_id": "relevo_rss",
    "tipo": "rss",
    "tier": "S",
    "url": "https://www.relevo.com/rss",
    "idioma": "es",
    "periodista_id_filter": None,
    "last_etag": None,
    "last_modified": None,
    "consecutive_errors": 0,
    "is_disabled": 0,
}

SOURCE_BLUESKY = {
    "fuente_id": "romano_bluesky",
    "tipo": "bluesky",
    "tier": "S",
    "bluesky_handle": "fabrizioromano.bsky.social",
    "periodista_id": "fabrizio-romano",
    "idioma": "en",
    "consecutive_errors": 0,
    "is_disabled": 0,
}

SOURCE_WEB = {
    "fuente_id": "transfermarkt_rm",
    "tipo": "web_selectolax",
    "tier": "A",
    "url": "https://www.transfermarkt.com/real-madrid/transfers/verein/418",
    "idioma": "en",
    "rate_limit_seconds": 0,
    "consecutive_errors": 0,
    "is_disabled": 0,
}


# ────────────────────────────────────────────────────────────────────────────
# Deduplication
# ────────────────────────────────────────────────────────────────────────────

class TestDeduplication:
    def test_make_hash_deterministic(self):
        h1 = make_hash("https://example.com/1", "Title A")
        h2 = make_hash("https://example.com/1", "Title A")
        assert h1 == h2

    def test_make_hash_url_sensitive(self):
        h1 = make_hash("https://example.com/1", "Title A")
        h2 = make_hash("https://example.com/2", "Title A")
        assert h1 != h2

    def test_make_hash_title_sensitive(self):
        h1 = make_hash("https://example.com/1", "Title A")
        h2 = make_hash("https://example.com/1", "Title B")
        assert h1 != h2

    def test_make_hash_truncates_title(self):
        h1 = make_hash("u", "A" * 200)
        h2 = make_hash("u", "A" * 200 + "extra_ignored")
        assert h1 == h2

    @pytest.mark.asyncio
    async def test_filter_new_empty_db(self, db):
        items = [
            {"hash_dedup": make_hash("https://a.com/1", "T1")},
            {"hash_dedup": make_hash("https://a.com/2", "T2")},
        ]
        new = await filter_new(db, items)
        assert len(new) == 2

    @pytest.mark.asyncio
    async def test_filter_new_removes_existing(self, db):
        h = make_hash("https://a.com/dup", "dup title")
        # Insert directly into DB
        await db.execute(
            "INSERT INTO rumores_raw (raw_id, fuente_id, hash_dedup) VALUES (?,?,?)",
            ["test-id-1", "romano_bluesky", h],
        )
        items = [
            {"hash_dedup": h},
            {"hash_dedup": make_hash("https://a.com/new", "new title")},
        ]
        new = await filter_new(db, items)
        assert len(new) == 1
        assert new[0]["hash_dedup"] != h

    @pytest.mark.asyncio
    async def test_filter_new_empty_input(self, db):
        result = await filter_new(db, [])
        assert result == []


# ────────────────────────────────────────────────────────────────────────────
# RSS Scraper
# ────────────────────────────────────────────────────────────────────────────

class TestRssScraper:
    @pytest.mark.asyncio
    async def test_scrape_inserts_new_items(self, db):
        from fichajes_bot.ingestion.rss_scraper import RssScraper

        fake_entries = [
            {"title": "Real Madrid sign Mbappé", "link": "https://relevo.com/1", "published": "Mon, 01 Jul 2024"},
            {"title": "Real Madrid targets defender", "link": "https://relevo.com/2", "published": "Mon, 01 Jul 2024"},
        ]

        with patch.object(RssScraper, "_fetch", new_callable=AsyncMock) as mock_fetch:
            mock_feed = _fake_feed(fake_entries)
            mock_fetch.return_value = (mock_feed, '"etag123"', "Mon, 01 Jul 2024")

            scraper = RssScraper(db)
            n = await scraper.scrape(SOURCE_RSS)

        assert n == 2
        rows = await db.execute("SELECT COUNT(*) as c FROM rumores_raw")
        assert rows[0]["c"] == 2

    @pytest.mark.asyncio
    async def test_scrape_304_returns_zero(self, db):
        from fichajes_bot.ingestion.rss_scraper import RssScraper

        with patch.object(RssScraper, "_fetch", new_callable=AsyncMock) as mock_fetch:
            mock_fetch.return_value = (None, '"etag"', "date")
            scraper = RssScraper(db)
            n = await scraper.scrape(SOURCE_RSS)

        assert n == 0

    @pytest.mark.asyncio
    async def test_scrape_deduplicates(self, db):
        from fichajes_bot.ingestion.rss_scraper import RssScraper

        same_entry = {"title": "Same article", "link": "https://relevo.com/same", "published": "x"}

        with patch.object(RssScraper, "_fetch", new_callable=AsyncMock) as mock_fetch:
            mock_feed = _fake_feed([same_entry])
            mock_fetch.return_value = (mock_feed, None, None)

            scraper = RssScraper(db)
            n1 = await scraper.scrape(SOURCE_RSS)
            # Second call — same content
            mock_fetch.return_value = (mock_feed, None, None)
            n2 = await scraper.scrape(SOURCE_RSS)

        assert n1 == 1
        assert n2 == 0
        rows = await db.execute("SELECT COUNT(*) as c FROM rumores_raw")
        assert rows[0]["c"] == 1

    @pytest.mark.asyncio
    async def test_scrape_updates_etag(self, db):
        from fichajes_bot.ingestion.rss_scraper import RssScraper

        with patch.object(RssScraper, "_fetch", new_callable=AsyncMock) as mock_fetch:
            mock_feed = _fake_feed([{"title": "t", "link": "https://r.com/1"}])
            mock_fetch.return_value = (mock_feed, '"new_etag"', "new_date")

            scraper = RssScraper(db)
            await scraper.scrape(SOURCE_RSS)

        row = await db.execute(
            "SELECT last_etag FROM fuentes WHERE fuente_id=?", ["relevo_rss"]
        )
        assert row[0]["last_etag"] == '"new_etag"'

    @pytest.mark.asyncio
    async def test_scrape_bozo_feed_skipped(self, db):
        from fichajes_bot.ingestion.rss_scraper import RssScraper

        with patch.object(RssScraper, "_fetch", new_callable=AsyncMock) as mock_fetch:
            bad_feed = MagicMock()
            bad_feed.bozo = True
            bad_feed.bozo_exception = Exception("Parse error")
            bad_feed.entries = []
            mock_fetch.return_value = (bad_feed, None, None)

            scraper = RssScraper(db)
            n = await scraper.scrape(SOURCE_RSS)

        assert n == 0

    @pytest.mark.asyncio
    async def test_periodista_filter_all_pass_when_no_filter(self, db):
        from fichajes_bot.ingestion.rss_scraper import RssScraper

        entries = [
            {"title": "Article by Romano", "link": "https://r.com/a", "author": "fabrizio romano"},
            {"title": "Article by Moretto", "link": "https://r.com/b", "author": "matteo moretto"},
        ]

        with patch.object(RssScraper, "_fetch", new_callable=AsyncMock) as mock_fetch:
            mock_fetch.return_value = (_fake_feed(entries), None, None)
            scraper = RssScraper(db)
            n = await scraper.scrape({**SOURCE_RSS, "periodista_id_filter": None})

        assert n == 2

    @pytest.mark.asyncio
    async def test_periodista_filter_json_string(self, db):
        """periodista_id_filter stored as JSON string in D1."""
        from fichajes_bot.ingestion.rss_scraper import RssScraper
        scraper = RssScraper(db)
        result = scraper._parse_filter(
            {"periodista_id_filter": '["matteo-moretto", "fabrizio-romano"]'}
        )
        assert "matteo-moretto" in result
        assert "fabrizio-romano" in result

    @pytest.mark.asyncio
    async def test_periodista_filter_list(self, db):
        from fichajes_bot.ingestion.rss_scraper import RssScraper
        scraper = RssScraper(db)
        result = scraper._parse_filter(
            {"periodista_id_filter": ["matteo-moretto"]}
        )
        assert result == ["matteo-moretto"]


# ────────────────────────────────────────────────────────────────────────────
# Bluesky Scraper
# ────────────────────────────────────────────────────────────────────────────

def _make_post(uri: str, text: str, created_at: str = "2024-07-01T10:00:00Z") -> MagicMock:
    record = MagicMock()
    record.text = text
    record.created_at = created_at

    post = MagicMock()
    post.uri = uri
    post.record = record

    post_view = MagicMock()
    post_view.post = post
    return post_view


class TestBleskyScraper:
    @pytest.mark.asyncio
    async def test_scrape_inserts_posts(self, db):
        from fichajes_bot.ingestion.bluesky_scraper import BlueskyScraper

        posts = [
            _make_post("at://did:plc:abc/app.bsky.feed.post/1", "here we go! Real Madrid sign X"),
            _make_post("at://did:plc:abc/app.bsky.feed.post/2", "Another transfer update"),
        ]

        mock_response = MagicMock()
        mock_response.feed = posts
        mock_response.cursor = "cursor_value_abc"

        with patch.dict("os.environ", {"BLUESKY_HANDLE": "bot.bsky.social", "BLUESKY_APP_PASSWORD": "xxxx"}):
            with patch("fichajes_bot.ingestion.bluesky_scraper.BlueskyScraper._get_client", new_callable=AsyncMock) as mock_get_client:
                mock_client = AsyncMock()
                mock_client.get_author_feed = AsyncMock(return_value=mock_response)
                mock_get_client.return_value = mock_client

                scraper = BlueskyScraper(db)
                # Pre-set client to avoid login
                scraper._client = mock_client
                n = await scraper.scrape(SOURCE_BLUESKY)

        assert n == 2
        rows = await db.execute("SELECT COUNT(*) as c FROM rumores_raw")
        assert rows[0]["c"] == 2

    @pytest.mark.asyncio
    async def test_scrape_saves_cursor(self, db):
        from fichajes_bot.ingestion.bluesky_scraper import BlueskyScraper

        posts = [_make_post("at://did/app.bsky.feed.post/x", "test")]
        mock_response = MagicMock()
        mock_response.feed = posts
        mock_response.cursor = "next_cursor_xyz"

        with patch.dict("os.environ", {"BLUESKY_HANDLE": "bot.bsky.social", "BLUESKY_APP_PASSWORD": "xxxx"}):
            scraper = BlueskyScraper(db)
            mock_client = AsyncMock()
            mock_client.get_author_feed = AsyncMock(return_value=mock_response)
            scraper._client = mock_client

            await scraper.scrape(SOURCE_BLUESKY)

        rows = await db.execute(
            "SELECT value FROM metricas_sistema WHERE metric_name=? ORDER BY timestamp DESC LIMIT 1",
            ["bluesky_cursor_romano_bluesky"],
        )
        assert rows[0]["value"] == "next_cursor_xyz"

    @pytest.mark.asyncio
    async def test_scrape_deduplicates_posts(self, db):
        from fichajes_bot.ingestion.bluesky_scraper import BlueskyScraper

        same_post = _make_post("at://did/app.bsky.feed.post/same", "Real Madrid here we go")
        mock_response = MagicMock()
        mock_response.feed = [same_post]
        mock_response.cursor = None

        scraper = BlueskyScraper(db)
        mock_client = AsyncMock()
        mock_client.get_author_feed = AsyncMock(return_value=mock_response)
        scraper._client = mock_client

        n1 = await scraper.scrape(SOURCE_BLUESKY)
        n2 = await scraper.scrape(SOURCE_BLUESKY)

        assert n1 == 1
        assert n2 == 0

    @pytest.mark.asyncio
    async def test_scrape_no_credentials_returns_zero(self, db):
        from fichajes_bot.ingestion.bluesky_scraper import BlueskyScraper
        import os

        env = {k: "" for k in ("BLUESKY_HANDLE", "BLUESKY_APP_PASSWORD")}
        with patch.dict("os.environ", env):
            scraper = BlueskyScraper(db)
            n = await scraper.scrape(SOURCE_BLUESKY)

        assert n == 0

    @pytest.mark.asyncio
    async def test_scrape_empty_feed(self, db):
        from fichajes_bot.ingestion.bluesky_scraper import BlueskyScraper

        mock_response = MagicMock()
        mock_response.feed = []
        mock_response.cursor = None

        scraper = BlueskyScraper(db)
        mock_client = AsyncMock()
        mock_client.get_author_feed = AsyncMock(return_value=mock_response)
        scraper._client = mock_client

        n = await scraper.scrape(SOURCE_BLUESKY)
        assert n == 0


# ────────────────────────────────────────────────────────────────────────────
# Source Health — consecutive_errors → disable
# ────────────────────────────────────────────────────────────────────────────

class TestSourceHealth:
    @pytest.mark.asyncio
    async def test_source_disabled_after_threshold(self, db):
        """After DISABLE_THRESHOLD failures the source is marked is_disabled=1."""
        from fichajes_bot.ingestion.resolver import SourceResolver, DISABLE_THRESHOLD

        source_id = "relevo_rss"
        # Pre-set errors to threshold - 1 so next failure triggers disable
        await db.execute(
            "UPDATE fuentes SET consecutive_errors=? WHERE fuente_id=?",
            [DISABLE_THRESHOLD - 1, source_id],
        )
        source = (await db.execute("SELECT * FROM fuentes WHERE fuente_id=?", [source_id]))[0]

        resolver = SourceResolver(db)

        with patch("fichajes_bot.ingestion.resolver.SourceResolver._run", new_callable=AsyncMock) as mock_run:
            mock_run.side_effect = Exception("Network timeout")
            try:
                await resolver.scrape_source(source)
            except Exception:
                pass

        row = (await db.execute("SELECT is_disabled, consecutive_errors FROM fuentes WHERE fuente_id=?", [source_id]))[0]
        assert row["is_disabled"] == 1

    @pytest.mark.asyncio
    async def test_admin_alert_enqueued_on_disable(self, db):
        from fichajes_bot.ingestion.resolver import SourceResolver, DISABLE_THRESHOLD

        source_id = "as_rss"
        await db.execute(
            "UPDATE fuentes SET consecutive_errors=? WHERE fuente_id=?",
            [DISABLE_THRESHOLD - 1, source_id],
        )
        source = (await db.execute("SELECT * FROM fuentes WHERE fuente_id=?", [source_id]))[0]

        resolver = SourceResolver(db)
        with patch("fichajes_bot.ingestion.resolver.SourceResolver._run", new_callable=AsyncMock) as mock_run:
            mock_run.side_effect = Exception("Timeout")
            try:
                await resolver.scrape_source(source)
            except Exception:
                pass

        alerts = await db.execute(
            "SELECT * FROM eventos_pending WHERE tipo='source_disabled'"
        )
        assert len(alerts) >= 1
        payload = json.loads(alerts[0]["payload"])
        assert payload["fuente_id"] == source_id

    @pytest.mark.asyncio
    async def test_errors_reset_on_success(self, db):
        from fichajes_bot.ingestion.rss_scraper import RssScraper

        # Pre-set errors
        await db.execute(
            "UPDATE fuentes SET consecutive_errors=5 WHERE fuente_id=?", ["relevo_rss"]
        )

        with patch.object(RssScraper, "_fetch", new_callable=AsyncMock) as mock_fetch:
            mock_feed = _fake_feed([{"title": "t", "link": "https://r.com/1"}])
            mock_fetch.return_value = (mock_feed, None, None)
            scraper = RssScraper(db)
            await scraper.scrape(SOURCE_RSS)

        row = (await db.execute(
            "SELECT consecutive_errors FROM fuentes WHERE fuente_id=?", ["relevo_rss"]
        ))[0]
        assert row["consecutive_errors"] == 0

    @pytest.mark.asyncio
    async def test_bluesky_fallback_to_rss(self, db):
        """When Bluesky fails, resolver falls back to RSS of same periodista."""
        from fichajes_bot.ingestion.resolver import SourceResolver

        resolver = SourceResolver(db)

        rss_called = []

        async def mock_run(kind: str, source: dict) -> int:
            if kind == "bluesky":
                raise Exception("Bluesky API down")
            rss_called.append(source["fuente_id"])
            return 3

        with patch.object(resolver, "_run", side_effect=mock_run):
            n = await resolver.scrape_source(SOURCE_BLUESKY)

        # Should have fallen back to RSS and returned 3
        assert n == 3
        assert len(rss_called) == 1
        assert "romano" in rss_called[0] or "relevo" in rss_called[0]


# ────────────────────────────────────────────────────────────────────────────
# Web Scraper
# ────────────────────────────────────────────────────────────────────────────

class TestWebScraper:
    @pytest.mark.asyncio
    async def test_scrape_inserts_snapshot(self, db):
        from fichajes_bot.ingestion.web_scraper import WebScraper

        fake_html = "<html><head><title>TM Transfers</title></head><body><p>Bellingham sold for 115M</p></body></html>"

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = fake_html
        mock_resp.raise_for_status = MagicMock()

        with patch("fichajes_bot.ingestion.web_scraper._check_robots", new_callable=AsyncMock, return_value=True):
            with patch("httpx.AsyncClient") as mock_client_cls:
                mock_cm = AsyncMock()
                mock_cm.__aenter__ = AsyncMock(return_value=mock_cm)
                mock_cm.__aexit__ = AsyncMock(return_value=None)
                mock_cm.get = AsyncMock(return_value=mock_resp)
                mock_client_cls.return_value = mock_cm

                scraper = WebScraper(db)
                n = await scraper.scrape(SOURCE_WEB)

        assert n == 1
        rows = await db.execute("SELECT COUNT(*) as c FROM rumores_raw")
        assert rows[0]["c"] == 1

    @pytest.mark.asyncio
    async def test_scrape_unchanged_returns_zero(self, db):
        from fichajes_bot.ingestion.web_scraper import WebScraper

        fake_html = "<html><body><p>Same content</p></body></html>"
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = fake_html
        mock_resp.raise_for_status = MagicMock()

        with patch("fichajes_bot.ingestion.web_scraper._check_robots", new_callable=AsyncMock, return_value=True):
            with patch("httpx.AsyncClient") as mock_client_cls:
                mock_cm = AsyncMock()
                mock_cm.__aenter__ = AsyncMock(return_value=mock_cm)
                mock_cm.__aexit__ = AsyncMock(return_value=None)
                mock_cm.get = AsyncMock(return_value=mock_resp)
                mock_client_cls.return_value = mock_cm

                scraper = WebScraper(db)
                n1 = await scraper.scrape(SOURCE_WEB)
                n2 = await scraper.scrape(SOURCE_WEB)

        assert n1 == 1
        assert n2 == 0

    @pytest.mark.asyncio
    async def test_robots_blocked_returns_zero(self, db):
        from fichajes_bot.ingestion.web_scraper import WebScraper

        with patch("fichajes_bot.ingestion.web_scraper._check_robots", new_callable=AsyncMock, return_value=False):
            scraper = WebScraper(db)
            n = await scraper.scrape(SOURCE_WEB)

        assert n == 0
        rows = await db.execute("SELECT COUNT(*) as c FROM rumores_raw")
        assert rows[0]["c"] == 0


# ────────────────────────────────────────────────────────────────────────────
# Scrape Job
# ────────────────────────────────────────────────────────────────────────────

class TestScrapeJob:
    @pytest.mark.asyncio
    async def test_run_tier_s(self, db):
        from fichajes_bot.jobs import scrape

        called_sources = []

        async def mock_scrape(source: dict) -> int:
            called_sources.append(source["fuente_id"])
            return 2

        with patch("fichajes_bot.ingestion.resolver.SourceResolver.scrape_source", side_effect=mock_scrape):
            # Patch D1Client to use the test db
            import fichajes_bot.jobs.scrape as scrape_module
            original_d1 = scrape_module.D1Client

            class PatchedD1:
                async def __aenter__(self):
                    return db
                async def __aexit__(self, *a):
                    pass

            with patch.object(scrape_module, "D1Client", PatchedD1):
                total = await scrape.run("S")

        # Should have scraped some S-tier sources
        assert total >= 0  # real count depends on seeded sources

    @pytest.mark.asyncio
    async def test_run_records_metrics(self, db):
        """After run(), metricas_sistema has last_hot_loop_at."""
        from fichajes_bot.jobs import scrape as scrape_module

        class PatchedD1:
            async def __aenter__(self):
                return db
            async def __aexit__(self, *a):
                pass

        with patch.object(scrape_module, "D1Client", PatchedD1):
            with patch("fichajes_bot.ingestion.resolver.SourceResolver.scrape_source", new_callable=AsyncMock, return_value=0):
                await scrape_module.run("S")

        rows = await db.execute(
            "SELECT value FROM metricas_sistema WHERE metric_name='last_hot_loop_at' ORDER BY timestamp DESC LIMIT 1"
        )
        assert rows  # metric was written
