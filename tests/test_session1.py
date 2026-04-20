"""Session 1 tests — schema, seeding, and prefilter."""

from __future__ import annotations

import pytest

from fichajes_bot.extraction.prefilter import prefilter
from fichajes_bot.utils.helpers import sha256_hash, slugify


class TestPrefilter:
    def test_real_madrid_passes(self):
        assert prefilter("Real Madrid want to sign Mbappé")

    def test_unrelated_fails(self):
        assert not prefilter("Barcelona signed a new striker today")

    def test_bernabeu_passes(self):
        assert prefilter("Press conference at the Bernabeu")

    def test_ancelotti_passes(self):
        assert prefilter("Ancelotti confirmed the transfer")

    def test_empty_fails(self):
        assert not prefilter("")


class TestHelpers:
    def test_slug(self):
        assert slugify("Fabrizio Romano") == "fabrizio-romano"

    def test_slug_accents(self):
        assert slugify("Vinícius Júnior") == "vinicius-junior"

    def test_hash_deterministic(self):
        h1 = sha256_hash("url1", "title1")
        h2 = sha256_hash("url1", "title1")
        assert h1 == h2

    def test_hash_different(self):
        h1 = sha256_hash("url1", "title1")
        h2 = sha256_hash("url1", "title2")
        assert h1 != h2


class TestD1Schema:
    @pytest.mark.asyncio
    async def test_periodistas_seeded(self, db):
        rows = await db.execute("SELECT COUNT(*) as n FROM periodistas")
        assert rows[0]["n"] >= 50

    @pytest.mark.asyncio
    async def test_fuentes_seeded(self, db):
        rows = await db.execute("SELECT COUNT(*) as n FROM fuentes")
        assert rows[0]["n"] >= 25

    @pytest.mark.asyncio
    async def test_lexicon_seeded(self, db):
        rows = await db.execute("SELECT COUNT(*) as n FROM lexicon_entries")
        assert rows[0]["n"] >= 100

    @pytest.mark.asyncio
    async def test_flags_seeded(self, db):
        rows = await db.execute("SELECT COUNT(*) as n FROM flags_sistema")
        assert rows[0]["n"] >= 10

    @pytest.mark.asyncio
    async def test_all_18_tables_exist(self, db):
        tables = [
            "fuentes", "periodistas", "rumores_raw", "jugadores", "rumores",
            "score_history", "eventos_pending", "alertas_log", "metricas_sistema",
            "flags_sistema", "modelo_economico", "lexicon_entries", "llm_cache",
            "calibracion_periodistas", "substitution_graph", "cantera_jugadores",
            "cedidos", "retractaciones",
        ]
        for table in tables:
            rows = await db.execute(f"SELECT 1 FROM {table} LIMIT 1")
            # Should not raise — table exists


class TestRumorRawRepository:
    @pytest.mark.asyncio
    async def test_insert_and_dedup(self, db):
        from fichajes_bot.persistence.repositories import RumorRawRepository
        repo = RumorRawRepository(db)

        items = [
            {"fuente_id": "romano_bluesky", "hash_dedup": "hash001",
             "titulo": "Romano: here we go!", "url_canonico": "https://bsky.app/test1"},
            {"fuente_id": "romano_bluesky", "hash_dedup": "hash001",
             "titulo": "Romano: here we go!", "url_canonico": "https://bsky.app/test1"},
        ]
        await repo.insert_batch([items[0]])
        await repo.insert_batch([items[1]])  # duplicate — should be ignored

        rows = await db.execute("SELECT COUNT(*) as n FROM rumores_raw WHERE hash_dedup='hash001'")
        assert rows[0]["n"] == 1

    @pytest.mark.asyncio
    async def test_hash_check(self, db):
        from fichajes_bot.persistence.repositories import RumorRawRepository
        repo = RumorRawRepository(db)

        await repo.insert_batch([
            {"fuente_id": "romano_bluesky", "hash_dedup": "unique_hash_xyz",
             "titulo": "test", "url_canonico": "https://example.com"}
        ])
        exists = await repo.hashes_exist_batch(["unique_hash_xyz", "nonexistent"])
        assert "unique_hash_xyz" in exists
        assert "nonexistent" not in exists
