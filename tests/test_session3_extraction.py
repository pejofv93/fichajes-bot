"""Session 3 tests — hybrid extractor: prefilter, regex, lexicon, gemini, pipeline."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from fichajes_bot.extraction.confidence import THRESHOLD, compute_confidence, needs_llm
from fichajes_bot.extraction.language_detect import detect
from fichajes_bot.extraction.prefilter import prefilter, prefilter_debug
from fichajes_bot.extraction.regex_extractor import RegexExtractor


# ════════════════════════════════════════════════════════════════════════════
# PREFILTER — 30 cases
# ════════════════════════════════════════════════════════════════════════════

PREFILTER_POSITIVE = [
    # Spanish
    "Real Madrid ficha a Mbappé por 180 millones",
    "El Real Madrid ha alcanzado un acuerdo total con el jugador",
    "Aquí vamos: Bellingham al Real Madrid, contrato firmado",
    "Acuerdo cerrado. Real Madrid y Dortmund llegan a un trato",
    "Revisión médica mañana para el nuevo fichaje del Madrid",
    "Florentino Pérez anuncia el traspaso del centrocampista",
    "Los blancos cierran la incorporación del defensa",
    "Real Madrid CF presenta a su nuevo atacante esta tarde",
    "Ancelotti confirma el fichaje del extremo internacional",
    "El merengue llega a Madrid para firmar su contrato",
    # English
    "Here we go! Real Madrid sign new midfielder – contract agreed",
    "Real Madrid are interested in signing the striker this summer",
    "Done deal: Real Madrid complete signing of the winger",
    "Real Madrid have made contact over the transfer of the defender",
    "Medical scheduled for Real Madrid new signing tomorrow",
    "Real Madrid want to sign the player in the January window",
    # Italian
    "Real Madrid: accordo trovato per il centrocampista brasiliano",
    "Visite mediche per il nuovo acquisto del Real Madrid domani",
    "Il Real Madrid vuole il giocatore per la prossima stagione",
    # German
    "Real Madrid: Einigung erzielt – Wechsel perfekt",
    "Medizincheck bei Real Madrid morgen geplant",
    "Interesse von Real Madrid am Mittelfeldspieler bestätigt",
    # French
    "Accord trouvé entre le Real Madrid et le club vendeur",
    "Real Madrid: visite médicale prévue pour le nouveau joueur",
    "Le Real Madrid veut signer le milieu de terrain cet été",
]

PREFILTER_NEGATIVE = [
    # No RM mention
    "Barcelona sign new striker from Atletico Madrid for 50M",
    "Manchester City complete the signing of the midfielder",
    "Here we go! PSG sign the striker – done deal confirmed",
    "Juventus have reached an agreement with the player",
    "Bayern Munich and Dortmund agree fee for the defender",
    # RM mention but no transfer signal
    "Real Madrid beat Barcelona 3-1 in El Clásico last night",
    "Real Madrid draw 2-2 against Atletico in the derby",
    "Ancelotti discusses the team's tactics ahead of the match",
    "Real Madrid youth academy produces another talented player",
    "Bernabeu stadium renovation expected to finish next year",
]


class TestPrefilter:
    @pytest.mark.parametrize("text", PREFILTER_POSITIVE)
    def test_positive_cases(self, text):
        assert prefilter(text), f"Should PASS: {text}"

    @pytest.mark.parametrize("text", PREFILTER_NEGATIVE)
    def test_negative_cases(self, text):
        assert not prefilter(text), f"Should FAIL: {text}"

    def test_empty_string(self):
        assert not prefilter("")

    def test_none_like_empty(self):
        assert not prefilter("   ")

    def test_debug_shows_rm_match(self):
        d = prefilter_debug("Real Madrid sign new player")
        assert d["rm_match"] is not None

    def test_debug_shows_transfer_match(self):
        d = prefilter_debug("Real Madrid sign new player")
        assert d["transfer_match"] is not None

    def test_case_insensitive(self):
        assert prefilter("REAL MADRID FICHAJE OFICIAL")
        assert prefilter("real madrid done deal")


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
# REGEX EXTRACTOR — 50 curated texts, accuracy > 85% (43/50)
# ════════════════════════════════════════════════════════════════════════════

# Each tuple: (text, expected_tipo, expected_fase_min, lang)
REGEX_CASES = [
    # ── Spanish FICHAJE ────────────────────────────────────────────────────
    ("Aquí vamos. Real Madrid firma el contrato con Mbappé.",            "FICHAJE", 6, "es"),
    ("Acuerdo total alcanzado entre Real Madrid y el club cedente.",     "FICHAJE", 6, "es"),
    ("Contrato firmado, presentación mañana en el Bernabéu.",           "FICHAJE", 6, "es"),
    ("Fichaje confirmado: el jugador llega al Real Madrid.",            "FICHAJE", 6, "es"),
    ("Ya es oficial. El Real Madrid anuncia el fichaje.",               "FICHAJE", 6, "es"),
    ("Done deal. El Madrid acuerda el traspaso.",                       "FICHAJE", 6, "es"),
    ("Pasa el médico mañana en las instalaciones del Madrid.",          "FICHAJE", 5, "es"),
    ("Revisión médica completada. Contrato hasta 2029.",               "FICHAJE", 5, "es"),
    ("Acuerdo cerrado entre clubs. El jugador viaja a Madrid.",        "FICHAJE", 5, "es"),
    ("Acuerdo personal alcanzado entre el jugador y el club.",         "FICHAJE", 4, "es"),
    ("Negociaciones avanzadas entre Real Madrid y el vendedor.",       "FICHAJE", 3, "es"),
    ("Oferta presentada por el Real Madrid al club francés.",          "FICHAJE", 3, "es"),
    ("El Real Madrid quiere al centrocampista para el próximo verano.","FICHAJE", 2, "es"),
    ("Interés del Real Madrid en el extremo alemán.",                  "FICHAJE", 1, "es"),
    # ── Spanish SALIDA ─────────────────────────────────────────────────────
    ("El jugador no renovará con el Real Madrid.",                     "SALIDA",  3, "es"),
    ("Ha pedido la salida del club blanco.",                           "SALIDA",  3, "es"),
    ("Salida confirmada del delantero al final de temporada.",         "SALIDA",  5, "es"),
    ("Venta cerrada por 80 millones de euros.",                        "SALIDA",  6, "es"),
    ("Rescisión acordada entre el jugador y el Real Madrid.",          "SALIDA",  5, "es"),
    ("Fuera de los planes del entrenador para la próxima temporada.",  "SALIDA",  3, "es"),
    # ── Spanish CESION ─────────────────────────────────────────────────────
    ("Cedido al Borussia Dortmund por una temporada.",                 "CESION",  5, "es"),
    ("Cesión confirmada del joven canterano al equipo alemán.",        "CESION",  6, "es"),
    # ── Spanish RENOVACION ─────────────────────────────────────────────────
    ("Renovación acordada con el capitán hasta 2027.",                 "RENOVACION", 5, "es"),
    ("Nuevo contrato firmado. Renueva hasta 2028.",                    "RENOVACION", 6, "es"),
    # ── English FICHAJE ────────────────────────────────────────────────────
    ("Here we go! Real Madrid sign the midfielder – contract agreed.", "FICHAJE", 6, "en"),
    ("Done deal confirmed. Real Madrid complete the transfer.",        "FICHAJE", 6, "en"),
    ("Contract signed. Real Madrid announce new arrival.",             "FICHAJE", 6, "en"),
    ("Medical scheduled for tomorrow at Real Madrid training ground.", "FICHAJE", 5, "en"),
    ("Fee agreed between Real Madrid and the selling club.",          "FICHAJE", 4, "en"),
    ("Personal terms agreed between the player and Real Madrid.",     "FICHAJE", 4, "en"),
    ("Real Madrid are in advanced talks to sign the striker.",        "FICHAJE", 3, "en"),
    ("Formal offer submitted by Real Madrid for the defender.",       "FICHAJE", 3, "en"),
    ("Real Madrid have made contact over signing the player.",        "FICHAJE", 2, "en"),
    ("Real Madrid are interested in signing the winger.",             "FICHAJE", 1, "en"),
    # ── English SALIDA ─────────────────────────────────────────────────────
    ("The player will not renew his contract at Real Madrid.",        "SALIDA",  3, "en"),
    ("Has asked to leave Real Madrid this summer.",                   "SALIDA",  3, "en"),
    ("Sale agreed between Real Madrid and the buying club.",          "SALIDA",  6, "en"),
    ("Contract not renewed. Player leaves at end of season.",         "SALIDA",  5, "en"),
    # ── English RENOVACION ─────────────────────────────────────────────────
    ("Contract extension signed until 2028 at Real Madrid.",          "RENOVACION", 5, "en"),
    ("New deal signed. Renewal confirmed at Real Madrid.",            "RENOVACION", 6, "en"),
    # ── Italian ────────────────────────────────────────────────────────────
    ("Accordo trovato tra Real Madrid e il club cedente.",            "FICHAJE", 5, "it"),
    ("Fumata bianca per il trasferimento al Real Madrid.",            "FICHAJE", 6, "it"),
    ("Visite mediche completate. Contratto firmato.",                 "FICHAJE", 5, "it"),
    ("Non rinnoverà con il Real Madrid.",                             "SALIDA",  3, "it"),
    # ── German ─────────────────────────────────────────────────────────────
    ("Einigung erzielt! Wechsel zu Real Madrid perfekt.",             "FICHAJE", 5, "de"),
    ("Deal perfekt, Medizincheck morgen bei Real Madrid.",            "FICHAJE", 6, "de"),
    ("Verlässt Real Madrid im Sommer ablösefrei.",                    "SALIDA",  5, "de"),
    # ── French ─────────────────────────────────────────────────────────────
    ("Accord trouvé entre le Real Madrid et le club vendeur.",        "FICHAJE", 5, "fr"),
    ("Transfert confirmé, contrat signé au Real Madrid.",             "FICHAJE", 6, "fr"),
    ("Départ confirmé. Il quitte le Real Madrid cet été.",            "SALIDA",  6, "fr"),
]


class TestRegexExtractor:
    def setup_method(self):
        self.extractor = RegexExtractor()

    @pytest.mark.parametrize("text,expected_tipo,min_fase,lang", REGEX_CASES)
    def test_regex_accuracy(self, text, expected_tipo, min_fase, lang):
        result = self.extractor.extract(text, lang)
        assert result is not None, f"Expected match for: {text[:60]}"
        assert result.tipo_operacion == expected_tipo, (
            f"Expected {expected_tipo}, got {result.tipo_operacion} for: {text[:60]}"
        )
        assert result.fase_rumor >= min_fase - 1, (  # allow ±1 phase
            f"Expected fase >= {min_fase-1}, got {result.fase_rumor} for: {text[:60]}"
        )

    def test_no_match_returns_none(self):
        result = self.extractor.extract("Cristiano Ronaldo scores a hat-trick for Al Nassr", "en")
        assert result is None

    def test_high_confidence_phase6(self):
        r = self.extractor.extract("Here we go! Real Madrid sign Bellingham", "en")
        assert r is not None
        assert r.confianza >= 0.90

    def test_low_confidence_phase1(self):
        r = self.extractor.extract("Real Madrid are interested in signing the player", "en")
        assert r is not None
        assert r.confianza < 0.60

    def test_negation_reduces_confidence(self):
        r = self.extractor.extract(
            "Real Madrid contract signed – FAKE NEWS, totally false", "en"
        )
        assert r is not None
        assert r.negation_found is True
        assert r.confianza < 0.70

    def test_known_name_extraction(self):
        r = self.extractor.extract("Real Madrid sign Bellingham on a 5-year deal", "en")
        assert r is not None
        assert r.jugador_nombre is not None
        assert "bellingham" in r.jugador_nombre.lower()

    def test_accuracy_threshold(self):
        """At least 85% of 50 cases must produce the correct tipo."""
        correct = 0
        total = len(REGEX_CASES)
        for text, expected_tipo, min_fase, lang in REGEX_CASES:
            r = self.extractor.extract(text, lang)
            if r is not None and r.tipo_operacion == expected_tipo:
                correct += 1
        accuracy = correct / total
        assert accuracy >= 0.85, (
            f"Regex accuracy {accuracy:.1%} < 85% ({correct}/{total} correct)"
        )


# ════════════════════════════════════════════════════════════════════════════
# LEXICON MATCHER
# ════════════════════════════════════════════════════════════════════════════

class TestLexiconMatcher:
    def _make_entries(self) -> list[dict]:
        return [
            {"frase": "here we go", "idioma": "en", "categoria": "fichaje",
             "fase_rumor": 6, "tipo_operacion": "FICHAJE", "peso_base": 0.98},
            {"frase": "aquí vamos", "idioma": "es", "categoria": "fichaje",
             "fase_rumor": 6, "tipo_operacion": "FICHAJE", "peso_base": 0.98},
            {"frase": "contrato firmado", "idioma": "es", "categoria": "fichaje",
             "fase_rumor": 6, "tipo_operacion": "FICHAJE", "peso_base": 0.97},
            {"frase": "no renovará", "idioma": "es", "categoria": "salida",
             "fase_rumor": 3, "tipo_operacion": "SALIDA", "peso_base": 0.75},
            {"frase": "fee agreed", "idioma": "en", "categoria": "fichaje",
             "fase_rumor": 4, "tipo_operacion": "FICHAJE", "peso_base": 0.82},
        ]

    def test_match_found(self):
        from fichajes_bot.extraction.lexicon_matcher import LexiconMatcher
        m = LexiconMatcher()
        m.load_from_list(self._make_entries())
        matches = m.match("Real Madrid: here we go, contract signed!", "en")
        assert len(matches) >= 1
        frases = [x["frase"] for x in matches]
        assert "here we go" in frases

    def test_match_language_filter(self):
        from fichajes_bot.extraction.lexicon_matcher import LexiconMatcher
        m = LexiconMatcher()
        m.load_from_list(self._make_entries())
        # English text, should NOT match Spanish entries
        matches = m.match("here we go Real Madrid signing", "en")
        for match in matches:
            lang = (match.get("idioma") or "")[:2].lower()
            assert lang in ("en", ""), f"Got non-English entry: {match}"

    def test_no_match(self):
        from fichajes_bot.extraction.lexicon_matcher import LexiconMatcher
        m = LexiconMatcher()
        m.load_from_list(self._make_entries())
        matches = m.match("Barcelona wins the league title", "es")
        assert matches == []

    def test_compute_weight_empty(self):
        from fichajes_bot.extraction.lexicon_matcher import LexiconMatcher
        m = LexiconMatcher()
        m.load_from_list([])
        assert m.compute_weight([]) == 0.0

    def test_compute_weight_single(self):
        from fichajes_bot.extraction.lexicon_matcher import LexiconMatcher
        m = LexiconMatcher()
        entries = self._make_entries()
        m.load_from_list(entries)
        matches = m.match("here we go", "en")
        w = m.compute_weight(matches)
        assert w >= 0.90

    def test_best_tipo(self):
        from fichajes_bot.extraction.lexicon_matcher import LexiconMatcher
        m = LexiconMatcher()
        m.load_from_list(self._make_entries())
        matches = m.match("aquí vamos, contrato firmado", "es")
        tipo = m.best_tipo(matches)
        assert tipo == "FICHAJE"

    def test_best_fase(self):
        from fichajes_bot.extraction.lexicon_matcher import LexiconMatcher
        m = LexiconMatcher()
        m.load_from_list(self._make_entries())
        matches = m.match("aquí vamos, contrato firmado", "es")
        fase = m.best_fase(matches)
        assert fase == 6

    @pytest.mark.asyncio
    async def test_load_from_db(self, db):
        """Lexicon entries seeded in DB are loadable."""
        from fichajes_bot.extraction.lexicon_matcher import LexiconMatcher
        # Load all entries (there are 200+ seeded)
        entries = await db.execute("SELECT * FROM lexicon_entries")
        assert len(entries) > 100

        m = LexiconMatcher()
        m.load_from_list(entries)
        assert m._loaded

        # Verify Spanish and English phrase both match
        es_matches = m.match("aquí vamos, contrato firmado", "es")
        assert len(es_matches) >= 1, "Should find Spanish phrases"

        en_matches = m.match("here we go signed contract", "en")
        assert len(en_matches) >= 1, "Should find English phrases"


# ════════════════════════════════════════════════════════════════════════════
# CONFIDENCE
# ════════════════════════════════════════════════════════════════════════════

class TestConfidence:
    def test_high_regex_no_lex_above_threshold(self):
        c = compute_confidence(regex_confianza=0.98, lexicon_weight=0.0, n_lexicon_matches=0)
        assert c >= THRESHOLD

    def test_low_regex_needs_llm(self):
        c = compute_confidence(regex_confianza=0.45, lexicon_weight=0.0, n_lexicon_matches=0)
        assert needs_llm(c)

    def test_corroboration_boosts_confidence(self):
        c_alone = compute_confidence(0.65, 0.0, 0)
        c_combo = compute_confidence(0.65, 0.70, 3)
        assert c_combo > c_alone

    def test_negation_penalty(self):
        c_clean = compute_confidence(0.90, 0.90, 2, negation_found=False)
        c_negated = compute_confidence(0.90, 0.90, 2, negation_found=True)
        assert c_negated < c_clean

    def test_trial_balloon_penalty(self):
        c_clean = compute_confidence(0.70, 0.70, 2, is_trial_balloon=False)
        c_balloon = compute_confidence(0.70, 0.70, 2, is_trial_balloon=True)
        assert c_balloon < c_clean

    def test_zero_input_returns_zero(self):
        c = compute_confidence(None, 0.0, 0)
        assert c == 0.0

    def test_needs_llm_below_threshold(self):
        assert needs_llm(0.50) is True
        assert needs_llm(0.59) is True

    def test_no_llm_at_threshold(self):
        assert needs_llm(THRESHOLD) is False
        assert needs_llm(0.95) is False


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


class TestExtractionPipeline:
    @pytest.mark.asyncio
    async def test_high_confidence_text_uses_regex_no_gemini(self, db):
        """Phase-6 text → confidence >= 0.6, no Gemini call needed."""
        from fichajes_bot.extraction.pipeline import ExtractionPipeline

        pipeline = ExtractionPipeline(db)
        gemini_called = []

        async def mock_gemini_extract(text, idioma="es"):
            gemini_called.append(text)
            return None

        pipeline._gemini.extract = mock_gemini_extract

        raw = _make_raw("Real Madrid: here we go! Test Incoming Player XYZ signs contract. Done deal confirmed.")
        result = await pipeline.process(raw)

        assert result is not None
        assert result["extraido_con"] == "regex"
        assert result["tipo_operacion"] == "FICHAJE"
        assert len(gemini_called) == 0

    @pytest.mark.asyncio
    async def test_low_confidence_falls_through_to_gemini(self, db):
        """Low-confidence text → Gemini is called."""
        from fichajes_bot.extraction.pipeline import ExtractionPipeline

        pipeline = ExtractionPipeline(db)
        gemini_called = []

        fake_gemini_result = {
            "es_real_madrid": True,
            "tipo_operacion": "FICHAJE",
            "jugador_nombre": "TestPlayer",
            "confianza": 0.80,
            "fase_rumor": 3,
            "lexico_detectado": "sondeo",
            "club_destino": None,
            "club_origen": None,
        }

        async def mock_gemini_extract(text, idioma="es"):
            gemini_called.append(text)
            return fake_gemini_result

        pipeline._gemini.extract = mock_gemini_extract

        # Text that prefilter passes and regex gives phase-1 low confidence → Gemini called
        raw = _make_raw(
            "Real Madrid are interested in signing the midfielder this summer.",
            idioma="en",
        )
        result = await pipeline.process(raw)

        assert len(gemini_called) == 1

    @pytest.mark.asyncio
    async def test_budget_exceeded_uses_regex_fallback(self, db):
        """GeminiBudgetExceeded → fallback to regex result, no crash."""
        from fichajes_bot.extraction.gemini_client import GeminiBudgetExceeded
        from fichajes_bot.extraction.pipeline import ExtractionPipeline

        pipeline = ExtractionPipeline(db)

        async def mock_gemini_extract(text, idioma="es"):
            raise GeminiBudgetExceeded("limit hit")

        pipeline._gemini.extract = mock_gemini_extract

        # Text that gives weak but non-zero regex signal
        raw = _make_raw(
            "Real Madrid are interested in signing the midfielder this summer.",
            idioma="en",
        )
        # Should not raise — should fall back to regex result
        result = await pipeline.process(raw)
        # May be None (if below fallback threshold) — but must NOT raise
        # The key assertion is that no exception propagated
        assert True  # reached here without exception

    @pytest.mark.asyncio
    async def test_prefilter_blocks_non_rm_text(self, db):
        """Text without RM keywords → None without any DB access."""
        from fichajes_bot.extraction.pipeline import ExtractionPipeline

        pipeline = ExtractionPipeline(db)
        raw = _make_raw("Barcelona sign new striker from Atletico.", idioma="es")
        result = await pipeline.process(raw)
        assert result is None

    @pytest.mark.asyncio
    async def test_empty_text_returns_none(self, db):
        from fichajes_bot.extraction.pipeline import ExtractionPipeline

        pipeline = ExtractionPipeline(db)
        raw = _make_raw("", idioma="en")
        result = await pipeline.process(raw)
        assert result is None

    @pytest.mark.asyncio
    async def test_result_persisted_to_rumores(self, db):
        """Successful extraction inserts a row into rumores."""
        from fichajes_bot.extraction.pipeline import ExtractionPipeline

        pipeline = ExtractionPipeline(db)
        pipeline._gemini.extract = AsyncMock(return_value=None)

        raw = _make_raw(
            "Real Madrid: here we go! Bellingham signs 5-year contract. Done deal.",
            idioma="en",
        )
        result = await pipeline.process(raw)

        assert result is not None
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
        pipeline._gemini.extract = AsyncMock(return_value=None)

        raw = _make_raw(
            "Here we go! Real Madrid sign Bellingham – contract agreed done deal.",
            idioma="en",
        )
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
        pipeline._gemini.extract = AsyncMock(return_value=None)

        raw = _make_raw(
            "Real Madrid done deal: contract signed, medical completed.",
            idioma="en",
        )
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

        # Insert some raw items
        raw_items = [
            {
                "raw_id": str(uuid.uuid4()),
                "fuente_id": "romano_bluesky",
                "titulo": "Real Madrid: here we go! Done deal contract signed.",
                "texto_completo": "Real Madrid: here we go! Done deal, contract signed. Bellingham.",
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
            # Disable Gemini for speed
            with patch("fichajes_bot.extraction.gemini_client.GeminiClient.extract",
                       new_callable=AsyncMock, return_value=None):
                counts = await process_module.run(limit=10)

        # All items should have been processed (either extracted or discarded)
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
            with patch("fichajes_bot.extraction.gemini_client.GeminiClient.extract",
                       new_callable=AsyncMock, return_value=None):
                await process_module.run(limit=5)

        rows = await db.execute(
            "SELECT value FROM metricas_sistema WHERE metric_name='rumores_procesados_hoy' "
            "ORDER BY timestamp DESC LIMIT 1"
        )
        assert rows  # metric was written
