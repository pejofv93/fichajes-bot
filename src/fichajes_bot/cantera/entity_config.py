"""CanteraConfig — per-entity configuration for cantera scoring.

Loadable from configs/cantera.yaml; defaults baked in as dataclass fields.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any

import yaml
from loguru import logger

# ── Type enum-like constants ──────────────────────────────────────────────────

FICHAJE = "FICHAJE"
CESION = "CESION"
SALIDA = "SALIDA"
PROMOCION = "PROMOCION"
FICHAJE_JUVENIL = "FICHAJE_JUVENIL"
PROMOCION_CASTILLA = "PROMOCION_CASTILLA"


@dataclass
class CedidosTracking:
    minutos: bool = True
    goles: bool = True
    asistencias: bool = True
    rating: bool = True
    lesiones: bool = True


@dataclass
class CanteraConfig:
    entidad: str
    edad_max: int
    tipo_operaciones: list[str]
    umbral_alerta: float
    tracking: CedidosTracking | None = None

    @classmethod
    def from_dict(cls, entidad: str, data: dict[str, Any]) -> "CanteraConfig":
        tracking = None
        if "tracking" in data:
            t = data["tracking"]
            tracking = CedidosTracking(
                minutos=t.get("minutos", True),
                goles=t.get("goles", True),
                asistencias=t.get("asistencias", True),
                rating=t.get("rating", True),
                lesiones=t.get("lesiones", True),
            )
        return cls(
            entidad=entidad,
            edad_max=data.get("edad_max", 23),
            tipo_operaciones=data.get("tipo_operaciones", [FICHAJE]),
            umbral_alerta=data.get("umbral_alerta", 0.5),
            tracking=tracking,
        )


# ── Built-in defaults ─────────────────────────────────────────────────────────

_DEFAULTS: dict[str, CanteraConfig] = {
    "castilla": CanteraConfig(
        entidad="castilla",
        edad_max=23,
        tipo_operaciones=[FICHAJE, CESION, SALIDA, PROMOCION],
        umbral_alerta=0.5,
    ),
    "juvenil_a": CanteraConfig(
        entidad="juvenil_a",
        edad_max=19,
        tipo_operaciones=[FICHAJE_JUVENIL, PROMOCION_CASTILLA, CESION],
        umbral_alerta=0.4,
    ),
    "cedidos": CanteraConfig(
        entidad="cedidos",
        edad_max=27,
        tipo_operaciones=[CESION, FICHAJE],
        umbral_alerta=0.6,
        tracking=CedidosTracking(),
    ),
}


def load_cantera_configs(config_path: str | None = None) -> dict[str, CanteraConfig]:
    """Load CanteraConfig per entity from YAML, falling back to defaults.

    Returns dict keyed by entity name: 'castilla', 'juvenil_a', 'cedidos'.
    """
    if config_path is None:
        config_path = os.path.join(
            os.path.dirname(__file__), "..", "..", "..", "configs", "cantera.yaml"
        )

    configs = dict(_DEFAULTS)

    try:
        with open(config_path, "r", encoding="utf-8") as f:
            raw = yaml.safe_load(f) or {}

        for entidad, data in raw.items():
            if entidad in configs:
                configs[entidad] = CanteraConfig.from_dict(entidad, data)
            else:
                configs[entidad] = CanteraConfig.from_dict(entidad, data)

        logger.info(f"Loaded cantera configs from {config_path}")

    except FileNotFoundError:
        logger.info("configs/cantera.yaml not found — using built-in defaults")
    except Exception as exc:
        logger.warning(f"Error loading cantera.yaml: {exc} — using defaults")

    return configs
