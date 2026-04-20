"""Calibrator — Bayesian update of journalist reliability and lexicon weights.

calibrate_journalists(window_days=90)
    Scans jugadores with recent outcomes and updates Beta-Binomial posteriors
    for every journalist who reported on them.

calibrate_lexicon(window_days=90)
    For lexicon entries with ≥20 observations, adjusts peso_aprendido using
    shrinkage toward the original curated peso_base.
"""

from __future__ import annotations

import json
from typing import Any

from loguru import logger

from fichajes_bot.calibration.reliability_manager import ReliabilityManager
from fichajes_bot.persistence.d1_client import D1Client

# Minimum observations before updating lexicon weight empirically
LEXICON_MIN_OBS = 20
# Maximum divergence before we flag the entry as 'learned'
LEXICON_DRIFT_THRESHOLD = 0.30
# Shrinkage weight toward original curated weight (K pseudo-observations)
LEXICON_SHRINKAGE_K = 20.0


class Calibrator:
    """Orchestrate journalist and lexicon calibration."""

    def __init__(self, db: D1Client, reliability_manager: ReliabilityManager) -> None:
        self.db = db
        self.rm = reliability_manager

    # ── Journalist calibration ────────────────────────────────────────────────

    async def calibrate_journalists(self, window_days: int = 90) -> dict[str, int]:
        """Update journalist reliabilities from outcomes in the last window_days.

        Returns dict {periodista_id: n_updates_applied}.
        """
        # Jugadores with a recent outcome
        jugadores = await self.db.execute(
            """SELECT jugador_id, outcome_clasificado, fecha_outcome,
                      club_actual, tipo_operacion_principal
               FROM jugadores
               WHERE outcome_clasificado IS NOT NULL
                 AND fecha_outcome >= datetime('now', ?)
               ORDER BY fecha_outcome DESC""",
            [f"-{window_days} days"],
        )

        if not jugadores:
            logger.info("Calibrator: no recent outcomes found")
            return {}

        updates_per_journalist: dict[str, int] = {}
        batch: list[dict[str, Any]] = []

        for jug in jugadores:
            jugador_id = jug["jugador_id"]
            outcome = jug["outcome_clasificado"]
            club = jug.get("club_actual")

            # Find all non-retracted rumores for this jugador
            rumores = await self.db.execute(
                """SELECT rumor_id, periodista_id, tipo_operacion, fuente_id
                   FROM rumores
                   WHERE jugador_id = ? AND retractado = 0 AND periodista_id IS NOT NULL""",
                [jugador_id],
            )

            for r in rumores:
                periodista_id = r["periodista_id"]
                tipo = r.get("tipo_operacion")
                rumor_outcome = _rumor_outcome(tipo, outcome)
                if rumor_outcome is None:
                    continue

                batch.append(
                    {
                        "periodista_id": periodista_id,
                        "outcome": rumor_outcome,
                        "context": "rm",
                        "rumor_id": r["rumor_id"],
                        "club": club,
                        "tipo": tipo,
                    }
                )
                updates_per_journalist[periodista_id] = (
                    updates_per_journalist.get(periodista_id, 0) + 1
                )

        if batch:
            await self.rm.batch_update(batch)

        total = sum(updates_per_journalist.values())
        logger.info(
            f"Calibrator.calibrate_journalists: {total} updates across "
            f"{len(updates_per_journalist)} journalists "
            f"(window={window_days}d)"
        )
        for pid, n in sorted(updates_per_journalist.items(), key=lambda x: -x[1])[:10]:
            logger.debug(f"  {pid}: {n} updates")

        return updates_per_journalist

    # ── Lexicon calibration ───────────────────────────────────────────────────

    async def calibrate_lexicon(self, window_days: int = 90) -> int:
        """Update lexicon weights from empirical hit rates.

        Returns number of entries updated.
        """
        # Fetch entries from curated manual lexicon with enough observations
        entries = await self.db.execute(
            """SELECT entry_id, frase, peso_base, n_ocurrencias, n_aciertos,
                      peso_aprendido, origen
               FROM lexicon_entries
               WHERE n_ocurrencias >= ?
               ORDER BY n_ocurrencias DESC""",
            [LEXICON_MIN_OBS],
        )

        if not entries:
            # Also try to update observation counts from the rumores window
            await self._refresh_lexicon_counts(window_days)
            entries = await self.db.execute(
                """SELECT entry_id, frase, peso_base, n_ocurrencias, n_aciertos,
                          peso_aprendido, origen
                   FROM lexicon_entries
                   WHERE n_ocurrencias >= ?""",
                [LEXICON_MIN_OBS],
            )

        updated = 0
        for e in entries:
            n = int(e.get("n_ocurrencias") or 0)
            k = int(e.get("n_aciertos") or 0)
            peso_base = float(e.get("peso_base") or 0.5)
            current_aprendido = e.get("peso_aprendido")
            origen = e.get("origen") or "curado_manual"

            if n < LEXICON_MIN_OBS:
                continue

            hit_rate = k / n
            # Shrinkage toward the curated base weight
            peso_new = (n * hit_rate + LEXICON_SHRINKAGE_K * peso_base) / (
                n + LEXICON_SHRINKAGE_K
            )

            drift = abs(hit_rate - peso_base)
            new_origen = "learned" if drift > LEXICON_DRIFT_THRESHOLD else origen

            if current_aprendido is None or abs(float(current_aprendido) - peso_new) > 0.005:
                await self.db.execute(
                    """UPDATE lexicon_entries
                       SET peso_aprendido = ?, origen = ?, updated_at = datetime('now')
                       WHERE entry_id = ?""",
                    [round(peso_new, 4), new_origen, e["entry_id"]],
                )
                updated += 1
                if new_origen == "learned":
                    logger.info(
                        f"Lexicon drift: '{e['frase']}' "
                        f"base={peso_base:.2f} empirical={hit_rate:.2f} "
                        f"→ adjusted={peso_new:.2f}"
                    )

        logger.info(f"Calibrator.calibrate_lexicon: {updated} entries updated")
        return updated

    async def _refresh_lexicon_counts(self, window_days: int) -> None:
        """Update n_ocurrencias / n_aciertos from rumores in window."""
        # For each lexicon entry, count rumores where it was detected
        # and how many of those ended CONFIRMADO
        try:
            await self.db.execute(
                """UPDATE lexicon_entries
                   SET n_ocurrencias = (
                       SELECT COUNT(*) FROM rumores
                       WHERE lexico_detectado LIKE '%' || lexicon_entries.frase || '%'
                         AND fecha_publicacion >= datetime('now', ?)
                   ),
                   n_aciertos = (
                       SELECT COUNT(*) FROM rumores
                       WHERE lexico_detectado LIKE '%' || lexicon_entries.frase || '%'
                         AND outcome = 'CONFIRMADO'
                         AND fecha_publicacion >= datetime('now', ?)
                   )
                   WHERE origen IN ('curado_manual', 'learned')""",
                [f"-{window_days} days", f"-{window_days} days"],
            )
        except Exception as exc:
            logger.warning(f"Calibrator: could not refresh lexicon counts: {exc}")


# ── Helpers ───────────────────────────────────────────────────────────────────


def _rumor_outcome(tipo_operacion: str | None, jugador_outcome: str) -> str | None:
    """Map (rumor tipo, jugador outcome) → 'CONFIRMADO' | 'FALLIDO' | None.

    None means we cannot determine the outcome (e.g. rumor is about RENOVACION
    but jugador's outcome is a FICHAJE — ambiguous).
    """
    outcome_to_tipo = {
        "FICHAJE_EFECTIVO": "FICHAJE",
        "SALIDA_EFECTIVA": "SALIDA",
        "RENOVACION_EFECTIVA": "RENOVACION",
        "CESION_EFECTIVA": "CESION",
        "OPERACION_CAIDA": None,  # all rumors FALLIDO
    }

    expected_tipo = outcome_to_tipo.get(jugador_outcome)

    if jugador_outcome == "OPERACION_CAIDA":
        return "FALLIDO"

    if expected_tipo is None:
        return None

    if tipo_operacion == expected_tipo:
        return "CONFIRMADO"

    # Opposite type (e.g. SALIDA rumor when player joined) → FALLIDO
    if tipo_operacion in ("FICHAJE", "SALIDA", "RENOVACION", "CESION"):
        return "FALLIDO"

    return None
