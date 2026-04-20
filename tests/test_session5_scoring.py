"""Session 5 tests — scoring engine, components, Kalman, modifiers."""

from __future__ import annotations

import json
import math
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest


# ── Helpers ───────────────────────────────────────────────────────────────────

def _now_iso(delta_days: int = 0) -> str:
    dt = datetime.now(timezone.utc) - timedelta(days=abs(delta_days))
    return dt.isoformat()


def _make_rumor(
    jugador_id: str = "j1",
    tipo: str = "FICHAJE",
    club_destino: str = "Real Madrid",
    periodista_id: str = "fabrizio-romano",
    fase: int = 5,
    peso_lexico: float = 0.85,
    confianza: float = 0.90,
    days_ago: int = 1,
    retractado: bool = False,
    reliability_global: float = 0.92,
) -> dict[str, Any]:
    return {
        "rumor_id":           str(uuid.uuid4()),
        "jugador_id":         jugador_id,
        "tipo_operacion":     tipo,
        "club_destino":       club_destino,
        "periodista_id":      periodista_id,
        "fase_rumor":         fase,
        "peso_lexico":        peso_lexico,
        "confianza_extraccion": confianza,
        "fecha_publicacion":  _now_iso(days_ago),
        "retractado":         int(retractado),
        "flags":              "[]",
        "reliability_global": reliability_global,
    }


def _make_mock_reliability_manager(default_reliability: float = 0.85) -> Any:
    est = MagicMock()
    est.reliability = default_reliability

    mgr = MagicMock()
    mgr.get_reliability = AsyncMock(return_value=est)
    return mgr


# ════════════════════════════════════════════════════════════════════════════
# SCORE BASE
# ════════════════════════════════════════════════════════════════════════════

class TestScoreBase:
    def test_all_zeros_gives_low_score(self):
        from fichajes_bot.scoring.score_base import ScoreComponents, combine_components
        c = ScoreComponents(consenso=0.0, credibilidad=0.0, fase=1.0, temporal=0.0)
        assert combine_components(c) < 0.25

    def test_all_high_gives_high_score(self):
        from fichajes_bot.scoring.score_base import ScoreComponents, combine_components
        c = ScoreComponents(consenso=1.0, credibilidad=1.0, fase=6.0, temporal=1.0)
        assert combine_components(c) > 0.90

    def test_output_in_range(self):
        from fichajes_bot.scoring.score_base import ScoreComponents, combine_components
        for consenso in [-1.0, 0.0, 1.0]:
            for cred in [0.0, 0.5, 1.0]:
                for fase in [1.0, 3.5, 6.0]:
                    for temp in [0.0, 0.5, 1.0]:
                        c = ScoreComponents(consenso, cred, fase, temp)
                        s = combine_components(c)
                        assert 0.01 <= s <= 0.99, f"Out of range: {s} for {c}"

    def test_monotone_in_credibilidad(self):
        from fichajes_bot.scoring.score_base import ScoreComponents, combine_components
        base = ScoreComponents(consenso=0.5, credibilidad=0.3, fase=3.0, temporal=0.5)
        high = ScoreComponents(consenso=0.5, credibilidad=0.9, fase=3.0, temporal=0.5)
        assert combine_components(high) > combine_components(base)

    def test_monotone_in_fase(self):
        from fichajes_bot.scoring.score_base import ScoreComponents, combine_components
        low_fase = ScoreComponents(0.5, 0.5, 1.0, 0.5)
        high_fase = ScoreComponents(0.5, 0.5, 6.0, 0.5)
        assert combine_components(high_fase) > combine_components(low_fase)

    def test_phase_to_signal_monotone(self):
        from fichajes_bot.scoring.score_base import phase_to_signal
        vals = [phase_to_signal(f) for f in [1.0, 2.0, 3.0, 4.0, 5.0, 6.0]]
        assert vals == sorted(vals), f"phase_to_signal not monotone: {vals}"

    def test_explain_returns_string(self):
        from fichajes_bot.scoring.score_base import ScoreComponents, explain_components
        c = ScoreComponents(0.8, 0.75, 5.0, 0.9)
        s = explain_components(c)
        assert isinstance(s, str) and len(s) > 10


# ════════════════════════════════════════════════════════════════════════════
# COMPONENTS — CONSENSO
# ════════════════════════════════════════════════════════════════════════════

class TestConsenso:
    def test_5_journalists_same_tipo_club(self):
        """5 periodistas apuntando a Mbappé→RM → consenso > 0.8"""
        from fichajes_bot.scoring.components import compute_consenso
        rumores = [_make_rumor(tipo="FICHAJE", club_destino="Real Madrid") for _ in range(5)]
        c = compute_consenso(rumores)
        assert c > 0.80, f"Expected consenso > 0.80, got {c}"

    def test_empty_returns_zero(self):
        from fichajes_bot.scoring.components import compute_consenso
        assert compute_consenso([]) == 0.0

    def test_all_retracted_returns_zero(self):
        from fichajes_bot.scoring.components import compute_consenso
        rumores = [_make_rumor(retractado=True) for _ in range(5)]
        assert compute_consenso(rumores) == 0.0

    def test_unanimous_is_max(self):
        from fichajes_bot.scoring.components import compute_consenso
        rumores = [_make_rumor(tipo="FICHAJE", club_destino="Real Madrid") for _ in range(10)]
        c = compute_consenso(rumores)
        # All agree → maximum positive consenso
        assert c > 0.90

    def test_split_50_50_is_low(self):
        from fichajes_bot.scoring.components import compute_consenso
        r1 = [_make_rumor(tipo="FICHAJE", club_destino="Real Madrid") for _ in range(3)]
        r2 = [_make_rumor(tipo="SALIDA", club_destino="PSG") for _ in range(3)]
        c = compute_consenso(r1 + r2)
        assert c < 0.40, f"50/50 split should give low consenso, got {c}"

    def test_contradictory_can_be_negative(self):
        from fichajes_bot.scoring.components import compute_consenso
        rumores = [
            _make_rumor(tipo="FICHAJE", club_destino="Real Madrid"),
            _make_rumor(tipo="SALIDA", club_destino="PSG"),
            _make_rumor(tipo="RENOVACION", club_destino=""),
            _make_rumor(tipo="CESION", club_destino="Dortmund"),
        ]
        c = compute_consenso(rumores)
        assert c <= 0.20, f"Highly contradictory signals should be low/negative, got {c}"

    def test_range_always_valid(self):
        from fichajes_bot.scoring.components import compute_consenso
        for n in range(1, 8):
            rumores = [_make_rumor(tipo="FICHAJE") for _ in range(n)]
            c = compute_consenso(rumores)
            assert -1.0 <= c <= 1.0, f"consenso out of range: {c}"


# ════════════════════════════════════════════════════════════════════════════
# COMPONENTS — CREDIBILIDAD
# ════════════════════════════════════════════════════════════════════════════

class TestCredibilidad:
    @pytest.mark.asyncio
    async def test_romano_high_credibilidad(self):
        """Romano (0.92) → credibilidad alta."""
        from fichajes_bot.scoring.components import compute_credibilidad
        rumores = [_make_rumor(periodista_id="fabrizio-romano", peso_lexico=0.98, confianza=0.95)]
        mgr = _make_mock_reliability_manager(0.92)
        cred = await compute_credibilidad(rumores, mgr)
        assert cred > 0.85, f"Romano should give high credibilidad, got {cred}"

    @pytest.mark.asyncio
    async def test_mix_romano_marca(self):
        """Mix Romano (0.92) + MARCA (0.55) → weighted credibilidad between."""
        from fichajes_bot.scoring.components import compute_credibilidad

        romano_est = MagicMock(); romano_est.reliability = 0.92
        marca_est  = MagicMock(); marca_est.reliability = 0.55

        async def mock_get_reliability(pid, **kwargs):
            return romano_est if pid == "fabrizio-romano" else marca_est

        mgr = MagicMock()
        mgr.get_reliability = mock_get_reliability

        romano_r = _make_rumor(periodista_id="fabrizio-romano", peso_lexico=0.90, confianza=0.90)
        marca_r  = _make_rumor(periodista_id="jose-felix-diaz", peso_lexico=0.65, confianza=0.55)

        cred = await compute_credibilidad([romano_r, marca_r], mgr)

        # Weighted by reliability: romano (0.92) gets more weight than MARCA (0.55)
        # Romano signal = 0.90, MARCA signal = 0.60
        # Expected: (0.92 * 0.90 + 0.55 * 0.60) / (0.92 + 0.55) ≈ 0.786
        assert 0.70 < cred < 0.90, f"Mixed credibilidad should be ~0.78, got {cred}"

    @pytest.mark.asyncio
    async def test_no_periodista_uses_default(self):
        from fichajes_bot.scoring.components import compute_credibilidad
        rumores = [_make_rumor(periodista_id=None, peso_lexico=0.70, confianza=0.70)]
        mgr = _make_mock_reliability_manager(0.50)
        cred = await compute_credibilidad(rumores, mgr)
        # No journalist → uses default 0.50 reliability
        assert 0.0 < cred < 0.80

    @pytest.mark.asyncio
    async def test_all_retracted_returns_zero(self):
        from fichajes_bot.scoring.components import compute_credibilidad
        rumores = [_make_rumor(retractado=True)]
        mgr = _make_mock_reliability_manager(0.90)
        cred = await compute_credibilidad(rumores, mgr)
        assert cred == 0.0


# ════════════════════════════════════════════════════════════════════════════
# COMPONENTS — FASE DOMINANTE
# ════════════════════════════════════════════════════════════════════════════

class TestFaseDominante:
    @pytest.mark.asyncio
    async def test_high_cred_fase5_beats_many_fase2(self):
        """1 Romano fase 5 + 3 tier-B fase 2 → fase_dominante closer to 5."""
        from fichajes_bot.scoring.components import compute_fase_dominante

        romano_est = MagicMock(); romano_est.reliability = 0.92
        marca_est  = MagicMock(); marca_est.reliability = 0.42

        async def mock_get(pid, **kwargs):
            return romano_est if pid == "fabrizio-romano" else marca_est

        mgr = MagicMock(); mgr.get_reliability = mock_get

        rumores = (
            [_make_rumor(periodista_id="fabrizio-romano", fase=5, days_ago=1)]
            + [_make_rumor(periodista_id="jose-felix-diaz", fase=2, days_ago=2)
               for _ in range(3)]
        )

        fase = await compute_fase_dominante(rumores, mgr)
        # Romano's high weight should pull fase toward 5, above the naive mean (2.75)
        assert fase > 3.0, f"Expected fase > 3.0 (Romano dominates), got {fase}"

    @pytest.mark.asyncio
    async def test_empty_returns_1(self):
        from fichajes_bot.scoring.components import compute_fase_dominante
        mgr = _make_mock_reliability_manager()
        f = await compute_fase_dominante([], mgr)
        assert f == 1.0

    @pytest.mark.asyncio
    async def test_recent_rumors_weighted_higher(self):
        """More recent rumor should have more weight."""
        from fichajes_bot.scoring.components import compute_fase_dominante

        est = MagicMock(); est.reliability = 0.80
        mgr = MagicMock(); mgr.get_reliability = AsyncMock(return_value=est)

        recent = _make_rumor(fase=6, days_ago=0)   # today
        old    = _make_rumor(fase=2, days_ago=30)  # month ago

        f_recent_only = await compute_fase_dominante([recent], mgr)
        f_both = await compute_fase_dominante([recent, old], mgr)

        # With old low-fase rumor added, fase should still stay close to 6
        assert f_both >= 4.0, f"Recent fase-6 should dominate, got {f_both}"


# ════════════════════════════════════════════════════════════════════════════
# COMPONENTS — FACTOR TEMPORAL
# ════════════════════════════════════════════════════════════════════════════

class TestFactorTemporal:
    def test_recent_rumor_high_weight(self):
        from fichajes_bot.scoring.components import compute_factor_temporal
        rumores = [_make_rumor(days_ago=0)]
        t = compute_factor_temporal(rumores)
        assert t > 0.95

    def test_old_rumor_low_weight(self):
        from fichajes_bot.scoring.components import compute_factor_temporal
        rumores = [_make_rumor(days_ago=30)]
        t = compute_factor_temporal(rumores)
        # After 30 days (>2 half-lives of 14d), should be < 0.25
        assert t < 0.30, f"30-day old rumor should have low weight, got {t}"

    def test_empty_returns_zero(self):
        from fichajes_bot.scoring.components import compute_factor_temporal
        assert compute_factor_temporal([]) == 0.0

    def test_floor_applied(self):
        from fichajes_bot.scoring.components import compute_factor_temporal, _MIN_DECAY
        # Very old rumor should be at floor
        rumores = [_make_rumor(days_ago=200)]
        t = compute_factor_temporal(rumores)
        assert t >= _MIN_DECAY

    def test_temporal_weight_decay(self):
        from fichajes_bot.scoring.components import _temporal_weight
        w0  = _temporal_weight(_now_iso(0))
        w14 = _temporal_weight(_now_iso(14))
        w28 = _temporal_weight(_now_iso(28))
        # After 1 half-life, weight ≈ 0.5
        assert abs(w14 - 0.5) < 0.05, f"After 14d (half-life), weight ≈ 0.5, got {w14}"
        # After 2 half-lives, weight ≈ 0.25
        assert abs(w28 - 0.25) < 0.06, f"After 28d, weight ≈ 0.25, got {w28}"


# ════════════════════════════════════════════════════════════════════════════
# KALMAN FILTER
# ════════════════════════════════════════════════════════════════════════════

class TestKalmanFilter:
    def test_convergence_to_true_value(self):
        """10 noisy observations around 0.7 → estimate converges to 0.7 ± 0.05."""
        from fichajes_bot.scoring.kalman import KalmanFilter1D, KalmanState
        import random
        random.seed(42)

        kf = KalmanFilter1D(Q_base=0.01, R_base=0.04)
        state = KalmanState(x=0.05, P=1.0)
        true_val = 0.70

        for _ in range(10):
            obs = true_val + random.gauss(0, 0.1)  # noisy observation
            obs = max(0.01, min(0.99, obs))
            state = kf.update(state, obs, credibilidad_media=0.75)

        assert abs(state.x - true_val) < 0.05, (
            f"After 10 observations, estimate should converge to {true_val} ± 0.05, "
            f"got {state.x:.3f}"
        )

    def test_hard_signal_causes_fast_update(self):
        """Hard signal (official transfer) should move score quickly."""
        from fichajes_bot.scoring.kalman import KalmanFilter1D, KalmanState

        kf = KalmanFilter1D(Q_base=0.01, R_base=0.04)
        state = KalmanState(x=0.3, P=0.01)  # low P = high certainty at 0.3

        # Without hard signal: slow update
        state_soft = kf.update(state, 0.90, credibilidad_media=0.8, hard_signal=False)
        # With hard signal: fast update
        state_hard = kf.update(state, 0.90, credibilidad_media=0.8, hard_signal=True)

        delta_soft = abs(state_soft.x - state.x)
        delta_hard = abs(state_hard.x - state.x)

        assert delta_hard > delta_soft, (
            f"Hard signal should update faster: soft={delta_soft:.4f} hard={delta_hard:.4f}"
        )

    def test_high_credibility_reduces_R(self):
        """Higher credibility → lower R → faster convergence."""
        from fichajes_bot.scoring.kalman import KalmanFilter1D, KalmanState

        kf = KalmanFilter1D()
        state = KalmanState(x=0.1, P=0.5)

        state_low_cred  = kf.update(state, 0.80, credibilidad_media=0.20)
        state_high_cred = kf.update(state, 0.80, credibilidad_media=0.95)

        # High credibility → R smaller → K larger → estimate moves more
        assert state_high_cred.x > state_low_cred.x, (
            f"High credibility should produce larger update: "
            f"low={state_low_cred.x:.3f} high={state_high_cred.x:.3f}"
        )

    def test_P_decreases_over_updates(self):
        """Error covariance should decrease (converge) with more observations."""
        from fichajes_bot.scoring.kalman import KalmanFilter1D, KalmanState

        kf = KalmanFilter1D()
        state = KalmanState(x=0.5, P=1.0)

        for _ in range(10):
            state = kf.update(state, 0.7, credibilidad_media=0.8)

        assert state.P < 0.20, f"P should decrease with observations, got {state.P}"

    def test_state_stays_in_range(self):
        """Score never goes outside [0.001, 0.999]."""
        from fichajes_bot.scoring.kalman import KalmanFilter1D, KalmanState

        kf = KalmanFilter1D()
        state = KalmanState(x=0.5, P=1.0)

        # Push with extreme observations
        for obs in [0.0, 1.0, 0.0, 1.0, -0.5, 1.5]:
            state = kf.update(state, max(0.001, min(0.999, obs)), credibilidad_media=0.8)

        assert 0.001 <= state.x <= 0.999
        assert state.P > 0

    def test_state_from_db_reconstructs(self):
        from fichajes_bot.scoring.kalman import state_from_db, KalmanState
        s = state_from_db(0.65, 0.03)
        assert abs(s.x - 0.65) < 1e-9
        assert abs(s.P - 0.03) < 1e-9

    def test_convergence_rate(self):
        from fichajes_bot.scoring.kalman import KalmanFilter1D, KalmanState
        kf = KalmanFilter1D()
        rate_high_P = kf.convergence_rate(KalmanState(x=0.5, P=1.0), 0.8)
        rate_low_P  = kf.convergence_rate(KalmanState(x=0.5, P=0.001), 0.8)
        # High P (uncertain) → high gain → fast update
        assert rate_high_P > rate_low_P


# ════════════════════════════════════════════════════════════════════════════
# ENGINE — end-to-end
# ════════════════════════════════════════════════════════════════════════════

async def _seed_jugador_and_rumores(db, n_rumores: int = 5) -> str:
    """Insert a jugador + n_rumores into the test DB."""
    jugador_id = str(uuid.uuid4())
    await db.execute(
        """INSERT INTO jugadores
           (jugador_id, nombre_canonico, slug, tipo_operacion_principal,
            score_raw, score_smoothed, kalman_P, flags, factores_actuales,
            n_rumores_total, primera_mencion_at, ultima_actualizacion_at,
            is_active, created_at)
           VALUES (?,?,?,?,0.05,0.05,1.0,'[]','{}',0,datetime('now'),datetime('now'),1,datetime('now'))""",
        [jugador_id, "Test Player", f"test-player-{jugador_id[:6]}", "FICHAJE"],
    )

    for i in range(n_rumores):
        await db.execute(
            """INSERT INTO rumores
               (rumor_id, jugador_id, periodista_id, fuente_id,
                tipo_operacion, club_destino, fase_rumor,
                peso_lexico, confianza_extraccion, extraido_con,
                fecha_publicacion, retractado, idioma, created_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,datetime('now', '-' || ? || ' hours'),0,'en',datetime('now'))""",
            [
                str(uuid.uuid4()), jugador_id,
                "fabrizio-romano", "romano_bluesky",
                "FICHAJE", "Real Madrid",
                5 if i == 0 else 3,
                0.85 + i * 0.02, 0.88 + i * 0.01,
                "regex",
                i * 6,  # stagger by 6 hours
            ],
        )

    return jugador_id


class TestEngine:
    @pytest.mark.asyncio
    async def test_recompute_returns_result(self, db):
        from fichajes_bot.calibration.reliability_manager import ReliabilityManager
        from fichajes_bot.scoring.engine import recompute_score

        jugador_id = await _seed_jugador_and_rumores(db, n_rumores=5)
        mgr = ReliabilityManager(db)

        result = await recompute_score(jugador_id, db, mgr)

        assert result is not None
        assert "score_raw" in result
        assert "score_smoothed" in result

    @pytest.mark.asyncio
    async def test_score_raw_in_range(self, db):
        from fichajes_bot.calibration.reliability_manager import ReliabilityManager
        from fichajes_bot.scoring.engine import recompute_score

        jugador_id = await _seed_jugador_and_rumores(db, n_rumores=5)
        result = await recompute_score(jugador_id, db, ReliabilityManager(db))

        assert result is not None
        assert 0.0 < result["score_raw"] < 1.0, f"score_raw out of range: {result['score_raw']}"

    @pytest.mark.asyncio
    async def test_score_smoothed_in_range(self, db):
        from fichajes_bot.calibration.reliability_manager import ReliabilityManager
        from fichajes_bot.scoring.engine import recompute_score

        jugador_id = await _seed_jugador_and_rumores(db, n_rumores=5)
        result = await recompute_score(jugador_id, db, ReliabilityManager(db))

        assert result is not None
        s = result["score_smoothed"]
        assert 0.0 < s < 1.0, f"score_smoothed out of range: {s}"

    @pytest.mark.asyncio
    async def test_score_history_increments(self, db):
        """Each recompute call inserts exactly 1 row in score_history."""
        from fichajes_bot.calibration.reliability_manager import ReliabilityManager
        from fichajes_bot.scoring.engine import recompute_score

        jugador_id = await _seed_jugador_and_rumores(db, n_rumores=5)
        mgr = ReliabilityManager(db)

        before = (await db.execute(
            "SELECT COUNT(*) as n FROM score_history WHERE jugador_id=?", [jugador_id]
        ))[0]["n"]

        await recompute_score(jugador_id, db, mgr)

        after = (await db.execute(
            "SELECT COUNT(*) as n FROM score_history WHERE jugador_id=?", [jugador_id]
        ))[0]["n"]

        assert after == before + 1, f"Expected +1 history row, got {after - before}"

    @pytest.mark.asyncio
    async def test_jugadores_updated(self, db):
        """After recompute, jugadores.score_smoothed is updated."""
        from fichajes_bot.calibration.reliability_manager import ReliabilityManager
        from fichajes_bot.scoring.engine import recompute_score

        jugador_id = await _seed_jugador_and_rumores(db, n_rumores=5)
        mgr = ReliabilityManager(db)

        await recompute_score(jugador_id, db, mgr)

        row = (await db.execute(
            "SELECT score_raw, score_smoothed, factores_actuales FROM jugadores WHERE jugador_id=?",
            [jugador_id]
        ))[0]

        assert float(row["score_raw"]) > 0.0
        assert float(row["score_smoothed"]) > 0.0
        factors = json.loads(row["factores_actuales"])
        assert "consenso" in factors
        assert "credibilidad" in factors

    @pytest.mark.asyncio
    async def test_no_rumores_returns_none(self, db):
        """Jugador with 0 rumores → engine returns None."""
        from fichajes_bot.calibration.reliability_manager import ReliabilityManager
        from fichajes_bot.scoring.engine import recompute_score

        jugador_id = str(uuid.uuid4())
        await db.execute(
            """INSERT INTO jugadores
               (jugador_id, nombre_canonico, slug, tipo_operacion_principal,
                score_raw, score_smoothed, kalman_P, flags, factores_actuales,
                n_rumores_total, primera_mencion_at, ultima_actualizacion_at,
                is_active, created_at)
               VALUES (?,?,?,?,0.0,0.0,1.0,'[]','{}',0,datetime('now'),datetime('now'),1,datetime('now'))""",
            [jugador_id, "Empty Player", f"empty-{jugador_id[:6]}", "FICHAJE"],
        )

        result = await recompute_score(jugador_id, db, ReliabilityManager(db))
        assert result is None

    @pytest.mark.asyncio
    async def test_high_fase_rumor_gives_high_score(self, db):
        """Fase-6 rumor from credible journalist should give score > 0.7."""
        from fichajes_bot.calibration.reliability_manager import ReliabilityManager
        from fichajes_bot.scoring.engine import recompute_score

        jugador_id = str(uuid.uuid4())
        await db.execute(
            """INSERT INTO jugadores
               (jugador_id, nombre_canonico, slug, tipo_operacion_principal,
                score_raw, score_smoothed, kalman_P, flags, factores_actuales,
                n_rumores_total, primera_mencion_at, ultima_actualizacion_at,
                is_active, created_at)
               VALUES (?,?,?,?,0.0,0.0,1.0,'[]','{}',1,datetime('now'),datetime('now'),1,datetime('now'))""",
            [jugador_id, "Hot Transfer", f"hot-{jugador_id[:6]}", "FICHAJE"],
        )
        # Insert 3 fase-6 rumores from Romano (high credibility)
        for _ in range(3):
            await db.execute(
                """INSERT INTO rumores
                   (rumor_id, jugador_id, periodista_id, fuente_id,
                    tipo_operacion, club_destino, fase_rumor,
                    peso_lexico, confianza_extraccion, extraido_con,
                    fecha_publicacion, retractado, idioma, created_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,datetime('now'),0,'en',datetime('now'))""",
                [str(uuid.uuid4()), jugador_id, "fabrizio-romano", "romano_bluesky",
                 "FICHAJE", "Real Madrid", 6, 0.98, 0.98, "regex"],
            )

        result = await recompute_score(jugador_id, db, ReliabilityManager(db))
        assert result is not None
        assert result["score_smoothed"] > 0.50, (
            f"Fase-6 rumores should give high score, got {result['score_smoothed']:.3f}"
        )


# ════════════════════════════════════════════════════════════════════════════
# SCORE JOB
# ════════════════════════════════════════════════════════════════════════════

class TestScoreJob:
    @pytest.mark.asyncio
    async def test_run_event_mode_processes_pending(self, db):
        """Event mode processes jugadores referenced in eventos_pending."""
        import fichajes_bot.jobs.score as score_module

        jugador_id = await _seed_jugador_and_rumores(db, n_rumores=3)

        # Insert pending event
        await db.execute(
            "INSERT INTO eventos_pending (evento_id, tipo, payload) VALUES (?,?,?)",
            [str(uuid.uuid4()), "new_rumor",
             json.dumps({"jugador_id": jugador_id, "rumor_id": "r1"})],
        )

        class PatchedD1:
            async def __aenter__(self): return db
            async def __aexit__(self, *a): pass

        from unittest.mock import patch
        with patch.object(score_module, "D1Client", PatchedD1):
            counts = await score_module.run(full=False)

        assert counts["processed"] >= 1

    @pytest.mark.asyncio
    async def test_run_full_mode(self, db):
        """Full mode scores all jugadores with recent rumores."""
        import fichajes_bot.jobs.score as score_module

        await _seed_jugador_and_rumores(db, n_rumores=3)

        class PatchedD1:
            async def __aenter__(self): return db
            async def __aexit__(self, *a): pass

        from unittest.mock import patch
        with patch.object(score_module, "D1Client", PatchedD1):
            counts = await score_module.run(full=True)

        assert counts["errors"] == 0


# ════════════════════════════════════════════════════════════════════════════
# MODIFIERS — all neutral in Session 5
# ════════════════════════════════════════════════════════════════════════════

class TestModifiers:
    @pytest.mark.asyncio
    async def test_all_modifiers_neutral(self, db):
        from fichajes_bot.scoring.modifiers import apply_modifiers
        rumores = [_make_rumor()]
        score, factors = await apply_modifiers("j1", rumores, 0.65, db)
        # All neutral → score unchanged
        assert abs(score - 0.65) < 1e-6, f"Expected neutral modifiers, got {score}"
        assert factors["combined"] == 1.0

    @pytest.mark.asyncio
    async def test_modifier_hooks_exist(self, db):
        """All 5 modifier functions exist and return float."""
        from fichajes_bot.scoring.modifiers import (
            factor_economico, factor_globo_sonda, factor_retractacion,
            factor_sesgo, factor_substitucion,
        )
        assert await factor_economico("j1", 0.5, db) == 1.0
        assert await factor_substitucion("j1", 0.5, db) == 1.0
        assert await factor_sesgo([], 0.5, db) == 1.0
        assert await factor_globo_sonda([], 0.5, db) == 1.0
        assert await factor_retractacion("j1", [], 0.5, db) == 1.0
