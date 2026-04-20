#!/usr/bin/env python3
"""seed_lexicon_to_d1.py — Parse configs/lexicon/*.yaml and upsert to D1.

Idempotent: uses INSERT OR REPLACE so multiple runs are safe.
Assigns origen='curado_manual' to all entries.

YAML structures handled:
  - Simple flat: { frases: [{frase, fase, peso, periodista_id?, tipo?}] }
  - Sectioned: { fichaje: [...], salida: [...], renovacion: [...] }
  - Negation: { patrones: {es: [{frase, peso}], en: [...], ...} }
  - Intensity: { modificadores: {positivos: [...], negativos: [...]} }
  - Trial balloon: { marcadores_globo_sonda: {es: [...], en: [...], ...} }

Usage:
    python scripts/seed_lexicon_to_d1.py
    python scripts/seed_lexicon_to_d1.py --dry-run
    python scripts/seed_lexicon_to_d1.py --dir configs/lexicon
"""

from __future__ import annotations

import asyncio
import hashlib
import os
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "src"))

# ── YAML file → (idioma, tipo_operacion, categoria) metadata ─────────────────

FILE_META: dict[str, dict[str, str]] = {
    "es_fichaje.yaml":   {"idioma": "es", "tipo": "FICHAJE",    "cat": "fichaje"},
    "es_salida.yaml":    {"idioma": "es", "tipo": "SALIDA",     "cat": "salida"},
    "en_signing.yaml":   {"idioma": "en", "tipo": "FICHAJE",    "cat": "fichaje"},
    "en_departure.yaml": {"idioma": "en", "tipo": "SALIDA",     "cat": "salida"},
    "it_acquisto.yaml":  {"idioma": "it", "tipo": None,         "cat": None},
    "de_transfer.yaml":  {"idioma": "de", "tipo": None,         "cat": None},
    "fr_transfert.yaml": {"idioma": "fr", "tipo": None,         "cat": None},
    "negation.yaml":     {"idioma": None, "tipo": None,         "cat": "negacion"},
    "intensity.yaml":    {"idioma": None, "tipo": None,         "cat": "intensificador"},
    "trial_balloon.yaml":{"idioma": None, "tipo": None,         "cat": "globo_sonda"},
    "phases.yaml":       {"idioma": None, "tipo": None,         "cat": None},  # skip config
}

SECTION_TIPO: dict[str, str] = {
    "fichaje":    "FICHAJE",
    "salida":     "SALIDA",
    "renovacion": "RENOVACION",
    "cesion":     "CESION",
    "renewal":    "RENOVACION",
}

SECTION_CAT: dict[str, str] = {
    "fichaje":    "fichaje",
    "salida":     "salida",
    "renovacion": "renovacion",
    "cesion":     "cesion",
    "renewal":    "renovacion",
}


def _entry_id(frase: str, idioma: str, categoria: str) -> str:
    raw = f"{idioma}|{categoria}|{frase.lower().strip()}"
    return hashlib.sha256(raw.encode()).hexdigest()[:32]


def parse_yaml_file(path: Path) -> list[dict[str, Any]]:
    """Parse one YAML file into a list of lexicon_entries rows."""
    import yaml  # type: ignore[import]

    fname = path.name
    meta = FILE_META.get(fname)
    if meta is None:
        print(f"  [skip] unknown file: {fname}")
        return []
    if meta.get("cat") is None and meta.get("tipo") is None and fname == "phases.yaml":
        return []  # phases.yaml is config, not entries

    with path.open(encoding="utf-8") as f:
        data = yaml.safe_load(f)

    if not data:
        return []

    entries: list[dict[str, Any]] = []

    # ── Flat format: {frases: [...]} ─────────────────────────────────────────
    if "frases" in data:
        base_idioma = meta["idioma"] or "es"
        base_tipo = meta["tipo"]
        base_cat = meta["cat"] or "fichaje"

        for item in data["frases"]:
            frase = item.get("frase", "").strip()
            if not frase:
                continue
            tipo = item.get("tipo") or base_tipo
            cat = _cat_from_tipo(tipo) if tipo else base_cat
            idioma = item.get("idioma") or base_idioma
            entries.append({
                "entry_id":      _entry_id(frase, idioma, cat),
                "frase":         frase,
                "idioma":        idioma,
                "categoria":     cat,
                "fase_rumor":    item.get("fase"),
                "tipo_operacion":tipo,
                "peso_base":     float(item.get("peso", 0.5)),
                "periodista_id": item.get("periodista_id"),
                "origen":        "curado_manual",
            })

    # ── Sectioned format: {fichaje: [...], salida: [...], ...} ───────────────
    for section, tipo in SECTION_TIPO.items():
        if section not in data:
            continue
        base_idioma = meta["idioma"] or "es"
        cat = SECTION_CAT[section]
        for item in data[section]:
            frase = item.get("frase", "").strip()
            if not frase:
                continue
            idioma = item.get("idioma") or base_idioma
            # Allow per-item tipo override (e.g., cesion entries inside salida section)
            item_tipo = item.get("tipo") or tipo
            item_cat = _cat_from_tipo(item_tipo)
            entries.append({
                "entry_id":      _entry_id(frase, idioma, item_cat),
                "frase":         frase,
                "idioma":        idioma,
                "categoria":     item_cat,
                "fase_rumor":    item.get("fase"),
                "tipo_operacion":item_tipo,
                "peso_base":     float(item.get("peso", 0.5)),
                "periodista_id": item.get("periodista_id"),
                "origen":        "curado_manual",
            })

    # ── Negation format: {patrones: {es: [...], en: [...]}} ─────────────────
    if "patrones" in data:
        for idioma, items in data["patrones"].items():
            if not isinstance(items, list):
                continue
            for item in items:
                frase = item.get("frase", "").strip()
                if not frase:
                    continue
                peso = float(item.get("peso", -0.5))
                entries.append({
                    "entry_id":      _entry_id(frase, idioma, "negacion"),
                    "frase":         frase,
                    "idioma":        idioma,
                    "categoria":     "negacion",
                    "fase_rumor":    None,
                    "tipo_operacion":None,
                    "peso_base":     peso,
                    "periodista_id": None,
                    "origen":        "curado_manual",
                })

    # ── Intensity format: {modificadores: {positivos: [...], negativos: [...]}}
    if "modificadores" in data:
        for section_name in ("positivos", "negativos"):
            items = data["modificadores"].get(section_name, [])
            for item in items:
                frase = item.get("frase", "").strip()
                if not frase:
                    continue
                idioma = item.get("idioma", "es")
                amp = float(item.get("amplificador", 0.0))
                entries.append({
                    "entry_id":      _entry_id(frase, idioma, "intensificador"),
                    "frase":         frase,
                    "idioma":        idioma,
                    "categoria":     "intensificador",
                    "fase_rumor":    None,
                    "tipo_operacion":None,
                    "peso_base":     amp,
                    "periodista_id": item.get("periodista_id"),
                    "origen":        "curado_manual",
                })

    # ── Trial balloon format: {marcadores_globo_sonda: {es: [...], en: [...]}}
    if "marcadores_globo_sonda" in data:
        for idioma, items in data["marcadores_globo_sonda"].items():
            if not isinstance(items, list):
                continue
            for item in items:
                frase = str(item).strip() if isinstance(item, str) else item.get("frase", "").strip()
                if not frase:
                    continue
                entries.append({
                    "entry_id":      _entry_id(frase, idioma, "globo_sonda"),
                    "frase":         frase,
                    "idioma":        idioma,
                    "categoria":     "globo_sonda",
                    "fase_rumor":    None,
                    "tipo_operacion":None,
                    "peso_base":     -0.10,
                    "periodista_id": None,
                    "origen":        "curado_manual",
                })

    return entries


def _cat_from_tipo(tipo: str | None) -> str:
    mapping = {
        "FICHAJE": "fichaje",
        "SALIDA": "salida",
        "CESION": "cesion",
        "RENOVACION": "renovacion",
    }
    return mapping.get(tipo or "", "fichaje")


async def seed(lexicon_dir: Path, dry_run: bool = False) -> int:
    """Parse YAMLs and upsert to D1. Returns count of entries processed."""
    try:
        import yaml  # noqa: F401
    except ImportError:
        print("Error: pyyaml not installed. Run: pip install pyyaml")
        return 0

    all_entries: list[dict[str, Any]] = []
    yaml_files = sorted(lexicon_dir.glob("*.yaml"))

    if not yaml_files:
        print(f"No YAML files found in {lexicon_dir}")
        return 0

    print(f"Parsing {len(yaml_files)} YAML files from {lexicon_dir}...")

    for yf in yaml_files:
        entries = parse_yaml_file(yf)
        print(f"  {yf.name}: {len(entries)} entries")
        all_entries.extend(entries)

    # Deduplicate by entry_id (last write wins for same phrase/lang/cat)
    deduped: dict[str, dict] = {}
    for e in all_entries:
        deduped[e["entry_id"]] = e
    final = list(deduped.values())

    print(f"\nTotal unique entries to upsert: {len(final)}")

    if dry_run:
        print("\n[DRY RUN — not writing to D1]")
        # Print sample
        for e in final[:5]:
            print(f"  {e['entry_id'][:8]} | {e['idioma']:2} | {e['categoria']:14} | {e['frase'][:50]}")
        print(f"  ... and {len(final)-5} more")
        return len(final)

    from fichajes_bot.persistence.d1_client import D1Client

    async with D1Client() as db:
        batch_size = 20
        inserted = 0
        for i in range(0, len(final), batch_size):
            batch = final[i : i + batch_size]
            stmts = []
            for e in batch:
                stmts.append({
                    "sql": """
                        INSERT OR REPLACE INTO lexicon_entries
                        (entry_id, frase, idioma, categoria, fase_rumor,
                         tipo_operacion, peso_base, periodista_id, origen,
                         created_at, updated_at)
                        VALUES (?,?,?,?,?,?,?,?,?,datetime('now'),datetime('now'))
                    """,
                    "params": [
                        e["entry_id"],
                        e["frase"],
                        e["idioma"],
                        e["categoria"],
                        e.get("fase_rumor"),
                        e.get("tipo_operacion"),
                        e["peso_base"],
                        e.get("periodista_id"),
                        e["origen"],
                    ],
                })
            await db.execute_batch(stmts)
            inserted += len(batch)
            print(f"  Upserted {inserted}/{len(final)} entries...", end="\r")

    print(f"\n✅ Seeded {len(final)} lexicon entries to D1 (origen='curado_manual')")
    return len(final)


def main() -> None:
    import argparse

    from dotenv import load_dotenv
    load_dotenv()

    parser = argparse.ArgumentParser(description="Seed lexicon YAML files to D1")
    parser.add_argument("--dry-run", action="store_true", help="Parse only, no DB writes")
    parser.add_argument("--dir", default=str(ROOT / "configs" / "lexicon"),
                        help="Directory containing YAML files")
    args = parser.parse_args()

    lexicon_dir = Path(args.dir)
    if not lexicon_dir.exists():
        print(f"Error: directory not found: {lexicon_dir}")
        sys.exit(1)

    count = asyncio.run(seed(lexicon_dir, dry_run=args.dry_run))
    print(f"\nDone. {count} entries processed.")


if __name__ == "__main__":
    main()
