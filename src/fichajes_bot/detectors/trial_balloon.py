"""TrialBalloonDetector — identifies rumores that may be deliberate test balloons.

A "globo sonda" (trial balloon) is a rumor deliberately leaked by an agent,
club, or player's entourage to gauge market reaction — not a genuine transfer tip.

Seven heuristics, each contributes a weight to probability in [0, 1]:
  a) single_source          +0.25  Only 1 journalist in >48h window
  b) agent_adjacent         +0.20  All sources are tier B/C (tabloid/clickbait)
  c) price_inflation        +0.15  Transfer fee figures rising >30% in <7d
  d) suspicious_timing      +0.15  Another very advanced signing competes for attention
  e) no_geo_corroboration   +0.10  Only pro-RM media; no neutral/international source
  f) retraction_pattern     +0.10  Player has prior retracted rumors in last 90d
  g) unusually_specific     +0.05  High-certainty phrases from non-tier-S source

If sum >= GLOBO_THRESHOLD (0.50): flag POSIBLE_GLOBO_SONDA on the jugador.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone
from typing import Optional

from loguru import logger

from fichajes_bot.persistence.d1_client import D1Client

HEURISTIC_WEIGHTS: dict[str, float] = {
    "single_source":           0.25,
    "agent_adjacent":          0.20,
    "price_inflation":         0.15,
    "suspicious_timing":       0.15,
    "no_geo_corroboration":    0.10,
    "retraction_pattern":      0.10,
    "unusually_specific":      0.05,
}

GLOBO_THRESHOLD = 0.50
_SINGLE_SOURCE_HOURS = 48
_PRICE_INFLATION_RATIO = 1.30
_PRICE_INFLATION_DAYS  = 7
_SUSPICIOUS_SCORE_THRESHOLD = 0.80   # another jugador is "very advanced"

_SPECIFIC_PHRASES = [
    "acuerdo alcanzado",
    "acuerdo total",
    "100 millones",
    "aquí está",
    "firmará",
    "cifra acordada",
    "médico superado",
    "here we go",
]


class TrialBalloonDetector:
    """Evaluates whether a set of rumors looks like a deliberate trial balloon."""

    def __init__(self, db: D1Client) -> None:
        self.db = db

    async def evaluate(
        self,
        jugador_id: str,
        rumores_recientes: list[dict],
    ) -> tuple[float, list[str]]:
        """Return (probabilidad_globo, heuristicas_activadas).

        Caller should pass all active rumores for this player (non-retracted,
        last 7 days). The detector checks each heuristic independently.
        """
        if not rumores_recientes:
            return 0.0, []

        activated: list[str] = []

        if await self._single_source(rumores_recientes):
            activated.append("single_source")

        if await self._agent_adjacent(rumores_recientes):
            activated.append("agent_adjacent")

        if self._price_inflation(rumores_recientes):
            activated.append("price_inflation")

        if await self._suspicious_timing(jugador_id):
            activated.append("suspicious_timing")

        if await self._no_geo_corroboration(rumores_recientes):
            activated.append("no_geo_corroboration")

        if await self._retraction_pattern(jugador_id):
            activated.append("retraction_pattern")

        if await self._unusually_specific(rumores_recientes):
            activated.append("unusually_specific")

        prob = min(1.0, sum(HEURISTIC_WEIGHTS[h] for h in activated))

        if prob >= GLOBO_THRESHOLD:
            await self._flag_globo_sonda(jugador_id)

        logger.debug(
            f"TrialBalloon: {jugador_id[:8]} prob={prob:.2f} "
            f"heuristics={activated}"
        )
        return prob, activated

    # ── Heuristic (a) — single source ────────────────────────────────────────

    async def _single_source(self, rumores: list[dict]) -> bool:
        """Only 1 journalist reported in the last 48h window."""
        cutoff = (
            datetime.now(timezone.utc) - timedelta(hours=_SINGLE_SOURCE_HOURS)
        ).isoformat()

        recent = [
            r for r in rumores
            if (r.get("fecha_publicacion") or "") >= cutoff
        ]
        if not recent:
            recent = rumores  # fallback: use all if dates missing

        distinct = {r.get("periodista_id") for r in recent if r.get("periodista_id")}
        return len(distinct) <= 1

    # ── Heuristic (b) — agent adjacent ───────────────────────────────────────

    async def _agent_adjacent(self, rumores: list[dict]) -> bool:
        """All source fuentes are tier B or C (no high-quality corroboration)."""
        fuente_ids = list({r.get("fuente_id") for r in rumores if r.get("fuente_id")})
        if not fuente_ids:
            return False

        placeholders = ",".join("?" * len(fuente_ids))
        rows = await self.db.execute(
            f"SELECT tier FROM fuentes WHERE fuente_id IN ({placeholders})",
            fuente_ids,
        )
        if not rows:
            return False
        return all(row["tier"] in ("B", "C") for row in rows)

    # ── Heuristic (c) — price inflation ──────────────────────────────────────

    def _price_inflation(self, rumores: list[dict]) -> bool:
        """Transfer fee figures mentioned are rising >30% across recent rumors."""
        cutoff = datetime.now(timezone.utc) - timedelta(days=_PRICE_INFLATION_DAYS)
        cutoff_str = cutoff.isoformat()

        prices: list[float] = []
        for r in rumores:
            texto = (r.get("texto_fragmento") or "").lower()
            # Match patterns like "45M", "45 millones", "45 mill"
            matches = re.findall(r"(\d+(?:[.,]\d+)?)\s*(?:m(?:ill(?:ones?)?)?€?|€m)", texto)
            for m in matches:
                try:
                    prices.append(float(m.replace(",", ".")))
                except ValueError:
                    pass

        if len(prices) < 2:
            return False

        return max(prices) > min(prices) * _PRICE_INFLATION_RATIO

    # ── Heuristic (d) — suspicious timing ────────────────────────────────────

    async def _suspicious_timing(self, jugador_id: str) -> bool:
        """Another jugador is very close to signing (score > threshold)."""
        rows = await self.db.execute(
            """SELECT COUNT(*) as n FROM jugadores
               WHERE score_smoothed >= ? AND is_active = 1
                 AND jugador_id != ?
                 AND tipo_operacion_principal = 'FICHAJE'""",
            [_SUSPICIOUS_SCORE_THRESHOLD, jugador_id],
        )
        return bool(rows and rows[0]["n"] > 0)

    # ── Heuristic (e) — no geographic corroboration ───────────────────────────

    async def _no_geo_corroboration(self, rumores: list[dict]) -> bool:
        """All sources carry a directional bias; no neutral/international media."""
        fuente_ids = list({r.get("fuente_id") for r in rumores if r.get("fuente_id")})
        if not fuente_ids:
            return False

        placeholders = ",".join("?" * len(fuente_ids))
        rows = await self.db.execute(
            f"SELECT sesgo FROM fuentes WHERE fuente_id IN ({placeholders})",
            fuente_ids,
        )
        if not rows:
            return False
        return all(row["sesgo"] not in ("neutral", "oficial") for row in rows)

    # ── Heuristic (f) — retraction pattern ───────────────────────────────────

    async def _retraction_pattern(self, jugador_id: str) -> bool:
        """Player has had at least one retracted rumor in the last 90 days."""
        rows = await self.db.execute(
            """SELECT COUNT(*) as n FROM retractaciones
               WHERE jugador_id = ?
                 AND (fecha_retractacion IS NULL
                      OR fecha_retractacion >= datetime('now', '-90 days'))""",
            [jugador_id],
        )
        return bool(rows and rows[0]["n"] > 0)

    # ── Heuristic (g) — unusually specific ───────────────────────────────────

    async def _unusually_specific(self, rumores: list[dict]) -> bool:
        """High-certainty claim from a non-tier-S journalist."""
        has_specific = any(
            any(phrase in (r.get("texto_fragmento") or "").lower()
                for phrase in _SPECIFIC_PHRASES)
            for r in rumores
        )
        if not has_specific:
            return False

        periodista_ids = list(
            {r.get("periodista_id") for r in rumores if r.get("periodista_id")}
        )
        if not periodista_ids:
            return True  # specific claim, no identified journalist → suspicious

        placeholders = ",".join("?" * len(periodista_ids))
        rows = await self.db.execute(
            f"SELECT tier FROM periodistas WHERE periodista_id IN ({placeholders})",
            periodista_ids,
        )
        return not any(row["tier"] == "S" for row in rows)

    # ── Flag management ───────────────────────────────────────────────────────

    async def _flag_globo_sonda(self, jugador_id: str) -> None:
        """Add POSIBLE_GLOBO_SONDA to the player's flags."""
        rows = await self.db.execute(
            "SELECT flags FROM jugadores WHERE jugador_id=? LIMIT 1",
            [jugador_id],
        )
        if not rows:
            return
        try:
            flags: list = json.loads(rows[0]["flags"] or "[]")
        except Exception:
            flags = []

        if "POSIBLE_GLOBO_SONDA" not in flags:
            flags.append("POSIBLE_GLOBO_SONDA")
            await self.db.execute(
                "UPDATE jugadores SET flags=? WHERE jugador_id=?",
                [json.dumps(flags), jugador_id],
            )
            logger.info(f"TrialBalloon: POSIBLE_GLOBO_SONDA flag set on {jugador_id[:8]}")
