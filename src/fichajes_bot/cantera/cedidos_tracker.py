"""CedidosTracker — tracks loan players and evaluates return probability.

Data sources:
  - D1 tabla rendimiento_cedidos (updated by cold-loop scraping)
  - Rumores mentioning "compra definitiva" / "opción de compra"
"""

from __future__ import annotations

import json
from typing import Any

from loguru import logger

from fichajes_bot.persistence.d1_client import D1Client

# ── Factor bounds ─────────────────────────────────────────────────────────────

FACTOR_MIN = 0.30
FACTOR_MAX = 1.50

FACTOR_MINUTOS_ALTO = 1.30       # >70% minutes
FACTOR_RATING_ALTO = 1.20        # Sofascore rating > 7.0
FACTOR_LESION = 0.70             # Prolonged injury
FACTOR_COMPRA_DEFINITIVA = 0.50  # Rumour of permanent purchase

UMBRAL_ALERTA_VUELTA = 0.70
MINUTOS_ALTO_PCT = 0.70


class CedidosTracker:
    """Evaluate return probability for loaned players."""

    def __init__(self, db: D1Client) -> None:
        self.db = db

    async def fetch_loan_performance(self, jugador_id: str) -> dict[str, Any] | None:
        """Return latest performance metrics from rendimiento_cedidos."""
        rows = await self.db.execute(
            """SELECT * FROM rendimiento_cedidos
               WHERE jugador_id = ?
               ORDER BY actualizado_at DESC LIMIT 1""",
            [jugador_id],
        )
        return rows[0] if rows else None

    async def evaluate_return_probability(self, jugador: dict[str, Any]) -> float:
        """Compute return probability factor in [0.3, 1.5].

        Rules:
          +1.30 if minutes > 70% of team total minutes
          +1.20 if Sofascore rating > 7.0
          ×0.70 if prolonged injury in current season
          ×0.50 if rumour of permanent purchase by loan club
        Returns base 1.0 modified by each applicable factor.
        """
        jugador_id = jugador["jugador_id"]
        factor = 1.0

        perf = await self.fetch_loan_performance(jugador_id)

        if perf:
            partidos = int(perf.get("partidos") or 0)
            minutos = int(perf.get("minutos") or 0)
            rating = float(perf.get("rating_medio") or 0.0)
            has_lesion = bool(perf.get("lesion_larga"))

            # Minutes factor: compare to ~90 min × partidos
            if partidos > 0:
                pct_minutos = minutos / (partidos * 90)
                if pct_minutos >= MINUTOS_ALTO_PCT:
                    factor *= FACTOR_MINUTOS_ALTO
                    logger.debug(f"cedidos {jugador_id[:8]}: minutos boost {pct_minutos:.0%}")

            if rating >= 7.0:
                factor *= FACTOR_RATING_ALTO
                logger.debug(f"cedidos {jugador_id[:8]}: rating boost {rating}")

            if has_lesion:
                factor *= FACTOR_LESION
                logger.debug(f"cedidos {jugador_id[:8]}: lesion penalty")

        # Check for "compra definitiva" rumours
        has_compra = await self._has_compra_definitiva_rumour(jugador_id)
        if has_compra:
            factor *= FACTOR_COMPRA_DEFINITIVA
            logger.debug(f"cedidos {jugador_id[:8]}: compra definitiva penalty")

        factor = max(FACTOR_MIN, min(FACTOR_MAX, factor))

        # Compute score_vuelta = normalize factor to [0, 1]
        score_vuelta = min(1.0, (factor - FACTOR_MIN) / (FACTOR_MAX - FACTOR_MIN))

        if score_vuelta > UMBRAL_ALERTA_VUELTA:
            logger.info(
                f"ALERTA cedidos: {jugador.get('nombre_canonico','?')} "
                f"score_vuelta={score_vuelta:.2f} > {UMBRAL_ALERTA_VUELTA}"
            )

        return factor

    async def get_all_cedidos_metrics(self) -> list[dict[str, Any]]:
        """Return all cedidos with their performance and return factor."""
        jugadores = await self.db.execute(
            """SELECT j.*, rc.partidos, rc.minutos, rc.goles, rc.asistencias,
                      rc.rating_medio, rc.club_cesion, rc.temporada, rc.lesion_larga
               FROM jugadores j
               LEFT JOIN rendimiento_cedidos rc ON j.jugador_id = rc.jugador_id
               WHERE j.entidad = 'cedido' AND j.is_active = 1
               ORDER BY rc.rating_medio DESC NULLS LAST"""
        )

        results = []
        for j in jugadores:
            try:
                factor = await self.evaluate_return_probability(j)
                score_vuelta = min(1.0, (factor - FACTOR_MIN) / (FACTOR_MAX - FACTOR_MIN))
                row = dict(j)
                row["factor_vuelta"] = round(factor, 3)
                row["score_vuelta"] = round(score_vuelta, 3)
                results.append(row)
            except Exception as exc:
                logger.error(f"cedidos metrics error {j.get('jugador_id','?')[:8]}: {exc}")

        return results

    async def _has_compra_definitiva_rumour(self, jugador_id: str) -> bool:
        """Check if there's a recent rumour about permanent purchase."""
        try:
            rows = await self.db.execute(
                """SELECT COUNT(*) as n FROM rumores
                   WHERE jugador_id = ?
                     AND retractado = 0
                     AND (LOWER(texto_fragmento) LIKE '%compra definitiva%'
                          OR LOWER(texto_fragmento) LIKE '%opcion de compra%'
                          OR LOWER(texto_fragmento) LIKE '%purchase option%'
                          OR LOWER(texto_fragmento) LIKE '%permanent deal%')
                     AND fecha_publicacion >= datetime('now', '-60 days')""",
                [jugador_id],
            )
            return int((rows[0].get("n") or 0)) > 0 if rows else False
        except Exception:
            return False
