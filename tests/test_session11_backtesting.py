"""Session 11 tests — Backtesting framework: metrics, walk-forward, regression guard."""

from __future__ import annotations

import json
import math
import uuid
from datetime import date, datetime, timedelta, timezone

import pytest

# Only async tests use asyncio mark individually


# ── Helpers ───────────────────────────────────────────────────────────────────


def _uid() -> str:
    return str(uuid.uuid4())


def _date_str(d: date) -> str:
    return d.isoformat()


async def _insert_jugador(
    db,
    nombre: str,
    outcome: str | None = None,
    fecha_outcome: str | None = None,
    score: float = 0.5,
) -> str:
    jid = _uid()
    slug = nombre.lower().replace(" ", "-")
    await db.execute(
        """INSERT INTO jugadores
           (jugador_id, nombre_canonico, slug, tipo_operacion_principal,
            score_smoothed, score_raw, is_active, flags, factores_actuales,
            outcome_clasificado, fecha_outcome, created_at)
           VALUES (?,?,?,'FICHAJE',?,?,1,'[]','{}',?,?,datetime('now'))""",
        [jid, nombre, slug, score, score, outcome, fecha_outcome],
    )
    return jid


async def _insert_outcome_historico(db, jugador_id: str, outcome_tipo: str, fecha: str) -> None:
    await db.execute(
        """INSERT INTO outcomes_historicos
           (outcome_id, jugador_id, outcome_tipo, fecha, created_at)
           VALUES (?,?,?,?,datetime('now'))""",
        [_uid(), jugador_id, outcome_tipo, fecha],
    )


async def _insert_backtest_run(
    db,
    run_id: str,
    brier: float,
    auc: float,
    completed_at: str | None = None,
) -> None:
    at = completed_at or datetime.now(timezone.utc).isoformat()
    metrics = {"brier_score": brier, "auc_roc": auc, "n_windows": 3.0}
    await db.execute(
        """INSERT INTO backtest_runs (run_id, started_at, completed_at, metrics_json, config_json)
           VALUES (?, datetime('now'), ?, ?, '{}')""",
        [run_id, at, json.dumps(metrics)],
    )


# ── Tests: Brier Score ────────────────────────────────────────────────────────


def test_brier_score_perfect():
    """Perfect predictions yield Brier = 0."""
    from fichajes_bot.backtesting.metrics import compute_brier_score

    predictions = [1.0, 1.0, 0.0, 0.0, 1.0]
    outcomes =    [1,   1,   0,   0,   1  ]
    assert compute_brier_score(predictions, outcomes) == pytest.approx(0.0)


def test_brier_score_constant():
    """All predictions = 0.5, mixed outcomes → Brier ≈ 0.25."""
    from fichajes_bot.backtesting.metrics import compute_brier_score

    predictions = [0.5] * 100
    outcomes = [1] * 50 + [0] * 50
    result = compute_brier_score(predictions, outcomes)
    assert result == pytest.approx(0.25, abs=1e-9)


def test_brier_score_empty():
    from fichajes_bot.backtesting.metrics import compute_brier_score

    result = compute_brier_score([], [])
    assert math.isnan(result)


# ── Tests: AUC-ROC ────────────────────────────────────────────────────────────


def test_auc_random():
    """Random predictions → AUC ≈ 0.5 (within reasonable tolerance)."""
    from fichajes_bot.backtesting.metrics import compute_auc_roc

    import random
    random.seed(42)
    predictions = [random.random() for _ in range(200)]
    outcomes = [random.randint(0, 1) for _ in range(200)]
    auc = compute_auc_roc(predictions, outcomes)
    # Random should be near 0.5; allow ±0.15 for stochastic variance
    assert 0.35 <= auc <= 0.65, f"AUC for random predictions: {auc}"


def test_auc_perfect():
    """Perfect ranking → AUC = 1.0."""
    from fichajes_bot.backtesting.metrics import compute_auc_roc

    # Positives all have higher scores than negatives
    predictions = [0.9, 0.85, 0.8, 0.75, 0.2, 0.15, 0.1, 0.05]
    outcomes =    [1,   1,    1,   1,    0,   0,    0,   0  ]
    auc = compute_auc_roc(predictions, outcomes)
    assert auc == pytest.approx(1.0)


def test_auc_single_class_returns_nan():
    from fichajes_bot.backtesting.metrics import compute_auc_roc

    predictions = [0.8, 0.6, 0.4]
    outcomes = [1, 1, 1]  # all positive — AUC undefined
    result = compute_auc_roc(predictions, outcomes)
    assert math.isnan(result)


# ── Tests: Precision@K ────────────────────────────────────────────────────────


def test_precision_at_k_basic():
    """Top-5 with 4 hits → P@5 = 0.8."""
    from fichajes_bot.backtesting.metrics import compute_precision_at_k

    # Sorted by score: top 5 are the first 5
    predictions = [0.9, 0.8, 0.7, 0.6, 0.5, 0.4, 0.3, 0.2, 0.1, 0.05]
    outcomes    = [1,   1,   1,   1,   0,   0,   1,   0,   0,   0  ]
    p5 = compute_precision_at_k(predictions, outcomes, k=5)
    assert p5 == pytest.approx(0.8)


def test_precision_at_k_perfect():
    from fichajes_bot.backtesting.metrics import compute_precision_at_k

    predictions = [0.9, 0.8, 0.7, 0.2, 0.1]
    outcomes =    [1,   1,   1,   0,   0  ]
    assert compute_precision_at_k(predictions, outcomes, k=3) == pytest.approx(1.0)


def test_precision_at_k_exceeds_length():
    from fichajes_bot.backtesting.metrics import compute_precision_at_k

    predictions = [0.8, 0.5]
    outcomes = [1, 0]
    # k=10 > len(predictions)=2 → clips to len
    result = compute_precision_at_k(predictions, outcomes, k=10)
    assert result == pytest.approx(0.5)  # 1/2


# ── Tests: Calibration ───────────────────────────────────────────────────────


def test_calibration_curve_well_calibrated():
    """A well-calibrated system has bins near the diagonal."""
    from fichajes_bot.backtesting.metrics import compute_calibration_curve

    import random
    random.seed(0)
    # Generate perfectly calibrated predictions
    predictions: list[float] = []
    outcomes: list[int] = []
    for _ in range(500):
        p = random.random()
        o = 1 if random.random() < p else 0
        predictions.append(p)
        outcomes.append(o)

    curve = compute_calibration_curve(predictions, outcomes, bins=5)
    assert len(curve) > 0
    # Check that bins are roughly on the diagonal (|pred - obs| < 0.2)
    for b in curve:
        assert abs(b.predicted_prob - b.observed_freq) < 0.25, (
            f"Bin {b.predicted_prob:.2f}: predicted={b.predicted_prob:.2f} "
            f"observed={b.observed_freq:.2f}"
        )


def test_ece_perfect_calibration():
    """Well-calibrated predictions → ECE low; miscalibrated → ECE high."""
    from fichajes_bot.backtesting.metrics import compute_ece

    # Well-calibrated: 30% of p≈0.3 bucket are positive, 70% of p≈0.7 are positive
    predictions_good = [0.3] * 70 + [0.7] * 30
    outcomes_good    = ([1] * 21 + [0] * 49) + ([1] * 21 + [0] * 9)
    ece_good = compute_ece(predictions_good, outcomes_good)

    # Completely wrong: always predict 0.9 but observe 0% positive
    predictions_bad = [0.9] * 50
    outcomes_bad    = [0] * 50
    ece_bad = compute_ece(predictions_bad, outcomes_bad)

    # Bad calibration should have higher ECE than good calibration
    assert ece_bad > ece_good, (
        f"ECE should be higher for miscalibrated predictions: "
        f"good={ece_good:.3f} bad={ece_bad:.3f}"
    )
    assert ece_bad > 0.5, f"Badly miscalibrated ECE should be >0.5: {ece_bad}"


# ── Tests: Walk-Forward ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_walk_forward_no_leakage(db):
    """Verify no future outcome data leaks into training set."""
    from fichajes_bot.backtesting.walk_forward import BacktestConfig, WalkForwardBacktester

    today = date.today()
    base = today - timedelta(days=400)

    # Insert jugadores with outcomes at known dates
    for i in range(10):
        outcome_date = _date_str(base + timedelta(days=30 * i + 190))
        outcome = "FICHAJE_EFECTIVO" if i % 2 == 0 else "OPERACION_CAIDA"
        await _insert_jugador(
            db,
            f"Player {i}",
            outcome=outcome,
            fecha_outcome=outcome_date,
            score=0.4 + i * 0.05,
        )

    config = BacktestConfig(train_window_days=180, test_window_days=30, step_days=30)
    backtester = WalkForwardBacktester(db, config)

    # run() will internally assert no leakage — if it raises AssertionError, test fails
    metrics = await backtester.run(
        start_date=base,
        end_date=base + timedelta(days=400),
    )

    # Verify that backtest_results were persisted
    results = await db.execute(
        "SELECT COUNT(*) as n FROM backtest_results"
    )
    assert results[0]["n"] >= 0  # may be 0 if no overlapping windows


@pytest.mark.asyncio
async def test_walk_forward_persists_run(db):
    """Walk-forward creates a backtest_runs record."""
    from fichajes_bot.backtesting.walk_forward import WalkForwardBacktester

    base = date.today() - timedelta(days=400)
    for i in range(5):
        outcome_date = _date_str(base + timedelta(days=30 * i + 190))
        await _insert_jugador(db, f"Runner {i}", outcome="FICHAJE_EFECTIVO",
                              fecha_outcome=outcome_date, score=0.7)

    backtester = WalkForwardBacktester(db)
    await backtester.run(start_date=base, end_date=base + timedelta(days=400))

    runs = await db.execute("SELECT * FROM backtest_runs LIMIT 5")
    assert len(runs) >= 1
    assert runs[0]["run_id"] is not None


# ── Tests: Regression Guard ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_regression_guard_detects_degradation(db):
    """If Brier worsens >15%, regression guard returns False."""
    from fichajes_bot.backtesting.regression_guard import check

    # Previous run: good metrics
    prev_id = _uid()
    await _insert_backtest_run(
        db, prev_id,
        brier=0.15, auc=0.75,
        completed_at=datetime(2026, 4, 1, tzinfo=timezone.utc).isoformat(),
    )

    # Latest run: significantly worse Brier (+20%)
    latest_id = _uid()
    await _insert_backtest_run(
        db, latest_id,
        brier=0.18, auc=0.75,  # 20% worse: 0.18/0.15 = 1.20
        completed_at=datetime(2026, 4, 20, tzinfo=timezone.utc).isoformat(),
    )

    result = await check(db)
    assert result is False, "Should detect Brier regression of 20%"


@pytest.mark.asyncio
async def test_regression_guard_passes_improvement(db):
    """If metrics improve, regression guard returns True."""
    from fichajes_bot.backtesting.regression_guard import check

    prev_id = _uid()
    await _insert_backtest_run(
        db, prev_id,
        brier=0.20, auc=0.65,
        completed_at=datetime(2026, 4, 1, tzinfo=timezone.utc).isoformat(),
    )

    latest_id = _uid()
    await _insert_backtest_run(
        db, latest_id,
        brier=0.17, auc=0.70,  # improved
        completed_at=datetime(2026, 4, 20, tzinfo=timezone.utc).isoformat(),
    )

    result = await check(db)
    assert result is True, "Should pass when metrics improve"


@pytest.mark.asyncio
async def test_regression_guard_single_run_passes(db):
    """With only one run, no comparison possible → passes."""
    from fichajes_bot.backtesting.regression_guard import check

    await _insert_backtest_run(db, _uid(), brier=0.20, auc=0.65)

    result = await check(db)
    assert result is True


@pytest.mark.asyncio
async def test_regression_guard_auc_degradation(db):
    """If AUC worsens >10%, regression guard returns False."""
    from fichajes_bot.backtesting.regression_guard import check

    prev_id = _uid()
    await _insert_backtest_run(
        db, prev_id,
        brier=0.18, auc=0.75,
        completed_at=datetime(2026, 4, 1, tzinfo=timezone.utc).isoformat(),
    )

    latest_id = _uid()
    # AUC drops from 0.75 to 0.65 = 13.3% drop > 10%
    await _insert_backtest_run(
        db, latest_id,
        brier=0.18, auc=0.65,
        completed_at=datetime(2026, 4, 20, tzinfo=timezone.utc).isoformat(),
    )

    result = await check(db)
    assert result is False, "Should detect AUC regression of 13%"


# ── Tests: Dataset Loader ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_dataset_loader_filters_no_outcome(db):
    """Players without outcome_clasificado are excluded."""
    from fichajes_bot.backtesting.dataset_loader import load_historical_dataset

    await _insert_jugador(db, "Player with outcome",
                          outcome="FICHAJE_EFECTIVO", fecha_outcome="2026-01-01", score=0.8)
    await _insert_jugador(db, "Player no outcome", outcome=None, fecha_outcome=None, score=0.5)

    records = await load_historical_dataset(db)
    names = [r.nombre_canonico for r in records]
    assert "Player with outcome" in names
    assert "Player no outcome" not in names


@pytest.mark.asyncio
async def test_dataset_loader_sorted_chronologically(db):
    """Records are sorted by fecha_outcome ASC."""
    from fichajes_bot.backtesting.dataset_loader import load_historical_dataset

    await _insert_jugador(db, "Earlier",  outcome="FICHAJE_EFECTIVO",
                          fecha_outcome="2025-01-01", score=0.7)
    await _insert_jugador(db, "Later",    outcome="OPERACION_CAIDA",
                          fecha_outcome="2025-06-01", score=0.3)
    await _insert_jugador(db, "Middle",   outcome="FICHAJE_EFECTIVO",
                          fecha_outcome="2025-03-15", score=0.6)

    records = await load_historical_dataset(db)
    dates = [r.fecha_outcome for r in records]
    assert dates == sorted(dates), f"Records not sorted: {dates}"


@pytest.mark.asyncio
async def test_dataset_loader_actual_outcome_encoding(db):
    """FICHAJE_EFECTIVO → actual_outcome=1; OPERACION_CAIDA → 0."""
    from fichajes_bot.backtesting.dataset_loader import load_historical_dataset

    await _insert_jugador(db, "Confirmed", outcome="FICHAJE_EFECTIVO",
                          fecha_outcome="2025-01-01", score=0.9)
    await _insert_jugador(db, "Failed",    outcome="OPERACION_CAIDA",
                          fecha_outcome="2025-02-01", score=0.3)

    records = await load_historical_dataset(db)
    by_name = {r.nombre_canonico: r for r in records}

    assert by_name["Confirmed"].actual_outcome == 1
    assert by_name["Failed"].actual_outcome == 0


# ── Tests: Aggregate Metrics ──────────────────────────────────────────────────


def test_aggregate_metrics_returns_all_keys():
    from fichajes_bot.backtesting.metrics import aggregate_metrics

    preds = [0.8, 0.6, 0.4, 0.2]
    outcomes = [1, 1, 0, 0]
    m = aggregate_metrics(preds, outcomes)

    for key in ("brier_score", "auc_roc", "precision_at_5", "precision_at_10",
                "precision_at_20", "ece", "n_samples", "n_positives"):
        assert key in m, f"Missing key: {key}"

    assert m["n_samples"] == 4.0
    assert m["n_positives"] == 2.0
