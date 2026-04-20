"""Repository layer — thin wrappers over D1Client."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from .d1_client import D1Client


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _uuid() -> str:
    return str(uuid.uuid4())


class RumorRawRepository:
    def __init__(self, db: D1Client) -> None:
        self.db = db

    async def insert_batch(self, items: list[dict[str, Any]]) -> int:
        stmts = []
        for item in items:
            stmts.append({
                "sql": """
                    INSERT OR IGNORE INTO rumores_raw
                    (raw_id, fuente_id, url_canonico, titulo, texto_completo,
                     html_crudo, fecha_publicacion, idioma_detectado, hash_dedup)
                    VALUES (?,?,?,?,?,?,?,?,?)
                """,
                "params": [
                    _uuid(),
                    item["fuente_id"],
                    item.get("url_canonico"),
                    item.get("titulo"),
                    item.get("texto_completo"),
                    item.get("html_crudo"),
                    item.get("fecha_publicacion"),
                    item.get("idioma_detectado"),
                    item["hash_dedup"],
                ],
            })
        if stmts:
            await self.db.execute_batch(stmts)
        return len(stmts)

    async def get_unprocessed(self, limit: int = 100) -> list[dict]:
        return await self.db.execute(
            "SELECT * FROM rumores_raw WHERE procesado=0 AND descartado=0 "
            "ORDER BY fecha_ingesta ASC LIMIT ?",
            [limit],
        )

    async def mark_processed(self, raw_id: str, descartado: bool = False, motivo: str | None = None) -> None:
        await self.db.execute(
            "UPDATE rumores_raw SET procesado=1, descartado=?, motivo_descarte=? WHERE raw_id=?",
            [int(descartado), motivo, raw_id],
        )

    async def hash_exists(self, hash_val: str) -> bool:
        rows = await self.db.execute(
            "SELECT 1 FROM rumores_raw WHERE hash_dedup=? LIMIT 1", [hash_val]
        )
        return bool(rows)

    async def hashes_exist_batch(self, hashes: list[str]) -> set[str]:
        if not hashes:
            return set()
        placeholders = ",".join("?" * len(hashes))
        rows = await self.db.execute(
            f"SELECT hash_dedup FROM rumores_raw WHERE hash_dedup IN ({placeholders})",
            hashes,
        )
        return {r["hash_dedup"] for r in rows}


class JugadorRepository:
    def __init__(self, db: D1Client) -> None:
        self.db = db

    async def get_all_active(self) -> list[dict]:
        return await self.db.execute(
            "SELECT * FROM jugadores WHERE is_active=1 ORDER BY score_smoothed DESC"
        )

    async def upsert(self, data: dict[str, Any]) -> None:
        await self.db.execute(
            """
            INSERT INTO jugadores (jugador_id, nombre_canonico, slug, posicion,
                club_actual, tipo_operacion_principal, entidad, score_raw,
                score_smoothed, kalman_P, factores_actuales, flags,
                ultima_actualizacion_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(jugador_id) DO UPDATE SET
                score_raw=excluded.score_raw,
                score_smoothed=excluded.score_smoothed,
                kalman_P=excluded.kalman_P,
                factores_actuales=excluded.factores_actuales,
                flags=excluded.flags,
                ultima_actualizacion_at=excluded.ultima_actualizacion_at
            """,
            [
                data.get("jugador_id", _uuid()),
                data["nombre_canonico"],
                data.get("slug"),
                data.get("posicion"),
                data.get("club_actual"),
                data.get("tipo_operacion_principal", "FICHAJE"),
                data.get("entidad", "primer_equipo"),
                data.get("score_raw", 0.0),
                data.get("score_smoothed", 0.0),
                data.get("kalman_P", 1.0),
                data.get("factores_actuales", "{}"),
                data.get("flags", "[]"),
                _now(),
            ],
        )


class FuenteRepository:
    def __init__(self, db: D1Client) -> None:
        self.db = db

    async def get_active_by_tiers(self, tiers: list[str], tipo: str | None = None) -> list[dict]:
        placeholders = ",".join("?" * len(tiers))
        params: list = list(tiers)
        tipo_clause = ""
        if tipo:
            tipo_clause = " AND tipo=?"
            params.append(tipo)
        return await self.db.execute(
            f"SELECT * FROM fuentes WHERE tier IN ({placeholders}) "
            f"AND is_disabled=0{tipo_clause}",
            params,
        )

    async def disable(self, fuente_id: str) -> None:
        await self.db.execute(
            "UPDATE fuentes SET is_disabled=1, updated_at=datetime('now') WHERE fuente_id=?",
            [fuente_id],
        )

    async def bump_errors(self, fuente_id: str) -> None:
        await self.db.execute(
            "UPDATE fuentes SET consecutive_errors=consecutive_errors+1, "
            "updated_at=datetime('now') WHERE fuente_id=?",
            [fuente_id],
        )

    async def reset_errors(self, fuente_id: str) -> None:
        await self.db.execute(
            "UPDATE fuentes SET consecutive_errors=0, updated_at=datetime('now') WHERE fuente_id=?",
            [fuente_id],
        )


class MetricasRepository:
    def __init__(self, db: D1Client) -> None:
        self.db = db

    async def upsert(self, name: str, value: str, value_num: float | None = None) -> None:
        await self.db.execute(
            """INSERT INTO metricas_sistema (metric_id, metric_name, value, value_num, timestamp)
               VALUES (?,?,?,?,?)""",
            [_uuid(), name, value, value_num, _now()],
        )

    async def get_latest(self, name: str) -> dict | None:
        rows = await self.db.execute(
            "SELECT * FROM metricas_sistema WHERE metric_name=? ORDER BY timestamp DESC LIMIT 1",
            [name],
        )
        return rows[0] if rows else None
