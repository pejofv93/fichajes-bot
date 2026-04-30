"""Session 4 tests — Lexicon YAML, seed script, and ReliabilityManager."""
# Note: TestLexiconMatching removed — lexicon_matcher.py deleted in pipeline simplification.
# Note: TestPipelineReliabilityIntegration removed — get_reliability_manager() no longer in pipeline.

from __future__ import annotations

import math
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).parent.parent


# ════════════════════════════════════════════════════════════════════════════
# Helpers
# ════════════════════════════════════════════════════════════════════════════

def _load_yaml_entries(filename: str) -> list[dict]:
    """Parse one YAML lexicon file via the seed script parser."""
    from scripts.seed_lexicon_to_d1 import parse_yaml_file
    path = ROOT / "configs" / "lexicon" / filename
    return parse_yaml_file(path)


def _all_yaml_entries() -> list[dict]:
    from scripts.seed_lexicon_to_d1 import parse_yaml_file
    lexicon_dir = ROOT / "configs" / "lexicon"
    entries = []
    for yf in sorted(lexicon_dir.glob("*.yaml")):
        entries.extend(parse_yaml_file(yf))
    return entries


# ════════════════════════════════════════════════════════════════════════════
# YAML PARSING — structural correctness
# ════════════════════════════════════════════════════════════════════════════

class TestYamlStructure:
    def test_all_yaml_files_exist(self):
        lexicon_dir = ROOT / "configs" / "lexicon"
        expected = [
            "es_fichaje.yaml", "es_salida.yaml",
            "en_signing.yaml", "en_departure.yaml",
            "it_acquisto.yaml", "de_transfer.yaml", "fr_transfert.yaml",
            "negation.yaml", "intensity.yaml", "trial_balloon.yaml", "phases.yaml",
        ]
        for fname in expected:
            assert (lexicon_dir / fname).exists(), f"Missing: {fname}"

    def test_total_entries_above_250(self):
        entries = _all_yaml_entries()
        total = len(entries)
        assert total >= 250, f"Expected ≥250 entries, got {total}"

    def test_all_entries_have_required_fields(self):
        entries = _all_yaml_entries()
        for e in entries:
            assert "entry_id" in e and e["entry_id"], f"Missing entry_id: {e}"
            assert "frase" in e and e["frase"].strip(), f"Empty frase: {e}"
            assert "idioma" in e and e["idioma"], f"Missing idioma: {e}"
            assert "categoria" in e and e["categoria"], f"Missing categoria: {e}"
            assert "peso_base" in e, f"Missing peso_base: {e}"

    def test_no_duplicate_entry_ids(self):
        entries = _all_yaml_entries()
        ids = [e["entry_id"] for e in entries]
        assert len(ids) == len(set(ids)), f"Duplicate entry_ids: {len(ids) - len(set(ids))} dupes"

    def test_entry_ids_are_deterministic(self):
        from scripts.seed_lexicon_to_d1 import parse_yaml_file
        path = ROOT / "configs" / "lexicon" / "en_signing.yaml"
        e1 = parse_yaml_file(path)
        e2 = parse_yaml_file(path)
        ids1 = {e["entry_id"] for e in e1}
        ids2 = {e["entry_id"] for e in e2}
        assert ids1 == ids2, "Entry IDs must be deterministic"

    def test_spanish_entries_have_correct_idioma(self):
        entries = _load_yaml_entries("es_fichaje.yaml")
        for e in entries:
            assert e["idioma"] == "es", f"Expected es, got {e['idioma']} for {e['frase']}"

    def test_english_signing_entries_have_correct_idioma(self):
        entries = _load_yaml_entries("en_signing.yaml")
        for e in entries:
            # All en_signing entries should be 'en' (some may have tipo=RENOVACION)
            assert e["idioma"] == "en"

    def test_negation_entries_have_negative_peso(self):
        entries = _load_yaml_entries("negation.yaml")
        for e in entries:
            assert e["peso_base"] < 0, f"Negation entry should have negative peso: {e['frase']}"

    def test_journalist_specific_entries_have_periodista_id(self):
        all_entries = _all_yaml_entries()
        journalist_frases = ["here we go", "fumata bianca", "deal perfekt"]
        for frase in journalist_frases:
            matches = [e for e in all_entries if e["frase"].lower() == frase.lower()]
            journalist_entries = [e for e in matches if e.get("periodista_id")]
            assert len(journalist_entries) >= 1, (
                f"'{frase}' should have at least one entry with periodista_id"
            )

    def test_phases_yaml_not_in_entries(self):
        """phases.yaml is config, not lexicon entries — should be skipped."""
        from scripts.seed_lexicon_to_d1 import parse_yaml_file
        path = ROOT / "configs" / "lexicon" / "phases.yaml"
        entries = parse_yaml_file(path)
        assert entries == [], "phases.yaml should produce 0 lexicon entries"



# ════════════════════════════════════════════════════════════════════════════
# SEED SCRIPT — idempotency and correctness
# ════════════════════════════════════════════════════════════════════════════

class TestSeedScript:
    @pytest.mark.asyncio
    async def test_seed_dry_run_counts(self, db):
        from scripts.seed_lexicon_to_d1 import seed
        lexicon_dir = ROOT / "configs" / "lexicon"
        count = await seed(lexicon_dir, dry_run=True)
        assert count >= 250

    @pytest.mark.asyncio
    async def test_seed_inserts_to_db(self, db):
        """Seed writes entries to lexicon_entries table."""
        import os
        os.environ["D1_MODE"] = "emulated"
        from scripts.seed_lexicon_to_d1 import parse_yaml_file

        entries = parse_yaml_file(ROOT / "configs" / "lexicon" / "en_signing.yaml")

        # Insert via the same batch logic as the script
        for e in entries[:5]:
            await db.execute(
                """INSERT OR REPLACE INTO lexicon_entries
                   (entry_id, frase, idioma, categoria, fase_rumor,
                    tipo_operacion, peso_base, periodista_id, origen,
                    created_at, updated_at)
                   VALUES (?,?,?,?,?,?,?,?,?,datetime('now'),datetime('now'))""",
                [
                    e["entry_id"], e["frase"], e["idioma"], e["categoria"],
                    e.get("fase_rumor"), e.get("tipo_operacion"), e["peso_base"],
                    e.get("periodista_id"), e["origen"],
                ],
            )

        rows = await db.execute("SELECT COUNT(*) as n FROM lexicon_entries")
        # Should have at least the 5 we just inserted + seed migrations
        assert rows[0]["n"] >= 5

    @pytest.mark.asyncio
    async def test_seed_is_idempotent(self, db):
        """Running seed twice should not duplicate entries."""
        from scripts.seed_lexicon_to_d1 import parse_yaml_file

        path = ROOT / "configs" / "lexicon" / "es_fichaje.yaml"
        entries = parse_yaml_file(path)

        async def insert_all():
            for e in entries:
                await db.execute(
                    """INSERT OR REPLACE INTO lexicon_entries
                       (entry_id, frase, idioma, categoria, fase_rumor,
                        tipo_operacion, peso_base, periodista_id, origen,
                        created_at, updated_at)
                       VALUES (?,?,?,?,?,?,?,?,?,datetime('now'),datetime('now'))""",
                    [
                        e["entry_id"], e["frase"], e["idioma"], e["categoria"],
                        e.get("fase_rumor"), e.get("tipo_operacion"), e["peso_base"],
                        e.get("periodista_id"), e["origen"],
                    ],
                )

        await insert_all()
        count_after_first = (await db.execute(
            "SELECT COUNT(*) as n FROM lexicon_entries WHERE idioma='es' AND categoria='fichaje'"
        ))[0]["n"]

        await insert_all()  # second run
        count_after_second = (await db.execute(
            "SELECT COUNT(*) as n FROM lexicon_entries WHERE idioma='es' AND categoria='fichaje'"
        ))[0]["n"]

        assert count_after_first == count_after_second, (
            f"Seed is not idempotent: {count_after_first} vs {count_after_second}"
        )


# ════════════════════════════════════════════════════════════════════════════
# RELIABILITY MANAGER — Beta-Binomial + shrinkage
# ════════════════════════════════════════════════════════════════════════════

class TestReliabilityManager:

    # ── Shrinkage ─────────────────────────────────────────────────────────────

    def test_shrinkage_formula_zero_local(self):
        from fichajes_bot.calibration.reliability_manager import _shrinkage
        # n=0 local → result ≈ global_r
        result = _shrinkage(0.5, 0, 0.8, k=10)
        assert abs(result - 0.8) < 0.01

    def test_shrinkage_formula_many_local(self):
        from fichajes_bot.calibration.reliability_manager import _shrinkage
        # n=100 local → result ≈ local_r
        result = _shrinkage(0.3, 100, 0.8, k=10)
        assert result < 0.4, f"High n should stay near local_r, got {result}"

    def test_shrinkage_blend_at_n5(self):
        from fichajes_bot.calibration.reliability_manager import _shrinkage
        # n=5, K=10: blend = (5*local + 10*global) / 15
        local_r, global_r = 0.9, 0.5
        expected = (5 * local_r + 10 * global_r) / 15
        result = _shrinkage(local_r, 5, global_r, k=10)
        assert abs(result - expected) < 1e-9

    def test_beta_mean(self):
        from fichajes_bot.calibration.reliability_manager import _beta_mean
        assert abs(_beta_mean(1.0, 1.0) - 0.5) < 1e-9    # uniform prior
        assert abs(_beta_mean(9.0, 1.0) - 0.9) < 1e-9    # 90% win rate
        assert abs(_beta_mean(3.0, 7.0) - 0.3) < 1e-9    # 30% win rate

    @pytest.mark.asyncio
    async def test_get_reliability_global_known_journalist(self, db):
        """Known journalist (seeded) returns non-trivial reliability."""
        from fichajes_bot.calibration.reliability_manager import ReliabilityManager
        mgr = ReliabilityManager(db)
        est = await mgr.get_reliability("fabrizio-romano")
        assert 0.0 < est.reliability <= 1.0
        assert est.context == "global"
        assert est.n_global >= 0

    @pytest.mark.asyncio
    async def test_get_reliability_unknown_journalist_returns_prior(self, db):
        """Unknown journalist gets the prior estimate (reliability=0.5)."""
        from fichajes_bot.calibration.reliability_manager import (
            ReliabilityManager, BETA_ALPHA_PRIOR, BETA_BETA_PRIOR, _beta_mean
        )
        mgr = ReliabilityManager(db)
        est = await mgr.get_reliability("totally-unknown-journalist-xyz")
        expected = _beta_mean(BETA_ALPHA_PRIOR, BETA_BETA_PRIOR)
        assert abs(est.reliability - expected) < 0.01

    @pytest.mark.asyncio
    async def test_shrinkage_applied_when_rm_n_low(self, db):
        """When n_rm < threshold, shrinkage is applied toward global."""
        from fichajes_bot.calibration.reliability_manager import (
            ReliabilityManager, SHRINKAGE_THRESHOLD
        )
        # fabrizio-romano seeded with n_predicciones_rm=0
        mgr = ReliabilityManager(db)
        est = await mgr.get_reliability("fabrizio-romano", context="rm")
        # With n_rm=0, shrinkage must be applied
        assert est.shrinkage_applied, (
            "Shrinkage should be applied when n_rm=0 < threshold"
        )
        # And result should be close to global reliability
        est_global = await mgr.get_reliability("fabrizio-romano")
        assert abs(est.reliability - est_global.reliability) < 0.20, (
            f"With n=0 local, reliability should be close to global: "
            f"{est.reliability:.3f} vs {est_global.reliability:.3f}"
        )

    @pytest.mark.asyncio
    async def test_update_increases_reliability_on_wins(self, db):
        """10 consecutive wins → reliability rises above 0.7."""
        from fichajes_bot.calibration.reliability_manager import ReliabilityManager

        mgr = ReliabilityManager(db)
        periodista_id = "fabrizio-romano"

        # Get baseline
        est_before = await mgr.get_reliability(periodista_id)
        baseline = est_before.reliability

        # Apply 10 wins
        for _ in range(10):
            await mgr.update_after_outcome(periodista_id, "CONFIRMADO", context="global")

        est_after = await mgr.get_reliability(periodista_id)
        assert est_after.reliability > baseline, (
            f"After 10 wins, reliability should increase: {baseline:.3f} → {est_after.reliability:.3f}"
        )
        assert est_after.reliability > 0.70, (
            f"After 10 wins from baseline {baseline:.3f}, reliability should be > 0.70, "
            f"got {est_after.reliability:.3f}"
        )

    @pytest.mark.asyncio
    async def test_update_decreases_reliability_on_losses(self, db):
        """10 consecutive losses → reliability decreases."""
        from fichajes_bot.calibration.reliability_manager import ReliabilityManager

        mgr = ReliabilityManager(db)
        periodista_id = "fabrizio-romano"

        est_before = await mgr.get_reliability(periodista_id)
        baseline = est_before.reliability

        for _ in range(10):
            await mgr.update_after_outcome(periodista_id, "FALLIDO", context="global")

        est_after = await mgr.get_reliability(periodista_id)
        assert est_after.reliability < baseline, (
            f"After 10 losses, reliability should decrease: {baseline:.3f} → {est_after.reliability:.3f}"
        )

    @pytest.mark.asyncio
    async def test_shrinkage_blend_5_local_100_global(self, db):
        """n=5 club, n=100 global → blended correctly toward global."""
        from fichajes_bot.calibration.reliability_manager import (
            ReliabilityManager, SHRINKAGE_K, _shrinkage
        )
        mgr = ReliabilityManager(db)

        # Set up journalist with known global stats (100 observations, 80% accuracy)
        # Directly update the DB
        await db.execute(
            """UPDATE periodistas SET
               n_predicciones_global=100, n_aciertos_global=80,
               alpha_global=81.0, beta_global=21.0,
               reliability_global=81.0/102.0
               WHERE periodista_id='fabrizio-romano'"""
        )

        # Get global reliability
        mgr.clear_cache()
        est_global = await mgr.get_reliability("fabrizio-romano", context="global")
        assert abs(est_global.reliability - 81.0/102.0) < 0.01

        # Get RM context (n_rm=0 → fully shrunk to global)
        est_rm = await mgr.get_reliability("fabrizio-romano", context="rm")
        expected = _shrinkage(
            local_r=est_rm.alpha / (est_rm.alpha + est_rm.beta),  # RM-specific estimate
            n_local=est_rm.n_observations,
            global_r=est_global.reliability,
            k=SHRINKAGE_K,
        )
        assert abs(est_rm.reliability - expected) < 0.01, (
            f"Blended reliability {est_rm.reliability:.4f} != expected {expected:.4f}"
        )

    @pytest.mark.asyncio
    async def test_cache_avoids_repeated_db_queries(self, db):
        """Second call to get_reliability uses cache."""
        from fichajes_bot.calibration.reliability_manager import ReliabilityManager

        mgr = ReliabilityManager(db)
        query_count = [0]
        original_execute = db.execute

        async def counting_execute(sql, params=None):
            query_count[0] += 1
            return await original_execute(sql, params)

        db.execute = counting_execute

        await mgr.get_reliability("fabrizio-romano")
        q1 = query_count[0]

        await mgr.get_reliability("fabrizio-romano")  # cache hit
        q2 = query_count[0]

        assert q2 == q1, f"Second call should not query DB (cache): {q1} vs {q2} queries"

    @pytest.mark.asyncio
    async def test_cache_invalidated_after_update(self, db):
        """After update_after_outcome, cache is cleared for that journalist."""
        from fichajes_bot.calibration.reliability_manager import ReliabilityManager

        mgr = ReliabilityManager(db)
        await mgr.get_reliability("fabrizio-romano")
        cache_before = "fabrizio-romano|global" in mgr._cache

        await mgr.update_after_outcome("fabrizio-romano", "CONFIRMADO")
        cache_after = "fabrizio-romano|global" in mgr._cache

        assert cache_before is True, "Cache should be populated after first get"
        assert cache_after is False, "Cache should be cleared after update"

    @pytest.mark.asyncio
    async def test_reliability_estimate_uncertainty(self, db):
        """Uncertainty is higher when n is small."""
        from fichajes_bot.calibration.reliability_manager import ReliabilityManager

        mgr = ReliabilityManager(db)

        est_low_n = await mgr.get_reliability("fabrizio-romano")
        # After many wins, alpha becomes large → uncertainty drops
        for _ in range(50):
            await mgr.update_after_outcome("fabrizio-romano", "CONFIRMADO")

        mgr.clear_cache()
        est_high_n = await mgr.get_reliability("fabrizio-romano")

        assert est_high_n.uncertainty < est_low_n.uncertainty, (
            "More observations → lower uncertainty"
        )

    @pytest.mark.asyncio
    async def test_credible_interval_contains_reliability(self, db):
        """The 95% CI should contain the point estimate."""
        from fichajes_bot.calibration.reliability_manager import ReliabilityManager

        mgr = ReliabilityManager(db)
        est = await mgr.get_reliability("fabrizio-romano")
        lo, hi = est.credible_interval_95
        assert lo <= est.reliability <= hi

    @pytest.mark.asyncio
    async def test_update_rm_context_tracked_separately(self, db):
        """Updates to 'rm' context update alpha_rm/beta_rm independently."""
        from fichajes_bot.calibration.reliability_manager import ReliabilityManager

        mgr = ReliabilityManager(db)

        # Read initial rm stats
        row_before = (await db.execute(
            "SELECT n_predicciones_rm, alpha_rm FROM periodistas WHERE periodista_id='fabrizio-romano'"
        ))[0]

        await mgr.update_after_outcome("fabrizio-romano", "CONFIRMADO", context="rm")

        row_after = (await db.execute(
            "SELECT n_predicciones_rm, alpha_rm FROM periodistas WHERE periodista_id='fabrizio-romano'"
        ))[0]

        assert row_after["n_predicciones_rm"] == row_before["n_predicciones_rm"] + 1
        assert row_after["alpha_rm"] == row_before["alpha_rm"] + 1.0

    @pytest.mark.asyncio
    async def test_batch_update(self, db):
        """batch_update processes multiple updates correctly."""
        from fichajes_bot.calibration.reliability_manager import ReliabilityManager

        mgr = ReliabilityManager(db)
        updates = [
            {"periodista_id": "fabrizio-romano", "outcome": "CONFIRMADO"},
            {"periodista_id": "david-ornstein",  "outcome": "CONFIRMADO"},
            {"periodista_id": "fabrizio-romano", "outcome": "FALLIDO"},
        ]
        await mgr.batch_update(updates)

        row = (await db.execute(
            "SELECT n_predicciones_global FROM periodistas WHERE periodista_id='fabrizio-romano'"
        ))[0]
        # Should have 2 more predictions (1 CONFIRMADO + 1 FALLIDO)
        assert row["n_predicciones_global"] >= 2


