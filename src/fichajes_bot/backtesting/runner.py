"""Backtesting runner — CLI entry point.

Usage:
    python -m fichajes_bot.backtesting.runner [--start YYYY-MM-DD] [--end YYYY-MM-DD]

Outputs a markdown report to scripts/backtest_report_YYYYMMDD.md.
"""

from __future__ import annotations

import argparse
import asyncio
import json
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from loguru import logger

from fichajes_bot.backtesting.dataset_loader import load_historical_dataset
from fichajes_bot.backtesting.metrics import (
    aggregate_metrics,
    compute_calibration_curve,
    compute_ece,
)
from fichajes_bot.backtesting.walk_forward import BacktestConfig, WalkForwardBacktester
from fichajes_bot.persistence.d1_client import D1Client


async def run(
    start_date: date | None = None,
    end_date: date | None = None,
    _db: D1Client | None = None,
) -> dict[str, Any]:
    """Execute backtesting and generate report. Returns metrics dict."""
    logger.info(f"backtest runner: start={start_date} end={end_date}")

    async def _run_with_db(db: D1Client) -> dict[str, Any]:
        config = BacktestConfig(
            train_window_days=180,
            test_window_days=30,
            step_days=30,
        )
        backtester = WalkForwardBacktester(db, config)
        metrics = await backtester.run(start_date=start_date, end_date=end_date)

        if not metrics:
            logger.warning("backtest runner: no results produced")
            return {}

        # Fetch all results from this run
        run_id = getattr(backtester, "_last_run_id", None)
        if run_id:
            all_results = await db.execute(
                "SELECT * FROM backtest_results WHERE run_id = ?", [run_id]
            )
        else:
            all_results = []

        report = _generate_report(metrics, all_results, config, start_date, end_date)
        _save_report(report)

        # Generate calibration plot if matplotlib is available
        try:
            from scripts.plot_calibration import generate_calibration_plot
            preds = [r["predicted_score"] for r in all_results]
            outcomes = [r["actual_outcome"] for r in all_results]
            if preds:
                generate_calibration_plot(preds, outcomes)
        except Exception as exc:
            logger.debug(f"calibration plot skipped: {exc}")

        return metrics

    if _db is not None:
        return await _run_with_db(_db)

    async with D1Client() as db:
        return await _run_with_db(db)


def _generate_report(
    metrics: dict[str, float],
    results: list[dict[str, Any]],
    config: BacktestConfig,
    start_date: date | None,
    end_date: date | None,
) -> str:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    lines: list[str] = [
        "# Backtest Report — Fichajes Bot",
        f"",
        f"**Generated:** {now}  ",
        f"**Period:** {start_date or 'all'} → {end_date or 'all'}  ",
        f"**Config:** train_window={config.train_window_days}d, test_window={config.test_window_days}d, step={config.step_days}d",
        f"",
        "## Métricas Agregadas",
        f"",
        f"| Métrica | Valor |",
        f"|---------|-------|",
        f"| **Brier Score** ↓ | {_fmt(metrics.get('brier_score'))} |",
        f"| **AUC-ROC** ↑ | {_fmt(metrics.get('auc_roc'))} |",
        f"| **Precision@5** ↑ | {_fmt(metrics.get('precision_at_5'))} |",
        f"| **Precision@10** ↑ | {_fmt(metrics.get('precision_at_10'))} |",
        f"| **Precision@20** ↑ | {_fmt(metrics.get('precision_at_20'))} |",
        f"| **ECE** ↓ | {_fmt(metrics.get('ece'))} |",
        f"| Ventanas backtest | {int(metrics.get('n_windows', 0))} |",
        f"| Predicciones totales | {int(metrics.get('n_samples', 0))} |",
        f"| Positivos (operación confirmada) | {int(metrics.get('n_positives', 0))} |",
        f"",
    ]

    if results:
        # Breakdown by tipo_operacion
        lines += _breakdown_by_tipo(results)
        lines += _breakdown_by_score_band(results)
        lines += _breakdown_by_periodista(results)
        lines += _breakdown_detection_time(results)

    lines += [
        "## Interpretación",
        "",
        "- **Brier < 0.20**: sistema bien calibrado",
        "- **AUC > 0.70**: buen poder discriminante",
        "- **Precision@5 > 0.60**: top-5 jugadores más probables son fiables",
        "- **ECE < 0.10**: buena calibración probabilística",
        "",
        f"*Generado por Fichajes Bot v3.1 backtesting framework*",
    ]

    return "\n".join(lines)


def _breakdown_by_tipo(results: list[dict[str, Any]]) -> list[str]:
    lines = ["## Desglose por Tipo de Operación", ""]
    tipos: dict[str, tuple[list[float], list[int]]] = {}
    for r in results:
        t = r.get("tipo") or "DESCONOCIDO"
        preds, outs = tipos.setdefault(t, ([], []))
        preds.append(r["predicted_score"])
        outs.append(r["actual_outcome"])

    if not tipos:
        return lines + ["Sin datos\n"]

    lines += ["| Tipo | Brier | AUC | P@5 | N |", "|------|-------|-----|-----|---|"]
    for tipo, (preds, outs) in sorted(tipos.items()):
        m = aggregate_metrics(preds, outs) if preds else {}
        lines.append(
            f"| {tipo} | {_fmt(m.get('brier_score'))} | {_fmt(m.get('auc_roc'))} | "
            f"{_fmt(m.get('precision_at_5'))} | {len(preds)} |"
        )
    lines.append("")
    return lines


def _breakdown_by_score_band(results: list[dict[str, Any]]) -> list[str]:
    lines = ["## Desglose por Banda de Score", ""]
    bands = {
        "Alta (≥70%)": ([], []),
        "Media (40-70%)": ([], []),
        "Baja (<40%)": ([], []),
    }
    for r in results:
        p = r["predicted_score"]
        o = r["actual_outcome"]
        if p >= 0.70:
            bands["Alta (≥70%)"][0].append(p)
            bands["Alta (≥70%)"][1].append(o)
        elif p >= 0.40:
            bands["Media (40-70%)"][0].append(p)
            bands["Media (40-70%)"][1].append(o)
        else:
            bands["Baja (<40%)"][0].append(p)
            bands["Baja (<40%)"][1].append(o)

    lines += ["| Banda | Brier | AUC | P@5 | N | Hit rate |", "|-------|-------|-----|-----|---|----------|"]
    for banda, (preds, outs) in bands.items():
        if not preds:
            lines.append(f"| {banda} | — | — | — | 0 | — |")
            continue
        m = aggregate_metrics(preds, outs)
        hit_rate = sum(outs) / len(outs) if outs else 0
        lines.append(
            f"| {banda} | {_fmt(m.get('brier_score'))} | {_fmt(m.get('auc_roc'))} | "
            f"{_fmt(m.get('precision_at_5'))} | {len(preds)} | {hit_rate:.1%} |"
        )
    lines.append("")
    return lines


def _breakdown_by_periodista(results: list[dict[str, Any]]) -> list[str]:
    lines = ["## Desglose por Periodista Principal", ""]
    periodistas: dict[str, tuple[list[float], list[int]]] = {}
    for r in results:
        p = r.get("periodista_principal") or "Desconocido"
        preds, outs = periodistas.setdefault(p, ([], []))
        preds.append(r["predicted_score"])
        outs.append(r["actual_outcome"])

    if not periodistas:
        return lines + ["Sin datos\n"]

    # Sort by count descending, show top 10
    sorted_p = sorted(periodistas.items(), key=lambda x: len(x[1][0]), reverse=True)[:10]
    lines += ["| Periodista | Brier | AUC | Hit rate | N |", "|------------|-------|-----|----------|---|"]
    for per, (preds, outs) in sorted_p:
        m = aggregate_metrics(preds, outs) if preds else {}
        hit_rate = sum(outs) / len(outs) if outs else 0
        lines.append(
            f"| {per} | {_fmt(m.get('brier_score'))} | {_fmt(m.get('auc_roc'))} | "
            f"{hit_rate:.1%} | {len(preds)} |"
        )
    lines.append("")
    return lines


def _breakdown_detection_time(results: list[dict[str, Any]]) -> list[str]:
    """Show breakdown stats — detection time requires score_history with timestamps."""
    lines = ["## Tiempo de Detección de Señales Duras", ""]
    lines += [
        "Análisis de latencia entre publicación del rumor y detección del hard signal.",
        "",
        "*(Requiere acumulación de datos reales — disponible tras ≥30 días de operación)*",
        "",
    ]
    return lines


def _fmt(v: float | None) -> str:
    if v is None or (isinstance(v, float) and v != v):  # nan check
        return "—"
    return f"{v:.4f}"


def _save_report(content: str) -> None:
    today = datetime.now(timezone.utc).strftime("%Y%m%d")
    output_dir = Path(__file__).parent.parent.parent.parent / "scripts"
    output_dir.mkdir(exist_ok=True)
    path = output_dir / f"backtest_report_{today}.md"
    path.write_text(content, encoding="utf-8")
    logger.info(f"backtest report saved: {path}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Run walk-forward backtest")
    parser.add_argument("--start", type=lambda s: date.fromisoformat(s), default=None)
    parser.add_argument("--end", type=lambda s: date.fromisoformat(s), default=None)
    args = parser.parse_args()
    asyncio.run(run(start_date=args.start, end_date=args.end))


if __name__ == "__main__":
    main()
