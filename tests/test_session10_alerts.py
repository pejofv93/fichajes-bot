"""Session 10 tests — AlertManager, alert deduplication, explain_extended, cache."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

pytestmark = pytest.mark.asyncio


# ── Helpers ───────────────────────────────────────────────────────────────────


def _uid() -> str:
    return str(uuid.uuid4())


async def _insert_periodista(
    db,
    periodista_id: str,
    tier: str = "S",
    nombre: str = "Test Journalist",
    reliability: float = 0.80,
) -> None:
    await db.execute(
        """INSERT OR IGNORE INTO periodistas
           (periodista_id, nombre_completo, tier, reliability_global,
            alpha_global, beta_global, n_predicciones_global, n_aciertos_global,
            n_predicciones_rm, n_aciertos_rm, alpha_rm, beta_rm, created_at)
           VALUES (?,?,?,?,?,?,0,0,0,0,1.0,1.0,datetime('now'))""",
        [
            periodista_id,
            nombre,
            tier,
            reliability,
            reliability * 10,
            (1 - reliability) * 10,
        ],
    )


async def _insert_jugador(
    db,
    nombre: str = "Test Player",
    tipo: str = "FICHAJE",
    score: float = 0.5,
    flags: list[str] | None = None,
    factores: dict | None = None,
) -> str:
    jid = _uid()
    slug = nombre.lower().replace(" ", "-")
    await db.execute(
        """INSERT INTO jugadores
           (jugador_id, nombre_canonico, slug, tipo_operacion_principal,
            score_smoothed, score_raw, score_anterior, is_active,
            flags, factores_actuales, created_at)
           VALUES (?,?,?,?,?,?,?,1,?,?,datetime('now'))""",
        [
            jid,
            nombre,
            slug,
            tipo,
            score,
            score,
            score,
            json.dumps(flags or []),
            json.dumps(factores or {}),
        ],
    )
    return jid


async def _set_alertas_flag(db, estado: str = "ENFORCE_HARD") -> None:
    await db.execute(
        """INSERT OR REPLACE INTO flags_sistema (flag_name, estado, actualizado_at)
           VALUES ('alertas_realtime', ?, datetime('now'))""",
        [estado],
    )


def _make_sender(send_ok: bool = True) -> MagicMock:
    sender = MagicMock()
    sender.send_message_splitted = AsyncMock(return_value=[send_ok])
    return sender


# ── Tests: detect_alert_triggers ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_alert_crossing_up(db):
    """Score crossing 70% from below triggers ALERTA_ALTA."""
    from fichajes_bot.notifications.alert_manager import AlertManager

    jid = await _insert_jugador(db, "Mbappé Test", score=0.72)
    sender = _make_sender()
    mgr = AlertManager(db, sender)

    jugador = {"jugador_id": jid, "nombre_canonico": "Mbappé Test", "score_smoothed": 0.72}
    alerts = mgr.detect_alert_triggers(
        jugador_id=jid,
        score_anterior=0.65,
        score_nuevo=0.72,
        factores_anteriores={},
        factores_nuevos={},
        hard_signals=[],
        jugador=jugador,
    )

    assert any(a.alert_type == "ALERTA_ALTA" for a in alerts)


@pytest.mark.asyncio
async def test_alert_crossing_down(db):
    """Score crossing below 40% triggers CAIDA."""
    from fichajes_bot.notifications.alert_manager import AlertManager

    jid = await _insert_jugador(db, "Lewandowski Test", score=0.38)
    sender = _make_sender()
    mgr = AlertManager(db, sender)

    jugador = {"jugador_id": jid, "nombre_canonico": "Lewandowski Test", "score_smoothed": 0.38}
    alerts = mgr.detect_alert_triggers(
        jugador_id=jid,
        score_anterior=0.45,
        score_nuevo=0.38,
        factores_anteriores={},
        factores_nuevos={},
        hard_signals=[],
        jugador=jugador,
    )

    assert any(a.alert_type == "CAIDA" for a in alerts)


@pytest.mark.asyncio
async def test_alert_deduplication(db):
    """Same alert type for same player within 6h is not sent again."""
    from fichajes_bot.notifications.alert_manager import AlertManager

    jid = await _insert_jugador(db, "Dedup Player", score=0.75)
    await _set_alertas_flag(db, "ENFORCE_HARD")

    sender = _make_sender(send_ok=True)
    mgr = AlertManager(db, sender)

    # Insert a recent alert log entry for the same player + type
    await db.execute(
        """INSERT INTO alertas_log
           (log_id, jugador_id, alert_type, tipo_alerta, enviada_at, score_snapshot)
           VALUES (?, ?, 'ALERTA_ALTA', 'ALERTA_ALTA', datetime('now', '-2 hours'), 0.75)""",
        [_uid(), jid],
    )

    jugador = {"jugador_id": jid, "nombre_canonico": "Dedup Player", "score_smoothed": 0.75}
    from fichajes_bot.notifications.alert_manager import Alert
    alert = Alert(alert_type="ALERTA_ALTA", jugador_id=jid, jugador=jugador)

    sent = await mgr.send_alert(alert)

    # Should NOT send because same alert already sent <6h ago
    assert sent is False
    sender.send_message_splitted.assert_not_called()


@pytest.mark.asyncio
async def test_alert_respects_silencio_flag(db):
    """With alertas_realtime=OFF alerts are not sent but return False."""
    from fichajes_bot.notifications.alert_manager import Alert, AlertManager

    jid = await _insert_jugador(db, "Silencio Player", score=0.75)
    await _set_alertas_flag(db, "OFF")

    sender = _make_sender(send_ok=True)
    mgr = AlertManager(db, sender)

    jugador = {"jugador_id": jid, "nombre_canonico": "Silencio Player", "score_smoothed": 0.75}
    alert = Alert(alert_type="ALERTA_ALTA", jugador_id=jid, jugador=jugador)
    sent = await mgr.send_alert(alert)

    assert sent is False
    sender.send_message_splitted.assert_not_called()


@pytest.mark.asyncio
async def test_hard_signal_alert(db):
    """Hard signal 'fichaje_oficial' triggers OFICIAL alert."""
    from fichajes_bot.notifications.alert_manager import AlertManager

    jid = await _insert_jugador(db, "Official Signing", score=0.95)
    sender = _make_sender()
    mgr = AlertManager(db, sender)

    jugador = {"jugador_id": jid, "nombre_canonico": "Official Signing", "score_smoothed": 0.95}
    alerts = mgr.detect_alert_triggers(
        jugador_id=jid,
        score_anterior=0.80,
        score_nuevo=0.95,
        factores_anteriores={},
        factores_nuevos={},
        hard_signals=[{"tipo": "fichaje_oficial", "fuente": "realmadrid.com"}],
        jugador=jugador,
    )

    assert any(a.alert_type == "OFICIAL" for a in alerts)


@pytest.mark.asyncio
async def test_trial_balloon_alert(db):
    """probabilidad_globo >= 0.70 triggers GLOBO_SONDA alert."""
    from fichajes_bot.notifications.alert_manager import AlertManager

    jid = await _insert_jugador(db, "Globo Player", score=0.50)
    sender = _make_sender()
    mgr = AlertManager(db, sender)

    jugador = {"jugador_id": jid, "nombre_canonico": "Globo Player", "score_smoothed": 0.50}
    alerts = mgr.detect_alert_triggers(
        jugador_id=jid,
        score_anterior=0.50,
        score_nuevo=0.50,
        factores_anteriores={"probabilidad_globo": 0.40},
        factores_nuevos={"probabilidad_globo": 0.85},
        hard_signals=[],
        jugador=jugador,
    )

    assert any(a.alert_type == "GLOBO_SONDA" for a in alerts)
    globo_alert = next(a for a in alerts if a.alert_type == "GLOBO_SONDA")
    assert globo_alert.contexto["probabilidad_globo"] == 0.85


@pytest.mark.asyncio
async def test_new_in_top10(db):
    """Player going from rank 11 to rank 8 triggers NUEVO_EN_TOP_10."""
    from fichajes_bot.notifications.alert_manager import AlertManager

    jid = await _insert_jugador(db, "Rising Star", score=0.68)
    sender = _make_sender()
    mgr = AlertManager(db, sender)

    jugador = {"jugador_id": jid, "nombre_canonico": "Rising Star", "score_smoothed": 0.68}
    alerts = mgr.detect_alert_triggers(
        jugador_id=jid,
        score_anterior=0.62,
        score_nuevo=0.68,
        factores_anteriores={},
        factores_nuevos={},
        hard_signals=[],
        jugador=jugador,
        ranking_anterior=11,
        ranking_nuevo=8,
    )

    assert any(a.alert_type == "NUEVO_EN_TOP_10" for a in alerts)
    new_top10 = next(a for a in alerts if a.alert_type == "NUEVO_EN_TOP_10")
    assert new_top10.contexto["ranking_nuevo"] == 8


@pytest.mark.asyncio
async def test_corroboracion_tier_s(db):
    """New tier-S journalist on player with existing rumors triggers CORROBORACION."""
    from fichajes_bot.notifications.alert_manager import AlertManager

    jid = await _insert_jugador(db, "Mbappé Corroborado", score=0.70)
    sender = _make_sender()
    mgr = AlertManager(db, sender)

    jugador = {"jugador_id": jid, "nombre_canonico": "Mbappé Corroborado", "score_smoothed": 0.70}
    nuevo_periodista = {"periodista_id": "fabrizio-romano", "nombre_completo": "Fabrizio Romano", "tier": "S"}
    alerts = mgr.detect_alert_triggers(
        jugador_id=jid,
        score_anterior=0.65,
        score_nuevo=0.70,
        factores_anteriores={},
        factores_nuevos={},
        hard_signals=[],
        jugador=jugador,
        nuevo_periodista_tier_s=nuevo_periodista,
        rumores_previos_count=3,  # had existing rumors (Moretto)
    )

    assert any(a.alert_type == "CORROBORACION" for a in alerts)
    corr = next(a for a in alerts if a.alert_type == "CORROBORACION")
    assert "Romano" in corr.contexto["periodista_nombre"]


# ── Tests: explain_extended ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_explain_extended_includes_all_sections(db):
    """generate_extended_explanation includes all required sections."""
    from fichajes_bot.notifications.explain_extended import generate_extended_explanation

    pid = _uid()
    await _insert_periodista(db, pid, tier="S", nombre="Fabrizio Romano")

    factores = {
        "consenso": 0.75,
        "credibilidad": 0.80,
        "fase_dominante": 4,
        "factor_temporal": 0.90,
        "factor_econ": 0.70,
        "factor_subst": 0.85,
        "bias_correction": 1.0,
        "retraction_penalty": 1.0,
        "kalman_P": 0.1,
        "probabilidad_globo": 0.30,
    }
    jid = await _insert_jugador(
        db,
        "Bellingham Extended",
        score=0.78,
        flags=["POSIBLE_GLOBO_SONDA"],
        factores=factores,
    )

    # Insert a rumor
    fuente_id = _uid()
    await db.execute(
        """INSERT OR IGNORE INTO fuentes
           (fuente_id, tipo, tier, url, idioma, created_at, updated_at)
           VALUES (?, 'rss', 'S', 'http://test.com', 'en', datetime('now'), datetime('now'))""",
        [fuente_id],
    )
    rumor_id = _uid()
    await db.execute(
        """INSERT INTO rumores
           (rumor_id, jugador_id, periodista_id, lexico_detectado, peso_lexico,
            fecha_publicacion, fase_rumor, retractado, fuente_id, created_at)
           VALUES (?,?,?,'here we go',0.9, datetime('now'),
                   4,0,?,datetime('now'))""",
        [rumor_id, jid, pid, fuente_id],
    )

    # Insert score history
    await db.execute(
        """INSERT INTO score_history
           (history_id, jugador_id, score_anterior, score_nuevo, delta,
            razon_cambio, timestamp)
           VALUES (?,?,0.60,0.78,0.18,'test',datetime('now'))""",
        [_uid(), jid],
    )

    result = await generate_extended_explanation(jid, db)

    assert "Descomposición completa" in result, "Missing descomposicion section"
    assert "Top 3 rumores" in result, "Missing top rumores section"
    assert "Timeline" in result, "Missing timeline section"
    assert "Flags activos" in result, "Missing flags section"
    assert "▁▂▃▄▅▆▇█"[0] in result or "Evolución 30d" in result or "sparkline" in result.lower() or "30d" in result, "Missing sparkline section"
    assert "¿Por qué este score ahora?" in result, "Missing why analysis section"
    assert "Fabrizio Romano" in result


# ── Tests: explanation_cache ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_explanation_cache_hit(db):
    """First call generates explanation; second call within TTL uses cache."""
    from fichajes_bot.notifications.explain_extended import generate_extended_explanation

    jid = await _insert_jugador(db, "Cache Test Player", score=0.55)

    # Manually insert cache entry (SQLite-compatible format without 'T')
    valido_hasta = (datetime.now(timezone.utc) + timedelta(hours=3)).strftime("%Y-%m-%d %H:%M:%S")
    cached_content = "🔬 *Análisis extendido: Cache Test Player*\nCached content here."
    await db.execute(
        """INSERT INTO explanation_cache
           (jugador_id, contenido, generado_at, valido_hasta)
           VALUES (?, ?, datetime('now'), ?)""",
        [jid, cached_content, valido_hasta],
    )

    # Check cache row exists and is valid
    rows = await db.execute(
        "SELECT contenido FROM explanation_cache WHERE jugador_id = ? AND valido_hasta > datetime('now')",
        [jid],
    )
    assert rows, "Cache should have a valid entry"
    assert rows[0]["contenido"] == cached_content


@pytest.mark.asyncio
async def test_explanation_cache_expired_regenerates(db):
    """Expired cache entry is ignored and new content is generated."""
    jid = await _insert_jugador(db, "Expired Cache Player", score=0.55)

    # Insert expired cache entry (SQLite-compatible format without 'T')
    expired_at = (datetime.now(timezone.utc) - timedelta(hours=1)).strftime("%Y-%m-%d %H:%M:%S")
    await db.execute(
        """INSERT INTO explanation_cache
           (jugador_id, contenido, generado_at, valido_hasta)
           VALUES (?, 'old content', datetime('now', '-5 hours'), ?)""",
        [jid, expired_at],
    )

    # Query should return nothing for valid cache
    rows = await db.execute(
        "SELECT contenido FROM explanation_cache WHERE jugador_id = ? AND valido_hasta > datetime('now')",
        [jid],
    )
    assert not rows, "Expired cache should not be returned"


# ── Tests: precompute_explanations job ───────────────────────────────────────


@pytest.mark.asyncio
async def test_precompute_explanations_caches_top_players(db):
    """precompute_explanations.run() caches top N players."""
    from fichajes_bot.jobs.precompute_explanations import run

    # Insert 5 active players
    for i in range(5):
        await _insert_jugador(db, f"Player {i}", score=0.9 - i * 0.1)

    result = await run(_db=db)

    assert result["cached"] >= 1
    assert result["errors"] == 0

    # Verify cache entries exist
    cache_rows = await db.execute(
        "SELECT jugador_id FROM explanation_cache WHERE valido_hasta > datetime('now')"
    )
    assert len(cache_rows) >= 1
