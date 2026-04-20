"""TemporalValidator — market window and event timing modifier.

Produces a multiplier reflecting how favorable the timing is for a transfer:

  Factor range: [0.5, 1.5]
  - 1.40  inside verano window (Jun–Sep)
  - 1.50  final 7 days of any window (cierre urgency)
  - 1.20  inside enero window (Jan)
  - 1.00  outside window with "próxima temporada" indicator
  - 0.70  outside window, no forward-looking indicator
  + 0.20 multiplier boost when jugador has FIN_CONTRATO_PROX flag

Reads configs/temporal.yaml for window definitions and special events.
"""

from __future__ import annotations

import json
from datetime import date, datetime, timezone
from pathlib import Path

import yaml
from loguru import logger

from fichajes_bot.persistence.d1_client import D1Client

_CONFIGS_DIR = Path(__file__).parent.parent.parent.parent / "configs"

FACTOR_VERANO      = 1.40
FACTOR_ENERO       = 1.20
FACTOR_FUERA_VENT  = 0.70
FACTOR_NEUTRO      = 1.00
FACTOR_CIERRE      = 1.50
FACTOR_CONTRATO    = 1.20  # multiplied when FIN_CONTRATO_PROX flag set

FACTOR_MIN = 0.50
FACTOR_MAX = 1.50

_DIAS_CIERRE_BOOST = 7

_PROXIMA_TEMPORADA_KEYWORDS = (
    "próxima temporada",
    "proxima temporada",
    "next season",
    "summer",
    "verano",
    "for the summer",
    "julio",
    "agosto",
)


class TemporalValidator:
    """Evaluates transfer timing relative to the market calendar."""

    def __init__(self, db: D1Client) -> None:
        self.db = db
        self._config: dict | None = None

    def _load_config(self) -> dict:
        if self._config is not None:
            return self._config
        try:
            self._config = yaml.safe_load(
                (_CONFIGS_DIR / "temporal.yaml").read_text(encoding="utf-8")
            ) or {}
        except Exception:
            self._config = {}
        return self._config

    def _current_date(self) -> date:
        return datetime.now(timezone.utc).date()

    def _in_verano(self, d: date) -> bool:
        """June 1 through September 1 inclusive."""
        return (d.month in (6, 7, 8)) or (d.month == 9 and d.day == 1)

    def _in_enero(self, d: date) -> bool:
        return d.month == 1

    def _days_to_window_close(self, d: date) -> int | None:
        """Days until end of current window, or None if not in a window."""
        if self._in_verano(d):
            close = date(d.year, 9, 1)
            return (close - d).days
        if self._in_enero(d):
            close = date(d.year, 2, 1)
            return (close - d).days
        return None

    def _special_event_boost(self, d: date) -> float:
        """Check if date falls within a special-event window from config."""
        config = self._load_config()
        events = config.get("eventos_especiales") or []
        for event in events:
            try:
                start = date.fromisoformat(str(event["fecha_inicio"]))
                end   = date.fromisoformat(str(event["fecha_fin"]))
                if start <= d <= end:
                    factor = float(event.get("factor_multiplicador", 1.0))
                    logger.debug(f"TemporalValidator: special event '{event['nombre']}' → ×{factor}")
                    return factor
            except Exception:
                continue
        return 1.0

    def _is_proxima_temporada(self, rumor: dict) -> bool:
        texto = (rumor.get("texto_fragmento") or "").lower()
        return any(kw in texto for kw in _PROXIMA_TEMPORADA_KEYWORDS)

    def evaluate(self, rumor: dict, jugador: dict) -> float:
        """Return temporal modifier factor in [0.5, 1.5].

        Args:
            rumor:   Rumor dict with at least 'texto_fragmento' and 'flags'.
            jugador: Jugador dict with at least 'flags'.
        """
        today = self._current_date()

        # Base factor from market window
        in_verano = self._in_verano(today)
        in_enero  = self._in_enero(today)

        if in_verano:
            factor = FACTOR_VERANO
        elif in_enero:
            factor = FACTOR_ENERO
        elif self._is_proxima_temporada(rumor):
            factor = FACTOR_NEUTRO
        else:
            factor = FACTOR_FUERA_VENT

        # Cierre-de-mercado urgency boost
        days_left = self._days_to_window_close(today)
        if days_left is not None and days_left <= _DIAS_CIERRE_BOOST:
            factor = FACTOR_CIERRE
            logger.debug(f"TemporalValidator: window closing in {days_left}d → cierre boost")

        # Special event boost (post-Mundial/Euro etc.)
        event_mult = self._special_event_boost(today)
        if event_mult != 1.0:
            factor = min(FACTOR_MAX, factor * event_mult)

        # Contract expiry boost
        jugador_flags = jugador.get("flags") or "[]"
        if isinstance(jugador_flags, str):
            try:
                flags_list = json.loads(jugador_flags)
            except Exception:
                flags_list = []
        else:
            flags_list = list(jugador_flags)

        if "FIN_CONTRATO_PROX" in flags_list:
            factor = min(FACTOR_MAX, factor * FACTOR_CONTRATO)
            logger.debug("TemporalValidator: FIN_CONTRATO_PROX boost applied")

        factor = max(FACTOR_MIN, min(FACTOR_MAX, factor))
        logger.debug(f"TemporalValidator: {today} → factor={factor:.2f}")
        return factor
