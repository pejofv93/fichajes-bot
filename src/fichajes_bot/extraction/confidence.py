"""Confidence computation for the hybrid extractor.

Combines signals from regex patterns, lexicon matches, and context signals.
The resulting score determines whether we go to Gemini (< THRESHOLD) or not.
"""

from __future__ import annotations

from typing import Optional

THRESHOLD = 0.60  # minimum confidence to accept without LLM


def compute_confidence(
    regex_confianza: Optional[float],
    lexicon_weight: float,
    n_lexicon_matches: int,
    negation_found: bool = False,
    is_trial_balloon: bool = False,
) -> float:
    """Compute a combined confidence score.

    Args:
        regex_confianza:    Base confidence from regex pattern match (None if no match).
        lexicon_weight:     Aggregate weight from lexicon matches (0.0–1.0).
        n_lexicon_matches:  Number of distinct lexicon entries matched.
        negation_found:     Whether a negation phrase was detected.
        is_trial_balloon:   Whether trial-balloon markers were found.

    Returns:
        Float in [0.0, 1.0].
    """
    # Start from the stronger of regex or lexicon
    base = max(
        float(regex_confianza or 0.0),
        lexicon_weight,
    )

    if base == 0.0:
        return 0.0

    # Corroboration boost: multiple independent signals
    if regex_confianza and lexicon_weight >= 0.5:
        # Both agree — mutual reinforcement
        base = min(1.0, base + 0.08)

    if n_lexicon_matches >= 3:
        base = min(1.0, base + 0.05)

    # Penalties
    if negation_found:
        base = max(0.0, base - 0.30)

    if is_trial_balloon:
        base = max(0.0, base - 0.12)

    return round(base, 4)


def needs_llm(confidence: float) -> bool:
    """True if confidence is below threshold and we should call Gemini."""
    return confidence < THRESHOLD
