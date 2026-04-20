"""Generate extended /explain explanations for a player."""

from __future__ import annotations

import json
from typing import Any

from loguru import logger

from fichajes_bot.persistence.d1_client import D1Client

_SPARK_CHARS = "▁▂▃▄▅▆▇█"


def _sparkline(scores: list[float]) -> str:
    if not scores:
        return ""
    lo, hi = min(scores), max(scores)
    rng = hi - lo or 0.01
    return "".join(
        _SPARK_CHARS[min(7, int(((s - lo) / rng) * 8))]
        for s in scores
    )


def _fmt(v: float | None) -> str:
    if v is None:
        return "?"
    return f"{int(round(v * 100))}%"


def _flag_explanation(flag: str) -> str:
    explanations = {
        "POSIBLE_GLOBO_SONDA": "Solo 1 fuente en >48h sin corroboración",
        "RETRACTADO_TIER_S": "Una fuente tier-S retractó la información",
        "OFICIAL_CONFIRMADO": "Señal dura de operación oficial detectada",
        "SESGO_MEDIO_DETECTADO": "Fuente con sesgo mediático documentado",
        "BAJA_FIABILIDAD_HISTORICA": "Periodista con reliability < 0.4 en contexto RM",
        "ECONOMIC_FLAG": "Restricciones económicas pueden bloquear la operación",
        "TEMPORAL_DECAY": "Score en decaimiento por falta de noticias recientes",
    }
    return explanations.get(flag, "Flag activo")


async def generate_extended_explanation(jugador_id: str, db: D1Client) -> str:
    """Generate full extended explanation text for a player."""
    try:
        # ── Fetch player data ────────────────────────────────────────────────
        rows = await db.execute(
            "SELECT * FROM jugadores WHERE jugador_id = ?", [jugador_id]
        )
        if not rows:
            return f"Jugador no encontrado: {jugador_id}"
        j: dict[str, Any] = rows[0]

        factores: dict[str, Any] = json.loads(j.get("factores_actuales") or "{}")
        flags: list[str] = json.loads(j.get("flags") or "[]")
        score_now = j.get("score_smoothed", 0.0)
        score_raw = j.get("score_raw", 0.0)

        # ── Score 7 days ago ─────────────────────────────────────────────────
        hist_7d = await db.execute(
            """SELECT score_nuevo FROM score_history
               WHERE jugador_id = ?
                 AND timestamp <= datetime('now', '-7 days')
               ORDER BY timestamp DESC LIMIT 1""",
            [jugador_id],
        )
        score_7d_ago = hist_7d[0]["score_nuevo"] if hist_7d else None
        score_delta_str = ""
        if score_7d_ago is not None:
            delta = int(round((score_now - score_7d_ago) * 100))
            arrow = "▲" if delta >= 0 else "▼"
            score_delta_str = f" ({arrow}{abs(delta)}% vs hace 7d)"

        # ── Top 3 rumores by weight ──────────────────────────────────────────
        top_rumores = await db.execute(
            """SELECT r.lexico_detectado, r.peso_lexico, r.fecha_publicacion,
                      r.rumor_id, r.fase_rumor,
                      p.nombre_completo AS periodista_nombre,
                      p.reliability_global, p.tier
               FROM rumores r
               JOIN periodistas p ON r.periodista_id = p.periodista_id
               WHERE r.jugador_id = ? AND r.retractado = 0
               ORDER BY ABS(r.peso_lexico) DESC LIMIT 3""",
            [jugador_id],
        )

        # ── Timeline: last 10 rumores ────────────────────────────────────────
        timeline = await db.execute(
            """SELECT r.fecha_publicacion, r.lexico_detectado, r.fase_rumor,
                      p.nombre_completo AS periodista_nombre, p.tier,
                      r.retractado
               FROM rumores r
               JOIN periodistas p ON r.periodista_id = p.periodista_id
               WHERE r.jugador_id = ?
               ORDER BY r.fecha_publicacion DESC LIMIT 10""",
            [jugador_id],
        )

        # ── Sparkline 30 days ────────────────────────────────────────────────
        spark_rows = await db.execute(
            """SELECT score_nuevo FROM score_history
               WHERE jugador_id = ?
                 AND timestamp >= datetime('now', '-30 days')
               ORDER BY timestamp ASC""",
            [jugador_id],
        )
        spark_scores = [r["score_nuevo"] for r in spark_rows]
        spark = _sparkline(spark_scores)

        # ── "¿Por qué este score ahora?" analysis ───────────────────────────
        analysis_lines = await _build_why_analysis(j, factores, flags, top_rumores, db)

        # ── Assemble output ──────────────────────────────────────────────────
        lines: list[str] = []

        lines.append(f"🔬 *Análisis extendido: {j['nombre_canonico']}*")
        lines.append("━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
        lines.append("")

        # Score + delta
        lines.append(f"📊 *Score actual: {_fmt(score_now)}*{score_delta_str}")
        lines.append(f"   raw: {_fmt(score_raw)} | smoothed: {_fmt(score_now)}")
        lines.append("")

        # Full factor decomposition
        lines.append("🧮 *Descomposición completa:*")
        lines.append(f"├─ *Componentes:*")
        lines.append(f"│  ├─ Consenso:        {_fmt(factores.get('consenso'))}")
        lines.append(f"│  ├─ Credibilidad:    {_fmt(factores.get('credibilidad'))}")
        lines.append(f"│  ├─ Fase rumor:      {factores.get('fase_dominante', '?')}/6")
        lines.append(f"│  └─ Temporal:        {_fmt(factores.get('factor_temporal'))}")
        lines.append(f"├─ *Modificadores:*")
        lines.append(f"│  ├─ Económico:       {_fmt(factores.get('factor_econ'))}")
        lines.append(f"│  ├─ Sustitución:     {_fmt(factores.get('factor_subst'))}")
        lines.append(f"│  ├─ Sesgo medio:     {_fmt(factores.get('bias_correction'))}")
        lines.append(f"│  ├─ Retractación:    {_fmt(factores.get('retraction_penalty'))}")
        lines.append(f"│  └─ Kalman P:        {factores.get('kalman_P', '?')}")
        lines.append("")

        # Top 3 rumores
        if top_rumores:
            lines.append("📰 *Top 3 rumores con más peso:*")
            for i, r in enumerate(top_rumores, 1):
                fecha = (r.get("fecha_publicacion") or "?")[:10]
                rel = _fmt(r.get("reliability_global"))
                lines.append(
                    f"{i}. *{r.get('periodista_nombre', '?')}* ({r.get('tier', '?')}) · "
                    f"`{r.get('lexico_detectado', '?')}` · peso: {_fmt(r.get('peso_lexico'))} · "
                    f"reliability: {rel} · {fecha}"
                )
            lines.append("")

        # Timeline
        if timeline:
            lines.append("📅 *Timeline (últimos 10 eventos):*")
            for r in timeline:
                fecha = (r.get("fecha_publicacion") or "?")[:10]
                retracted = " ~~retractado~~" if r.get("retractado") else ""
                tipo = r.get("lexico_detectado") or f"fase {r.get('fase_rumor', '?')}"
                lines.append(
                    f"• {fecha} — *{r.get('periodista_nombre', '?')}* "
                    f"({r.get('tier', '?')}) — `{tipo}`{retracted}"
                )
            lines.append("")

        # Active flags
        if flags:
            lines.append("🚩 *Flags activos:*")
            for f_name in flags:
                lines.append(f"• *{f_name}*: {_flag_explanation(f_name)}")
            lines.append("")

        # Sparkline
        if spark:
            lines.append(f"📈 *Evolución 30d:* `{spark}`")
            lines.append("")

        # Why analysis
        if analysis_lines:
            lines.append("💡 *¿Por qué este score ahora?*")
            for line in analysis_lines:
                lines.append(f"• {line}")

        return "\n".join(lines)

    except Exception as exc:
        logger.error(f"generate_extended_explanation error for {jugador_id}: {exc}")
        return f"Error generando explicación: {exc}"


async def _build_why_analysis(
    jugador: dict[str, Any],
    factores: dict[str, Any],
    flags: list[str],
    top_rumores: list[dict[str, Any]],
    db: D1Client,
) -> list[str]:
    lines: list[str] = []

    if top_rumores:
        top = top_rumores[0]
        nombre_p = top.get("periodista_nombre", "Fuente")
        lexico = top.get("lexico_detectado", "información")
        fecha = (top.get("fecha_publicacion") or "?")[:10]
        peso = top.get("peso_lexico", 0)
        if peso and peso > 0:
            lines.append(f"Score subió porque *{nombre_p}* reportó `{lexico}` el {fecha}")
        elif peso and peso < 0:
            lines.append(f"Score bajó porque *{nombre_p}* publicó `{lexico}` (señal negativa) el {fecha}")

    if factores.get("credibilidad") is not None:
        cred = factores["credibilidad"]
        if cred < 0.4:
            low_rel_rumor = next(
                (r for r in top_rumores if (r.get("reliability_global") or 1.0) < 0.4),
                None,
            )
            if low_rel_rumor:
                p = low_rel_rumor.get("periodista_nombre", "Este periodista")
                ctx = f"en contexto {jugador.get('tipo_operacion_principal', 'RM')}"
                lines.append(
                    f"Score bajo porque *{p}* tiene reliability baja {ctx}"
                )

    if "POSIBLE_GLOBO_SONDA" in flags:
        lines.append("Flag POSIBLE_GLOBO_SONDA activo porque solo 1 fuente en >48h sin corroboración")

    if "RETRACTADO_TIER_S" in flags:
        periodista_ret = factores.get("retraction_periodista", "una fuente tier-S")
        lines.append(f"Score penalizado por retractación de *{periodista_ret}*")

    econ = factores.get("factor_econ")
    if econ is not None and econ < 0.6:
        lines.append("Factor económico bajo: restricciones salariales limitan la operación")

    return lines
