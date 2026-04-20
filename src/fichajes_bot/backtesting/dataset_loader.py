"""Load historical dataset for backtesting.

Produces a list of dicts with jugador state + known outcome, ordered by
fecha_outcome ASC so walk-forward splitter can iterate chronologically.
Only includes jugadores with a classified outcome (outcome_clasificado != NULL).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from loguru import logger

from fichajes_bot.persistence.d1_client import D1Client


@dataclass
class BacktestRecord:
    jugador_id: str
    nombre_canonico: str
    tipo_operacion: str
    fecha_outcome: str
    actual_outcome: int          # 1=confirmed, 0=not confirmed
    predicted_score: float       # score_smoothed at prediction time
    periodista_principal: str | None = None
    rumores: list[dict[str, Any]] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


async def load_historical_dataset(db: D1Client) -> list[BacktestRecord]:
    """Return all jugadores with known outcomes, oldest first."""
    rows = await db.execute(
        """SELECT j.jugador_id, j.nombre_canonico, j.tipo_operacion_principal,
                  j.outcome_clasificado, j.fecha_outcome,
                  j.score_smoothed, j.score_raw
           FROM jugadores j
           WHERE j.outcome_clasificado IS NOT NULL
             AND j.fecha_outcome IS NOT NULL
           ORDER BY j.fecha_outcome ASC"""
    )

    if not rows:
        logger.warning("backtesting: no historical records with classified outcomes found")
        return []

    # Also pull from outcomes_historicos for backfill-sourced records
    hist_rows = await db.execute(
        """SELECT oh.jugador_id, oh.outcome_tipo, oh.fecha,
                  j.nombre_canonico, j.tipo_operacion_principal, j.score_smoothed
           FROM outcomes_historicos oh
           JOIN jugadores j ON oh.jugador_id = j.jugador_id
           WHERE oh.fecha IS NOT NULL
           ORDER BY oh.fecha ASC"""
    )

    records: list[BacktestRecord] = []
    seen_ids: set[str] = set()

    # From jugadores outcome_clasificado
    for row in rows:
        jid = row["jugador_id"]
        seen_ids.add(jid)
        outcome_raw = row.get("outcome_clasificado", "PENDIENTE")
        actual = 1 if outcome_raw in ("FICHAJE_EFECTIVO", "SALIDA_EFECTIVA",
                                       "RENOVACION_EFECTIVA", "CESION_EFECTIVA") else 0
        periodista = await _get_principal_periodista(db, jid)
        records.append(BacktestRecord(
            jugador_id=jid,
            nombre_canonico=row["nombre_canonico"],
            tipo_operacion=row.get("tipo_operacion_principal", "FICHAJE"),
            fecha_outcome=row["fecha_outcome"],
            actual_outcome=actual,
            predicted_score=float(row.get("score_smoothed") or 0.0),
            periodista_principal=periodista,
        ))

    # From outcomes_historicos (backfill data, if not already included)
    for row in hist_rows:
        jid = row["jugador_id"]
        if jid in seen_ids:
            continue
        seen_ids.add(jid)
        outcome_tipo = row.get("outcome_tipo", "OPERACION_CAIDA")
        actual = 1 if outcome_tipo != "OPERACION_CAIDA" else 0
        periodista = await _get_principal_periodista(db, jid)
        records.append(BacktestRecord(
            jugador_id=jid,
            nombre_canonico=row["nombre_canonico"],
            tipo_operacion=row.get("tipo_operacion_principal", "FICHAJE"),
            fecha_outcome=row["fecha"],
            actual_outcome=actual,
            predicted_score=float(row.get("score_smoothed") or 0.0),
            periodista_principal=periodista,
        ))

    # Sort by fecha_outcome (walk-forward order)
    records.sort(key=lambda r: r.fecha_outcome)
    logger.info(f"backtesting: loaded {len(records)} historical records with outcomes")
    return records


async def _get_principal_periodista(db: D1Client, jugador_id: str) -> str | None:
    """Get the journalist with the most rumors about this player."""
    rows = await db.execute(
        """SELECT p.nombre_completo, COUNT(r.rumor_id) as n
           FROM rumores r
           JOIN periodistas p ON r.periodista_id = p.periodista_id
           WHERE r.jugador_id = ? AND r.retractado = 0
           GROUP BY r.periodista_id
           ORDER BY n DESC LIMIT 1""",
        [jugador_id],
    )
    if rows:
        return rows[0]["nombre_completo"]
    return None
