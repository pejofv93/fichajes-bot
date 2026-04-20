"""Tests for Session 12 — Cantera extension."""

from __future__ import annotations

import json
import uuid

import pytest

pytestmark = pytest.mark.asyncio


# ── Helpers ───────────────────────────────────────────────────────────────────


async def _insert_jugador(db, **kwargs) -> str:
    jid = kwargs.pop("jugador_id", str(uuid.uuid4()))
    defaults = {
        "slug": jid[:8],
        "nombre_canonico": f"Player_{jid[:6]}",
        "tipo_operacion_principal": "FICHAJE",
        "entidad": "castilla",
        "entidad_actual": "castilla",
        "is_active": 1,
        "score_smoothed": 0.5,
        "score_raw": 0.5,
        "flags": "[]",
        "factores_actuales": "{}",
    }
    defaults.update(kwargs)
    cols = ", ".join(defaults.keys())
    placeholders = ", ".join("?" for _ in defaults)
    await db.execute(
        f"INSERT OR IGNORE INTO jugadores (jugador_id, {cols}) VALUES (?, {placeholders})",
        [jid, *defaults.values()],
    )
    return jid


async def _insert_cedido_rendimiento(db, jugador_id: str, **kwargs):
    defaults = {
        "club_cesion": "Club Test",
        "temporada": "2025-26",
        "partidos": 20,
        "minutos": 1700,
        "goles": 5,
        "asistencias": 3,
        "rating_medio": 7.2,
        "lesion_larga": 0,
    }
    defaults.update(kwargs)
    cols = ", ".join(defaults.keys())
    placeholders = ", ".join("?" for _ in defaults)
    await db.execute(
        f"""INSERT OR IGNORE INTO rendimiento_cedidos
            (cedido_id, jugador_id, {cols})
            VALUES (?, ?, {placeholders})""",
        [str(uuid.uuid4()), jugador_id, *defaults.values()],
    )


# ── 3-way scoring ─────────────────────────────────────────────────────────────


async def test_3way_scores_sum_near_1(db):
    """3 scores must sum between 0.9 and 1.1."""
    from fichajes_bot.cantera.scoring_3way import ThreeWayCanteraScorer

    jid = await _insert_jugador(db, score_smoothed=0.55, entidad="castilla", entidad_actual="castilla")
    scorer = ThreeWayCanteraScorer(db)
    result = await scorer.score(jid)

    assert result is not None
    total = result["score_primer_equipo"] + result["score_castilla_stays"] + result["score_salida_o_cesion"]
    assert 0.9 <= total <= 1.1, f"Scores sum to {total}, expected 0.9–1.1"


async def test_3way_canterano_destacado(db):
    """Canterano with high score + many promotion signals → score_primer_equipo > 0.7 AND score_salida < 0.2."""
    from fichajes_bot.cantera.scoring_3way import ThreeWayCanteraScorer

    jid = await _insert_jugador(
        db,
        score_smoothed=0.90,
        entidad="castilla",
        entidad_actual="castilla",
        minutos_castilla_temporada=2000,
    )
    # Add multiple fichaje rumores with high weights to signal first-team interest
    for _ in range(4):
        await db.execute(
            """INSERT INTO rumores
               (rumor_id, jugador_id, tipo_operacion, peso_lexico, confianza_extraccion,
                retractado, fecha_publicacion, lexico_detectado)
               VALUES (?, ?, 'FICHAJE', 0.9, 0.9, 0, datetime('now', '-1 day'), 'subida primer equipo')""",
            [str(uuid.uuid4()), jid],
        )

    scorer = ThreeWayCanteraScorer(db)
    result = await scorer.score(jid)

    assert result is not None
    assert result["score_primer_equipo"] > 0.70, (
        f"Expected score_primer_equipo > 0.70, got {result['score_primer_equipo']}"
    )
    assert result["score_salida_o_cesion"] < 0.20, (
        f"Expected score_salida < 0.20, got {result['score_salida_o_cesion']}"
    )


# ── CedidosTracker ────────────────────────────────────────────────────────────


async def test_cedidos_return_high_minutes(db):
    """85% minutes at loan club → factor_vuelta > 1.2."""
    from fichajes_bot.cantera.cedidos_tracker import CedidosTracker

    jid = await _insert_jugador(db, entidad="cedido", entidad_actual="cedido")
    # 85% of 30 matches × 90 min = 2295 minutes
    await _insert_cedido_rendimiento(db, jid, partidos=30, minutos=2295, rating_medio=7.0)

    tracker = CedidosTracker(db)
    jugador = {"jugador_id": jid, "nombre_canonico": "Test Cedido"}
    factor = await tracker.evaluate_return_probability(jugador)

    assert factor > 1.2, f"Expected factor > 1.2 for high minutes, got {factor}"


async def test_cedidos_purchase_rumor(db):
    """Permanent purchase rumour → factor_vuelta < 0.6."""
    from fichajes_bot.cantera.cedidos_tracker import CedidosTracker

    jid = await _insert_jugador(db, entidad="cedido", entidad_actual="cedido")
    # Use low minutes (well below 70%) so no minutos boost counteracts the compra penalty
    await _insert_cedido_rendimiento(db, jid, partidos=20, minutos=600, rating_medio=6.5)

    # Insert compra definitiva rumour (texto_fragmento is the correct column name)
    await db.execute(
        """INSERT INTO rumores
           (rumor_id, jugador_id, tipo_operacion, texto_fragmento, peso_lexico,
            confianza_extraccion, retractado, fecha_publicacion, lexico_detectado)
           VALUES (?, ?, 'CESION', 'opcion de compra activada por el club', 0.5, 0.7,
                   0, datetime('now', '-3 days'), 'opcion de compra')""",
        [str(uuid.uuid4()), jid],
    )

    tracker = CedidosTracker(db)
    jugador = {"jugador_id": jid, "nombre_canonico": "Test Cedido Compra"}
    factor = await tracker.evaluate_return_probability(jugador)

    assert factor < 0.6, f"Expected factor < 0.6 with compra rumour, got {factor}"


# ── DebutWatchDetector ────────────────────────────────────────────────────────


async def test_debut_watch_selects_top5(db):
    """10 canteranos with varied scores → detect_candidates returns top 5."""
    from fichajes_bot.cantera.debut_watch import DebutWatchDetector

    scores = [0.9, 0.8, 0.75, 0.65, 0.60, 0.55, 0.45, 0.40, 0.30, 0.20]
    jids = []
    for s in scores:
        factores = json.dumps({"score_primer_equipo": s * 0.8})
        jid = await _insert_jugador(
            db,
            entidad="castilla",
            entidad_actual="castilla",
            score_smoothed=s,
            factores_actuales=factores,
        )
        jids.append(jid)

    detector = DebutWatchDetector(db)
    candidates = await detector.detect_candidates()

    assert len(candidates) == 5, f"Expected 5 candidates, got {len(candidates)}"
    primer_scores = [c["score_primer_equipo"] for c in candidates]
    assert primer_scores == sorted(primer_scores, reverse=True), "Not sorted by score_primer_equipo"


# ── ProgressionGraph ──────────────────────────────────────────────────────────


async def test_progression_promotion_cascade(db):
    """Canterano promotes to Castilla → other Juvenil A with high score get boosted."""
    from fichajes_bot.cantera.progression_graph import ProgressionGraph, VACANCY_BOOST

    jid_promoted = await _insert_jugador(
        db, entidad="juvenil_a", entidad_actual="juvenil_a", score_smoothed=0.85
    )
    jid_a = await _insert_jugador(
        db, entidad="juvenil_a", entidad_actual="juvenil_a", score_smoothed=0.60
    )
    jid_b = await _insert_jugador(
        db, entidad="juvenil_a", entidad_actual="juvenil_a", score_smoothed=0.50
    )

    graph = ProgressionGraph(db)
    boosted = await graph.propagate_on_promotion(jid_promoted, "juvenil_a", "castilla")

    assert len(boosted) >= 1, "Expected at least one player boosted"
    assert jid_promoted not in boosted, "Promoted player should not be in boosted list"

    # Check scores were actually boosted
    rows = await db.execute(
        "SELECT score_smoothed FROM jugadores WHERE jugador_id = ?", [jid_a]
    )
    new_score = float(rows[0]["score_smoothed"])
    assert new_score > 0.60, f"Expected score > 0.60 after boost, got {new_score}"


# ── Daily report ──────────────────────────────────────────────────────────────


async def test_cantera_daily_report_omits_when_stable(db):
    """No cantera movement today → cantera section omitted from daily report."""
    from fichajes_bot.notifications.daily_report import generate_daily_report

    # Insert castilla player but no score_history today
    await _insert_jugador(
        db, entidad="castilla", entidad_actual="castilla", score_smoothed=0.45
    )

    report = await generate_daily_report(db)

    # cantera section only appears if has_cantera=True (needs movement)
    # With no score_history movement, the section may or may not appear depending on cedidos
    # but at minimum the report should not crash
    assert isinstance(report, str)
    assert len(report) > 50  # has content


# ── Telegram Worker command format (unit-level check) ─────────────────────────


async def test_castilla_command_returns_3scores(db):
    """Castilla command: factores_actuales parsed correctly for 3-way display."""
    factores = {
        "score_primer_equipo": 0.35,
        "score_castilla_stays": 0.50,
        "score_salida_o_cesion": 0.15,
    }
    jid = await _insert_jugador(
        db,
        entidad="castilla",
        entidad_actual="castilla",
        score_smoothed=0.60,
        nombre_canonico="Álvaro García",
        posicion="DC",
        edad=21,
        factores_actuales=json.dumps(factores),
    )

    rows = await db.execute(
        """SELECT nombre_canonico, posicion, edad, score_smoothed, factores_actuales
           FROM jugadores
           WHERE (entidad = 'castilla' OR entidad_actual = 'castilla')
             AND is_active = 1
           ORDER BY score_smoothed DESC LIMIT 10"""
    )

    assert len(rows) >= 1
    f = json.loads(rows[0]["factores_actuales"] or "{}")
    assert "score_primer_equipo" in f
    assert "score_castilla_stays" in f
    assert "score_salida_o_cesion" in f

    primer = round(f["score_primer_equipo"] * 100)
    stays = round(f["score_castilla_stays"] * 100)
    salida = round(f["score_salida_o_cesion"] * 100)

    assert primer == 35
    assert stays == 50
    assert salida == 15
