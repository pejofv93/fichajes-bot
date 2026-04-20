#!/usr/bin/env python
"""Load historical backfill into D1 and calibrate the system.

Steps:
  1. Load rumores_historicos.jsonl → insert jugadores + rumores into D1
  2. Mark rumores outcomes from the ground-truth data
  3. Update jugadores.outcome_clasificado from transfer outcome
  4. Insert outcomes_historicos records
  5. Run calibrate_journalists() to update journalist reliabilities
  6. Run calibrate_lexicon() to adjust lexicon weights
  7. Print post-backfill reliability report
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import uuid
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from loguru import logger
from fichajes_bot.calibration.calibrator import Calibrator
from fichajes_bot.calibration.reliability_manager import ReliabilityManager
from fichajes_bot.persistence.d1_client import D1Client


BACKFILL_PATH = Path(__file__).parent.parent / "data" / "backfill" / "rumores_historicos.jsonl"


async def _ensure_jugador(db: D1Client, jugador_slug: str, nombre: str,
                           posicion: str | None, edad: int | None,
                           tipo: str, outcome: str) -> str:
    """Upsert a jugador row and return jugador_id."""
    existing = await db.execute(
        "SELECT jugador_id FROM jugadores WHERE slug=? LIMIT 1",
        [jugador_slug],
    )
    if existing:
        return existing[0]["jugador_id"]

    jugador_id = str(uuid.uuid4())
    await db.execute(
        """INSERT OR IGNORE INTO jugadores
           (jugador_id, nombre_canonico, slug, posicion, edad,
            tipo_operacion_principal, entidad, score_raw, score_smoothed,
            is_active, created_at)
           VALUES (?,?,?,?,?,'FICHAJE','primer_equipo',0.0,0.0,1,datetime('now'))""",
        [jugador_id, nombre, jugador_slug, posicion, edad],
    )
    return jugador_id


async def _insert_rumor(db: D1Client, r: dict, jugador_id: str) -> None:
    try:
        await db.execute(
            """INSERT OR IGNORE INTO rumores
               (rumor_id, jugador_id, periodista_id, tipo_operacion, fase_rumor,
                lexico_detectado, peso_lexico, confianza_extraccion, extraido_con,
                club_destino, texto_fragmento, fecha_publicacion, idioma,
                outcome, outcome_at, retractado, created_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,0,datetime('now'))""",
            [
                r["rumor_id"], jugador_id, r["periodista_id"],
                r["tipo_operacion"], r["fase_rumor"],
                r.get("lexico_detectado"), r.get("peso_lexico", 0.0),
                r.get("confianza_extraccion", 0.6),
                r.get("extraido_con", "regex"),
                r.get("club_destino"), r.get("texto_fragmento"),
                r.get("fecha_publicacion"), r.get("idioma", "es"),
                r.get("outcome"), r.get("outcome_at"),
            ],
        )
    except Exception as exc:
        logger.warning(f"Could not insert rumor {r['rumor_id'][:8]}: {exc}")


async def _mark_jugador_outcome(
    db: D1Client, jugador_id: str, outcome: str, fecha: str,
    valor_m: float | None
) -> None:
    await db.execute(
        """UPDATE jugadores SET
             outcome_clasificado = ?,
             fecha_outcome = ?,
             fuente_confirmacion = 'backfill_historico'
           WHERE jugador_id = ? AND outcome_clasificado IS NULL""",
        [outcome, fecha, jugador_id],
    )
    try:
        await db.execute(
            """INSERT OR IGNORE INTO outcomes_historicos
               (outcome_id, jugador_id, outcome_tipo, fecha, valor_traspaso_m,
                fuente_confirmacion)
               VALUES (?,?,?,?,?,'backfill_historico')""",
            [str(uuid.uuid4()), jugador_id, outcome, fecha, valor_m],
        )
    except Exception as exc:
        logger.warning(f"Could not insert outcome for {jugador_id}: {exc}")


async def run() -> None:
    if not BACKFILL_PATH.exists():
        logger.error(f"Backfill file not found: {BACKFILL_PATH}")
        logger.info("Run scripts/generate_backfill.py first")
        return

    lines = BACKFILL_PATH.read_text(encoding="utf-8").strip().splitlines()
    rumores = [json.loads(line) for line in lines if line.strip()]
    logger.info(f"Loading {len(rumores)} historical rumors from backfill")

    async with D1Client() as db:
        # Group by player
        by_player: dict[str, list[dict]] = defaultdict(list)
        for r in rumores:
            by_player[r["jugador_slug"]].append(r)

        jugador_id_map: dict[str, str] = {}
        inserted_rumores = 0

        # 1 & 2. Insert jugadores and rumores
        for slug, player_rumores in by_player.items():
            first = player_rumores[0]
            jugador_id = await _ensure_jugador(
                db=db,
                jugador_slug=slug,
                nombre=first["nombre_canonico"],
                posicion=first.get("_posicion"),
                edad=first.get("_edad"),
                tipo=first["tipo_operacion"],
                outcome=first["_transfer_outcome"],
            )
            jugador_id_map[slug] = jugador_id

            for r in player_rumores:
                await _insert_rumor(db, r, jugador_id)
                inserted_rumores += 1

            # 3. Mark jugador outcome
            first_rumor = player_rumores[0]
            await _mark_jugador_outcome(
                db=db,
                jugador_id=jugador_id,
                outcome=first_rumor["_transfer_outcome"],
                fecha=first_rumor["_transfer_fecha_oficial"],
                valor_m=first_rumor.get("_transfer_valor_m"),
            )

        logger.info(
            f"Backfill loaded: {len(by_player)} jugadores, "
            f"{inserted_rumores} rumores"
        )

        # 4. Calibrate journalists
        rm = ReliabilityManager(db)
        calibrator = Calibrator(db, rm)

        journalist_updates = await calibrator.calibrate_journalists(window_days=3650)
        lexicon_updates = await calibrator.calibrate_lexicon(window_days=3650)

        logger.info(
            f"Calibration done: "
            f"{sum(journalist_updates.values())} journalist updates, "
            f"{lexicon_updates} lexicon updates"
        )

        # 5. Report post-backfill reliabilities
        print("\n" + "=" * 60)
        print("POST-BACKFILL RELIABILITY REPORT")
        print("=" * 60)
        top = await rm.get_top_journalists(n=20, min_observations=3)
        for est in top:
            # Fetch journalist name
            rows = await db.execute(
                "SELECT periodista_id, nombre_completo FROM periodistas "
                "LIMIT 50"
            )
            pid_to_name = {r["periodista_id"]: r["nombre_completo"] for r in rows}
            break

        journalists_data = await db.execute(
            """SELECT periodista_id, nombre_completo, reliability_global,
                      n_predicciones_global, n_aciertos_global,
                      reliability_rm, n_predicciones_rm, n_aciertos_rm
               FROM periodistas
               WHERE n_predicciones_global > 0
               ORDER BY reliability_global DESC LIMIT 20"""
        )
        for r in journalists_data:
            global_r = r.get("reliability_global") or 0.0
            rm_r = r.get("reliability_rm") or 0.0
            n_g = r.get("n_predicciones_global") or 0
            n_rm = r.get("n_predicciones_rm") or 0
            print(
                f"{r['nombre_completo']:<30} "
                f"global={global_r:.2f} (n={n_g:3d})  "
                f"rm={rm_r:.2f} (n={n_rm:3d})"
            )
        print("=" * 60)


def main() -> None:
    asyncio.run(run())


if __name__ == "__main__":
    main()
