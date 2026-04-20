"""ThreeWayCanteraScorer — 3-way probability scoring for cantera players.

For each canterano generates three independent scores:
  score_primer_equipo  — probability of promotion / debut in first team
  score_castilla_stays — probability of staying in Castilla
  score_salida_o_cesion — probability of leaving (loan or sale)

The three scores approximately sum to 1.0 (not exactly — residual captures uncertainty).
"""

from __future__ import annotations

import json
from typing import Any

from loguru import logger

from fichajes_bot.persistence.d1_client import D1Client

# ── Normalization target ──────────────────────────────────────────────────────

_TARGET_SUM = 1.0
_UNCERTAINTY_BUDGET = 0.05   # allowed deviation from 1.0

# ── Prior weights for each outcome ───────────────────────────────────────────
# Based on historical base rates for Real Madrid cantero pool

_PRIOR_PRIMER = 0.10
_PRIOR_STAYS = 0.55
_PRIOR_SALIDA = 0.35


class ThreeWayCanteraScorer:
    """Compute 3-way cantera scores from jugador data and rumores."""

    def __init__(self, db: D1Client) -> None:
        self.db = db

    async def score(self, jugador_id: str) -> dict[str, float] | None:
        """Compute 3-way scores for a single canterano.

        Returns dict with keys:
            score_primer_equipo, score_castilla_stays, score_salida_o_cesion, sum_check
        or None if insufficient data.
        """
        rows = await self.db.execute(
            "SELECT * FROM jugadores WHERE jugador_id = ? LIMIT 1", [jugador_id]
        )
        if not rows:
            logger.warning(f"3way: jugador not found {jugador_id[:8]}")
            return None

        jugador = rows[0]
        entidad = jugador.get("entidad_actual") or jugador.get("entidad") or "castilla"

        rumores = await self.db.execute(
            """SELECT r.*, p.reliability_global
               FROM rumores r
               LEFT JOIN periodistas p ON r.periodista_id = p.periodista_id
               WHERE r.jugador_id = ?
                 AND r.retractado = 0
                 AND (r.fecha_publicacion IS NULL
                      OR r.fecha_publicacion >= datetime('now', '-60 days'))
               ORDER BY r.fecha_publicacion DESC""",
            [jugador_id],
        )

        factores = json.loads(jugador.get("factores_actuales") or "{}")

        f_minutos = await self._factor_minutos_castilla(jugador_id, entidad)
        f_rotacion = await self._factor_rotacion_primer_equipo()
        f_contrato = self._factor_contrato_vencimiento(jugador)

        primer = self._score_primer_equipo(jugador, rumores, factores, f_minutos, f_rotacion, f_contrato)
        salida = self._score_salida(jugador, rumores, factores, f_contrato)
        stays = max(0.0, 1.0 - primer - salida + _UNCERTAINTY_BUDGET)

        # Normalise so they approximately sum to 1
        total = primer + stays + salida
        if total > 0:
            primer = round(primer / total, 4)
            stays = round(stays / total, 4)
            salida = round(1.0 - primer - stays, 4)

        result = {
            "score_primer_equipo":   max(0.0, min(1.0, primer)),
            "score_castilla_stays":  max(0.0, min(1.0, stays)),
            "score_salida_o_cesion": max(0.0, min(1.0, salida)),
            "sum_check":             round(primer + stays + salida, 4),
        }

        logger.debug(
            f"3way {jugador.get('nombre_canonico','?')[:20]}: "
            f"primer={result['score_primer_equipo']:.2f} "
            f"stays={result['score_castilla_stays']:.2f} "
            f"salida={result['score_salida_o_cesion']:.2f}"
        )
        return result

    async def score_batch(self, entidad: str | None = None) -> list[dict[str, Any]]:
        """Score all canteranos (optionally filtered by entidad)."""
        where = "AND entidad_actual = ?" if entidad else ""
        params = [entidad] if entidad else []

        jugadores = await self.db.execute(
            f"""SELECT jugador_id FROM jugadores
                WHERE (entidad = 'castilla' OR entidad = 'juvenil_a'
                       OR entidad_actual IN ('castilla', 'juvenil_a'))
                  AND is_active = 1
                  {where}""",
            params,
        )

        results = []
        for j in jugadores:
            jid = j["jugador_id"]
            scores = await self.score(jid)
            if scores:
                scores["jugador_id"] = jid
                results.append(scores)

        return results

    # ── Component builders ────────────────────────────────────────────────────

    def _score_primer_equipo(
        self,
        jugador: dict,
        rumores: list[dict],
        factores: dict,
        f_minutos: float,
        f_rotacion: float,
        f_contrato: float,
    ) -> float:
        base = _PRIOR_PRIMER

        # Current score is the primary signal for promotion potential
        score_actual = float(jugador.get("score_smoothed") or 0.0)
        base += score_actual * 0.80

        # Promotion-specific rumour signals
        promo_count = sum(
            1 for r in rumores
            if (r.get("tipo_operacion") or "").upper() in ("PROMOCION", "DEBUT", "CONVOCATORIA")
        )
        base += promo_count * 0.06

        # Modifiers: minutos and rotation are multiplicative
        base = min(0.98, base * f_minutos * f_rotacion)
        base += f_contrato * 0.05

        return max(0.0, min(0.98, base))

    def _score_salida(
        self,
        jugador: dict,
        rumores: list[dict],
        factores: dict,
        f_contrato: float,
    ) -> float:
        base = _PRIOR_SALIDA

        # Salida/cesion signals from rumores
        salida_count = sum(
            1 for r in rumores
            if (r.get("tipo_operacion") or "").upper() in ("SALIDA", "CESION", "TRASPASO")
        )
        base += salida_count * 0.07

        # Age factor — older canteranos more likely to leave
        edad = jugador.get("edad") or 20
        if edad >= 22:
            base += 0.10
        elif edad >= 20:
            base += 0.05

        # Contract ending → more likely to leave
        base += f_contrato * 0.10

        # Existing score_smoothed towards SALIDA amplifies salida probability
        tipo_principal = (jugador.get("tipo_operacion_principal") or "").upper()
        if tipo_principal == "SALIDA":
            base += float(jugador.get("score_smoothed") or 0.0) * 0.30

        # High-scoring player in castilla → suppress salida (they'll be promoted, not sold)
        score_actual = float(jugador.get("score_smoothed") or 0.0)
        if score_actual > 0.80 and tipo_principal != "SALIDA":
            base *= 0.55

        return max(0.0, min(0.98, base))

    async def _factor_minutos_castilla(self, jugador_id: str, entidad: str) -> float:
        """Boost for primer_equipo if player is getting minutes at Castilla."""
        if entidad not in ("castilla", "primer_equipo"):
            return 1.0

        try:
            row = await self.db.execute(
                """SELECT minutos_castilla_temporada FROM jugadores
                   WHERE jugador_id = ? LIMIT 1""",
                [jugador_id],
            )
            if not row:
                return 1.0
            minutos = float(row[0].get("minutos_castilla_temporada") or 0)
            # ~30 matches × 90 min = 2700 total possible
            if minutos > 1800:
                return 1.4
            if minutos > 900:
                return 1.2
            return 1.0
        except Exception:
            return 1.0

    async def _factor_rotacion_primer_equipo(self) -> float:
        """Boost if primer equipo is rotating heavily (many injuries / cup squad)."""
        try:
            rows = await self.db.execute(
                """SELECT COUNT(*) as n FROM jugadores
                   WHERE entidad = 'primer_equipo'
                     AND tipo_operacion_principal = 'SALIDA'
                     AND score_smoothed >= 0.50
                     AND is_active = 1"""
            )
            n_salidas = int((rows[0].get("n") or 0)) if rows else 0
            if n_salidas >= 3:
                return 1.3
            if n_salidas >= 1:
                return 1.1
            return 1.0
        except Exception:
            return 1.0

    def _factor_contrato_vencimiento(self, jugador: dict) -> float:
        """Factor for contract ending soon — boosts both primer and salida."""
        contrato_hasta = jugador.get("contrato_hasta") or ""
        if not contrato_hasta:
            return 0.0

        try:
            from datetime import datetime, timezone
            expiry = datetime.fromisoformat(str(contrato_hasta)[:10])
            expiry = expiry.replace(tzinfo=timezone.utc)
            now = datetime.now(timezone.utc)
            days_left = (expiry - now).days

            if days_left <= 180:
                return 1.0
            if days_left <= 365:
                return 0.5
            return 0.0
        except Exception:
            return 0.0
