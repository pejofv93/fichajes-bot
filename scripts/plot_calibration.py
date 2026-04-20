"""Generate calibration reliability diagram + prediction histogram.

Saves PNG to docs/backtest_plots/.
Called from backtesting runner after a backtest run.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path


def generate_calibration_plot(
    predictions: list[float],
    outcomes: list[int],
    output_dir: Path | None = None,
) -> Path | None:
    """Generate reliability diagram and histogram. Returns output path or None."""
    try:
        import matplotlib
        matplotlib.use("Agg")  # non-interactive backend
        import matplotlib.pyplot as plt
        import matplotlib.gridspec as gridspec
    except ImportError:
        return None

    from fichajes_bot.backtesting.metrics import compute_calibration_curve

    if output_dir is None:
        output_dir = Path(__file__).parent.parent / "docs" / "backtest_plots"
    output_dir.mkdir(parents=True, exist_ok=True)

    curve = compute_calibration_curve(predictions, outcomes, bins=10)
    if not curve:
        return None

    pred_vals = [b.predicted_prob for b in curve]
    obs_vals = [b.observed_freq for b in curve]

    today = datetime.now(timezone.utc).strftime("%Y%m%d")
    outpath = output_dir / f"calibration_{today}.png"

    fig = plt.figure(figsize=(10, 8))
    gs = gridspec.GridSpec(2, 1, height_ratios=[3, 1])

    # ── Reliability diagram ──────────────────────────────────────────────────
    ax0 = fig.add_subplot(gs[0])
    ax0.plot([0, 1], [0, 1], "k--", lw=1.5, label="Perfect calibration")
    ax0.plot(pred_vals, obs_vals, "o-", color="#F7931A", lw=2.5,
             ms=8, label="Fichajes Bot")

    ax0.fill_between(pred_vals, pred_vals, obs_vals,
                     alpha=0.15, color="#F7931A", label="Calibration gap")

    ax0.set_xlim(0, 1)
    ax0.set_ylim(0, 1)
    ax0.set_xlabel("Predicted probability", fontsize=12)
    ax0.set_ylabel("Observed frequency", fontsize=12)
    ax0.set_title("Reliability Diagram — Fichajes Bot v3.1", fontsize=14, fontweight="bold")
    ax0.legend(loc="upper left")
    ax0.grid(True, alpha=0.3)

    # Annotate count per bin
    for pred, obs, count in zip(pred_vals, obs_vals, [b.count for b in curve]):
        ax0.annotate(f"n={count}", xy=(pred, obs), xytext=(pred + 0.02, obs + 0.03),
                     fontsize=8, color="gray")

    # ── Prediction histogram ─────────────────────────────────────────────────
    ax1 = fig.add_subplot(gs[1])
    ax1.hist(predictions, bins=20, color="#F7931A", alpha=0.7, edgecolor="white")
    ax1.set_xlabel("Predicted probability", fontsize=10)
    ax1.set_ylabel("Count", fontsize=10)
    ax1.set_title("Prediction Distribution", fontsize=11)
    ax1.set_xlim(0, 1)
    ax1.grid(True, alpha=0.3, axis="y")

    plt.tight_layout()
    plt.savefig(outpath, dpi=150, bbox_inches="tight",
                facecolor="#0A0A0A" if _dark_mode() else "white")
    plt.close()

    return outpath


def _dark_mode() -> bool:
    return False  # configurable in future


if __name__ == "__main__":
    # Example: generate with synthetic data
    import random
    preds = [random.betavariate(2, 3) for _ in range(200)]
    outcomes = [1 if p + random.gauss(0, 0.2) > 0.5 else 0 for p in preds]
    path = generate_calibration_plot(preds, outcomes)
    if path:
        print(f"Saved: {path}")
    else:
        print("matplotlib not available")
