"""BiasCorrector — adjusts rumor weight based on documented media bias.

Each news source has a known directional bias (pro-RM, pro-Barça, neutral, etc.).
When a biased source reports something that aligns with their bias, we discount it.
When they report against their bias, we treat it as more credible (neutral or slight boost).

Bias table summary (from configs/bias.yaml):
  pro-rm    + FICHAJE → 0.75   (inflating RM signings — common pattern)
  pro-rm    + SALIDA  → 0.75   (suspicious if they push a salida narrative)
  pro-barca + FICHAJE → 0.95   (against their bias → credible)
  pro-barca + SALIDA  → 0.65   (exaggerating RM departures — documented pattern)
  sensacionalista     → 0.50   (low base accuracy regardless of direction)
  clickbait           → 0.40   (very low accuracy)
  neutral             → 1.00   (no correction needed)

evaluate(rumor) → factor in [0.40, 1.10] for one rumor.
Caller (modifiers.py) takes the weighted mean across all rumores for a player.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import yaml
from loguru import logger

from fichajes_bot.persistence.d1_client import D1Client

_CONFIGS_DIR = Path(__file__).parent.parent.parent.parent / "configs"

# Factor table: (sesgo_value, tipo_operacion) → bias correction factor
_BIAS_TABLE: dict[tuple[str, str], float] = {
    # Pro-RM sources inflate fichajes; suppress-then-leak salidas = unreliable
    ("pro-rm", "FICHAJE"):     0.75,
    ("pro-rm", "SALIDA"):      0.75,
    ("pro-rm", "RENOVACION"):  0.85,
    ("pro-rm", "CESION"):      0.90,
    # Levemente (lightly) biased
    ("levemente-pro-rm", "FICHAJE"):     0.85,
    ("levemente-pro-rm", "SALIDA"):      0.90,
    ("levemente-pro-rm", "RENOVACION"):  0.95,
    # Pro-Barça: fichaje RM = against bias → credible; salida RM = with bias → discount
    ("pro-barca", "FICHAJE"):     0.95,
    ("pro-barca", "SALIDA"):      0.65,
    ("pro-barca", "RENOVACION"):  0.90,
    ("pro-barca", "CESION"):      0.90,
    # Sensationalist sources
    ("sensacionalista", "FICHAJE"):     0.50,
    ("sensacionalista", "SALIDA"):      0.55,
    ("sensacionalista-pro-rm", "FICHAJE"):  0.50,
    ("sensacionalista-pro-rm", "SALIDA"):   0.55,
    # Clickbait aggregators
    ("clickbait", "FICHAJE"):  0.40,
    ("clickbait", "SALIDA"):   0.45,
    # Neutral/official sources — no correction
    ("neutral", "FICHAJE"):     1.00,
    ("neutral", "SALIDA"):      1.00,
    ("neutral", "RENOVACION"):  1.00,
    ("neutral", "CESION"):      1.00,
    ("oficial", "FICHAJE"):     1.00,
    ("oficial", "SALIDA"):      1.00,
}

_DEFAULT_FACTOR = 1.00
_FACTOR_MIN = 0.40
_FACTOR_MAX = 1.10


class BiasCorrector:
    """Applies documented media-bias corrections to rumor scores."""

    def __init__(self, db: D1Client) -> None:
        self.db = db
        self._config: Optional[dict] = None
        self._fuente_sesgo_cache: dict[str, str] = {}

    def _load_config(self) -> dict:
        if self._config is not None:
            return self._config
        try:
            self._config = yaml.safe_load(
                (_CONFIGS_DIR / "bias.yaml").read_text(encoding="utf-8")
            ) or {}
        except Exception:
            self._config = {}
        return self._config

    async def _get_sesgo(self, fuente_id: str) -> Optional[str]:
        """Fetch sesgo for a fuente (cached per instance)."""
        if fuente_id in self._fuente_sesgo_cache:
            return self._fuente_sesgo_cache[fuente_id]

        rows = await self.db.execute(
            "SELECT sesgo FROM fuentes WHERE fuente_id=? LIMIT 1",
            [fuente_id],
        )
        sesgo = rows[0]["sesgo"] if rows else None
        if fuente_id:
            self._fuente_sesgo_cache[fuente_id] = sesgo or "neutral"
        return sesgo

    async def evaluate(self, rumor: dict) -> float:
        """Return bias correction factor for a single rumor in [0.40, 1.10].

        Looks up the source's sesgo via DB and maps to the bias table.
        Returns 1.0 (neutral) when no source information is available.
        """
        fuente_id = rumor.get("fuente_id")
        tipo = rumor.get("tipo_operacion") or "FICHAJE"

        if not fuente_id:
            return _DEFAULT_FACTOR

        sesgo = await self._get_sesgo(fuente_id)
        if not sesgo:
            return _DEFAULT_FACTOR

        factor = _BIAS_TABLE.get((sesgo, tipo), _DEFAULT_FACTOR)
        factor = max(_FACTOR_MIN, min(_FACTOR_MAX, factor))

        logger.debug(
            f"BiasCorrector: fuente={fuente_id} sesgo={sesgo} tipo={tipo} → {factor:.2f}"
        )
        return factor

    async def evaluate_batch(self, rumores: list[dict]) -> float:
        """Weighted mean bias factor across all rumores.

        Weight: peso_lexico (how strongly the rumor contributes to the signal).
        Falls back to 1.0 if no rumores or no fuente information.
        """
        if not rumores:
            return _DEFAULT_FACTOR

        total_weight = 0.0
        weighted_sum = 0.0

        for r in rumores:
            if r.get("retractado"):
                continue
            factor = await self.evaluate(r)
            weight = float(r.get("peso_lexico") or 0.5)
            weighted_sum += factor * weight
            total_weight += weight

        if total_weight == 0:
            return _DEFAULT_FACTOR

        result = weighted_sum / total_weight
        return max(_FACTOR_MIN, min(_FACTOR_MAX, result))
