"""Format alert messages by type with consistent style."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

ALERT_STYLES: dict[str, str] = {
    "ALERTA_ALTA": "🟢",
    "CAIDA": "🔴",
    "OFICIAL": "🏆",
    "RETRACTADO": "⚠️",
    "GLOBO_SONDA": "🎭",
    "NUEVO_EN_TOP_10": "📈",
    "CORROBORACION": "🎯",
}

ALERT_TITLES: dict[str, str] = {
    "ALERTA_ALTA": "ALERTA ALTA",
    "CAIDA": "CAÍDA DE SCORE",
    "OFICIAL": "OFICIAL",
    "RETRACTADO": "RETRACTADO",
    "GLOBO_SONDA": "POSIBLE GLOBO SONDA",
    "NUEVO_EN_TOP_10": "NUEVO EN TOP 10",
    "CORROBORACION": "CORROBORACIÓN TIER-S",
}


@dataclass
class FormattedAlert:
    titulo: str
    cuerpo: str


def format_alert(
    alert_type: str,
    jugador: dict[str, Any],
    contexto: dict[str, Any] | None = None,
) -> FormattedAlert:
    """Format an alert into title + body with /explain drill-down link."""
    ctx = contexto or {}
    emoji = ALERT_STYLES.get(alert_type, "ℹ️")
    titulo_base = ALERT_TITLES.get(alert_type, alert_type)
    nombre = jugador.get("nombre_canonico", "Desconocido")
    score_pct = int(round(jugador.get("score_smoothed", 0) * 100))
    slug = jugador.get("slug") or nombre.lower().replace(" ", "_")

    titulo = f"{emoji} *{titulo_base}: {nombre}*"

    if alert_type == "ALERTA_ALTA":
        score_prev = int(round(ctx.get("score_anterior", 0) * 100))
        cuerpo = (
            f"Score subió de *{score_prev}%* → *{score_pct}%* (umbral 70% alcanzado)\n"
            f"📌 /explain {slug}"
        )

    elif alert_type == "CAIDA":
        score_prev = int(round(ctx.get("score_anterior", 0) * 100))
        cuerpo = (
            f"Score bajó de *{score_prev}%* → *{score_pct}%* (por debajo del 40%)\n"
            f"📌 /explain {slug}"
        )

    elif alert_type == "OFICIAL":
        tipo = ctx.get("tipo_signal", "fichaje_oficial")
        cuerpo = (
            f"Señal dura detectada: `{tipo}`\n"
            f"Score actual: *{score_pct}%*\n"
            f"📌 /explain {slug}"
        )

    elif alert_type == "RETRACTADO":
        periodista = ctx.get("periodista_nombre", "Fuente tier-S")
        cuerpo = (
            f"Retractación detectada por *{periodista}* (tier-S)\n"
            f"Score actual: *{score_pct}%*\n"
            f"📌 /explain {slug}"
        )

    elif alert_type == "GLOBO_SONDA":
        prob = ctx.get("probabilidad_globo", 0.0)
        cuerpo = (
            f"Probabilidad de globo sonda: *{int(prob * 100)}%*\n"
            f"Score actual: *{score_pct}%*\n"
            f"📌 /explain {slug}"
        )

    elif alert_type == "NUEVO_EN_TOP_10":
        ranking = ctx.get("ranking_nuevo", "?")
        cuerpo = (
            f"Ha entrado en el top 10 en posición *#{ranking}*\n"
            f"Score actual: *{score_pct}%*\n"
            f"📌 /explain {slug}"
        )

    elif alert_type == "CORROBORACION":
        periodista = ctx.get("periodista_nombre", "Periodista tier-S")
        cuerpo = (
            f"*{periodista}* (tier-S) ha reportado sobre este jugador\n"
            f"Score actual: *{score_pct}%*\n"
            f"📌 /explain {slug}"
        )

    else:
        cuerpo = f"Score actual: *{score_pct}%*\n📌 /explain {slug}"

    return FormattedAlert(titulo=titulo, cuerpo=cuerpo)
