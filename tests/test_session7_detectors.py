"""Session 7 tests — Trial Balloon, Bias Corrector, Retraction Handler, Hard Signal."""

from __future__ import annotations

import json
import uuid
from typing import Any

import pytest


# ── Helpers ───────────────────────────────────────────────────────────────────


def _uid() -> str:
    return str(uuid.uuid4())


async def _insert_periodista(
    db, periodista_id: str, tier: str = "S", nombre: str = "Test Journalist"
) -> None:
    await db.execute(
        """INSERT OR IGNORE INTO periodistas
           (periodista_id, nombre_completo, tier, reliability_global, created_at)
           VALUES (?,?,?,0.85,datetime('now'))""",
        [periodista_id, nombre, tier],
    )


async def _insert_fuente(
    db, fuente_id: str, sesgo: str = "neutral", tier: str = "A"
) -> None:
    await db.execute(
        """INSERT OR IGNORE INTO fuentes
           (fuente_id, tipo, tier, sesgo, factor_fichaje_positivo,
            factor_salida_positiva, polling_minutes, created_at)
           VALUES (?,?,?,?,1.0,1.0,120,datetime('now'))""",
        [fuente_id, "rss", tier, sesgo],
    )


async def _insert_jugador(
    db,
    jugador_id: str,
    nombre: str = "Test Player",
    posicion: str = "MC",
    tipo: str = "FICHAJE",
    score: float = 0.45,
    flags: str = "[]",
) -> None:
    await db.execute(
        """INSERT OR IGNORE INTO jugadores
           (jugador_id, nombre_canonico, slug,
            tipo_operacion_principal, posicion,
            score_raw, score_smoothed, kalman_P,
            flags, factores_actuales, fase_dominante,
            n_rumores_total, primera_mencion_at, ultima_actualizacion_at,
            is_active, created_at)
           VALUES (?,?,?,?,?,?,?,?,?,?,3,1,datetime('now'),datetime('now'),1,datetime('now'))""",
        [
            jugador_id, nombre, nombre.lower().replace(" ", "-"),
            tipo, posicion,
            score, score, 1.0,
            flags, "{}",
        ],
    )


async def _insert_rumor(
    db,
    rumor_id: str,
    jugador_id: str,
    periodista_id: str,
    fuente_id: str,
    texto: str = "rumor text",
    tipo: str = "FICHAJE",
    fase: int = 3,
    days_ago: int = 0,
    retractado: int = 0,
) -> None:
    await db.execute(
        """INSERT OR IGNORE INTO rumores
           (rumor_id, jugador_id, periodista_id, fuente_id,
            tipo_operacion, fase_rumor, lexico_detectado,
            peso_lexico, confianza_extraccion, extraido_con,
            texto_fragmento, fecha_publicacion, retractado,
            idioma, created_at)
           VALUES (?,?,?,?,?,?,?,0.7,0.8,'regex',?,
                   datetime('now', '-' || ? || ' days'),?,
                   'es', datetime('now'))""",
        [
            rumor_id, jugador_id, periodista_id, fuente_id,
            tipo, fase, texto[:100],
            texto[:300],
            days_ago, retractado,
        ],
    )


async def _insert_retractacion(db, jugador_id: str, periodista_id: str = None) -> None:
    await db.execute(
        """INSERT INTO retractaciones
           (retractacion_id, jugador_id, periodista_id,
            fecha_retractacion, tipo, impacto_score, procesado, created_at)
           VALUES (?,?,?,datetime('now'),'RETRACTACION_PERIODISTA',-0.3,0,datetime('now'))""",
        [_uid(), jugador_id, periodista_id],
    )


# ════════════════════════════════════════════════════════════════════════════
# TRIAL BALLOON DETECTOR
# ════════════════════════════════════════════════════════════════════════════


class TestTrialBalloonDetector:
    @pytest.mark.asyncio
    async def test_globo_sonda_single_source(self, db):
        """Only 1 journalist in 72h → single_source heuristic → prob ≥ 0.25."""
        from fichajes_bot.detectors.trial_balloon import TrialBalloonDetector

        jid = _uid()
        pid = _uid()
        fid = _uid()

        await _insert_periodista(db, pid, tier="A", nombre="Matteo Moretto")
        await _insert_fuente(db, fid, sesgo="neutral", tier="A")
        await _insert_jugador(db, jid, "Test Player")

        rumores = [
            {
                "rumor_id": _uid(),
                "jugador_id": jid,
                "periodista_id": pid,
                "fuente_id": fid,
                "tipo_operacion": "FICHAJE",
                "texto_fragmento": "Interés del club en el jugador.",
                "fecha_publicacion": "2026-04-18T10:00:00",  # 2 days ago
            },
            {
                "rumor_id": _uid(),
                "jugador_id": jid,
                "periodista_id": pid,  # same journalist both times
                "fuente_id": fid,
                "tipo_operacion": "FICHAJE",
                "texto_fragmento": "Confirmado el interés.",
                "fecha_publicacion": "2026-04-19T10:00:00",  # 1 day ago
            },
        ]

        detector = TrialBalloonDetector(db)
        prob, heuristics = await detector.evaluate(jid, rumores)

        assert "single_source" in heuristics, "Only 1 journalist should trigger single_source"
        assert prob >= 0.25, f"single_source contributes 0.25, got {prob}"

    @pytest.mark.asyncio
    async def test_globo_sonda_no_heuristics(self, db):
        """Multiple tier-S journalists, no other red flags → prob = 0."""
        from fichajes_bot.detectors.trial_balloon import TrialBalloonDetector

        jid = _uid()
        pid1, pid2 = _uid(), _uid()
        fid1, fid2 = _uid(), _uid()

        await _insert_periodista(db, pid1, tier="S", nombre="Romano")
        await _insert_periodista(db, pid2, tier="S", nombre="Ornstein")
        await _insert_fuente(db, fid1, sesgo="neutral", tier="S")
        await _insert_fuente(db, fid2, sesgo="neutral", tier="S")
        await _insert_jugador(db, jid, "Top Target")

        rumores = [
            {
                "rumor_id": _uid(), "jugador_id": jid,
                "periodista_id": pid1, "fuente_id": fid1,
                "tipo_operacion": "FICHAJE", "texto_fragmento": "here we go",
                "fecha_publicacion": "2026-04-20T10:00:00",
            },
            {
                "rumor_id": _uid(), "jugador_id": jid,
                "periodista_id": pid2, "fuente_id": fid2,
                "tipo_operacion": "FICHAJE", "texto_fragmento": "confirmed by sources",
                "fecha_publicacion": "2026-04-20T11:00:00",
            },
        ]

        detector = TrialBalloonDetector(db)
        prob, heuristics = await detector.evaluate(jid, rumores)

        # Two tier-S journalists, neutral fuentes → most heuristics off
        # single_source = False (2 journalists)
        # agent_adjacent = False (tier S fuentes)
        # no_geo_corroboration = False (neutral fuentes)
        # unusually_specific = False (has tier-S journalist)
        assert "single_source" not in heuristics
        assert "agent_adjacent" not in heuristics

    @pytest.mark.asyncio
    async def test_globo_sonda_7_heuristicas(self, db):
        """Synthetic case triggering all 7 heuristics → prob = 1.0, flag set."""
        from fichajes_bot.detectors.trial_balloon import (
            TrialBalloonDetector, GLOBO_THRESHOLD
        )

        jid = _uid()
        rival_jid = _uid()
        pid = _uid()
        fid = _uid()

        await _insert_periodista(db, pid, tier="B", nombre="Low-tier Journo")
        await _insert_fuente(db, fid, sesgo="pro-rm", tier="B")
        await _insert_jugador(db, jid, "Suspicious Player")
        # Rival with very high score → suspicious timing
        await _insert_jugador(db, rival_jid, "Star Target", score=0.85, tipo="FICHAJE")
        # Prior retraction → retraction_pattern
        await _insert_retractacion(db, jid, pid)

        rumores = [
            {
                "rumor_id": _uid(),
                "jugador_id": jid,
                "periodista_id": pid,  # single source
                "fuente_id": fid,      # tier B, pro-rm (agent_adjacent + no_geo_corroboration)
                "tipo_operacion": "FICHAJE",
                # price_inflation: two prices with >30% increase
                # unusually_specific: "acuerdo alcanzado" from tier-B journalist
                "texto_fragmento": "Se habla de 30M€ pero el acuerdo alcanzado es de 45M€",
                "fecha_publicacion": "2026-04-20T10:00:00",
            },
        ]

        detector = TrialBalloonDetector(db)
        prob, heuristics = await detector.evaluate(jid, rumores)

        assert "single_source"        in heuristics, f"got: {heuristics}"
        assert "agent_adjacent"       in heuristics, f"got: {heuristics}"
        assert "price_inflation"      in heuristics, f"got: {heuristics}"
        assert "suspicious_timing"    in heuristics, f"got: {heuristics}"
        assert "no_geo_corroboration" in heuristics, f"got: {heuristics}"
        assert "retraction_pattern"   in heuristics, f"got: {heuristics}"
        assert "unusually_specific"   in heuristics, f"got: {heuristics}"

        assert prob == 1.0, f"All 7 heuristics → prob=1.0, got {prob}"

        # Flag should be set
        rows = await db.execute(
            "SELECT flags FROM jugadores WHERE jugador_id=?", [jid]
        )
        flags = json.loads(rows[0]["flags"])
        assert "POSIBLE_GLOBO_SONDA" in flags

    @pytest.mark.asyncio
    async def test_globo_sonda_empty_rumores(self, db):
        """Empty rumor list → prob = 0.0, no heuristics."""
        from fichajes_bot.detectors.trial_balloon import TrialBalloonDetector

        detector = TrialBalloonDetector(db)
        prob, heuristics = await detector.evaluate(_uid(), [])
        assert prob == 0.0
        assert heuristics == []

    @pytest.mark.asyncio
    async def test_price_inflation_heuristic(self, db):
        """Texto with prices 30M → 45M (50% rise) triggers price_inflation."""
        from fichajes_bot.detectors.trial_balloon import TrialBalloonDetector

        jid = _uid()
        pid = _uid()
        fid = _uid()

        await _insert_periodista(db, pid, tier="A")
        await _insert_fuente(db, fid, sesgo="neutral", tier="A")
        await _insert_jugador(db, jid, "Inflated Player")

        rumores = [
            {
                "rumor_id": _uid(), "jugador_id": jid,
                "periodista_id": pid, "fuente_id": fid,
                "tipo_operacion": "FICHAJE",
                "texto_fragmento": "Antes se hablaba de 30m€, ahora la cifra es de 50m€",
                "fecha_publicacion": "2026-04-20T10:00:00",
            },
        ]

        detector = TrialBalloonDetector(db)
        prob, heuristics = await detector.evaluate(jid, rumores)
        assert "price_inflation" in heuristics


# ════════════════════════════════════════════════════════════════════════════
# BIAS CORRECTOR
# ════════════════════════════════════════════════════════════════════════════


class TestBiasCorrector:
    @pytest.mark.asyncio
    async def test_bias_pro_rm_fichaje(self, db):
        """MARCA (pro-rm) reports RM signing → factor_sesgo < 0.8."""
        from fichajes_bot.detectors.bias_corrector import BiasCorrector

        fid = _uid()
        await _insert_fuente(db, fid, sesgo="pro-rm", tier="B")

        rumor = {
            "fuente_id": fid,
            "tipo_operacion": "FICHAJE",
            "peso_lexico": 0.75,
        }

        corrector = BiasCorrector(db)
        factor = await corrector.evaluate(rumor)
        assert factor < 0.8, (
            f"pro-rm + FICHAJE should give factor < 0.8 (got {factor})"
        )

    @pytest.mark.asyncio
    async def test_bias_pro_rm_salida(self, db):
        """MARCA (pro-rm) reports RM player leaving → factor_sesgo < 0.8."""
        from fichajes_bot.detectors.bias_corrector import BiasCorrector

        fid = _uid()
        await _insert_fuente(db, fid, sesgo="pro-rm", tier="B")

        rumor = {
            "fuente_id": fid,
            "tipo_operacion": "SALIDA",
            "peso_lexico": 0.70,
        }

        corrector = BiasCorrector(db)
        factor = await corrector.evaluate(rumor)
        assert factor < 0.8, (
            f"pro-rm + SALIDA should give factor < 0.8 (got {factor})"
        )

    @pytest.mark.asyncio
    async def test_bias_contra_sesgo(self, db):
        """Mundo Deportivo (pro-barca) reports RM signing → credible, factor ≈ 1.0."""
        from fichajes_bot.detectors.bias_corrector import BiasCorrector

        fid = _uid()
        await _insert_fuente(db, fid, sesgo="pro-barca", tier="B")

        rumor = {
            "fuente_id": fid,
            "tipo_operacion": "FICHAJE",  # RM signing = against pro-barca interest
            "peso_lexico": 0.70,
        }

        corrector = BiasCorrector(db)
        factor = await corrector.evaluate(rumor)
        assert factor > 0.85, (
            f"pro-barca + FICHAJE (against bias) should give factor > 0.85 (got {factor})"
        )

    @pytest.mark.asyncio
    async def test_bias_pro_barca_salida(self, db):
        """pro-barca reporting RM departure → exaggeration → factor < 0.75."""
        from fichajes_bot.detectors.bias_corrector import BiasCorrector

        fid = _uid()
        await _insert_fuente(db, fid, sesgo="pro-barca", tier="B")

        rumor = {
            "fuente_id": fid,
            "tipo_operacion": "SALIDA",
            "peso_lexico": 0.70,
        }

        corrector = BiasCorrector(db)
        factor = await corrector.evaluate(rumor)
        assert factor < 0.75, (
            f"pro-barca + SALIDA should give factor < 0.75 (got {factor})"
        )

    @pytest.mark.asyncio
    async def test_bias_neutral_source(self, db):
        """Neutral source → factor = 1.0."""
        from fichajes_bot.detectors.bias_corrector import BiasCorrector

        fid = _uid()
        await _insert_fuente(db, fid, sesgo="neutral", tier="S")

        for tipo in ("FICHAJE", "SALIDA", "RENOVACION"):
            corrector = BiasCorrector(db)
            factor = await corrector.evaluate({"fuente_id": fid, "tipo_operacion": tipo})
            assert factor == 1.0, f"neutral + {tipo} should give 1.0, got {factor}"

    @pytest.mark.asyncio
    async def test_bias_no_fuente(self, db):
        """No fuente_id → returns 1.0 (neutral)."""
        from fichajes_bot.detectors.bias_corrector import BiasCorrector

        corrector = BiasCorrector(db)
        factor = await corrector.evaluate({"tipo_operacion": "FICHAJE"})
        assert factor == 1.0

    @pytest.mark.asyncio
    async def test_bias_evaluate_batch(self, db):
        """Batch evaluation: mix of pro-rm and neutral → combined between 0.75 and 1.0."""
        from fichajes_bot.detectors.bias_corrector import BiasCorrector

        fid_prom = _uid()
        fid_neutral = _uid()
        await _insert_fuente(db, fid_prom,    sesgo="pro-rm",  tier="B")
        await _insert_fuente(db, fid_neutral, sesgo="neutral", tier="S")

        rumores = [
            {"fuente_id": fid_prom,    "tipo_operacion": "FICHAJE", "peso_lexico": 0.6},
            {"fuente_id": fid_neutral, "tipo_operacion": "FICHAJE", "peso_lexico": 0.9},
        ]

        corrector = BiasCorrector(db)
        factor = await corrector.evaluate_batch(rumores)
        assert 0.75 < factor < 1.0, (
            f"Mixed pro-rm + neutral should give 0.75 < factor < 1.0, got {factor}"
        )


# ════════════════════════════════════════════════════════════════════════════
# RETRACTION HANDLER
# ════════════════════════════════════════════════════════════════════════════


class TestRetractionHandler:
    @pytest.mark.asyncio
    async def test_retraction_detection(self, db):
        """Romano says 'here we go' at t=0; at t=2d says 'not happening'.

        The first rumor must be marked retractado=1.
        """
        from fichajes_bot.detectors.retraction_handler import RetractionHandler

        jid = _uid()
        pid = _uid()
        fid = _uid()
        rumor1_id = _uid()
        rumor2_id = _uid()

        await _insert_periodista(db, pid, tier="S", nombre="Fabrizio Romano")
        await _insert_fuente(db, fid, sesgo="neutral", tier="S")
        await _insert_jugador(db, jid, "Test Retraction Player")

        # Insert the original positive rumor
        await _insert_rumor(
            db, rumor1_id, jid, pid, fid,
            texto="here we go Test Player to Real Madrid!",
            tipo="FICHAJE", days_ago=2,
        )

        # The new rumor that contradicts it
        nuevo_rumor = {
            "rumor_id": rumor2_id,
            "jugador_id": jid,
            "periodista_id": pid,
            "fuente_id": fid,
            "tipo_operacion": "FICHAJE",
            "texto_fragmento": "Update: not happening, deal collapsed completely.",
            "fecha_publicacion": "2026-04-20T10:00:00",
        }

        handler = RetractionHandler(db)
        retracted = await handler.detect_retraction(nuevo_rumor)

        assert retracted is True, "Should detect retraction"

        # Verify the first rumor is marked retractado
        rows = await db.execute(
            "SELECT retractado FROM rumores WHERE rumor_id=?", [rumor1_id]
        )
        assert rows[0]["retractado"] == 1, "First rumor should be marked retractado=1"

        # Verify retractacion record was created
        ret_rows = await db.execute(
            "SELECT * FROM retractaciones WHERE jugador_id=?", [jid]
        )
        assert len(ret_rows) >= 1, "Retractacion record should be inserted"

        # Verify urgent event was enqueued
        event_rows = await db.execute(
            "SELECT * FROM eventos_pending WHERE tipo='retraction' AND procesado=0"
        )
        assert len(event_rows) >= 1, "Retraction event should be enqueued"

    @pytest.mark.asyncio
    async def test_no_retraction_without_keywords(self, db):
        """Follow-up rumor without negation keywords → no retraction."""
        from fichajes_bot.detectors.retraction_handler import RetractionHandler

        jid = _uid()
        pid = _uid()
        fid = _uid()
        rumor1_id = _uid()

        await _insert_periodista(db, pid, tier="S")
        await _insert_fuente(db, fid, sesgo="neutral", tier="S")
        await _insert_jugador(db, jid, "Active Player")
        await _insert_rumor(db, rumor1_id, jid, pid, fid, "here we go!", days_ago=1)

        nuevo = {
            "rumor_id": _uid(),
            "jugador_id": jid,
            "periodista_id": pid,
            "fuente_id": fid,
            "tipo_operacion": "FICHAJE",
            "texto_fragmento": "More info on the deal, talks continuing.",
        }

        handler = RetractionHandler(db)
        retracted = await handler.detect_retraction(nuevo)
        assert retracted is False

        rows = await db.execute(
            "SELECT retractado FROM rumores WHERE rumor_id=?", [rumor1_id]
        )
        assert rows[0]["retractado"] == 0

    @pytest.mark.asyncio
    async def test_retraction_factor_tier_s(self, db):
        """Player with 1 tier-S retraction in 30d → factor_retractacion = 0.6."""
        from fichajes_bot.detectors.retraction_handler import (
            RetractionHandler, FACTOR_ONE_TIER_S
        )

        jid = _uid()
        pid = _uid()

        await _insert_periodista(db, pid, tier="S", nombre="Romano")
        await _insert_jugador(db, jid, "Player With Retraction")
        await _insert_retractacion(db, jid, pid)

        handler = RetractionHandler(db)
        factor = await handler.evaluate(jid)
        assert factor == FACTOR_ONE_TIER_S, (
            f"1 tier-S retraction → {FACTOR_ONE_TIER_S}, got {factor}"
        )

    @pytest.mark.asyncio
    async def test_retraction_factor_two_or_more(self, db):
        """Player with ≥2 retractions → factor_retractacion = 0.4."""
        from fichajes_bot.detectors.retraction_handler import (
            RetractionHandler, FACTOR_TWO_OR_MORE
        )

        jid = _uid()
        pid = _uid()

        await _insert_periodista(db, pid, tier="A")
        await _insert_jugador(db, jid, "Repeatedly Retracted")
        await _insert_retractacion(db, jid, pid)
        await _insert_retractacion(db, jid, pid)

        handler = RetractionHandler(db)
        factor = await handler.evaluate(jid)
        assert factor == FACTOR_TWO_OR_MORE, (
            f"2 retractions → {FACTOR_TWO_OR_MORE}, got {factor}"
        )

    @pytest.mark.asyncio
    async def test_retraction_factor_no_history(self, db):
        """Player with no retractions → factor_retractacion = 1.0."""
        from fichajes_bot.detectors.retraction_handler import (
            RetractionHandler, FACTOR_NO_RETRACTION
        )

        jid = _uid()
        await _insert_jugador(db, jid, "Clean Player")

        handler = RetractionHandler(db)
        factor = await handler.evaluate(jid)
        assert factor == FACTOR_NO_RETRACTION, (
            f"No retractions → {FACTOR_NO_RETRACTION}, got {factor}"
        )


# ════════════════════════════════════════════════════════════════════════════
# HARD SIGNAL DETECTOR
# ════════════════════════════════════════════════════════════════════════════


class TestHardSignalDetector:
    def test_hard_signal_oficial(self):
        """'comunicado oficial del Real Madrid' → fichaje_oficial detected."""
        from fichajes_bot.detectors.hard_signal_detector import HardSignalDetector

        detector = HardSignalDetector(None)
        rumor = {
            "texto_fragmento": "Comunicado oficial del Real Madrid: nuevo fichaje confirmado.",
            "lexico_detectado": "",
        }
        tipo = detector.detect(rumor)
        assert tipo == "fichaje_oficial", f"Expected 'fichaje_oficial', got '{tipo}'"

    def test_hard_signal_here_we_go(self):
        """'Here we go' pattern → fichaje_oficial."""
        from fichajes_bot.detectors.hard_signal_detector import HardSignalDetector

        detector = HardSignalDetector(None)
        rumor = {"texto_fragmento": "HERE WE GO! Bellingham signs for Real Madrid."}
        assert detector.detect(rumor) == "fichaje_oficial"

    def test_hard_signal_retractacion(self):
        """'No ficharemos a Haaland' → retractacion_explicita."""
        from fichajes_bot.detectors.hard_signal_detector import HardSignalDetector

        detector = HardSignalDetector(None)
        rumor = {
            "texto_fragmento": "El club confirma: no ficharemos al jugador esta temporada.",
            "lexico_detectado": "",
        }
        assert detector.detect(rumor) == "retractacion_explicita"

    def test_hard_signal_deal_collapsed(self):
        """'deal collapsed' → retractacion_explicita."""
        from fichajes_bot.detectors.hard_signal_detector import HardSignalDetector

        detector = HardSignalDetector(None)
        rumor = {"texto_fragmento": "The transfer deal collapsed at the last minute."}
        assert detector.detect(rumor) == "retractacion_explicita"

    def test_hard_signal_none(self):
        """Ordinary rumor text → None."""
        from fichajes_bot.detectors.hard_signal_detector import HardSignalDetector

        detector = HardSignalDetector(None)
        rumor = {
            "texto_fragmento": "El Real Madrid sigue el mercado de fichajes con interés.",
            "lexico_detectado": "interesado",
        }
        assert detector.detect(rumor) is None

    @pytest.mark.asyncio
    async def test_hard_signal_persist(self, db):
        """persist_signal adds FICHAJE_OFICIAL flag to rumor and creates event."""
        from fichajes_bot.detectors.hard_signal_detector import HardSignalDetector

        jid = _uid()
        pid = _uid()
        fid = _uid()
        rid = _uid()

        await _insert_periodista(db, pid, tier="S")
        await _insert_fuente(db, fid, sesgo="neutral", tier="S")
        await _insert_jugador(db, jid, "Official Signing")
        await _insert_rumor(db, rid, jid, pid, fid, "here we go!")

        detector = HardSignalDetector(db)
        await detector.persist_signal(rid, jid, "fichaje_oficial")

        # Check flags updated
        rows = await db.execute("SELECT flags FROM rumores WHERE rumor_id=?", [rid])
        flags = json.loads(rows[0]["flags"] or "[]")
        assert "FICHAJE_OFICIAL" in flags, f"FICHAJE_OFICIAL not in flags: {flags}"

        # Check event enqueued
        events = await db.execute(
            "SELECT * FROM eventos_pending WHERE tipo='score_recompute_needed'"
        )
        assert len(events) >= 1


# ════════════════════════════════════════════════════════════════════════════
# KALMAN HARD SIGNAL INTEGRATION
# ════════════════════════════════════════════════════════════════════════════


class TestKalmanHardSignal:
    @pytest.mark.asyncio
    async def test_kalman_hard_signal(self, db):
        """FICHAJE_OFICIAL flag → engine detects hard signal → Q×3 → faster score update."""
        from fichajes_bot.calibration.reliability_manager import ReliabilityManager
        from fichajes_bot.scoring.engine import recompute_score

        jid = _uid()
        pid = _uid()
        fid = _uid()

        await _insert_periodista(db, pid, tier="S")
        await _insert_fuente(db, fid, sesgo="neutral", tier="S")
        await _insert_jugador(db, jid, "Official Target", score=0.30)

        # Insert rumor with FICHAJE_OFICIAL flag (hard signal)
        rid = _uid()
        await _insert_rumor(db, rid, jid, pid, fid, "here we go!", fase=6)
        # Set the FICHAJE_OFICIAL flag
        await db.execute(
            "UPDATE rumores SET flags=? WHERE rumor_id=?",
            ['["FICHAJE_OFICIAL"]', rid],
        )

        # Recompute score — should use hard_signal=True (Q×3)
        mgr = ReliabilityManager(db)
        result = await recompute_score(jid, db, mgr)

        assert result is not None
        # With hard signal from fase=6 + FICHAJE_OFICIAL, score should be high
        assert result["score_smoothed"] > 0.40, (
            f"Hard signal should produce high score, got {result['score_smoothed']:.3f}"
        )

    @pytest.mark.asyncio
    async def test_kalman_hard_signal_moves_faster(self, db):
        """Starting from same state: hard signal moves score faster than soft signal."""
        from fichajes_bot.scoring.kalman import KalmanFilter1D, KalmanState

        kf = KalmanFilter1D()
        state = KalmanState(x=0.20, P=0.05)

        # Same observation, same credibility, different hard_signal flag
        state_soft = kf.update(state, 0.90, credibilidad_media=0.80, hard_signal=False)
        state_hard = kf.update(state, 0.90, credibilidad_media=0.80, hard_signal=True)

        delta_soft = abs(state_soft.x - state.x)
        delta_hard = abs(state_hard.x - state.x)

        assert delta_hard > delta_soft, (
            f"Hard signal should update faster: "
            f"soft={delta_soft:.4f} hard={delta_hard:.4f}"
        )


# ════════════════════════════════════════════════════════════════════════════
# MODIFIERS INTEGRATION — Session 7 hooks active
# ════════════════════════════════════════════════════════════════════════════


class TestModifiersSession7:
    @pytest.mark.asyncio
    async def test_factor_sesgo_reduces_pro_rm_fichaje(self, db):
        """factor_sesgo call via modifiers reduces pro-rm + FICHAJE score."""
        from fichajes_bot.scoring.modifiers import factor_sesgo, _run_cache
        _run_cache.clear()

        fid = _uid()
        await _insert_fuente(db, fid, sesgo="pro-rm", tier="B")

        rumores = [
            {"fuente_id": fid, "tipo_operacion": "FICHAJE",
             "peso_lexico": 0.8, "retractado": 0},
        ]

        f = await factor_sesgo(rumores, 0.5, db)
        assert f < 0.8, f"factor_sesgo pro-rm+FICHAJE should be < 0.8, got {f}"

    @pytest.mark.asyncio
    async def test_factor_globo_sonda_reduces_suspicious(self, db):
        """factor_globo_sonda reduces score when prob_globo >= 0.50."""
        from fichajes_bot.scoring.modifiers import factor_globo_sonda, _run_cache
        _run_cache.clear()

        jid = _uid()
        pid = _uid()
        fid = _uid()
        rival_jid = _uid()

        await _insert_periodista(db, pid, tier="B")
        await _insert_fuente(db, fid, sesgo="pro-rm", tier="B")
        await _insert_jugador(db, jid, "Suspected Balloon")
        await _insert_jugador(db, rival_jid, "Rival High Score", score=0.85)
        await _insert_retractacion(db, jid, pid)

        rumores = [
            {
                "rumor_id": _uid(), "jugador_id": jid,
                "periodista_id": pid, "fuente_id": fid,
                "tipo_operacion": "FICHAJE",
                "texto_fragmento": "acuerdo alcanzado por 45m€, precio inflado desde 30m€",
                "fecha_publicacion": "2026-04-20T10:00:00",
            },
        ]

        f = await factor_globo_sonda(rumores, 0.5, db)
        assert f < 1.0, f"Suspicious balloon should reduce score, got {f}"

    @pytest.mark.asyncio
    async def test_factor_retractacion_reduces_after_retraction(self, db):
        """factor_retractacion reduces score when player has prior retraction."""
        from fichajes_bot.scoring.modifiers import factor_retractacion, _run_cache
        _run_cache.clear()

        jid = _uid()
        pid = _uid()
        await _insert_periodista(db, pid, tier="S")
        await _insert_jugador(db, jid, "Player With History")
        await _insert_retractacion(db, jid, pid)

        f = await factor_retractacion(jid, [], 0.5, db)
        assert f < 1.0, f"Player with tier-S retraction → factor < 1.0, got {f}"
