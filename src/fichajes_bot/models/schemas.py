"""Pydantic schemas for all 18 D1 tables."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


class Fuente(BaseModel):
    fuente_id: str
    tipo: Literal["rss", "bluesky", "web_selectolax"]
    tier: Literal["S", "A", "B", "C"]
    url: str | None = None
    bluesky_handle: str | None = None
    periodista_id: str | None = None
    idioma: str = "es"
    sesgo: str = "neutral"
    factor_fichaje_positivo: float = 1.0
    factor_salida_positiva: float = 1.0
    polling_minutes: int = 120
    rate_limit_seconds: int = 0
    entidades: list[str] = Field(default_factory=list)
    is_disabled: bool = False
    consecutive_errors: int = 0
    last_fetched_at: datetime | None = None
    nota: str | None = None


class Periodista(BaseModel):
    periodista_id: str
    nombre_completo: str
    tier: Literal["S", "A", "B", "C"]
    medio_principal: str | None = None
    idioma: str = "en"
    reliability_global: float = 0.5
    alpha_global: float = 1.0
    beta_global: float = 1.0
    n_predicciones_global: int = 0
    n_aciertos_global: int = 0
    reliability_rm: float | None = None
    bluesky_handle: str | None = None


class RumorRaw(BaseModel):
    raw_id: str
    fuente_id: str
    url_canonico: str | None = None
    titulo: str | None = None
    texto_completo: str | None = None
    html_crudo: str | None = None
    fecha_publicacion: str | None = None
    fecha_ingesta: str | None = None
    idioma_detectado: str | None = None
    hash_dedup: str
    procesado: bool = False
    descartado: bool = False
    motivo_descarte: str | None = None


class Jugador(BaseModel):
    jugador_id: str
    nombre_canonico: str
    slug: str | None = None
    posicion: str | None = None
    club_actual: str | None = None
    edad: int | None = None
    valor_mercado_m: float | None = None
    tipo_operacion_principal: Literal["FICHAJE", "SALIDA", "RENOVACION", "CESION"] = "FICHAJE"
    entidad: Literal["primer_equipo", "castilla", "juvenil_a", "cedido"] = "primer_equipo"
    score_raw: float = 0.0
    score_smoothed: float = 0.0
    kalman_P: float = 1.0
    factores_actuales: dict[str, Any] = Field(default_factory=dict)
    fase_dominante: int = 1
    flags: list[str] = Field(default_factory=list)
    n_fuentes_distintas: int = 0
    n_rumores_total: int = 0
    is_active: bool = True


class Rumor(BaseModel):
    rumor_id: str
    raw_id: str | None = None
    jugador_id: str | None = None
    periodista_id: str | None = None
    fuente_id: str | None = None
    tipo_operacion: Literal["FICHAJE", "SALIDA", "RENOVACION", "CESION"] | None = None
    club_destino: str | None = None
    fase_rumor: int = 1
    lexico_detectado: str | None = None
    peso_lexico: float = 0.0
    confianza_extraccion: float = 0.0
    extraido_con: Literal["regex", "gemini"] | None = None
    es_globo_sonda: bool = False
    retractado: bool = False
    outcome: Literal["CONFIRMADO", "FALLIDO", "PENDIENTE"] | None = None
    fecha_publicacion: str | None = None
    idioma: str | None = None
    texto_fragmento: str | None = None


class ScoreHistory(BaseModel):
    history_id: str
    jugador_id: str
    score_anterior: float | None = None
    score_nuevo: float
    delta: float | None = None
    razon_cambio: str | None = None
    explicacion_humana: str | None = None
    factores_snapshot: dict[str, Any] = Field(default_factory=dict)
    timestamp: str | None = None


class LexiconEntry(BaseModel):
    entry_id: str
    frase: str
    idioma: str
    categoria: str
    fase_rumor: int | None = None
    tipo_operacion: str | None = None
    peso_base: float = 0.5
    periodista_id: str | None = None
    origen: str = "curado_manual"
    peso_aprendido: float | None = None
    n_ocurrencias: int = 0
    n_aciertos: int = 0


class ModeloEconomico(BaseModel):
    econ_id: str
    temporada: str | None = None
    tope_laliga_rm: float | None = None
    masa_salarial_actual: float | None = None
    margen_salarial: float | None = None
    presupuesto_fichajes_estimado: float | None = None
    presupuesto_fichajes_restante: float | None = None
    regla_actual: str | None = None
    politica_edad_max: int = 30
    activo: bool = True
    fuente: str | None = None
    confianza: float = 0.5
