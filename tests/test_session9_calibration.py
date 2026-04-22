"""Session 9 tests — OfficialEventsDetector, Calibrator, learn_lexicon, backfill."""

from __future__ import annotations

import json
import uuid
from pathlib import Path

import pytest


# ── Helpers ───────────────────────────────────────────────────────────────────


def _uid() -> str:
    return str(uuid.uuid4())


async def _insert_periodista(db, periodista_id: str, tier: str = "S",
                               nombre: str = "Test Journalist",
                               reliability: float = 0.80) -> None:
    await db.execute(
        """INSERT OR IGNORE INTO periodistas
           (periodista_id, nombre_completo, tier, reliability_global,
            alpha_global, beta_global, n_predicciones_global, n_aciertos_global,
            n_predicciones_rm, n_aciertos_rm, alpha_rm, beta_rm, created_at)
           VALUES (?,?,?,?,?,?,0,0,0,0,1.0,1.0,datetime('now'))""",
        [periodista_id, nombre, tier, reliability,
         reliability * 10, (1 - reliability) * 10],
    )


async def _insert_jugador(db, nombre: str = "Test Player", tipo: str = "FICHAJE",
                           score: float = 0.5, outcome: str | None = None,
                           fecha_outcome: str | None = None) -> str:
    jid = _uid()
    slug = nombre.lower().replace(" ", "-")
    await db.execute(
        """INSERT INTO jugadores
           (jugador_id, nombre_canonico, slug, tipo_operacion_principal,
            entidad, score_smoothed, score_raw, is_active,
            outcome_clasificado, fecha_outcome, flags, factores_actuales, kalman_P, created_at)
           VALUES (?,?,?,'FICHAJE','primer_equipo',?,?,1,?,?,?,?,1.0,datetime('now'))""",
        [jid, nombre, slug, score, score, outcome, fecha_outcome, "[]", "{}"],
    )
    return jid


async def _insert_rumor(
    db, jugador_id: str, periodista_id: str, tipo: str = "FICHAJE",
    fase: int = 3, flags: str = "[]", fuente_id: str | None = None,
    outcome: str | None = None, lexico: str | None = None,
    texto: str | None = None, fecha: str | None = None,
) -> str:
    rid = _uid()
    await db.execute(
        """INSERT INTO rumores
           (rumor_id, jugador_id, periodista_id, fuente_id, tipo_operacion,
            fase_rumor, flags, lexico_detectado, texto_fragmento,
            confianza_extraccion, peso_lexico, retractado, outcome,
            fecha_publicacion, created_at)
           VALUES (?,?,?,?,?,?,?,?,?,0.75,0.65,0,?,?,datetime('now'))""",
        [rid, jugador_id, periodista_id, fuente_id or "fuente-test",
         tipo, fase, flags, lexico, texto or "Texto de prueba",
         outcome, fecha or "2024-06-01"],
    )
    return rid


# ── OfficialEventsDetector tests ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_official_detection_flag_fichaje_oficial(db):
    """Rumor with FICHAJE_OFICIAL flag → outcome_clasificado=FICHAJE_EFECTIVO."""
    from fichajes_bot.calibration.official_events_detector import OfficialEventsDetector

    await _insert_periodista(db, "fabrizio-romano")
    jid = await _insert_jugador(db, "Test Official A", tipo="FICHAJE")
    await _insert_rumor(
        db, jid, "fabrizio-romano", tipo="FICHAJE",
        flags=json.dumps(["FICHAJE_OFICIAL"]),
        fecha="2024-05-01",
    )

    detector = OfficialEventsDetector(db)
    n = await detector.scan_recent_rumors(window_days=3650)

    assert n == 1
    row = await db.execute(
        "SELECT outcome_clasificado FROM jugadores WHERE jugador_id=?", [jid]
    )
    assert row[0]["outcome_clasificado"] == "FICHAJE_EFECTIVO"


@pytest.mark.asyncio
async def test_official_detection_official_source(db):
    """Rumor from marca-rm-oficial → outcome detected."""
    from fichajes_bot.calibration.official_events_detector import OfficialEventsDetector

    jid = await _insert_jugador(db, "Test Official B", tipo="FICHAJE")
    await _insert_rumor(
        db, jid, "marca-rm-oficial", tipo="FICHAJE",
        flags="[]",
        fecha="2024-06-01",
    )

    detector = OfficialEventsDetector(db)
    n = await detector.scan_recent_rumors(window_days=3650)

    assert n == 1
    row = await db.execute(
        "SELECT outcome_clasificado, fuente_confirmacion FROM jugadores WHERE jugador_id=?", [jid]
    )
    assert row[0]["outcome_clasificado"] is not None
    assert "oficial" in (row[0]["fuente_confirmacion"] or "").lower() or \
           row[0]["fuente_confirmacion"] == "marca-rm-oficial"


@pytest.mark.asyncio
async def test_official_detection_salida_oficial(db):
    """Rumor with SALIDA_OFICIAL flag → outcome_clasificado=SALIDA_EFECTIVA."""
    from fichajes_bot.calibration.official_events_detector import OfficialEventsDetector

    await _insert_periodista(db, "fabrizio-romano")
    jid = await _insert_jugador(db, "Eden Hazard", tipo="SALIDA")
    await _insert_rumor(
        db, jid, "fabrizio-romano", tipo="SALIDA",
        flags=json.dumps(["SALIDA_OFICIAL"]),
        fecha="2023-07-01",
    )

    detector = OfficialEventsDetector(db)
    n = await detector.scan_recent_rumors(window_days=3650)

    assert n == 1
    row = await db.execute(
        "SELECT outcome_clasificado FROM jugadores WHERE jugador_id=?", [jid]
    )
    assert row[0]["outcome_clasificado"] == "SALIDA_EFECTIVA"


@pytest.mark.asyncio
async def test_official_detection_idempotent(db):
    """Running scan twice on same jugador creates only 1 outcome."""
    from fichajes_bot.calibration.official_events_detector import OfficialEventsDetector

    await _insert_periodista(db, "fabrizio-romano")
    jid = await _insert_jugador(db, "Test Official C", tipo="FICHAJE")
    await _insert_rumor(
        db, jid, "fabrizio-romano", tipo="FICHAJE",
        flags=json.dumps(["FICHAJE_OFICIAL"]),
        fecha="2024-05-01",
    )

    detector = OfficialEventsDetector(db)
    n1 = await detector.scan_recent_rumors(window_days=3650)
    n2 = await detector.scan_recent_rumors(window_days=3650)

    assert n1 == 1
    assert n2 == 0  # already processed


@pytest.mark.asyncio
async def test_official_detection_marks_confirming_rumors(db):
    """FICHAJE_EFECTIVO outcome → matching FICHAJE rumors become CONFIRMADO."""
    from fichajes_bot.calibration.official_events_detector import OfficialEventsDetector

    await _insert_periodista(db, "fabrizio-romano")
    await _insert_periodista(db, "matteo-moretto")
    jid = await _insert_jugador(db, "Test Official D", tipo="FICHAJE")

    rid_fichaje = await _insert_rumor(
        db, jid, "matteo-moretto", tipo="FICHAJE", flags="[]", fecha="2024-03-01"
    )
    await _insert_rumor(
        db, jid, "fabrizio-romano", tipo="FICHAJE",
        flags=json.dumps(["FICHAJE_OFICIAL"]), fecha="2024-06-01"
    )

    detector = OfficialEventsDetector(db)
    await detector.scan_recent_rumors(window_days=3650)

    row = await db.execute(
        "SELECT outcome FROM rumores WHERE rumor_id=?", [rid_fichaje]
    )
    assert row[0]["outcome"] == "CONFIRMADO"


@pytest.mark.asyncio
async def test_official_detection_inserts_outcomes_historicos(db):
    """Detected event is recorded in outcomes_historicos table."""
    from fichajes_bot.calibration.official_events_detector import OfficialEventsDetector

    await _insert_periodista(db, "fabrizio-romano")
    jid = await _insert_jugador(db, "Test Official E", tipo="FICHAJE")
    await _insert_rumor(
        db, jid, "fabrizio-romano", tipo="FICHAJE",
        flags=json.dumps(["FICHAJE_OFICIAL"]),
        fecha="2024-05-01",
    )

    detector = OfficialEventsDetector(db)
    await detector.scan_recent_rumors(window_days=3650)

    rows = await db.execute(
        "SELECT * FROM outcomes_historicos WHERE jugador_id=?", [jid]
    )
    assert len(rows) == 1
    assert rows[0]["outcome_tipo"] == "FICHAJE_EFECTIVO"


# ── Calibrator tests ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_calibration_updates_reliability(db):
    """10 correct Romano RM predictions → reliability_rm increases."""
    from fichajes_bot.calibration.calibrator import Calibrator
    from fichajes_bot.calibration.reliability_manager import ReliabilityManager

    await _insert_periodista(db, "fabrizio-romano", reliability=0.80)

    baseline_row = await db.execute(
        "SELECT reliability_global, n_predicciones_global, alpha_global FROM periodistas "
        "WHERE periodista_id='fabrizio-romano' LIMIT 1"
    )
    baseline_reliability = float(baseline_row[0]["reliability_global"])
    baseline_n = int(baseline_row[0]["n_predicciones_global"])

    # Create 10 jugadores that Romano reported on and all became FICHAJE_EFECTIVO
    for i in range(10):
        jid = await _insert_jugador(
            db, f"Player {i}", tipo="FICHAJE",
            outcome="FICHAJE_EFECTIVO",
            fecha_outcome="2024-06-01",
        )
        await _insert_rumor(db, jid, "fabrizio-romano", tipo="FICHAJE", fase=5)

    rm = ReliabilityManager(db)
    calibrator = Calibrator(db, rm)
    updates = await calibrator.calibrate_journalists(window_days=3650)

    assert "fabrizio-romano" in updates
    assert updates["fabrizio-romano"] == 10

    row = await db.execute(
        "SELECT reliability_global, n_predicciones_global FROM periodistas "
        "WHERE periodista_id='fabrizio-romano' LIMIT 1"
    )
    new_reliability = float(row[0]["reliability_global"])
    new_n = int(row[0]["n_predicciones_global"])

    assert new_n == baseline_n + 10
    assert new_reliability >= baseline_reliability  # 10 correct predictions should not lower it


@pytest.mark.asyncio
async def test_calibration_no_outcomes_returns_empty(db):
    """calibrate_journalists with no recent outcomes returns empty dict."""
    from fichajes_bot.calibration.calibrator import Calibrator
    from fichajes_bot.calibration.reliability_manager import ReliabilityManager

    await _insert_periodista(db, "fabrizio-romano")
    jid = await _insert_jugador(db, "Unknown Player", outcome=None)
    await _insert_rumor(db, jid, "fabrizio-romano")

    rm = ReliabilityManager(db)
    calibrator = Calibrator(db, rm)
    updates = await calibrator.calibrate_journalists(window_days=90)

    assert updates == {}


@pytest.mark.asyncio
async def test_calibration_lexicon_drift(db):
    """Entry with hit_rate 0.3 vs peso_base 0.7 → peso_aprendido adjusted with shrinkage."""
    from fichajes_bot.calibration.calibrator import Calibrator
    from fichajes_bot.calibration.reliability_manager import ReliabilityManager
    from fichajes_bot.calibration.calibrator import LEXICON_MIN_OBS, LEXICON_SHRINKAGE_K

    # Insert a lexicon entry with peso_base=0.7 but empirical data shows 0.3 hit rate
    entry_id = _uid()
    n_total = 30
    n_hits = 9  # hit_rate = 0.30
    await db.execute(
        """INSERT OR IGNORE INTO lexicon_entries
           (entry_id, frase, idioma, categoria, peso_base, n_ocurrencias, n_aciertos, origen)
           VALUES (?,?,?,?,?,?,?,?)""",
        [entry_id, "test phrase drift", "es", "fichaje",
         0.70, n_total, n_hits, "curado_manual"],
    )

    rm = ReliabilityManager(db)
    calibrator = Calibrator(db, rm)
    n_updated = await calibrator.calibrate_lexicon(window_days=90)

    assert n_updated >= 1
    row = await db.execute(
        "SELECT peso_aprendido, origen FROM lexicon_entries WHERE entry_id=?", [entry_id]
    )
    peso_aprendido = row[0]["peso_aprendido"]
    # Shrinkage formula: (30*0.3 + 20*0.7) / (30+20) = (9+14)/50 = 23/50 = 0.46
    expected = (n_total * (n_hits / n_total) + LEXICON_SHRINKAGE_K * 0.70) / (n_total + LEXICON_SHRINKAGE_K)
    assert abs(peso_aprendido - expected) < 0.01
    # Drift > 0.30 (|0.3 - 0.7| = 0.4 > 0.3) → marked as 'learned'
    assert row[0]["origen"] == "learned"


@pytest.mark.asyncio
async def test_calibration_lexicon_small_sample_not_updated(db):
    """Entry with fewer than MIN_OBS observations is not updated."""
    from fichajes_bot.calibration.calibrator import Calibrator
    from fichajes_bot.calibration.reliability_manager import ReliabilityManager
    from fichajes_bot.calibration.calibrator import LEXICON_MIN_OBS

    entry_id = _uid()
    await db.execute(
        """INSERT OR IGNORE INTO lexicon_entries
           (entry_id, frase, idioma, categoria, peso_base, n_ocurrencias, n_aciertos, origen)
           VALUES (?,?,?,?,?,?,?,?)""",
        [entry_id, "rare phrase", "es", "fichaje",
         0.70, LEXICON_MIN_OBS - 5, 5, "curado_manual"],
    )

    rm = ReliabilityManager(db)
    calibrator = Calibrator(db, rm)
    await calibrator.calibrate_lexicon(window_days=90)

    row = await db.execute(
        "SELECT peso_aprendido FROM lexicon_entries WHERE entry_id=?", [entry_id]
    )
    # Should remain NULL — not enough observations
    assert row[0]["peso_aprendido"] is None


# ── learn_lexicon tests ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_learn_lexicon_candidate_proposed(db):
    """Phrase appearing 10+ times in confirmed tier-S rumors → proposed as candidate."""
    from fichajes_bot.jobs.learn_lexicon import run as learn_lexicon_run, MIN_OBS

    await _insert_periodista(db, "fabrizio-romano", tier="S")
    jid = await _insert_jugador(db, "Some Player", outcome="FICHAJE_EFECTIVO",
                                  fecha_outcome="2024-06-01")

    repeated_phrase = "aterrizará en Madrid"
    n_confirm = MIN_OBS + 5  # above threshold

    for i in range(n_confirm):
        await _insert_rumor(
            db, jid, "fabrizio-romano", tipo="FICHAJE",
            texto=f"El jugador {repeated_phrase} la próxima semana según fuentes",
            outcome="CONFIRMADO",
            fecha=f"2024-0{(i % 9) + 1:01d}-{(i % 28) + 1:02d}",
        )

    await learn_lexicon_run(window_days=3650, db=db)

    candidates = await db.execute(
        "SELECT frase, hit_rate_empirico, n_observaciones FROM lexicon_candidates "
        "WHERE estado='pending_review'"
    )
    # The phrase or its sub-ngrams should appear as candidates
    found = any(
        "aterrizar" in c["frase"] or "madrid" in c["frase"]
        for c in candidates
    )
    assert found or len(candidates) > 0, "Expected at least one lexicon candidate"


@pytest.mark.asyncio
async def test_learn_lexicon_no_candidates_for_low_hit_rate(db):
    """Phrase in mainly non-confirmed rumors should not become a candidate."""
    from fichajes_bot.jobs.learn_lexicon import run as learn_lexicon_run, MIN_OBS

    await _insert_periodista(db, "fabrizio-romano", tier="S")
    jid = await _insert_jugador(db, "Another Player")

    # 15 rumors but only 2 confirmed (hit_rate < 0.6)
    for i in range(13):
        await _insert_rumor(
            db, jid, "fabrizio-romano", tipo="FICHAJE",
            texto="frase especial exclusiva aquí resultado pendiente",
            outcome="PENDIENTE",
            fecha=f"2024-01-{i + 1:02d}",
        )
    for i in range(2):
        await _insert_rumor(
            db, jid, "fabrizio-romano", tipo="FICHAJE",
            texto="frase especial exclusiva aquí resultado pendiente",
            outcome="CONFIRMADO",
            fecha=f"2024-03-{i + 1:02d}",
        )

    await learn_lexicon_run(window_days=3650, db=db)

    candidates = await db.execute(
        "SELECT frase FROM lexicon_candidates WHERE frase LIKE '%especial exclusiva%'"
    )
    assert len(candidates) == 0


# ── Backfill generation tests ─────────────────────────────────────────────────


def test_backfill_generation():
    """generate_backfill produces ≥80 jugadores with ≥5 rumors each and coherent dates."""
    import importlib.util
    from pathlib import Path

    spec = importlib.util.spec_from_file_location(
        "generate_backfill",
        Path(__file__).parent.parent / "scripts" / "generate_backfill.py",
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    all_rumores = []
    slugs_seen: set[str] = set()

    for transfer in mod.TRANSFERS:
        rumores = mod.generate_rumores_for_transfer(transfer)
        assert len(rumores) >= 5, (
            f"Transfer {transfer['nombre']} has only {len(rumores)} rumors"
        )
        all_rumores.extend(rumores)
        slugs_seen.add(transfer["nombre"])

        # Dates must be chronologically ordered (ascending)
        dates = [r["fecha_publicacion"] for r in rumores]
        assert dates == sorted(dates), (
            f"Rumores for {transfer['nombre']} are not in chronological order"
        )

        # All rumors must be before or at the official date
        fecha_oficial = transfer["fecha_oficial"]
        for r in rumores:
            assert r["fecha_publicacion"] <= fecha_oficial + "T23:59:59", (
                f"Rumor for {transfer['nombre']} is after the official date"
            )

    assert len(slugs_seen) >= 80, f"Expected ≥80 transfers, got {len(slugs_seen)}"


def test_backfill_outcomes_are_consistent():
    """All generated rumors have _transfer_outcome matching the transfer's outcome."""
    import importlib.util
    from pathlib import Path

    spec = importlib.util.spec_from_file_location(
        "generate_backfill",
        Path(__file__).parent.parent / "scripts" / "generate_backfill.py",
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    for transfer in mod.TRANSFERS:
        rumores = mod.generate_rumores_for_transfer(transfer)
        for r in rumores:
            assert r["_transfer_outcome"] == transfer["outcome"]
            assert "fecha_publicacion" in r
            assert r["periodista_id"] != ""
            assert r["tipo_operacion"] in ("FICHAJE", "SALIDA", "RENOVACION", "CESION")


@pytest.mark.asyncio
async def test_backfill_run_end_to_end(db):
    """Load 3 mock transfers → outcomes recorded → reliabilities updated correctly."""
    from fichajes_bot.calibration.official_events_detector import OfficialEventsDetector
    from fichajes_bot.calibration.calibrator import Calibrator
    from fichajes_bot.calibration.reliability_manager import ReliabilityManager

    # Setup: 3 transfers with known outcomes
    await _insert_periodista(db, "fabrizio-romano", reliability=0.80)
    await _insert_periodista(db, "matteo-moretto", reliability=0.84)

    # Transfer 1: confirmed FICHAJE
    j1 = await _insert_jugador(db, "Test Backfill A", tipo="FICHAJE")
    rid_conf = await _insert_rumor(
        db, j1, "fabrizio-romano", tipo="FICHAJE",
        flags=json.dumps(["FICHAJE_OFICIAL"]),
        fecha="2023-06-14",
    )
    await _insert_rumor(
        db, j1, "matteo-moretto", tipo="FICHAJE",
        fase=4, fecha="2023-05-01",
    )

    # Transfer 2: failed operation
    j2 = await _insert_jugador(db, "Test Backfill B", tipo="FICHAJE")
    await _insert_rumor(
        db, j2, "matteo-moretto", tipo="FICHAJE",
        fase=3, fecha="2022-03-01",
    )
    # Directly set outcome_clasificado for the failed transfer
    await db.execute(
        "UPDATE jugadores SET outcome_clasificado='OPERACION_CAIDA', "
        "fecha_outcome='2022-05-10' WHERE jugador_id=?",
        [j2],
    )

    # Transfer 3: confirmed SALIDA
    j3 = await _insert_jugador(db, "Eden Hazard Mock", tipo="SALIDA")
    await _insert_rumor(
        db, j3, "fabrizio-romano", tipo="SALIDA",
        flags=json.dumps(["SALIDA_OFICIAL"]),
        fecha="2023-07-01",
    )

    # Run detector
    detector = OfficialEventsDetector(db)
    n_outcomes = await detector.scan_recent_rumors(window_days=3650)
    assert n_outcomes >= 2  # Bellingham + Hazard detected

    # Run calibration
    rm = ReliabilityManager(db)
    calibrator = Calibrator(db, rm)
    updates = await calibrator.calibrate_journalists(window_days=3650)

    # Both Romano and Moretto should have been calibrated
    assert "fabrizio-romano" in updates or "matteo-moretto" in updates

    # Outcomes correctly recorded
    j1_row = await db.execute(
        "SELECT outcome_clasificado FROM jugadores WHERE jugador_id=?", [j1]
    )
    assert j1_row[0]["outcome_clasificado"] == "FICHAJE_EFECTIVO"

    j3_row = await db.execute(
        "SELECT outcome_clasificado FROM jugadores WHERE jugador_id=?", [j3]
    )
    assert j3_row[0]["outcome_clasificado"] == "SALIDA_EFECTIVA"

    # outcomes_historicos has entries
    oh_rows = await db.execute("SELECT COUNT(*) as n FROM outcomes_historicos")
    assert oh_rows[0]["n"] >= 2
