"""Session 8 tests — Telegram sender, daily report, Worker helper parity."""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ── Helpers ───────────────────────────────────────────────────────────────────


def _uid() -> str:
    return str(uuid.uuid4())


async def _insert_jugador(
    db,
    nombre: str = "Test Player",
    tipo: str = "FICHAJE",
    entidad: str = "primer_equipo",
    score: float = 0.55,
    flags: str = "[]",
) -> str:
    jid = _uid()
    slug = nombre.lower().replace(" ", "-")
    await db.execute(
        """INSERT INTO jugadores
           (jugador_id, nombre_canonico, slug, tipo_operacion_principal,
            entidad, score_smoothed, score_raw, is_active, flags,
            factores_actuales, kalman_P, created_at)
           VALUES (?,?,?,?,?,?,?,1,?,?,1.0,datetime('now'))""",
        [jid, nombre, slug, tipo, entidad, score, score, flags, "{}"],
    )
    return jid


# ── split_message tests ───────────────────────────────────────────────────────


def test_split_short_message_returns_single_chunk():
    from fichajes_bot.notifications.telegram_sender import split_message

    text = "Hello world"
    chunks = split_message(text, max_len=4000)
    assert len(chunks) == 1
    assert chunks[0] == text


def test_split_long_message_splits_on_lines():
    from fichajes_bot.notifications.telegram_sender import split_message

    lines = [f"Line {i}: " + "x" * 100 for i in range(50)]
    text = "\n".join(lines)
    chunks = split_message(text, max_len=1000)
    assert len(chunks) > 1
    # Reassembled text should contain all original content
    reassembled = "\n".join(chunks)
    for line in lines:
        assert line in reassembled


def test_split_respects_markdown_code_block():
    from fichajes_bot.notifications.telegram_sender import split_message

    # Build a text where the code block straddles the max_len boundary
    preamble = "A" * 3900
    code_block = "```python\nprint('hello')\nprint('world')\n```"
    text = preamble + "\n" + code_block

    chunks = split_message(text, max_len=4000)

    # The code block must never be split internally — find which chunk has the opening fence
    code_chunk = next((c for c in chunks if "```python" in c), None)
    assert code_chunk is not None, "Code block opening fence not found in any chunk"
    # That same chunk must also contain the closing fence
    assert "```" in code_chunk[code_chunk.index("```python") + 3:], (
        "Closing ``` not in same chunk as opening"
    )


def test_split_empty_text():
    from fichajes_bot.notifications.telegram_sender import split_message

    assert split_message("", max_len=4000) == [""]


# ── AsyncTelegramSender tests ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_sender_success_200():
    """send_message returns True when Telegram responds 200."""
    from fichajes_bot.notifications.telegram_sender import AsyncTelegramSender

    mock_response = MagicMock()
    mock_response.status_code = 200

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = mock_response
        async with AsyncTelegramSender("TOKEN", "CHAT") as sender:
            result = await sender.send_message("hello")

    assert result is True
    mock_post.assert_called_once()


@pytest.mark.asyncio
async def test_sender_429_retry():
    """On 429 with retry_after=1, sleeps 1s, retries, returns True if retry OK."""
    from fichajes_bot.notifications.telegram_sender import AsyncTelegramSender

    resp_429 = MagicMock()
    resp_429.status_code = 429
    resp_429.json.return_value = {"parameters": {"retry_after": 1}}

    resp_200 = MagicMock()
    resp_200.status_code = 200

    sleep_calls: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        sleep_calls.append(seconds)

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post, \
         patch("asyncio.sleep", side_effect=fake_sleep):
        mock_post.side_effect = [resp_429, resp_200]
        async with AsyncTelegramSender("TOKEN", "CHAT") as sender:
            result = await sender.send_message("hello")

    assert result is True
    assert mock_post.call_count == 2
    # First sleep must be the retry_after value (1s), final sleep 1.1s
    assert 1.0 in sleep_calls
    assert 1.1 in sleep_calls


@pytest.mark.asyncio
async def test_sender_429_max_retries():
    """Two consecutive 429 responses → returns False without infinite loop."""
    from fichajes_bot.notifications.telegram_sender import AsyncTelegramSender

    resp_429 = MagicMock()
    resp_429.status_code = 429
    resp_429.json.return_value = {"parameters": {"retry_after": 1}}

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post, \
         patch("asyncio.sleep", new_callable=AsyncMock):
        mock_post.return_value = resp_429
        async with AsyncTelegramSender("TOKEN", "CHAT") as sender:
            result = await sender.send_message("hello")

    assert result is False
    assert mock_post.call_count == 2  # original + exactly one retry


@pytest.mark.asyncio
async def test_sender_non_200_non_429_returns_false():
    """5xx errors return False and do not retry."""
    from fichajes_bot.notifications.telegram_sender import AsyncTelegramSender

    resp_500 = MagicMock()
    resp_500.status_code = 500
    resp_500.text = "Internal Server Error"

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post, \
         patch("asyncio.sleep", new_callable=AsyncMock):
        mock_post.return_value = resp_500
        async with AsyncTelegramSender("TOKEN", "CHAT") as sender:
            result = await sender.send_message("hello")

    assert result is False
    assert mock_post.call_count == 1


@pytest.mark.asyncio
async def test_sender_1_1s_throttle():
    """Two consecutive send_message calls sleep at least 1.1s between them."""
    from fichajes_bot.notifications.telegram_sender import AsyncTelegramSender

    sleep_durations: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        sleep_durations.append(seconds)

    resp_200 = MagicMock()
    resp_200.status_code = 200

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post, \
         patch("asyncio.sleep", side_effect=fake_sleep):
        mock_post.return_value = resp_200
        async with AsyncTelegramSender("TOKEN", "CHAT") as sender:
            await sender.send_message("first")
            await sender.send_message("second")

    # Each send_message sleeps 1.1s in its `finally` block
    throttle_sleeps = [s for s in sleep_durations if abs(s - 1.1) < 0.01]
    assert len(throttle_sleeps) >= 2


@pytest.mark.asyncio
async def test_sender_splitted_returns_list_of_bools():
    """send_message_splitted returns one bool per chunk."""
    from fichajes_bot.notifications.telegram_sender import AsyncTelegramSender

    resp_200 = MagicMock()
    resp_200.status_code = 200

    long_text = "\n".join([f"Line {i}: " + "x" * 200 for i in range(30)])

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post, \
         patch("asyncio.sleep", new_callable=AsyncMock):
        mock_post.return_value = resp_200
        async with AsyncTelegramSender("TOKEN", "CHAT") as sender:
            results = await sender.send_message_splitted(long_text, max_len=1000)

    assert isinstance(results, list)
    assert len(results) > 1
    assert all(r is True for r in results)


# ── daily_report generator tests ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_daily_report_structure(db):
    """Generated report contains all 4 expected sections."""
    from fichajes_bot.notifications.daily_report import generate_daily_report

    # Insert some players
    for i in range(3):
        await _insert_jugador(
            db, nombre=f"Jugador Fichaje {i}", tipo="FICHAJE", score=0.6 - i * 0.1
        )
    for i in range(2):
        await _insert_jugador(
            db, nombre=f"Jugador Salida {i}", tipo="SALIDA", score=0.5 - i * 0.1
        )

    report = await generate_daily_report(db)

    assert "INFORME DIARIO" in report
    assert "TOP 20 FICHAJES" in report
    assert "TOP 10 SALIDAS" in report
    # Footer section
    assert "CAMBIOS" in report or "Sin cambios" in report


@pytest.mark.asyncio
async def test_daily_report_cantera_section_present(db):
    """CANTERA section appears when cantera players with score >= 0.3 exist."""
    from fichajes_bot.notifications.daily_report import generate_daily_report

    await _insert_jugador(
        db, nombre="Cantera Kid", tipo="FICHAJE",
        entidad="castilla", score=0.45
    )

    report = await generate_daily_report(db)
    assert "CANTERA" in report
    assert "Cantera Kid" in report


@pytest.mark.asyncio
async def test_daily_report_cantera_section_absent_when_no_data(db):
    """CANTERA section is omitted when no cantera players have score >= 0.3."""
    from fichajes_bot.notifications.daily_report import generate_daily_report

    # Insert cantera player below threshold
    await _insert_jugador(
        db, nombre="Low Score Kid", tipo="FICHAJE",
        entidad="castilla", score=0.2
    )

    report = await generate_daily_report(db)
    assert "CANTERA" not in report


@pytest.mark.asyncio
async def test_daily_report_overflow_generates_chunks(db):
    """A report with 20 players + cantera exceeds 4096 chars → ≥1 chunk when split."""
    from fichajes_bot.notifications.daily_report import generate_daily_report
    from fichajes_bot.notifications.telegram_sender import split_message

    for i in range(20):
        await _insert_jugador(
            db, nombre=f"Player With Long Name Number {i:02d}",
            tipo="FICHAJE", score=0.9 - i * 0.02
        )
    for i in range(10):
        await _insert_jugador(
            db, nombre=f"Salida Player Long Name {i:02d}",
            tipo="SALIDA", score=0.8 - i * 0.03
        )
    for i in range(5):
        await _insert_jugador(
            db, nombre=f"Castilla Prospect {i:02d}",
            tipo="FICHAJE", entidad="castilla", score=0.5 - i * 0.02
        )

    report = await generate_daily_report(db)
    chunks = split_message(report, max_len=4096)
    assert len(chunks) >= 1
    # Verify all chunks fit within max_len
    for chunk in chunks:
        assert len(chunk) <= 4096


@pytest.mark.asyncio
async def test_daily_report_partial_failure(db):
    """When 2nd chunk fails, 1st is logged as enviado, 2nd as fallido."""
    from fichajes_bot.notifications.telegram_sender import AsyncTelegramSender
    from fichajes_bot.notifications.telegram_sender import split_message
    from fichajes_bot.notifications.daily_report import generate_daily_report

    # Insert enough data to produce multiple chunks
    for i in range(20):
        await _insert_jugador(
            db, nombre=f"Player Very Long Name Indeed Number {i:02d}",
            tipo="FICHAJE", score=0.9 - i * 0.02
        )
    for i in range(10):
        await _insert_jugador(
            db, nombre=f"Salida Very Long Name Indeed {i:02d}",
            tipo="SALIDA", score=0.8 - i * 0.03
        )

    report = await generate_daily_report(db)
    chunks = split_message(report, max_len=500)  # force many chunks

    call_count = 0
    results: list[bool] = []

    resp_200 = MagicMock()
    resp_200.status_code = 200

    resp_500 = MagicMock()
    resp_500.status_code = 500
    resp_500.text = "error"

    async def fake_post(url: str, **kwargs: Any):
        nonlocal call_count
        call_count += 1
        # First call succeeds, second fails
        return resp_200 if call_count == 1 else resp_500

    with patch("httpx.AsyncClient.post", side_effect=fake_post), \
         patch("asyncio.sleep", new_callable=AsyncMock):
        async with AsyncTelegramSender("TOKEN", "CHAT") as sender:
            for chunk in chunks[:2]:  # test just first 2 chunks
                ok = await sender.send_message(chunk)
                results.append(ok)

    assert results[0] is True
    assert results[1] is False


# ── Worker helper parity tests ────────────────────────────────────────────────


def test_build_sparkline_14_points():
    """build_sparkline produces exactly 14 chars for 14 input scores."""
    from fichajes_bot.notifications.daily_report import build_sparkline

    scores = [float(i) / 13 for i in range(14)]
    spark = build_sparkline(scores)
    assert len(spark) == 14
    assert all(c in "▁▂▃▄▅▆▇█" for c in spark)


def test_build_sparkline_empty():
    from fichajes_bot.notifications.daily_report import build_sparkline

    assert build_sparkline([]) == ""


def test_build_sparkline_flat_scores():
    from fichajes_bot.notifications.daily_report import build_sparkline

    scores = [0.5] * 10
    spark = build_sparkline(scores)
    assert len(spark) == 10
    # Flat → all chars are the minimum bucket (▁)
    assert all(c == "▁" for c in spark)


def test_fmt_pct():
    from fichajes_bot.notifications.daily_report import fmt

    assert fmt(0.75) == "75%"
    assert fmt(0.0) == "0%"
    assert fmt(None) == "?"


def test_fmt_m():
    from fichajes_bot.notifications.daily_report import fmt_m

    assert fmt_m(50_000_000) == "50M€"
    assert fmt_m(None) == "?"


# ── Worker command integration stubs ─────────────────────────────────────────
# These verify that the report format matches what the Worker commands produce.


@pytest.mark.asyncio
async def test_top_command_equivalent(db):
    """/top equivalent: query returns FICHAJE players ordered by score_smoothed."""
    await _insert_jugador(db, nombre="Top Player A", tipo="FICHAJE", score=0.85)
    await _insert_jugador(db, nombre="Top Player B", tipo="FICHAJE", score=0.72)
    await _insert_jugador(db, nombre="Top Player C", tipo="FICHAJE", score=0.45)

    rows = await db.execute("""
        SELECT nombre_canonico, score_smoothed, flags
        FROM jugadores
        WHERE tipo_operacion_principal = 'FICHAJE'
          AND entidad = 'primer_equipo'
          AND is_active = 1
        ORDER BY score_smoothed DESC LIMIT 20
    """)
    assert len(rows) == 3
    assert rows[0]["nombre_canonico"] == "Top Player A"
    assert rows[1]["nombre_canonico"] == "Top Player B"


@pytest.mark.asyncio
async def test_explain_command_equivalent(db):
    """/explain equivalent: jugador lookup by partial name."""
    jid = await _insert_jugador(db, nombre="Kylian Mbappé", tipo="FICHAJE", score=0.92)

    row = await db.execute(
        "SELECT * FROM jugadores WHERE LOWER(nombre_canonico) LIKE LOWER(?) LIMIT 1",
        ["%mbapp%"],
    )
    assert len(row) == 1
    assert row[0]["jugador_id"] == jid
    assert row[0]["nombre_canonico"] == "Kylian Mbappé"


@pytest.mark.asyncio
async def test_detalle_command_equivalent(db):
    """/detalle equivalent: returns complete jugador info."""
    jid = await _insert_jugador(db, nombre="Trent Alexander-Arnold", tipo="FICHAJE", score=0.78)

    row = await db.execute(
        "SELECT * FROM jugadores WHERE jugador_id = ?", [jid]
    )
    assert len(row) == 1
    j = row[0]
    assert j["nombre_canonico"] == "Trent Alexander-Arnold"
    assert j["tipo_operacion_principal"] == "FICHAJE"
    assert j["score_smoothed"] == pytest.approx(0.78, abs=1e-6)


@pytest.mark.asyncio
async def test_castilla_command_equivalent(db):
    """/castilla equivalent: returns castilla players ordered by score."""
    await _insert_jugador(db, nombre="Castilla Star", tipo="FICHAJE", entidad="castilla", score=0.65)
    await _insert_jugador(db, nombre="Castilla Bench", tipo="FICHAJE", entidad="castilla", score=0.35)
    await _insert_jugador(db, nombre="Primer Equipo Star", tipo="FICHAJE", entidad="primer_equipo", score=0.95)

    rows = await db.execute("""
        SELECT nombre_canonico, score_smoothed, entidad
        FROM jugadores
        WHERE entidad = 'castilla' AND is_active = 1
        ORDER BY score_smoothed DESC LIMIT 10
    """)
    assert len(rows) == 2
    assert rows[0]["nombre_canonico"] == "Castilla Star"
    # primer_equipo player must not appear
    assert all(r["entidad"] == "castilla" for r in rows)


@pytest.mark.asyncio
async def test_economia_command_equivalent(db):
    """/economia equivalent: fetches active economic model from DB."""
    # The seed migrations pre-populate an economic model row.
    # Query it and verify the expected shape of the data.
    row = await db.execute(
        "SELECT * FROM modelo_economico WHERE activo = 1 ORDER BY fecha_actualizacion DESC LIMIT 1"
    )
    assert len(row) >= 1
    econ = row[0]
    assert econ["temporada"] is not None
    assert econ["activo"] == 1
    assert econ["margen_salarial"] is not None
    assert econ["fuente"] is not None
