"""score_cantera — CLI for 3-way cantera scoring.

Usage:
    python -m fichajes_bot.jobs.score_cantera [--entity castilla|juvenil_a|cedidos|all]

Recalculates 3-way scoring for all canterano entities.
Designed to run in cold-loop after `score --full`.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys

from loguru import logger

from fichajes_bot.cantera.cedidos_tracker import CedidosTracker
from fichajes_bot.cantera.debut_watch import DebutWatchDetector
from fichajes_bot.cantera.scoring_3way import ThreeWayCanteraScorer
from fichajes_bot.persistence.d1_client import D1Client


async def run(entity: str) -> None:
    db = D1Client()

    try:
        scorer = ThreeWayCanteraScorer(db)
        cedidos_tracker = CedidosTracker(db)
        debut_detector = DebutWatchDetector(db)

        entities_to_run = (
            ["castilla", "juvenil_a", "cedidos"]
            if entity == "all"
            else [entity]
        )

        total_scored = 0
        alerts_fired = 0

        for ent in entities_to_run:
            logger.info(f"score_cantera: processing entity={ent}")

            if ent == "cedidos":
                cedidos = await cedidos_tracker.get_all_cedidos_metrics()
                logger.info(f"score_cantera: cedidos={len(cedidos)} tracked")
                total_scored += len(cedidos)
            else:
                results = await scorer.score_batch(entidad=ent)
                logger.info(f"score_cantera: {ent} → {len(results)} jugadores scored")
                total_scored += len(results)

                # Persist 3-way scores into factores_actuales
                for r in results:
                    jid = r["jugador_id"]
                    try:
                        rows = await db.execute(
                            "SELECT factores_actuales FROM jugadores WHERE jugador_id=? LIMIT 1",
                            [jid],
                        )
                        factores = json.loads((rows[0].get("factores_actuales") or "{}")) if rows else {}
                        factores.update({
                            "score_primer_equipo":   r["score_primer_equipo"],
                            "score_castilla_stays":  r["score_castilla_stays"],
                            "score_salida_o_cesion": r["score_salida_o_cesion"],
                        })
                        await db.execute(
                            """UPDATE jugadores
                               SET factores_actuales = ?,
                                   ultima_actualizacion_at = datetime('now')
                               WHERE jugador_id = ?""",
                            [json.dumps(factores), jid],
                        )
                    except Exception as exc:
                        logger.error(f"persist 3way {jid[:8]}: {exc}")

        # Debut watch alerts
        if entity in ("all", "castilla", "juvenil_a"):
            debut_alerts = await debut_detector.check_debut_watch_alerts()
            alerts_fired = len(debut_alerts)
            for alert in debut_alerts:
                logger.info(
                    f"🎯 DEBUT WATCH ALERT: {alert['nombre_canonico']} "
                    f"score_primer={alert['score_primer_equipo']:.2f} "
                    f"+{alert['rise']:.2f} en 7d"
                )

        logger.info(
            f"score_cantera done: entity={entity} scored={total_scored} "
            f"debut_alerts={alerts_fired}"
        )

        # Record metric
        try:
            await db.execute(
                """INSERT OR REPLACE INTO metricas_sistema (metric_name, value, timestamp)
                   VALUES ('last_cantera_score_at', datetime('now'), datetime('now'))"""
            )
        except Exception:
            pass

    finally:
        await db.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Cantera 3-way scoring")
    parser.add_argument(
        "--entity",
        choices=["castilla", "juvenil_a", "cedidos", "all"],
        default="all",
        help="Entity to score (default: all)",
    )
    args = parser.parse_args()

    logger.remove()
    logger.add(sys.stderr, level="INFO", format="{time:HH:mm:ss} | {level} | {message}")

    asyncio.run(run(args.entity))


if __name__ == "__main__":
    main()
