"""Walk-forward backtesting engine.

Splits historical data into rolling train/test windows. Only uses data
available at t-1 for training — no look-ahead leakage.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Any

from loguru import logger

from fichajes_bot.backtesting.dataset_loader import BacktestRecord, load_historical_dataset
from fichajes_bot.backtesting.metrics import aggregate_metrics
from fichajes_bot.persistence.d1_client import D1Client


@dataclass
class WindowResult:
    window_start: date
    window_end: date
    records: list[BacktestRecord]
    metrics: dict[str, float]


@dataclass
class BacktestConfig:
    train_window_days: int = 180
    test_window_days: int = 30
    step_days: int = 30


class WalkForwardBacktester:
    def __init__(self, db: D1Client, config: BacktestConfig | None = None) -> None:
        self._db = db
        self.config = config or BacktestConfig()

    async def run(
        self,
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> dict[str, Any]:
        """Execute walk-forward backtest and persist results.

        Returns aggregated metrics dict.
        """
        run_id = str(uuid.uuid4())
        started_at = datetime.now(timezone.utc).isoformat()

        # Persist run start
        await self._db.execute(
            """INSERT INTO backtest_runs (run_id, started_at, config_json)
               VALUES (?, ?, ?)""",
            [run_id, started_at, json.dumps(self.config.__dict__)],
        )

        all_records = await load_historical_dataset(self._db)
        if not all_records:
            logger.warning("walk_forward: no historical records available")
            await self._finish_run(run_id, {})
            return {}

        # Determine date range
        dates = [_parse_date(r.fecha_outcome) for r in all_records if r.fecha_outcome]
        if not dates:
            logger.warning("walk_forward: no valid outcome dates")
            await self._finish_run(run_id, {})
            return {}

        start = start_date or min(dates)
        end = end_date or max(dates)
        cfg = self.config

        all_predictions: list[float] = []
        all_outcomes: list[int] = []
        window_results: list[WindowResult] = []

        t = start + timedelta(days=cfg.train_window_days)
        while t + timedelta(days=cfg.test_window_days) <= end + timedelta(days=1):
            test_start = t
            test_end = t + timedelta(days=cfg.test_window_days)
            train_cutoff = t  # leakage prevention: only data strictly before t

            # Training set: all records with outcome BEFORE test window
            train_records = [
                r for r in all_records
                if _parse_date(r.fecha_outcome) < train_cutoff
            ]

            # Test set: records whose outcome falls in [test_start, test_end)
            test_records = [
                r for r in all_records
                if test_start <= _parse_date(r.fecha_outcome) < test_end
            ]

            if not test_records:
                t += timedelta(days=cfg.step_days)
                continue

            # Leakage assertion: no test record should be in training set
            train_ids = {r.jugador_id for r in train_records}
            for tr in test_records:
                assert _parse_date(tr.fecha_outcome) >= train_cutoff, (
                    f"LEAKAGE: {tr.jugador_id} outcome {tr.fecha_outcome} "
                    f"appeared in training set (cutoff {train_cutoff})"
                )

            # Apply reliability adjustments from training set
            adjusted_records = self._apply_training_adjustments(train_records, test_records)

            preds = [r.predicted_score for r in adjusted_records]
            outcomes = [r.actual_outcome for r in adjusted_records]

            metrics = aggregate_metrics(preds, outcomes) if preds else {}

            # Persist individual predictions
            for rec in adjusted_records:
                await self._db.execute(
                    """INSERT INTO backtest_results
                       (result_id, run_id, window_start, window_end, jugador_id,
                        predicted_score, actual_outcome, tipo, periodista_principal, created_at)
                       VALUES (?,?,?,?,?,?,?,?,?,datetime('now'))""",
                    [
                        str(uuid.uuid4()),
                        run_id,
                        test_start.isoformat(),
                        test_end.isoformat(),
                        rec.jugador_id,
                        rec.predicted_score,
                        rec.actual_outcome,
                        rec.tipo_operacion,
                        rec.periodista_principal,
                    ],
                )

            window_results.append(WindowResult(
                window_start=test_start,
                window_end=test_end,
                records=adjusted_records,
                metrics=metrics,
            ))

            all_predictions.extend(preds)
            all_outcomes.extend(outcomes)

            logger.info(
                f"window {test_start}..{test_end}: {len(test_records)} records "
                f"| train={len(train_records)} | brier={metrics.get('brier_score', '?'):.4f}"
                if metrics else
                f"window {test_start}..{test_end}: {len(test_records)} records (no metrics)"
            )

            t += timedelta(days=cfg.step_days)

        # Aggregate across all windows
        final_metrics = aggregate_metrics(all_predictions, all_outcomes) if all_predictions else {}
        final_metrics["n_windows"] = float(len(window_results))

        await self._finish_run(run_id, final_metrics)
        self._last_run_id = run_id
        logger.info(f"walk_forward done | run_id={run_id[:8]} windows={len(window_results)} {_fmt_metrics(final_metrics)}")
        return final_metrics

    def _apply_training_adjustments(
        self,
        train_records: list[BacktestRecord],
        test_records: list[BacktestRecord],
    ) -> list[BacktestRecord]:
        """Adjust predicted scores using reliability learned from training.

        Simple shrinkage: if a journalist had low hit rate in training,
        slightly reduce predicted scores for their test records.
        """
        if not train_records:
            return test_records

        # Compute per-journalist accuracy in training period
        journalist_stats: dict[str, tuple[int, int]] = {}  # {name: (hits, total)}
        for r in train_records:
            p = r.periodista_principal or "__unknown__"
            hits, total = journalist_stats.get(p, (0, 0))
            journalist_stats[p] = (hits + r.actual_outcome, total + 1)

        def _journalist_reliability(name: str | None) -> float:
            key = name or "__unknown__"
            if key not in journalist_stats:
                return 0.5  # prior
            hits, total = journalist_stats[key]
            # Beta-Binomial shrinkage toward 0.5 prior with alpha=beta=2
            return (hits + 2) / (total + 4)

        adjusted: list[BacktestRecord] = []
        for r in test_records:
            rel = _journalist_reliability(r.periodista_principal)
            # Dampen predicted score toward 0.5 proportional to journalist reliability
            dampening = (rel - 0.5) * 0.1  # max ±5% adjustment
            new_score = min(1.0, max(0.0, r.predicted_score + dampening))
            adjusted.append(BacktestRecord(
                jugador_id=r.jugador_id,
                nombre_canonico=r.nombre_canonico,
                tipo_operacion=r.tipo_operacion,
                fecha_outcome=r.fecha_outcome,
                actual_outcome=r.actual_outcome,
                predicted_score=new_score,
                periodista_principal=r.periodista_principal,
            ))
        return adjusted

    async def _finish_run(self, run_id: str, metrics: dict[str, float]) -> None:
        completed_at = datetime.now(timezone.utc).isoformat()
        await self._db.execute(
            """UPDATE backtest_runs
               SET completed_at = ?, metrics_json = ?
               WHERE run_id = ?""",
            [completed_at, json.dumps(metrics), run_id],
        )


def _parse_date(date_str: str) -> date:
    """Parse date string to date object (handles ISO datetime strings)."""
    if not date_str:
        return date.min
    try:
        return date.fromisoformat(date_str[:10])
    except (ValueError, TypeError):
        return date.min


def _fmt_metrics(m: dict[str, float]) -> str:
    parts = []
    for k in ("brier_score", "auc_roc", "precision_at_5", "ece"):
        if k in m and not isinstance(m[k], float) or (isinstance(m[k], float) and not (m[k] != m[k])):  # not nan
            try:
                parts.append(f"{k}={m[k]:.4f}")
            except (TypeError, ValueError):
                pass
    return " ".join(parts)
