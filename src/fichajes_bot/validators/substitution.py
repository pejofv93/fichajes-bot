"""SubstitutionEngine — position graph for transfer viability.

Evaluates whether a position is oversupplied, undersupplied, or has
an imminent vacancy due to a player leaving.

Factor table:
  1.3  salida_inminente: player in that position has SALIDA score >= 0.6
  1.0  hueco_natural: few rivals in that position, no imminent signing
  0.6  posicion_saturada: >= MAX_CANDIDATES_SATURADA rivals, no imminent departure
  0.4  fichaje_avanzado: a more-advanced rival (fase >= 4) with higher score exists
"""

from __future__ import annotations

from loguru import logger

from fichajes_bot.persistence.d1_client import D1Client

FACTOR_SALIDA_INMINENTE = 1.30
FACTOR_HUECO_NATURAL    = 1.00
FACTOR_SATURADA         = 0.60
FACTOR_FICHAJE_AVANZADO = 0.40

SALIDA_SCORE_THRESHOLD  = 0.60  # score at or above which a SALIDA is "imminent"
FICHAJE_AVANZADO_FASE   = 4     # fase >= this + higher score → "more advanced rival"
MAX_CANDIDATES_SATURADA = 4     # >= this many rivals → saturated position


class SubstitutionEngine:
    """Builds and queries a position-level graph for substitution analysis."""

    def __init__(self, db: D1Client) -> None:
        self.db = db
        self._graph: dict | None = None
        self._eval_cache: dict[str, float] = {}

    async def build_graph(self) -> dict:
        """Build position-level graph from current jugadores state.

        Returns:
            {posicion: {"salidas": [...], "fichajes": [...]}}
        """
        salidas = await self.db.execute(
            """SELECT jugador_id, posicion, score_smoothed
               FROM jugadores
               WHERE tipo_operacion_principal = 'SALIDA'
                 AND is_active = 1
                 AND posicion IS NOT NULL"""
        )
        fichajes = await self.db.execute(
            """SELECT jugador_id, posicion, score_smoothed, fase_dominante
               FROM jugadores
               WHERE tipo_operacion_principal = 'FICHAJE'
                 AND is_active = 1
                 AND posicion IS NOT NULL"""
        )

        graph: dict = {}
        for row in salidas:
            pos = row["posicion"]
            if pos not in graph:
                graph[pos] = {"salidas": [], "fichajes": []}
            graph[pos]["salidas"].append(dict(row))

        for row in fichajes:
            pos = row["posicion"]
            if pos not in graph:
                graph[pos] = {"salidas": [], "fichajes": []}
            graph[pos]["fichajes"].append(dict(row))

        self._graph = graph
        logger.debug(f"SubstitutionEngine.build_graph: {len(graph)} positions indexed")
        return graph

    async def evaluate(self, jugador_id: str) -> float:
        """Return substitution factor for a potential signing.

        Checks (in priority order):
          1. Is there a more advanced rival at the same position?
          2. Is there an imminent departure at that position?
          3. Is the position oversaturated with candidates?
          4. Default: natural gap (neutral).
        """
        if jugador_id in self._eval_cache:
            return self._eval_cache[jugador_id]

        if self._graph is None:
            await self.build_graph()

        rows = await self.db.execute(
            "SELECT posicion, score_smoothed, fase_dominante FROM jugadores "
            "WHERE jugador_id=? LIMIT 1",
            [jugador_id],
        )
        if not rows:
            return FACTOR_HUECO_NATURAL

        jugador = rows[0]
        posicion = jugador.get("posicion")

        if not posicion or posicion not in self._graph:
            return FACTOR_HUECO_NATURAL

        pos_data = self._graph[posicion]
        rivals = [
            f for f in pos_data.get("fichajes", [])
            if f["jugador_id"] != jugador_id
        ]
        salidas = pos_data.get("salidas", [])

        jugador_score = float(jugador.get("score_smoothed") or 0.0)
        jugador_fase  = int(jugador.get("fase_dominante") or 1)

        # Priority 1: more-advanced rival
        for rival in rivals:
            rival_score = float(rival.get("score_smoothed") or 0.0)
            rival_fase  = int(rival.get("fase_dominante") or 1)
            if rival_fase >= FICHAJE_AVANZADO_FASE and rival_score > jugador_score:
                logger.debug(
                    f"SubstitutionEngine: {jugador_id[:8]} pos={posicion} "
                    f"→ FICHAJE_AVANZADO (rival fase={rival_fase} score={rival_score:.2f})"
                )
                self._eval_cache[jugador_id] = FACTOR_FICHAJE_AVANZADO
                return FACTOR_FICHAJE_AVANZADO

        # Priority 2: imminent departure frees up the slot
        imminent = [
            s for s in salidas
            if float(s.get("score_smoothed") or 0.0) >= SALIDA_SCORE_THRESHOLD
        ]
        if imminent:
            logger.debug(
                f"SubstitutionEngine: {jugador_id[:8]} pos={posicion} "
                f"→ SALIDA_INMINENTE ({len(imminent)} high-score departures)"
            )
            self._eval_cache[jugador_id] = FACTOR_SALIDA_INMINENTE
            return FACTOR_SALIDA_INMINENTE

        # Priority 3: position saturation
        if len(rivals) >= MAX_CANDIDATES_SATURADA:
            logger.debug(
                f"SubstitutionEngine: {jugador_id[:8]} pos={posicion} "
                f"→ SATURADA ({len(rivals)} rivals)"
            )
            self._eval_cache[jugador_id] = FACTOR_SATURADA
            return FACTOR_SATURADA

        # Default: natural gap
        logger.debug(
            f"SubstitutionEngine: {jugador_id[:8]} pos={posicion} "
            f"→ HUECO_NATURAL ({len(rivals)} rivals)"
        )
        self._eval_cache[jugador_id] = FACTOR_HUECO_NATURAL
        return FACTOR_HUECO_NATURAL

    async def propagate_on_signing(self, jugador_fichado_id: str) -> None:
        """When a player is signed, reduce scores of alternatives at same position."""
        rows = await self.db.execute(
            "SELECT posicion FROM jugadores WHERE jugador_id=? LIMIT 1",
            [jugador_fichado_id],
        )
        if not rows or not rows[0].get("posicion"):
            return

        posicion = rows[0]["posicion"]

        alternatives = await self.db.execute(
            """SELECT jugador_id, score_smoothed FROM jugadores
               WHERE posicion = ?
                 AND tipo_operacion_principal = 'FICHAJE'
                 AND jugador_id != ?
                 AND is_active = 1""",
            [posicion, jugador_fichado_id],
        )

        for alt in alternatives:
            alt_id = alt["jugador_id"]
            new_score = max(0.01, float(alt.get("score_smoothed") or 0.0) * 0.60)
            await self.db.execute(
                """UPDATE jugadores
                   SET score_smoothed = ?, score_raw = ?,
                       ultima_actualizacion_at = datetime('now')
                   WHERE jugador_id = ?""",
                [round(new_score, 6), round(new_score, 6), alt_id],
            )
            logger.info(
                f"SubstitutionEngine.propagate_on_signing: {alt_id[:8]} "
                f"score×0.6 (rival signed at pos={posicion})"
            )

        # Invalidate caches
        self._graph = None
        self._eval_cache.clear()

    async def propagate_on_sale(self, jugador_vendido_id: str) -> None:
        """When a player leaves, boost FICHAJE candidates at same position."""
        rows = await self.db.execute(
            "SELECT posicion FROM jugadores WHERE jugador_id=? LIMIT 1",
            [jugador_vendido_id],
        )
        if not rows or not rows[0].get("posicion"):
            return

        posicion = rows[0]["posicion"]

        candidates = await self.db.execute(
            """SELECT jugador_id, score_smoothed FROM jugadores
               WHERE posicion = ?
                 AND tipo_operacion_principal = 'FICHAJE'
                 AND is_active = 1""",
            [posicion],
        )

        for cand in candidates:
            cand_id = cand["jugador_id"]
            new_score = min(0.99, float(cand.get("score_smoothed") or 0.0) * 1.30)
            await self.db.execute(
                """UPDATE jugadores
                   SET score_smoothed = ?,
                       ultima_actualizacion_at = datetime('now')
                   WHERE jugador_id = ?""",
                [round(new_score, 6), cand_id],
            )
            logger.info(
                f"SubstitutionEngine.propagate_on_sale: {cand_id[:8]} "
                f"score×1.3 (vacancy at pos={posicion})"
            )

        # Invalidate caches
        self._graph = None
        self._eval_cache.clear()
