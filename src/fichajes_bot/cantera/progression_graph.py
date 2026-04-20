"""ProgressionGraph — hierarchy: Juvenil A → Castilla → Primer equipo.

Side branches: cesión, salida.

When a player promotes, a vacancy opens in the origin entity which boosts
scores for remaining candidates. Integrates with SubstitutionEngine.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

import uuid
from loguru import logger

from fichajes_bot.persistence.d1_client import D1Client

# ── Entity hierarchy ──────────────────────────────────────────────────────────

ENTITY_LEVELS = {
    "juvenil_a":    1,
    "castilla":     2,
    "primer_equipo": 3,
}

# Boost applied to remaining players in source entity when a vacancy opens
VACANCY_BOOST = 0.08


class ProgressionGraph:
    """Manages hierarchical progression between cantera entities."""

    def __init__(self, db: D1Client) -> None:
        self.db = db

    def build(self) -> dict[str, list[str]]:
        """Return static progression graph as adjacency dict."""
        return {
            "juvenil_a": ["castilla", "cesion", "salida"],
            "castilla": ["primer_equipo", "cesion", "salida"],
            "primer_equipo": ["salida"],
        }

    async def propagate_on_promotion(
        self,
        jugador_id: str,
        from_entity: str,
        to_entity: str,
    ) -> list[str]:
        """Handle promotion event: record it and boost remaining candidates.

        Returns list of jugador_ids whose scores were boosted.
        """
        from_level = ENTITY_LEVELS.get(from_entity, 0)
        to_level = ENTITY_LEVELS.get(to_entity, 0)

        if to_level <= from_level and to_entity not in ("cesion", "salida"):
            logger.warning(f"progression: not an upward move {from_entity} → {to_entity}")

        await self._record_progression(jugador_id, from_entity, to_entity)
        await self._update_player_entity(jugador_id, to_entity)

        boosted = await self._boost_vacancy_candidates(from_entity, jugador_id)

        logger.info(
            f"progression: {jugador_id[:8]} {from_entity} → {to_entity}; "
            f"boosted {len(boosted)} players"
        )
        return boosted

    async def get_progression_history(
        self, jugador_id: str
    ) -> list[dict[str, Any]]:
        """Return full progression history for a player."""
        try:
            return await self.db.execute(
                """SELECT * FROM progresiones_historicas
                   WHERE jugador_id = ?
                   ORDER BY fecha DESC""",
                [jugador_id],
            )
        except Exception:
            return []

    # ── Internal helpers ──────────────────────────────────────────────────────

    async def _record_progression(
        self, jugador_id: str, from_entity: str, to_entity: str
    ) -> None:
        try:
            await self.db.execute(
                """INSERT INTO progresiones_historicas
                   (progresion_id, jugador_id, from_entity, to_entity, fecha, tipo)
                   VALUES (?, ?, ?, ?, date('now'), ?)""",
                [
                    str(uuid.uuid4()),
                    jugador_id,
                    from_entity,
                    to_entity,
                    "PROMOCION" if ENTITY_LEVELS.get(to_entity, 0) > ENTITY_LEVELS.get(from_entity, 0) else "CESION_O_SALIDA",
                ],
            )
        except Exception as exc:
            logger.error(f"progression record error: {exc}")

    async def _update_player_entity(self, jugador_id: str, new_entity: str) -> None:
        try:
            await self.db.execute(
                """UPDATE jugadores
                   SET entidad_actual = ?,
                       ultima_actualizacion_at = datetime('now')
                   WHERE jugador_id = ?""",
                [new_entity, jugador_id],
            )
        except Exception as exc:
            logger.error(f"progression entity update error: {exc}")

    async def _boost_vacancy_candidates(
        self, entity: str, promoted_jugador_id: str
    ) -> list[str]:
        """Boost score_smoothed for top candidates in the vacated entity."""
        try:
            candidates = await self.db.execute(
                """SELECT jugador_id, score_smoothed, factores_actuales
                   FROM jugadores
                   WHERE (entidad = ? OR entidad_actual = ?)
                     AND jugador_id != ?
                     AND is_active = 1
                   ORDER BY score_smoothed DESC LIMIT 5""",
                [entity, entity, promoted_jugador_id],
            )
        except Exception:
            return []

        boosted = []
        for c in candidates:
            jid = c["jugador_id"]
            new_score = min(0.99, float(c["score_smoothed"] or 0.0) + VACANCY_BOOST)
            factores = json.loads(c.get("factores_actuales") or "{}")
            factores["vacancy_boost"] = round(VACANCY_BOOST, 4)
            factores["vacancy_from"] = promoted_jugador_id[:8]

            try:
                await self.db.execute(
                    """UPDATE jugadores
                       SET score_smoothed = ?,
                           factores_actuales = ?,
                           ultima_actualizacion_at = datetime('now')
                       WHERE jugador_id = ?""",
                    [round(new_score, 6), json.dumps(factores), jid],
                )
                boosted.append(jid)
            except Exception as exc:
                logger.error(f"vacancy boost error {jid[:8]}: {exc}")

        return boosted
