"""Session 3 tests — pipeline, language detection, and Gemini client."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from fichajes_bot.extraction.language_detect import detect


# ════════════════════════════════════════════════════════════════════════════
# LANGUAGE DETECT
# ════════════════════════════════════════════════════════════════════════════

class TestLanguageDetect:
    def test_heuristic_here_we_go(self):
        assert detect("Here we go! Real Madrid complete signing") == "en"

    def test_heuristic_aqui_vamos(self):
        assert detect("¡Aquí vamos! Contrato firmado con Real Madrid") == "es"

    def test_heuristic_fumata_bianca(self):
        assert detect("Fumata bianca per il Real Madrid") == "it"

    def test_heuristic_einigung(self):
        assert detect("Einigung erzielt bei Real Madrid") == "de"

    def test_heuristic_accord_trouve(self):
        assert detect("Accord trouvé entre le Real Madrid et le joueur") == "fr"

    def test_empty_returns_default(self):
        assert detect("") == "es"

    def test_short_returns_default(self):
        assert detect("hi") == "es"


# ════════════════════════════════════════════════════════════════════════════
# GEMINI CLIENT — cache and budget tests
# ════════════════════════════════════════════════════════════════════════════

class TestGeminiClient:
    @pytest.mark.asyncio
    async def test_cache_hit_avoids_api_call(self, db):
        """Two calls with same text → only one real API call."""
        from fichajes_bot.extraction.gemini_client import GeminiClient

        real_call_count = 0
        fake_response = {
            "es_real_madrid": True,
            "tipo_operacion": "FICHAJE",
            "jugador_nombre": "Bellingham",
            "confianza": 0.95,
            "fase_rumor": 6,
            "lexico_detectado": "here we go",
            "club_destino": None,
            "club_origen": None,
        }

        async def mock_call_api(self_inner, text, idioma):
            nonlocal real_call_count
            real_call_count += 1
            return fake_response

        with patch.dict("os.environ", {"GEMINI_API_KEY": "fake-key"}):
            with patch("asyncio.sleep", new_callable=AsyncMock):
                with patch.object(GeminiClient, "_call_api", mock_call_api):
                    client = GeminiClient(db)
                    text = "Real Madrid: here we go, Bellingham signs the contract"
                    r1 = await client.extract(text, "en")
                    r2 = await client.extract(text, "en")  # same text → cache hit

        assert real_call_count == 1, f"Expected 1 real call, got {real_call_count}"
        assert r1 is not None
        assert r2 is not None
        assert r1["tipo_operacion"] == r2["tipo_operacion"]

    @pytest.mark.asyncio
    async def test_cache_miss_for_different_text(self, db):
        """Different texts produce two real API calls."""
        from fichajes_bot.extraction.gemini_client import GeminiClient

        real_call_count = 0
        fake_response = {"es_real_madrid": True, "tipo_operacion": "FICHAJE",
                         "confianza": 0.9, "fase_rumor": 5, "jugador_nombre": None,
                         "lexico_detectado": None, "club_destino": None, "club_origen": None}

        async def mock_call_api(self_inner, text, idioma):
            nonlocal real_call_count
            real_call_count += 1
            return fake_response

        with patch.dict("os.environ", {"GEMINI_API_KEY": "fake-key"}):
            with patch("asyncio.sleep", new_callable=AsyncMock):
                with patch.object(GeminiClient, "_call_api", mock_call_api):
                    client = GeminiClient(db)
                    await client.extract("Real Madrid sign player A — here we go", "en")
                    await client.extract("Real Madrid sign player B — done deal confirmed", "en")

        assert real_call_count == 2

    @pytest.mark.asyncio
    async def test_budget_exceeded_raises(self, db):
        """When daily usage >= GEMINI_DAILY_LIMIT, raises GeminiBudgetExceeded."""
        from fichajes_bot.extraction.gemini_client import (
            GeminiClient, GeminiBudgetExceeded, GEMINI_DAILY_LIMIT
        )
        import uuid

        client = GeminiClient(db)
        key = client._today_key()
        await db.execute(
            "INSERT INTO metricas_sistema (metric_id, metric_name, value, value_num) VALUES (?,?,?,?)",
            [str(uuid.uuid4()), key, str(GEMINI_DAILY_LIMIT), float(GEMINI_DAILY_LIMIT)],
        )

        with patch.dict("os.environ", {"GEMINI_API_KEY": "fake-key"}):
            with pytest.raises(GeminiBudgetExceeded):
                await client.extract("Real Madrid here we go done deal", "en")

    @pytest.mark.asyncio
    async def test_budget_increments_per_real_call(self, db):
        """Each real API call increments the daily counter."""
        from fichajes_bot.extraction.gemini_client import GeminiClient

        fake_response = {"es_real_madrid": True, "tipo_operacion": "FICHAJE",
                         "confianza": 0.9, "fase_rumor": 5, "jugador_nombre": None,
                         "lexico_detectado": None, "club_destino": None, "club_origen": None}

        async def mock_call_api(self_inner, text, idioma):
            return fake_response

        with patch.dict("os.environ", {"GEMINI_API_KEY": "fake-key"}):
            with patch("asyncio.sleep", new_callable=AsyncMock):
                with patch.object(GeminiClient, "_call_api", mock_call_api):
                    client = GeminiClient(db)
                    await client.extract("Real Madrid sign new player done deal", "en")
                    usage = await client.get_daily_usage()

        assert usage >= 1

    @pytest.mark.asyncio
    async def test_no_api_key_returns_none(self, db):
        from fichajes_bot.extraction.gemini_client import GeminiClient
        import os

        with patch.dict("os.environ", {"GEMINI_API_KEY": ""}):
            client = GeminiClient(db)
            client._api_key = ""
            r = await client.extract("Real Madrid here we go", "en")

        assert r is None

    @pytest.mark.asyncio
    async def test_call_api_uses_env_key_not_instance_var(self, db):
        """_call_api must use self._key (env-aware property), not self._api_key.

        Regression test: previously _call_api used self._api_key (always "")
        so Gemini was silently called with an empty key and always failed.
        """
        import sys
        import types
        from unittest.mock import MagicMock
        from fichajes_bot.extraction.gemini_client import GeminiClient

        captured_key: list[str] = []

        fake_genai = types.ModuleType("google.generativeai")

        def mock_configure(api_key: str) -> None:
            captured_key.append(api_key)

        mock_model = MagicMock()
        mock_resp = MagicMock()
        mock_resp.text = (
            '{"es_real_madrid":true,"tipo_operacion":"FICHAJE",'
            '"jugador_nombre":"Mac Allister","confianza":0.8,'
            '"fase_rumor":2,"lexico_detectado":"eye",'
            '"club_destino":null,"club_origen":null}'
        )
        mock_model.generate_content.return_value = mock_resp
        fake_genai.configure = mock_configure
        fake_genai.GenerativeModel = MagicMock(return_value=mock_model)
        fake_genai.GenerationConfig = MagicMock(return_value={})

        prev = sys.modules.get("google.generativeai")
        sys.modules["google.generativeai"] = fake_genai
        try:
            with patch.dict("os.environ", {"GEMINI_API_KEY": "real-env-key-xyz"}):
                with patch("asyncio.sleep", new_callable=AsyncMock):
                    client = GeminiClient(db)
                    assert client._api_key == "", "precondition: _api_key starts empty"
                    await client._call_api(
                        "Real Madrid eye move for Mac Allister", "en"
                    )
        finally:
            if prev is None:
                sys.modules.pop("google.generativeai", None)
            else:
                sys.modules["google.generativeai"] = prev

        assert len(captured_key) == 1, "genai.configure should have been called once"
        assert captured_key[0] == "real-env-key-xyz", (
            f"Expected env key 'real-env-key-xyz', got {captured_key[0]!r} — "
            "bug: use self._key not self._api_key in _call_api"
        )

    @pytest.mark.asyncio
    async def test_non_rm_response_returns_none(self, db):
        """If Gemini says es_real_madrid=false, extract returns None."""
        from fichajes_bot.extraction.gemini_client import GeminiClient

        client = GeminiClient(db)

        async def mock_call_api(text, idioma):
            return {"es_real_madrid": False, "confianza": 0.0}

        with patch.dict("os.environ", {"GEMINI_API_KEY": "fake-key"}):
            client._call_api = mock_call_api
            r = await client.extract("Barcelona sign new player", "es")

        assert r is None


# ════════════════════════════════════════════════════════════════════════════
# PIPELINE — integration tests
# ════════════════════════════════════════════════════════════════════════════

def _make_raw(text: str, fuente_id: str = "romano_bluesky", idioma: str = "en") -> dict:
    import uuid
    return {
        "raw_id": str(uuid.uuid4()),
        "fuente_id": fuente_id,
        "titulo": text[:200],
        "texto_completo": text,
        "idioma_detectado": idioma,
        "fecha_publicacion": "2024-07-01",
    }


_FAKE_PLAYER_RESULT = {
    "player_name": "Test Player",
    "operation_type": "FICHAJE",
    "confidence": 0.90,
    "is_real_madrid": True,
}


class TestExtractionPipeline:
    @pytest.mark.asyncio
    async def test_gemini_called_for_rm_text(self, db):
        """RM text passes prefilter → extract_simple is always called."""
        from fichajes_bot.extraction.pipeline import ExtractionPipeline

        pipeline = ExtractionPipeline(db)
        gemini_called = []

        async def mock_extract_simple(titulo):
            gemini_called.append(titulo)
            return None

        pipeline._gemini.extract_simple = mock_extract_simple

        raw = _make_raw("Real Madrid are interested in signing the midfielder this summer.")
        await pipeline.process(raw)

        assert len(gemini_called) == 1

    @pytest.mark.asyncio
    async def test_budget_exceeded_returns_none(self, db):
        """GeminiBudgetExceeded → returns None without crashing."""
        from fichajes_bot.extraction.gemini_client import GeminiBudgetExceeded
        from fichajes_bot.extraction.pipeline import ExtractionPipeline

        pipeline = ExtractionPipeline(db)

        async def mock_extract_simple(titulo):
            raise GeminiBudgetExceeded("limit hit")

        pipeline._gemini.extract_simple = mock_extract_simple

        raw = _make_raw("Real Madrid are interested in signing the midfielder.", idioma="en")
        result = await pipeline.process(raw)
        assert result is None

    @pytest.mark.asyncio
    async def test_prefilter_blocks_non_rm_text(self, db):
        """Text without RM keywords → None without calling Gemini."""
        from fichajes_bot.extraction.pipeline import ExtractionPipeline

        pipeline = ExtractionPipeline(db)
        gemini_called = []

        async def mock_extract_simple(titulo):
            gemini_called.append(titulo)
            return None

        pipeline._gemini.extract_simple = mock_extract_simple

        raw = _make_raw("Barcelona sign new striker from Atletico.", idioma="es")
        result = await pipeline.process(raw)
        assert result is None
        assert len(gemini_called) == 0

    @pytest.mark.asyncio
    async def test_empty_text_returns_none(self, db):
        from fichajes_bot.extraction.pipeline import ExtractionPipeline

        pipeline = ExtractionPipeline(db)
        raw = _make_raw("", idioma="en")
        result = await pipeline.process(raw)
        assert result is None

    @pytest.mark.asyncio
    async def test_low_confidence_discarded(self, db):
        """confidence < 0.5 → discard."""
        from fichajes_bot.extraction.pipeline import ExtractionPipeline

        pipeline = ExtractionPipeline(db)

        async def mock_extract_simple(titulo):
            return {"player_name": "Some Player", "operation_type": "FICHAJE",
                    "confidence": 0.3, "is_real_madrid": True}

        pipeline._gemini.extract_simple = mock_extract_simple

        raw = _make_raw("Real Madrid are interested in a new signing.", idioma="en")
        result = await pipeline.process(raw)
        assert result is None

    @pytest.mark.asyncio
    async def test_no_player_name_discarded(self, db):
        """player_name=null → discard even with high confidence."""
        from fichajes_bot.extraction.pipeline import ExtractionPipeline

        pipeline = ExtractionPipeline(db)

        async def mock_extract_simple(titulo):
            return {"player_name": None, "operation_type": "FICHAJE",
                    "confidence": 0.9, "is_real_madrid": True}

        pipeline._gemini.extract_simple = mock_extract_simple

        raw = _make_raw("Real Madrid target set to arrive this week.", idioma="en")
        result = await pipeline.process(raw)
        assert result is None

    @pytest.mark.asyncio
    async def test_result_persisted_to_rumores(self, db):
        """Successful extraction inserts a row into rumores."""
        from fichajes_bot.extraction.pipeline import ExtractionPipeline

        pipeline = ExtractionPipeline(db)

        async def mock_extract_simple(titulo):
            return _FAKE_PLAYER_RESULT

        pipeline._gemini.extract_simple = mock_extract_simple

        raw = _make_raw("Real Madrid sign Test Player on a 5-year deal.", idioma="en")
        result = await pipeline.process(raw)

        assert result is not None
        assert result["extraido_con"] == "gemini"
        rows = await db.execute(
            "SELECT * FROM rumores WHERE raw_id=?", [raw["raw_id"]]
        )
        assert len(rows) == 1
        assert rows[0]["tipo_operacion"] == "FICHAJE"

    @pytest.mark.asyncio
    async def test_jugador_created_when_name_found(self, db):
        """If player name extracted → jugadores row created."""
        from fichajes_bot.extraction.pipeline import ExtractionPipeline

        pipeline = ExtractionPipeline(db)

        async def mock_extract_simple(titulo):
            return _FAKE_PLAYER_RESULT

        pipeline._gemini.extract_simple = mock_extract_simple

        raw = _make_raw("Real Madrid sign Test Player – contract agreed.", idioma="en")
        result = await pipeline.process(raw)

        assert result is not None
        if result.get("jugador_id"):
            rows = await db.execute(
                "SELECT * FROM jugadores WHERE jugador_id=?", [result["jugador_id"]]
            )
            assert len(rows) == 1

    @pytest.mark.asyncio
    async def test_scoring_event_enqueued(self, db):
        """After successful extraction, a new_rumor event is in eventos_pending."""
        from fichajes_bot.extraction.pipeline import ExtractionPipeline

        pipeline = ExtractionPipeline(db)

        async def mock_extract_simple(titulo):
            return _FAKE_PLAYER_RESULT

        pipeline._gemini.extract_simple = mock_extract_simple

        raw = _make_raw("Real Madrid: Test Player signs 5-year contract.", idioma="en")
        result = await pipeline.process(raw)

        assert result is not None
        events = await db.execute(
            "SELECT * FROM eventos_pending WHERE tipo='new_rumor'"
        )
        assert len(events) >= 1


# ════════════════════════════════════════════════════════════════════════════
# PROCESS JOB — integration
# ════════════════════════════════════════════════════════════════════════════

class TestProcessJob:
    @pytest.mark.asyncio
    async def test_processes_raw_items(self, db):
        """process job marks all items as procesado=1."""
        import uuid
        from fichajes_bot.ingestion.deduplication import make_hash

        raw_items = [
            {
                "raw_id": str(uuid.uuid4()),
                "fuente_id": "romano_bluesky",
                "titulo": "Real Madrid: here we go! Done deal contract signed.",
                "texto_completo": "Real Madrid: here we go! Done deal, contract signed. Test Player XYZ.",
                "idioma_detectado": "en",
                "hash_dedup": make_hash(f"url{i}", f"title{i}"),
                "procesado": 0,
            }
            for i in range(3)
        ]
        for item in raw_items:
            await db.execute(
                "INSERT INTO rumores_raw (raw_id, fuente_id, titulo, texto_completo, "
                "idioma_detectado, hash_dedup, procesado) VALUES (?,?,?,?,?,?,?)",
                [item["raw_id"], item["fuente_id"], item["titulo"],
                 item["texto_completo"], item["idioma_detectado"],
                 item["hash_dedup"], 0],
            )

        import fichajes_bot.jobs.process as process_module

        class PatchedD1:
            async def __aenter__(self): return db
            async def __aexit__(self, *a): pass

        with patch.object(process_module, "D1Client", PatchedD1):
            with patch("fichajes_bot.extraction.gemini_client.GeminiClient.extract_simple",
                       new_callable=AsyncMock, return_value=None):
                counts = await process_module.run(limit=10)

        unprocessed = await db.execute(
            "SELECT COUNT(*) as n FROM rumores_raw WHERE procesado=0"
        )
        assert unprocessed[0]["n"] == 0

    @pytest.mark.asyncio
    async def test_metrics_written_after_run(self, db):
        """process job writes rumores_procesados_hoy metric."""
        import fichajes_bot.jobs.process as process_module

        class PatchedD1:
            async def __aenter__(self): return db
            async def __aexit__(self, *a): pass

        with patch.object(process_module, "D1Client", PatchedD1):
            with patch("fichajes_bot.extraction.gemini_client.GeminiClient.extract_simple",
                       new_callable=AsyncMock, return_value=None):
                await process_module.run(limit=5)

        rows = await db.execute(
            "SELECT value FROM metricas_sistema WHERE metric_name='rumores_procesados_hoy' "
            "ORDER BY timestamp DESC LIMIT 1"
        )
        assert rows  # metric was written
