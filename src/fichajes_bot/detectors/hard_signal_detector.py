"""HardSignalDetector — identifies official/confirmed transfer announcements.

A "hard signal" is unambiguous evidence that a transfer is confirmed or has
definitively fallen through. Examples:
  - Official club announcement ("Real Madrid anuncia…")
  - Romano's "here we go"
  - Player's medical completed
  - Explicit official denial ("no ficharemos a…")

When a hard signal is detected:
  1. Return the tipo_señal string.
  2. Caller is responsible for updating rumor flags and enqueueing urgent events.

The Kalman filter in scoring/kalman.py uses hard_signal=True to apply Q×3,
allowing a much faster state update toward the new reality.
"""

from __future__ import annotations

import json
import re
import uuid
from typing import Optional

from loguru import logger

from fichajes_bot.persistence.d1_client import D1Client

# ── Pattern definitions ───────────────────────────────────────────────────────

_PATTERNS: dict[str, list[str]] = {
    "fichaje_oficial": [
        r"comunicado\s+oficial",
        r"real\s*madrid\s+(?:anuncia|confirma|presenta)",
        r"here\s+we\s+go\b",
        r"aquí\s+está[,!]",
        r"médico\s+(?:superado|pasado|completado)",
        r"bienvenido\s+(?:al\s+)?real\s+madrid",
        r"firma(?:do|rá)\s+(?:por|con)\s+el\s+real\s+madrid",
        r"acuerdo\s+(?:total\s+)?(?:cerrado|firmado|alcanzado|completado)",
        r"(?:contrato\s+)?firmado\s+hasta",
        r"operación\s+(?:cerrada|confirmada)",
    ],
    "retractacion_explicita": [
        r"no\s+(?:se\s+)?ficha(?:remos?|ará)",
        r"fin\s+del\s+rumor",
        r"desmentido\s+oficial",
        r"no\s+hay\s+(?:ningún\s+)?acuerdo",
        r"descartado\s+definitivamente",
        r"(?:el\s+)?traspaso\s+no\s+se\s+producirá",
        r"operación\s+(?:descartada|cancelada|rota)",
        r"las\s+partes\s+no\s+llegarán\s+a\s+un\s+acuerdo",
        r"deal\s+(?:off|collapsed|dead)",
        r"transfer\s+(?:collapses?|falls?\s+through)",
    ],
    "salida_oficial": [
        r"rescisión\s+de\s+contrato",
        r"fin\s+de\s+su\s+etapa\s+en\s+el\s+real\s+madrid",
        r"traspaso\s+(?:oficial(?:mente\s+)?)?confirmado",
        r"(?:el\s+)?real\s+madrid\s+(?:vende?|traspasa|cede)\s+a",
        r"abandona\s+(?:el\s+)?(?:real\s+)?madrid",
        r"sale\s+confirmed",
    ],
}

# Pre-compile for speed
_COMPILED: dict[str, list[re.Pattern]] = {
    tipo: [re.compile(p, re.IGNORECASE) for p in patterns]
    for tipo, patterns in _PATTERNS.items()
}

# Maps tipo_señal → rumor flag to set
_FLAG_MAP = {
    "fichaje_oficial":       "FICHAJE_OFICIAL",
    "retractacion_explicita": "RETRACTACION_OFICIAL",
    "salida_oficial":         "SALIDA_OFICIAL",
}


class HardSignalDetector:
    """Detects official/confirmed transfer signals in rumor text."""

    def __init__(self, db: D1Client) -> None:
        self.db = db

    def detect(self, rumor: dict) -> Optional[str]:
        """Scan rumor text for hard signal patterns.

        Returns tipo_señal ('fichaje_oficial' | 'retractacion_explicita' |
        'salida_oficial') or None if no hard signal found.

        This method is synchronous — it only does regex matching.
        Call persist_signal() afterward to update DB.
        """
        texto = (
            (rumor.get("texto_fragmento") or "")
            + " "
            + (rumor.get("lexico_detectado") or "")
        )
        if not texto.strip():
            return None

        for tipo_señal, patterns in _COMPILED.items():
            for pat in patterns:
                if pat.search(texto):
                    logger.debug(
                        f"HardSignalDetector: '{pat.pattern}' matched "
                        f"→ {tipo_señal}"
                    )
                    return tipo_señal

        return None

    async def persist_signal(
        self,
        rumor_id: str,
        jugador_id: Optional[str],
        tipo_señal: str,
    ) -> None:
        """Update rumor flags in DB and enqueue urgent scoring event.

        Called after detect() returns a non-None tipo_señal.
        """
        flag = _FLAG_MAP.get(tipo_señal)
        if flag and rumor_id:
            # Fetch current flags
            rows = await self.db.execute(
                "SELECT flags FROM rumores WHERE rumor_id=? LIMIT 1",
                [rumor_id],
            )
            if rows:
                try:
                    flags: list = json.loads(rows[0]["flags"] or "[]") if rows[0]["flags"] else []
                except Exception:
                    flags = []
                if flag not in flags:
                    flags.append(flag)
                    await self.db.execute(
                        "UPDATE rumores SET flags=? WHERE rumor_id=?",
                        [json.dumps(flags), rumor_id],
                    )

        # Enqueue urgent scoring event
        if jugador_id:
            await self.db.execute(
                """INSERT INTO eventos_pending (evento_id, tipo, payload)
                   VALUES (?,?,?)""",
                [
                    str(uuid.uuid4()),
                    "score_recompute_needed",
                    json.dumps({
                        "jugador_id": jugador_id,
                        "tipo_señal": tipo_señal,
                        "rumor_id": rumor_id,
                        "urgente": True,
                    }),
                ],
            )
            logger.info(
                f"HardSignalDetector: {tipo_señal} persisted for "
                f"jugador={jugador_id[:8]} rumor={rumor_id[:8]}"
            )
