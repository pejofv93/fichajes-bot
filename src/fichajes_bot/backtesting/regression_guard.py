"""Regression guard: compare latest backtest metrics vs previous run.

Exits with code 1 if Brier worsens >15% or AUC worsens >10%.
Integrated in ci.yml as an informational (non-blocking) step.
"""

from __future__ import annotations

import json
import sys

from loguru import logger

from fichajes_bot.persistence.d1_client import D1Client

BRIER_MAX_REGRESSION = 0.15   # 15% relative worsening allowed
AUC_MAX_REGRESSION = 0.10     # 10% relative worsening allowed


async def check(db: D1Client) -> bool:
    """Compare last two backtest runs. Returns True if OK, False if regression."""
    runs = await db.execute(
        """SELECT run_id, completed_at, metrics_json
           FROM backtest_runs
           WHERE completed_at IS NOT NULL
           ORDER BY completed_at DESC
           LIMIT 2"""
    )

    if len(runs) < 2:
        logger.info("regression_guard: fewer than 2 completed runs, skipping comparison")
        return True

    latest = json.loads(runs[0].get("metrics_json") or "{}")
    previous = json.loads(runs[1].get("metrics_json") or "{}")

    issues: list[str] = []

    # Brier: lower is better — regression if latest is much higher
    b_latest = latest.get("brier_score")
    b_prev = previous.get("brier_score")
    if b_latest is not None and b_prev is not None and b_prev > 0:
        regression_pct = (b_latest - b_prev) / b_prev
        if regression_pct > BRIER_MAX_REGRESSION:
            issues.append(
                f"Brier worsened {regression_pct:.1%} "
                f"({b_prev:.4f} → {b_latest:.4f}, threshold {BRIER_MAX_REGRESSION:.0%})"
            )

    # AUC: higher is better — regression if latest is much lower
    a_latest = latest.get("auc_roc")
    a_prev = previous.get("auc_roc")
    if a_latest is not None and a_prev is not None and a_prev > 0:
        regression_pct = (a_prev - a_latest) / a_prev
        if regression_pct > AUC_MAX_REGRESSION:
            issues.append(
                f"AUC worsened {regression_pct:.1%} "
                f"({a_prev:.4f} → {a_latest:.4f}, threshold {AUC_MAX_REGRESSION:.0%})"
            )

    if issues:
        logger.error("regression_guard: DEGRADATION DETECTED")
        for issue in issues:
            logger.error(f"  ✗ {issue}")
        return False

    logger.info(
        f"regression_guard: OK | "
        f"brier {b_prev:.4f}→{b_latest:.4f} | "
        f"auc {a_prev:.4f}→{a_latest:.4f}"
        if (b_latest and b_prev and a_latest and a_prev) else
        "regression_guard: OK (insufficient data for full comparison)"
    )
    return True


async def run_check() -> None:
    """CLI entry point: exit 1 on detected regression."""
    async with D1Client() as db:
        ok = await check(db)
    if not ok:
        sys.exit(1)


def main() -> None:
    import asyncio
    asyncio.run(run_check())


if __name__ == "__main__":
    main()
