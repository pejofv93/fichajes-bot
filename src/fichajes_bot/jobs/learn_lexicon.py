"""Job: learn_lexicon — discover new high-signal phrases from confirmed rumors.

Does NOT alter the live lexicon automatically. Instead it populates
`lexicon_candidates` with phrases for Pejo to review via the weekly report.

Algorithm
─────────
1. Fetch tier-S rumores from the last window_days that ended CONFIRMADO.
2. Extract all 2-4 word n-grams from texto_fragmento.
3. Count (ngram, total_seen, confirmed_count) across all tier-S rumores.
4. Keep n-grams with hit_rate > MIN_HIT_RATE AND n >= MIN_OBS that are not
   already in lexicon_entries.
5. Upsert into lexicon_candidates with estado='pending_review'.
"""

from __future__ import annotations

import asyncio
import argparse
import re
import uuid
from collections import defaultdict

from loguru import logger

from fichajes_bot.persistence.d1_client import D1Client

# Minimum observations before proposing a candidate
MIN_OBS = 10
# Minimum empirical hit rate to be worth proposing
MIN_HIT_RATE = 0.60
# Maximum candidates to insert per run (avoid spamming the table)
MAX_CANDIDATES = 50


def _extract_ngrams(text: str, n_min: int = 2, n_max: int = 4) -> list[str]:
    """Extract word n-grams from text. Returns lowercase, stripped."""
    words = re.findall(r"[a-záéíóúüñàèìòùçA-ZÁÉÍÓÚÜÑÀÈÌÒÙÇ]+", text.lower())
    ngrams = []
    for n in range(n_min, n_max + 1):
        for i in range(len(words) - n + 1):
            ngrams.append(" ".join(words[i : i + n]))
    return ngrams


async def _run_with_db(db: D1Client, window_days: int = 60) -> int:
    """Core logic that accepts an external db (for testability). Returns n candidates inserted."""
    # 1. Fetch tier-S rumores (all + confirmed) in window
    all_rumores = await db.execute(
        """SELECT r.rumor_id, r.texto_fragmento, r.outcome, r.tipo_operacion,
                  r.idioma, p.tier
           FROM rumores r
           LEFT JOIN periodistas p ON r.periodista_id = p.periodista_id
           WHERE r.texto_fragmento IS NOT NULL
             AND r.fecha_publicacion >= datetime('now', ?)
             AND p.tier = 'S'
           ORDER BY r.fecha_publicacion DESC LIMIT 5000""",
        [f"-{window_days} days"],
    )

    if not all_rumores:
        logger.info("learn_lexicon: no tier-S rumors in window")
        return 0

    # 2. Load existing lexicon phrases to exclude them
    existing = await db.execute("SELECT frase FROM lexicon_entries")
    known_phrases: set[str] = {r["frase"].lower() for r in existing}

    existing_candidates = await db.execute("SELECT frase FROM lexicon_candidates")
    known_phrases.update(r["frase"].lower() for r in existing_candidates)

    # 3. Count n-grams across all tier-S rumores
    ngram_total: dict[str, int] = defaultdict(int)
    ngram_confirmed: dict[str, int] = defaultdict(int)
    ngram_example: dict[str, str] = {}  # ngram → rumor_id example

    for row in all_rumores:
        text = row.get("texto_fragmento") or ""
        if len(text) < 10:
            continue
        outcome = row.get("outcome")
        rumor_id = row["rumor_id"]
        ngrams = _extract_ngrams(text)

        for ng in set(ngrams):  # deduplicate within same rumor
            ngram_total[ng] += 1
            if outcome == "CONFIRMADO":
                ngram_confirmed[ng] += 1
            if ng not in ngram_example:
                ngram_example[ng] = rumor_id

    # 4. Filter candidates
    candidates = []
    for ng, total in ngram_total.items():
        if total < MIN_OBS:
            continue
        confirmed = ngram_confirmed.get(ng, 0)
        hit_rate = confirmed / total
        if hit_rate < MIN_HIT_RATE:
            continue
        if ng in known_phrases:
            continue
        candidates.append((ng, total, confirmed, hit_rate, ngram_example.get(ng)))

    # Sort by hit_rate DESC, then n_obs DESC
    candidates.sort(key=lambda x: (-x[3], -x[1]))
    candidates = candidates[:MAX_CANDIDATES]

    # 5. Upsert into lexicon_candidates
    inserted = 0
    for ng, total, confirmed, hit_rate, example_id in candidates:
        peso_sugerido = round(hit_rate * 0.9, 3)  # conservative estimate
        try:
            await db.execute(
                """INSERT INTO lexicon_candidates
                   (candidate_id, frase, idioma, n_observaciones, n_aciertos,
                    hit_rate_empirico, peso_sugerido, estado, ejemplo_rumor_id)
                   VALUES (?,?,?,?,?,?,?,'pending_review',?)
                   ON CONFLICT(frase, idioma) DO UPDATE SET
                     n_observaciones = excluded.n_observaciones,
                     n_aciertos = excluded.n_aciertos,
                     hit_rate_empirico = excluded.hit_rate_empirico,
                     peso_sugerido = excluded.peso_sugerido""",
                [
                    str(uuid.uuid4()), ng, "es", total, confirmed,
                    round(hit_rate, 4), peso_sugerido, example_id,
                ],
            )
            inserted += 1
        except Exception as exc:
            logger.warning(f"learn_lexicon: could not upsert '{ng}': {exc}")

    logger.info(
        f"learn_lexicon job done | "
        f"analyzed={len(all_rumores)} rumores, "
        f"candidates_proposed={inserted}"
    )
    return inserted


async def run(window_days: int = 60, db: D1Client | None = None, **kwargs) -> None:
    logger.info(f"learn_lexicon job starting | window_days={window_days}")
    if db is not None:
        await _run_with_db(db, window_days=window_days)
        return
    async with D1Client() as _db:
        await _run_with_db(_db, window_days=window_days)


def main() -> None:
    parser = argparse.ArgumentParser(description="Discover new lexicon candidates")
    parser.add_argument("--window-days", type=int, default=60,
                        help="Days to analyze (default: 60)")
    args = parser.parse_args()
    asyncio.run(run(window_days=args.window_days))


if __name__ == "__main__":
    main()
