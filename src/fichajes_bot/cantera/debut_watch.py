"""DebutWatchDetector — identifies canteranos closest to first-team debut.

Signals:
  - Convocatoria en partido primer equipo (scraping / rumores)
  - Entrenamientos con primer equipo (rumores específicos)
  - Injuries at the canterano's position creating opportunity

Generates 🎯 DEBUT WATCH alert if score_primer_equipo rises > 0.20 in one week.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from loguru import logger

from fichajes_bot.persistence.d1_client import D1Client

# ── Constants ─────────────────────────────────────────────────────────────────

TOP_N = 5
SCORE_RISE_THRESHOLD = 0.20   # 20 pp rise in 7 days → DEBUT WATCH alert
DEBUT_WATCH_SIGNALS = {
    "CONVOCATORIA", "DEBUT", "PRIMER_EQUIPO", "ENTRENA_CON_PRIMER_EQUIPO",
}
_DEBUT_KEYWORDS_ES = [
    "convocado", "convocatoria", "entrena con el primer equipo",
    "primer equipo", "debut", "debutará",
]
_DEBUT_KEYWORDS_EN = [
    "called up", "train with first team", "first team debut",
    "squad list", "matchday squad",
]


class DebutWatchDetector:
    """Detect top candidates for first-team debut from cantera."""

    def __init__(self, db: D1Client) -> None:
        self.db = db

    async def detect_candidates(self) -> list[dict[str, Any]]:
        """Return top 5 canteranos by score_primer_equipo from factores_actuales."""
        rows = await self.db.execute(
            """SELECT j.jugador_id, j.nombre_canonico, j.posicion, j.edad,
                      j.entidad_actual, j.entidad,
                      j.factores_actuales, j.score_smoothed,
                      j.ultima_actualizacion_at
               FROM jugadores j
               WHERE (j.entidad IN ('castilla', 'juvenil_a')
                      OR j.entidad_actual IN ('castilla', 'juvenil_a'))
                 AND j.is_active = 1
               ORDER BY j.score_smoothed DESC LIMIT 30"""
        )

        scored = []
        for r in rows:
            factores = json.loads(r.get("factores_actuales") or "{}")
            score_primer = float(factores.get("score_primer_equipo") or 0.0)
            signals = await self._detect_debut_signals(r["jugador_id"])
            score_boost = score_primer + signals * 0.05
            scored.append({
                **r,
                "score_primer_equipo": round(score_boost, 4),
                "debut_signals": signals,
            })

        scored.sort(key=lambda x: x["score_primer_equipo"], reverse=True)
        return scored[:TOP_N]

    async def check_debut_watch_alerts(self) -> list[dict[str, Any]]:
        """Check if any canterano's score_primer_equipo rose >0.20 in last 7 days."""
        candidates = await self.detect_candidates()
        alerts = []

        for c in candidates:
            jugador_id = c["jugador_id"]
            current_score = c["score_primer_equipo"]

            week_ago_score = await self._score_primer_one_week_ago(jugador_id)
            if week_ago_score is None:
                continue

            rise = current_score - week_ago_score
            if rise >= SCORE_RISE_THRESHOLD:
                alerts.append({
                    "jugador_id": jugador_id,
                    "nombre_canonico": c["nombre_canonico"],
                    "score_primer_equipo": current_score,
                    "score_hace_7d": round(week_ago_score, 4),
                    "rise": round(rise, 4),
                    "debut_signals": c["debut_signals"],
                })
                logger.info(
                    f"🎯 DEBUT WATCH: {c['nombre_canonico']} "
                    f"score_primer={current_score:.2f} +{rise:.2f} en 7d"
                )

        return alerts

    # ── Helpers ───────────────────────────────────────────────────────────────

    async def _detect_debut_signals(self, jugador_id: str) -> int:
        """Count debut-related signals from recent rumores. Returns int count."""
        try:
            rows = await self.db.execute(
                """SELECT tipo_operacion, texto_fragmento, flags
                   FROM rumores
                   WHERE jugador_id = ?
                     AND retractado = 0
                     AND fecha_publicacion >= datetime('now', '-14 days')
                   ORDER BY fecha_publicacion DESC LIMIT 20""",
                [jugador_id],
            )
        except Exception:
            return 0

        count = 0
        for r in rows:
            tipo = (r.get("tipo_operacion") or "").upper()
            if tipo in DEBUT_WATCH_SIGNALS:
                count += 1
                continue

            texto = (r.get("texto_fragmento") or "").lower()
            flags_raw = r.get("flags")
            flags = json.loads(flags_raw) if isinstance(flags_raw, str) else (flags_raw or [])

            kw_hit = any(kw in texto for kw in _DEBUT_KEYWORDS_ES + _DEBUT_KEYWORDS_EN)
            flag_hit = any(f in DEBUT_WATCH_SIGNALS for f in flags)

            if kw_hit or flag_hit:
                count += 1

        return count

    async def _score_primer_one_week_ago(self, jugador_id: str) -> float | None:
        """Fetch score_primer_equipo from score_history ~7 days ago."""
        try:
            rows = await self.db.execute(
                """SELECT factores_snapshot FROM score_history
                   WHERE jugador_id = ?
                     AND timestamp <= datetime('now', '-6 days')
                   ORDER BY timestamp DESC LIMIT 1""",
                [jugador_id],
            )
            if not rows:
                return None
            snap = json.loads(rows[0].get("factores_snapshot") or "{}")
            return float(snap.get("score_primer_equipo") or 0.0)
        except Exception:
            return None
