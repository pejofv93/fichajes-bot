"""Cloudflare D1 REST API client for GitHub Actions jobs."""

from __future__ import annotations

import os
import re
import sqlite3
from typing import Any

import httpx
from loguru import logger


def _split_sql(sql: str) -> list[str]:
    """Split SQL file into individual statements, respecting parentheses."""
    statements = []
    depth = 0
    buf = []
    for char in sql:
        if char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
        if char == ";" and depth == 0:
            stmt = "".join(buf).strip()
            # Remove pure-comment statements
            lines = [l for l in stmt.splitlines() if l.strip() and not l.strip().startswith("--")]
            if lines:
                statements.append(stmt)
            buf = []
        else:
            buf.append(char)
    # Handle trailing content without semicolon
    remaining = "".join(buf).strip()
    if remaining:
        lines = [l for l in remaining.splitlines() if l.strip() and not l.strip().startswith("--")]
        if lines:
            statements.append(remaining)
    return statements


class D1Client:
    """Cliente para Cloudflare D1 via REST API desde GitHub Actions.

    En tests (D1_MODE=emulated) usa SQLite local transparentemente.
    """

    BASE = "https://api.cloudflare.com/client/v4"

    def __init__(self) -> None:
        self._mode = os.environ.get("D1_MODE", "cloudflare")
        if self._mode == "emulated":
            db_path = os.environ.get("D1_EMULATED_PATH", "test_d1.db")
            self._sqlite = sqlite3.connect(db_path)
            self._sqlite.row_factory = sqlite3.Row
            logger.debug(f"D1Client: emulated mode ({db_path})")
            self._client: httpx.AsyncClient | None = None
        else:
            self.account_id = os.environ["CLOUDFLARE_ACCOUNT_ID"]
            self.database_id = os.environ["CLOUDFLARE_D1_DATABASE_ID"]
            self.token = os.environ["CLOUDFLARE_API_TOKEN"]
            self._client = httpx.AsyncClient(
                base_url=self.BASE,
                headers={"Authorization": f"Bearer {self.token}"},
                timeout=30.0,
            )
            self._sqlite = None

    async def execute(self, sql: str, params: list[Any] | None = None) -> list[dict]:
        """Ejecutar una query y devolver filas."""
        params = params or []
        if self._mode == "emulated":
            return self._sqlite_execute(sql, params)
        r = await self._client.post(
            f"/accounts/{self.account_id}/d1/database/{self.database_id}/query",
            json={"sql": sql, "params": params},
        )
        r.raise_for_status()
        data = r.json()
        if not data["success"]:
            raise RuntimeError(f"D1 error: {data['errors']}")
        return data["result"][0]["results"]

    async def execute_batch(self, statements: list[dict[str, Any]]) -> None:
        """Ejecutar múltiples statements en batch (más eficiente)."""
        if self._mode == "emulated":
            for stmt in statements:
                self._sqlite_execute(stmt["sql"], stmt.get("params", []))
            return
        r = await self._client.post(
            f"/accounts/{self.account_id}/d1/database/{self.database_id}/batch",
            json={"statements": statements},
        )
        r.raise_for_status()
        data = r.json()
        if not data["success"]:
            raise RuntimeError(f"D1 batch error: {data['errors']}")

    async def execute_file(self, sql_content: str) -> None:
        """Ejecutar un archivo SQL completo (para migrations)."""
        statements = _split_sql(sql_content)
        if self._mode == "emulated":
            for stmt in statements:
                self._sqlite.execute(stmt)
            self._sqlite.commit()
            return
        for stmt in statements:
            await self.execute(stmt)

    def _sqlite_execute(self, sql: str, params: list[Any]) -> list[dict]:
        cur = self._sqlite.execute(sql, params)
        self._sqlite.commit()
        if cur.description is None:
            return []
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, row)) for row in cur.fetchall()]

    async def close(self) -> None:
        if self._client:
            await self._client.aclose()
        if self._sqlite:
            self._sqlite.close()

    async def __aenter__(self) -> "D1Client":
        return self

    async def __aexit__(self, *_: Any) -> None:
        await self.close()
