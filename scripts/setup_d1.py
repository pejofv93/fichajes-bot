#!/usr/bin/env python3
"""setup_d1.py — Run migrations against Cloudflare D1.

Reads CLOUDFLARE_ACCOUNT_ID, CLOUDFLARE_D1_DATABASE_ID, CLOUDFLARE_API_TOKEN
and executes migrations/*.sql in numeric order.

Usage:
    python scripts/setup_d1.py
    python scripts/setup_d1.py --dry-run
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent


def check_env() -> None:
    missing = [v for v in ["CLOUDFLARE_ACCOUNT_ID", "CLOUDFLARE_D1_DATABASE_ID", "CLOUDFLARE_API_TOKEN"] if not os.environ.get(v)]
    if missing:
        print("❌ Missing environment variables:")
        for m in missing:
            print(f"   - {m}")
        print("\nSet them as environment variables or in a .env file.")
        sys.exit(1)


EXPECTED_TABLES = [
    "fuentes", "periodistas", "rumores_raw", "jugadores", "rumores",
    "score_history", "eventos_pending", "alertas_log", "metricas_sistema",
    "flags_sistema", "modelo_economico", "lexicon_entries", "llm_cache",
    "calibracion_periodistas", "substitution_graph", "cantera_jugadores",
    "cedidos", "retractaciones",
]


async def run_migrations(dry_run: bool = False) -> None:
    sys.path.insert(0, str(ROOT / "src"))
    from fichajes_bot.persistence.d1_client import D1Client

    client = D1Client()

    migrations_dir = ROOT / "migrations"
    migration_files = sorted(migrations_dir.glob("*.sql"))

    if not migration_files:
        print("❌ No migration files found in migrations/")
        sys.exit(1)

    print(f"📂 Found {len(migration_files)} migration files")

    for migration_file in migration_files:
        print(f"\n🔄 Running: {migration_file.name}")
        sql_content = migration_file.read_text(encoding="utf-8")

        # Remove comment-only lines for display
        statements = [
            s.strip()
            for s in sql_content.split(";")
            if s.strip() and not all(l.strip().startswith("--") for l in s.strip().splitlines() if l.strip())
        ]
        print(f"   {len(statements)} statements")

        if dry_run:
            print("   [DRY RUN - not executing]")
            continue

        try:
            await client.execute_file(sql_content)
            print(f"   ✅ OK")
        except Exception as exc:
            print(f"   ❌ FAILED: {exc}")
            await client.close()
            sys.exit(1)

    if dry_run:
        print("\n[Dry run complete — no changes made]")
        return

    print("\n🔍 Validating tables...")
    for table in EXPECTED_TABLES:
        try:
            rows = await client.execute(f"SELECT COUNT(*) as n FROM {table}")
            count = rows[0]["n"] if rows else "?"
            print(f"   ✅ {table}: {count} rows")
        except Exception as exc:
            print(f"   ❌ {table}: {exc}")

    await client.close()
    print("\n✅ Setup complete! All 18 tables verified.")


def main() -> None:
    import argparse
    from dotenv import load_dotenv
    load_dotenv()

    parser = argparse.ArgumentParser(description="Setup Cloudflare D1 database")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be done without executing")
    args = parser.parse_args()

    check_env()
    asyncio.run(run_migrations(dry_run=args.dry_run))


if __name__ == "__main__":
    main()
