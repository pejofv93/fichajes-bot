"""Entity-specific scoring configuration overrides.

Different entity types (primer_equipo, castilla, juvenil_a, cedido) have
different scoring characteristics. Session 12 (cantera extension) will use
this module for three-way scoring on youth players.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

EntityType = Literal["primer_equipo", "castilla", "juvenil_a", "cedido"]


@dataclass
class EntityConfig:
    entity: EntityType
    Q_base: float = 0.01
    R_base: float = 0.04
    hard_signal_mult: float = 3.0
    window_days: int = 60
    min_rumores: int = 1
    half_life_days: float = 14.0
    score_max: float = 0.99
    score_min: float = 0.01


_ENTITY_CONFIGS: dict[EntityType, EntityConfig] = {
    "primer_equipo": EntityConfig(entity="primer_equipo"),
    "castilla": EntityConfig(
        entity="castilla",
        window_days=30,
        half_life_days=7.0,
        Q_base=0.02,
    ),
    "juvenil_a": EntityConfig(
        entity="juvenil_a",
        window_days=21,
        half_life_days=7.0,
        Q_base=0.03,
    ),
    "cedido": EntityConfig(
        entity="cedido",
        window_days=45,
        half_life_days=14.0,
    ),
}


def get_entity_config(entity: str | None) -> EntityConfig:
    key = entity or "primer_equipo"
    return _ENTITY_CONFIGS.get(key, _ENTITY_CONFIGS["primer_equipo"])
