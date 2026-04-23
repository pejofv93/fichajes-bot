"""Daily report generator — Variante B format."""

from __future__ import annotations

import json
from datetime import date
from typing import Any

from loguru import logger

from fichajes_bot.persistence.d1_client import D1Client


# ── Helpers (mirrored from Worker TS utilities) ────────────────────────────


def fmt(v: float | None) -> str:
    if v is None:
        return "?"
    return f"{round(v * 100)}%"


def fmt_m(v: float | None) -> str:
    if v is None:
        return "?"
    return f"{v / 1_000_000:.0f}M€"


def build_sparkline(scores: list[float]) -> str:
    if not scores:
        return ""
    chars = "▁▂▃▄▅▆▇█"
    min_s = min(scores)
    max_s = max(scores)
    rng = max_s - min_s or 0.01
    return "".join(
        chars[min(7, int(((s - min_s) / rng) * 8))] for s in scores
    )


def _is_market_open(d: date) -> bool:
    """Heuristic: summer window (Jun–Aug) and winter window (Jan) are open."""
    return d.month in (1, 6, 7, 8)


def _parse_flags(raw: Any) -> list[str]:
    if isinstance(raw, list):
        return raw
    if isinstance(raw, str):
        try:
            return json.loads(raw)
        except Exception:
            return []
    return []


def _clean_nombre(raw: Any) -> str:
    """Strip markdown asterisks that may have been stored in nombre_canonico."""
    return (raw or "?").strip("*").strip()


def _player_line(r: dict[str, Any], i: int) -> str:
    pct = round((r.get("score_smoothed") or 0) * 100)
    em = "🟢" if pct >= 70 else "🟡" if pct >= 40 else "🔴"
    flags = _parse_flags(r.get("flags"))
    glob_flag = " 🎭" if "POSIBLE_GLOBO_SONDA" in flags else ""
    nombre = _clean_nombre(r.get("nombre_canonico"))
    return f"{i + 1}. {em} *{nombre}* · {pct}%{glob_flag}"


# ── Main generator ─────────────────────────────────────────────────────────


async def generate_daily_report(d1: D1Client) -> str:
    """Query D1 and return the full Variante B daily report as Markdown."""
    today = date.today()
    fecha_str = today.strftime("%d/%m/%Y")
    mercado_str = "🟢 ABIERTO" if _is_market_open(today) else "🔴 CERRADO"

    fichajes = await d1.execute("""
        SELECT nombre_canonico, score_smoothed, flags
        FROM jugadores
        WHERE tipo_operacion_principal = 'FICHAJE'
          AND entidad = 'primer_equipo'
          AND is_active = 1
          AND (
            score_smoothed >= 0.05
            OR EXISTS (
              SELECT 1 FROM rumores r
              WHERE r.jugador_id = jugadores.jugador_id
                AND r.created_at > datetime('now', '-60 days')
            )
          )
        ORDER BY score_smoothed DESC LIMIT 20
    """)

    salidas = await d1.execute("""
        SELECT nombre_canonico, score_smoothed, flags
        FROM jugadores
        WHERE tipo_operacion_principal = 'SALIDA'
          AND entidad = 'primer_equipo'
          AND is_active = 1
        ORDER BY score_smoothed DESC LIMIT 10
    """)

    cantera_rows = await d1.execute("""
        SELECT jugador_id, nombre_canonico, score_smoothed, entidad,
               flags, factores_actuales
        FROM jugadores
        WHERE entidad IN ('castilla', 'juvenil_a')
          AND is_active = 1
          AND (
            score_smoothed >= 0.05
            OR EXISTS (
              SELECT 1 FROM rumores r
              WHERE r.jugador_id = jugadores.jugador_id
                AND r.created_at > datetime('now', '-60 days')
            )
          )
        ORDER BY entidad, score_smoothed DESC LIMIT 15
    """)

    # cedidos_rows is now fetched later with rendimiento_cedidos JOIN

    try:
        retractados = await d1.execute("""
            SELECT j.nombre_canonico, p.nombre_completo AS periodista,
                   r.fecha_publicacion
            FROM rumores r
            LEFT JOIN jugadores j ON r.jugador_id = j.jugador_id
            LEFT JOIN periodistas p ON r.periodista_id = p.periodista_id
            WHERE r.retractado = 1
              AND date(r.retractado_at) = date('now')
            ORDER BY r.retractado_at DESC LIMIT 5
        """)
    except Exception:
        retractados = []

    try:
        cambios = await d1.execute("""
            SELECT j.nombre_canonico, sh.delta, sh.razon_cambio
            FROM score_history sh
            JOIN jugadores j ON sh.jugador_id = j.jugador_id
            WHERE date(sh.timestamp) = date('now')
            ORDER BY ABS(sh.delta) DESC LIMIT 5
        """)
    except Exception:
        cambios = []

    lines: list[str] = [
        f"📅 *INFORME DIARIO — {fecha_str}*",
        f"Mercado: {mercado_str}",
        "━━━━━━━━━━━━━━━━━━━━",
        "",
        "🏆 *TOP 20 FICHAJES*",
    ]

    if fichajes:
        for i, r in enumerate(fichajes):
            lines.append(_player_line(r, i))
    else:
        lines.append("_Pocos movimientos esta semana — mercado tranquilo_ 😴")
    lines.append("")

    lines.append("📤 *TOP 10 SALIDAS*")
    if salidas:
        for i, r in enumerate(salidas):
            lines.append(_player_line(r, i))
    else:
        lines.append("_Sin datos todavía_")
    lines.append("")

    if retractados:
        lines.append("🚫 *RUMORES RETRACTADOS HOY*")
        for r in retractados:
            nombre = r.get("nombre_canonico") or "Jugador desconocido"
            periodista = r.get("periodista") or "fuente desconocida"
            fecha = (r.get("fecha_publicacion") or "")[:10]
            lines.append(f"• {nombre} — {periodista} ({fecha})")
        lines.append("")

    if cambios:
        lines.append("📈 *MAYORES CAMBIOS HOY*")
        seen_cambios: set[str] = set()
        for r in cambios:
            nombre = _clean_nombre(r.get("nombre_canonico"))
            if nombre.lower() in seen_cambios:
                continue
            seen_cambios.add(nombre.lower())
            delta = r.get("delta") or 0.0
            sign = "+" if delta >= 0 else ""
            pct_delta = f"{sign}{round(delta * 100)}%"
            razon = r.get("razon_cambio") or "?"
            lines.append(f"• *{nombre}* {pct_delta} — {razon}")
    else:
        lines.append("_Sin cambios significativos hoy_")
    lines.append("")

    # ── Castilla & Cantera — always shown at end ───────────────────────────
    castilla = [r for r in cantera_rows if r.get("entidad") == "castilla"]
    juvenil  = [r for r in cantera_rows if r.get("entidad") == "juvenil_a"]

    cedidos_with_metrics = await d1.execute("""
        SELECT j.nombre_canonico, j.score_smoothed,
               rc.club_cesion, rc.goles, rc.asistencias, rc.rating_medio
        FROM jugadores j
        LEFT JOIN rendimiento_cedidos rc ON j.jugador_id = rc.jugador_id
        WHERE j.entidad = 'cedido' AND j.is_active = 1
          AND (j.score_smoothed >= 0.05 OR rc.rating_medio IS NOT NULL)
        ORDER BY rc.rating_medio DESC NULLS LAST LIMIT 5
    """)

    lines.append("🏟️ *CASTILLA & CANTERA*")
    if castilla:
        lines.append("_Castilla (top 5):_")
        for i, r in enumerate(castilla[:5]):
            factores = _parse_flags(r.get("factores_actuales"))
            primer = round((factores.get("score_primer_equipo") or 0) * 100) if isinstance(factores, dict) else 0
            line = _player_line(r, i)
            if primer > 0:
                line += f" · 🎯debut:{primer}%"
            lines.append(line)
    if juvenil:
        lines.append("_Juvenil A (top 3):_")
        for i, r in enumerate(juvenil[:3]):
            lines.append(_player_line(r, i))
    if cedidos_with_metrics:
        lines.append("_Cedidos destacados:_")
        for r in cedidos_with_metrics[:3]:
            nombre = r.get("nombre_canonico") or "?"
            club   = r.get("club_cesion") or "?"
            rating = r.get("rating_medio")
            goles  = r.get("goles") or 0
            asist  = r.get("asistencias") or 0
            rating_str = f" ⭐{rating:.1f}" if rating else ""
            lines.append(f"• *{nombre}* @ {club} · ⚽{goles} 🅰️{asist}{rating_str}")
    if not castilla and not juvenil and not cedidos_with_metrics:
        lines.append("_Sin movimientos en cantera_")

    logger.info(
        f"Daily report generated: {len(fichajes)} fichajes, "
        f"{len(salidas)} salidas, "
        f"{len(castilla) + len(juvenil) + len(cedidos_with_metrics)} cantera entries"
    )
    return "\n".join(lines)
