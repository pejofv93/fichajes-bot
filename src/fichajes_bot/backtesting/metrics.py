"""Backtesting metrics: Brier, AUC-ROC, Precision@K, Calibration, ECE."""

from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass
class CalibrationBin:
    predicted_prob: float   # mean predicted probability in bin
    observed_freq: float    # empirical frequency of positive outcomes
    count: int              # number of samples in bin


def compute_brier_score(
    predictions: list[float], outcomes: list[int]
) -> float:
    """Brier score: mean squared error of probabilistic predictions.

    Lower is better. 0 = perfect. 0.25 = uninformative (all 0.5 constant).
    """
    if not predictions:
        return float("nan")
    n = len(predictions)
    return sum((p - o) ** 2 for p, o in zip(predictions, outcomes)) / n


def compute_auc_roc(
    predictions: list[float], outcomes: list[int]
) -> float:
    """AUC-ROC via trapezoidal rule.

    1.0 = perfect ranking. 0.5 = random. Below 0.5 = worse than random.
    """
    if not predictions or len(set(outcomes)) < 2:
        return float("nan")

    n = len(predictions)
    pairs = sorted(zip(predictions, outcomes), key=lambda x: -x[0])

    n_pos = sum(outcomes)
    n_neg = n - n_pos
    if n_pos == 0 or n_neg == 0:
        return float("nan")

    # Count concordant pairs via Wilcoxon-Mann-Whitney statistic
    concordant = 0
    for pred, outcome in pairs:
        if outcome == 1:
            # Count negatives ranked below this positive
            concordant += sum(
                1 for p2, o2 in zip(predictions, outcomes) if o2 == 0 and p2 < pred
            )
            # Ties count as 0.5
            concordant += 0.5 * sum(
                1 for p2, o2 in zip(predictions, outcomes) if o2 == 0 and p2 == pred
            )

    return concordant / (n_pos * n_neg)


def compute_precision_at_k(
    predictions: list[float], outcomes: list[int], k: int
) -> float:
    """Fraction of actual positives in top-K predicted.

    P@K = (# positives in top K) / K.
    Returns nan if k > len(predictions) or no predictions.
    """
    if not predictions or k <= 0:
        return float("nan")
    k = min(k, len(predictions))
    ranked = sorted(
        zip(predictions, outcomes), key=lambda x: -x[0]
    )
    hits = sum(o for _, o in ranked[:k])
    return hits / k


def compute_calibration_curve(
    predictions: list[float],
    outcomes: list[int],
    bins: int = 10,
) -> list[CalibrationBin]:
    """Reliability diagram data: predicted prob vs observed frequency per bin.

    A well-calibrated system has predicted_prob ≈ observed_freq in each bin.
    """
    if not predictions:
        return []

    bin_size = 1.0 / bins
    result: list[CalibrationBin] = []

    for b in range(bins):
        lo = b * bin_size
        hi = lo + bin_size
        in_bin = [
            (p, o) for p, o in zip(predictions, outcomes)
            if lo <= p < hi or (b == bins - 1 and p == 1.0)
        ]
        if not in_bin:
            continue
        mean_pred = sum(p for p, _ in in_bin) / len(in_bin)
        obs_freq = sum(o for _, o in in_bin) / len(in_bin)
        result.append(CalibrationBin(
            predicted_prob=mean_pred,
            observed_freq=obs_freq,
            count=len(in_bin),
        ))

    return result


def compute_ece(
    predictions: list[float],
    outcomes: list[int],
    bins: int = 10,
) -> float:
    """Expected Calibration Error: weighted mean absolute calibration error.

    Lower is better. 0 = perfectly calibrated.
    """
    if not predictions:
        return float("nan")

    curve = compute_calibration_curve(predictions, outcomes, bins)
    n = len(predictions)
    if n == 0:
        return float("nan")

    return sum(
        (b.count / n) * abs(b.predicted_prob - b.observed_freq)
        for b in curve
    )


def compute_reliability_diagram_data(
    predictions: list[float],
    outcomes: list[int],
    bins: int = 10,
) -> dict[str, list[float]]:
    """Return dict with 'predicted', 'observed', 'counts' for plotting."""
    curve = compute_calibration_curve(predictions, outcomes, bins)
    return {
        "predicted": [b.predicted_prob for b in curve],
        "observed": [b.observed_freq for b in curve],
        "counts": [b.count for b in curve],
    }


def aggregate_metrics(
    predictions: list[float], outcomes: list[int]
) -> dict[str, float]:
    """Compute all metrics in one call."""
    return {
        "brier_score": compute_brier_score(predictions, outcomes),
        "auc_roc": compute_auc_roc(predictions, outcomes),
        "precision_at_5": compute_precision_at_k(predictions, outcomes, 5),
        "precision_at_10": compute_precision_at_k(predictions, outcomes, 10),
        "precision_at_20": compute_precision_at_k(predictions, outcomes, 20),
        "ece": compute_ece(predictions, outcomes),
        "n_samples": float(len(predictions)),
        "n_positives": float(sum(outcomes)),
    }
