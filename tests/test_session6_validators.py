"""Session 6 tests — Economic, Substitution, Temporal validators + modifiers integration."""

from __future__ import annotations

import datetime
import uuid
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ── Helpers ───────────────────────────────────────────────────────────────────


def _uid() -> str:
    return str(uuid.uuid4())


async def _insert_modelo_economico(
    db,
    margen_m: float,
    presupuesto_m: float,
    tope_m: float = 780.0,
) -> None:
    # Deactivate any existing models (including the migration seed)
    await db.execute("UPDATE modelo_economico SET activo = 0")
    await db.execute(
        """INSERT INTO modelo_economico
           (econ_id, temporada, tope_laliga_rm, masa_salarial_actual,
            margen_salarial, presupuesto_fichajes_estimado,
            presupuesto_fichajes_restante, regla_actual, politica_edad_max,
            activo, fecha_actualizacion, fuente, confianza)
           VALUES (?,?,?,?,?,?,?,?,?,1,datetime('now'),?,?)""",
        [
            _uid(), "2025-26",
            round(tope_m * 1_000_000),
            round((tope_m - margen_m) * 1_000_000),
            round(margen_m * 1_000_000),
            round(presupuesto_m * 1_000_000),
            round(presupuesto_m * 1_000_000),
            "1_to_1", 30,
            "test", 0.90,
        ],
    )


async def _insert_jugador(
    db,
    jugador_id: str,
    nombre: str,
    posicion: str,
    tipo: str = "FICHAJE",
    score: float = 0.50,
    fase: int = 3,
    valor_mercado_m: float = 50.0,
    flags: str = "[]",
) -> None:
    await db.execute(
        """INSERT INTO jugadores
           (jugador_id, nombre_canonico, slug,
            posicion, tipo_operacion_principal,
            score_raw, score_smoothed, kalman_P,
            flags, factores_actuales, fase_dominante,
            valor_mercado_m,
            n_rumores_total, primera_mencion_at, ultima_actualizacion_at,
            is_active, created_at)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,0,datetime('now'),datetime('now'),1,datetime('now'))""",
        [
            jugador_id, nombre, nombre.lower().replace(" ", "-"),
            posicion, tipo,
            score, score, 1.0,
            flags, "{}", fase,
            valor_mercado_m,
        ],
    )


# ════════════════════════════════════════════════════════════════════════════
# ECONOMIC VALIDATOR
# ════════════════════════════════════════════════════════════════════════════


class TestEconomicValidator:
    @pytest.mark.asyncio
    async def test_economic_fits(self, db):
        """Mbappé scenario: salary 60M, margen 120M, budget 80M, transfer 60M → factor > 1.0."""
        from fichajes_bot.validators.economic import EconomicValidator

        # margen_salarial=120M > 1.5×salary(60M); presupuesto=80M > traspaso(60M)
        await _insert_modelo_economico(db, margen_m=120.0, presupuesto_m=80.0)

        validator = EconomicValidator(db)
        factor = await validator.evaluate(
            jugador_id=_uid(),
            salario_estimado_m=60.0,
            traspaso_estimado_m=60.0,
        )
        assert factor > 1.0, (
            f"margen=120M vs salary=60M (ratio=2.0>=1.5), budget=80M vs traspaso=60M "
            f"→ should be COMFORTABLE (>1.0), got {factor}"
        )

    @pytest.mark.asyncio
    async def test_economic_impossible(self, db):
        """Haaland-like scenario: salary 120M, margen 30M → deficit > 50M → factor < 0.5."""
        from fichajes_bot.validators.economic import EconomicValidator

        await _insert_modelo_economico(db, margen_m=30.0, presupuesto_m=20.0)

        validator = EconomicValidator(db)
        factor = await validator.evaluate(
            jugador_id=_uid(),
            salario_estimado_m=120.0,
            traspaso_estimado_m=250.0,
        )
        assert factor < 0.5, f"Should be impossible (deficit 90M > 50M), got {factor}"

    @pytest.mark.asyncio
    async def test_economic_needs_sale(self, db):
        """Moderate scenario: salary fits with some room but not comfortable."""
        from fichajes_bot.validators.economic import EconomicValidator

        await _insert_modelo_economico(db, margen_m=40.0, presupuesto_m=60.0)

        validator = EconomicValidator(db)
        factor = await validator.evaluate(
            jugador_id=_uid(),
            salario_estimado_m=35.0,
            traspaso_estimado_m=100.0,
        )
        # salary_ratio = 40/35 ≈ 1.14 < 1.5 → not comfortable
        # deficit = max(0, 35-40) = 0 < 50 → not impossible
        # transfer_ratio = 60/100 = 0.6 >= 0.5 → NEEDS_SALE
        assert 0.5 <= factor <= 1.0, f"Expected NEEDS_SALE factor, got {factor}"

    @pytest.mark.asyncio
    async def test_economic_no_modelo_returns_neutral(self, db):
        """Without an active modelo_economico → returns 1.0 (neutral)."""
        from fichajes_bot.validators.economic import EconomicValidator

        # Deactivate the migration seed so no active model exists
        await db.execute("UPDATE modelo_economico SET activo = 0")

        validator = EconomicValidator(db)
        factor = await validator.evaluate(_uid())
        assert factor == 1.0

    @pytest.mark.asyncio
    async def test_economic_caches_modelo(self, db):
        """Second call reuses cached modelo without extra DB query."""
        from fichajes_bot.validators.economic import EconomicValidator

        await _insert_modelo_economico(db, margen_m=80.0, presupuesto_m=60.0)

        validator = EconomicValidator(db)
        # First call
        f1 = await validator.evaluate(_uid(), salario_estimado_m=30.0, traspaso_estimado_m=80.0)
        assert validator._modelo is not None

        # Second call should reuse cache (no second DB fetch)
        f2 = await validator.evaluate(_uid(), salario_estimado_m=30.0, traspaso_estimado_m=80.0)
        assert f1 == f2


# ════════════════════════════════════════════════════════════════════════════
# SUBSTITUTION ENGINE
# ════════════════════════════════════════════════════════════════════════════


class TestSubstitutionEngine:
    @pytest.mark.asyncio
    async def test_substitution_salida_inminente(self, db):
        """Militao SALIDA score=0.75 + Huijsen FICHAJE CB → Huijsen factor > 1.2."""
        from fichajes_bot.validators.substitution import SubstitutionEngine

        militao_id = _uid()
        huijsen_id = _uid()

        await _insert_jugador(db, militao_id, "Test Salida CB", "CB",
                               tipo="SALIDA", score=0.75)
        await _insert_jugador(db, huijsen_id, "Test Fichaje CB", "CB",
                               tipo="FICHAJE", score=0.45)

        engine = SubstitutionEngine(db)
        factor = await engine.evaluate(huijsen_id)

        assert factor > 1.2, (
            f"Test Fichaje CB should benefit from Test Salida CB's imminent departure, got factor={factor}"
        )

    @pytest.mark.asyncio
    async def test_substitution_posicion_saturada(self, db):
        """CB position with 5 competing fichajes → target factor < 0.7."""
        from fichajes_bot.validators.substitution import SubstitutionEngine

        target_id = _uid()
        await _insert_jugador(db, target_id, "Target CB", "CB",
                               tipo="FICHAJE", score=0.30)

        # 5 rival CB candidates (>= MAX_CANDIDATES_SATURADA = 4)
        for i in range(5):
            await _insert_jugador(db, _uid(), f"Rival CB {i}", "CB",
                                   tipo="FICHAJE", score=0.40 + i * 0.05)

        engine = SubstitutionEngine(db)
        factor = await engine.evaluate(target_id)

        assert factor < 0.7, (
            f"Saturated CB position should reduce factor, got {factor}"
        )

    @pytest.mark.asyncio
    async def test_substitution_fichaje_avanzado(self, db):
        """Advanced rival (fase=5, higher score) at same position → factor = 0.4."""
        from fichajes_bot.validators.substitution import SubstitutionEngine

        target_id = _uid()
        rival_id  = _uid()

        await _insert_jugador(db, target_id, "Late Candidate", "MC",
                               tipo="FICHAJE", score=0.35, fase=2)
        await _insert_jugador(db, rival_id, "Advanced Rival", "MC",
                               tipo="FICHAJE", score=0.70, fase=5)

        engine = SubstitutionEngine(db)
        factor = await engine.evaluate(target_id)

        assert factor <= 0.4, (
            f"Advanced rival at MC should give FICHAJE_AVANZADO factor, got {factor}"
        )

    @pytest.mark.asyncio
    async def test_substitution_hueco_natural(self, db):
        """No rivals, no departures → factor = 1.0 (neutral)."""
        from fichajes_bot.validators.substitution import SubstitutionEngine

        target_id = _uid()
        await _insert_jugador(db, target_id, "Lone Candidate", "LW",
                               tipo="FICHAJE", score=0.50)

        engine = SubstitutionEngine(db)
        factor = await engine.evaluate(target_id)

        assert factor == 1.0, f"No rivals → HUECO_NATURAL = 1.0, got {factor}"

    @pytest.mark.asyncio
    async def test_substitution_propagate_signing(self, db):
        """2 ST rumored → 1 signs → the other's score drops > 30%."""
        from fichajes_bot.validators.substitution import SubstitutionEngine

        signed_id    = _uid()
        alternate_id = _uid()

        await _insert_jugador(db, signed_id,    "Signed ST",    "ST",
                               tipo="FICHAJE", score=0.70)
        await _insert_jugador(db, alternate_id, "Alternate ST", "ST",
                               tipo="FICHAJE", score=0.50)

        engine = SubstitutionEngine(db)

        # Record score before propagation
        before = (await db.execute(
            "SELECT score_smoothed FROM jugadores WHERE jugador_id=?", [alternate_id]
        ))[0]["score_smoothed"]

        await engine.propagate_on_signing(signed_id)

        after = (await db.execute(
            "SELECT score_smoothed FROM jugadores WHERE jugador_id=?", [alternate_id]
        ))[0]["score_smoothed"]

        drop_pct = (before - after) / before * 100
        assert drop_pct > 30, (
            f"Alternate ST should drop > 30% after rival signed. "
            f"before={before:.3f} after={after:.3f} drop={drop_pct:.1f}%"
        )

    @pytest.mark.asyncio
    async def test_substitution_propagate_sale(self, db):
        """Player leaves → FICHAJE candidates at same position are boosted."""
        from fichajes_bot.validators.substitution import SubstitutionEngine

        sold_id      = _uid()
        candidate_id = _uid()

        await _insert_jugador(db, sold_id,      "Outgoing CB", "CB",
                               tipo="SALIDA", score=0.75)
        await _insert_jugador(db, candidate_id, "Incoming CB", "CB",
                               tipo="FICHAJE", score=0.40)

        engine = SubstitutionEngine(db)

        before = (await db.execute(
            "SELECT score_smoothed FROM jugadores WHERE jugador_id=?", [candidate_id]
        ))[0]["score_smoothed"]

        await engine.propagate_on_sale(sold_id)

        after = (await db.execute(
            "SELECT score_smoothed FROM jugadores WHERE jugador_id=?", [candidate_id]
        ))[0]["score_smoothed"]

        assert after > before, (
            f"Candidate score should increase after sale. before={before:.3f} after={after:.3f}"
        )


# ════════════════════════════════════════════════════════════════════════════
# TEMPORAL VALIDATOR
# ════════════════════════════════════════════════════════════════════════════


class TestTemporalValidator:
    def test_temporal_ventana_verano(self, monkeypatch):
        """August → verano window → factor >= 1.3."""
        from fichajes_bot.validators.temporal import TemporalValidator

        validator = TemporalValidator(None)
        monkeypatch.setattr(validator, "_current_date",
                            lambda: datetime.date(2026, 8, 15))

        factor = validator.evaluate({}, {})
        assert factor >= 1.30, f"August should be in verano window, got {factor}"

    def test_temporal_fuera_ventana_penalizado(self, monkeypatch):
        """April (outside window), no 'next season' text → factor < 1.0."""
        from fichajes_bot.validators.temporal import TemporalValidator

        validator = TemporalValidator(None)
        monkeypatch.setattr(validator, "_current_date",
                            lambda: datetime.date(2026, 4, 20))

        factor = validator.evaluate({}, {})
        assert factor < 1.0, f"April outside window should penalise, got {factor}"

    def test_temporal_fuera_ventana_proxima_temporada(self, monkeypatch):
        """April but rumor says 'next season' → neutral factor."""
        from fichajes_bot.validators.temporal import TemporalValidator

        validator = TemporalValidator(None)
        monkeypatch.setattr(validator, "_current_date",
                            lambda: datetime.date(2026, 4, 20))

        rumor = {"texto_fragmento": "Interés para la próxima temporada."}
        factor = validator.evaluate(rumor, {})
        assert factor == 1.0, f"Next-season rumor outside window → neutral 1.0, got {factor}"

    def test_temporal_ventana_enero(self, monkeypatch):
        """January → enero window → factor >= 1.2."""
        from fichajes_bot.validators.temporal import TemporalValidator

        validator = TemporalValidator(None)
        monkeypatch.setattr(validator, "_current_date",
                            lambda: datetime.date(2026, 1, 15))

        factor = validator.evaluate({}, {})
        assert factor >= 1.20, f"January should be in enero window, got {factor}"

    def test_temporal_cierre_mercado(self, monkeypatch):
        """Last 7 days of verano window → cierre boost → factor = 1.5."""
        from fichajes_bot.validators.temporal import TemporalValidator, FACTOR_CIERRE

        validator = TemporalValidator(None)
        # August 26 → 6 days before September 1 (within _DIAS_CIERRE_BOOST=7)
        monkeypatch.setattr(validator, "_current_date",
                            lambda: datetime.date(2026, 8, 26))

        factor = validator.evaluate({}, {})
        assert factor == FACTOR_CIERRE, (
            f"Final week of verano should give FACTOR_CIERRE={FACTOR_CIERRE}, got {factor}"
        )

    def test_temporal_fin_contrato_boost(self, monkeypatch):
        """FIN_CONTRATO_PROX flag applies extra boost (tested outside window to avoid cap)."""
        from fichajes_bot.validators.temporal import TemporalValidator

        validator = TemporalValidator(None)
        # Use outside-window date so base factor is 0.70 (has room to grow)
        monkeypatch.setattr(validator, "_current_date",
                            lambda: datetime.date(2026, 4, 20))

        factor_base     = validator.evaluate({}, {})
        factor_contrato = validator.evaluate({}, {"flags": '["FIN_CONTRATO_PROX"]'})

        assert factor_contrato > factor_base, (
            f"FIN_CONTRATO_PROX should boost factor. base={factor_base} contrato={factor_contrato}"
        )
        # 0.70 * 1.20 = 0.84
        assert factor_contrato > 0.80

    def test_temporal_factor_always_in_range(self, monkeypatch):
        """Factor always stays within [0.5, 1.5] regardless of stacked boosts."""
        from fichajes_bot.validators.temporal import TemporalValidator, FACTOR_MIN, FACTOR_MAX

        validator = TemporalValidator(None)
        monkeypatch.setattr(validator, "_current_date",
                            lambda: datetime.date(2026, 8, 26))

        jugador_with_contract = {"flags": '["FIN_CONTRATO_PROX"]'}
        factor = validator.evaluate({}, jugador_with_contract)
        assert FACTOR_MIN <= factor <= FACTOR_MAX, (
            f"Factor out of [{FACTOR_MIN}, {FACTOR_MAX}]: {factor}"
        )


# ════════════════════════════════════════════════════════════════════════════
# MODIFIERS INTEGRATION
# ════════════════════════════════════════════════════════════════════════════


class TestModifiersIntegration:
    @pytest.mark.asyncio
    async def test_modifiers_integration_summer(self, db, monkeypatch):
        """Player with all 3 validators active (August, fits budget) → score boosted."""
        from fichajes_bot.scoring.modifiers import apply_modifiers, _run_cache
        from fichajes_bot.validators.temporal import TemporalValidator

        # Clear module-level cache to ensure fresh validators for this test
        _run_cache.clear()

        # Seed economic model with room for the player
        await _insert_modelo_economico(db, margen_m=100.0, presupuesto_m=80.0)

        # Seed jugador (no rivals → HUECO_NATURAL)
        jugador_id = _uid()
        await _insert_jugador(db, jugador_id, "Test Target LW", "LW",
                               tipo="FICHAJE", score=0.60, valor_mercado_m=60.0)

        # Patch date to August (verano window → boost)
        monkeypatch.setattr(
            "fichajes_bot.validators.temporal.TemporalValidator._current_date",
            lambda self: datetime.date(2026, 8, 10),
        )

        rumores = [{
            "rumor_id": _uid(),
            "jugador_id": jugador_id,
            "tipo_operacion": "FICHAJE",
            "peso_lexico": 0.85,
            "confianza_extraccion": 0.90,
            "texto_fragmento": "acuerdo total",
            "flags": "[]",
        }]

        score_raw = 0.60
        score_modified, factors = await apply_modifiers(jugador_id, rumores, score_raw, db)

        # Economic: margen(100M) > 1.5*salary(60*0.04=2.4M) → COMFORTABLE → 1.2
        # Substitution: no rivals → HUECO_NATURAL → 1.0
        # Temporal: August → 1.4
        # Combined ≈ 1.2 * 1.0 * 1.4 = 1.68 → score capped at 0.99
        assert score_modified > score_raw, (
            f"All positive modifiers should boost score. "
            f"raw={score_raw:.3f} modified={score_modified:.3f}"
        )
        assert score_modified <= 0.99
        assert factors["factor_econ"]  > 1.0
        assert factors["factor_subst"] == 1.0
        assert factors["factor_temporal_mod"] > 1.0

    @pytest.mark.asyncio
    async def test_modifiers_integration_winter_no_budget(self, db, monkeypatch):
        """April, no budget, saturated position → combined factor < 1.0."""
        from fichajes_bot.scoring.modifiers import apply_modifiers, _run_cache

        _run_cache.clear()

        # Tight economic model
        await _insert_modelo_economico(db, margen_m=20.0, presupuesto_m=15.0)

        jugador_id = _uid()
        await _insert_jugador(db, jugador_id, "Expensive Target", "CB",
                               tipo="FICHAJE", score=0.50, valor_mercado_m=150.0)

        # Saturate the position
        for i in range(5):
            await _insert_jugador(db, _uid(), f"Rival CB {i}", "CB",
                                   tipo="FICHAJE", score=0.40)

        monkeypatch.setattr(
            "fichajes_bot.validators.temporal.TemporalValidator._current_date",
            lambda self: datetime.date(2026, 4, 20),
        )

        rumores = [{"rumor_id": _uid(), "tipo_operacion": "FICHAJE",
                    "peso_lexico": 0.5, "texto_fragmento": "", "flags": "[]"}]

        score_raw = 0.50
        score_modified, factors = await apply_modifiers(jugador_id, rumores, score_raw, db)

        # Temporal: April outside window → 0.7
        # Substitution: 5 rivals → SATURADA → 0.6
        # Economic: 150M player, margen=20M → deficit=large → 0.3 or 0.7
        # Combined should be < 1.0 → score reduced
        assert score_modified < score_raw, (
            f"Negative conditions should reduce score. "
            f"raw={score_raw:.3f} modified={score_modified:.3f}"
        )

    @pytest.mark.asyncio
    async def test_modifiers_all_neutral_no_data(self, db, monkeypatch):
        """Unknown jugador, no active modelo_economico, in-window date → only temporal active."""
        from fichajes_bot.scoring.modifiers import apply_modifiers, _run_cache

        _run_cache.clear()

        # Deactivate migration seed so economic validator has no data
        await db.execute("UPDATE modelo_economico SET activo = 0")

        monkeypatch.setattr(
            "fichajes_bot.validators.temporal.TemporalValidator._current_date",
            lambda self: datetime.date(2026, 7, 15),
        )

        rumores = [{"rumor_id": _uid(), "tipo_operacion": "FICHAJE",
                    "peso_lexico": 0.5, "texto_fragmento": "", "flags": "[]"}]

        score, factors = await apply_modifiers("unknown-j1", rumores, 0.50, db)

        # Economic: no active modelo → 1.0
        # Substitution: no jugador in DB → 1.0
        # Temporal: July verano → 1.4
        assert factors["factor_econ"]  == 1.0
        assert factors["factor_subst"] == 1.0
        assert factors["factor_temporal_mod"] > 1.0
        assert score > 0.50, "July verano boost should increase score"
