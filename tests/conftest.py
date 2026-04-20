"""Test configuration — D1 emulated with in-memory SQLite."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

# Ensure src/ is importable
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

# Use emulated D1 for all tests
os.environ.setdefault("D1_MODE", "emulated")
os.environ.setdefault("D1_EMULATED_PATH", ":memory:")


@pytest.fixture()
async def db():
    """Provide an initialized in-memory D1 client with schema applied."""
    from fichajes_bot.persistence.d1_client import D1Client

    client = D1Client()

    migrations_dir = Path(__file__).parent.parent / "migrations"
    for migration_file in sorted(migrations_dir.glob("*.sql")):
        sql = migration_file.read_text(encoding="utf-8")
        await client.execute_file(sql)

    yield client
    await client.close()
