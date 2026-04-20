#!/usr/bin/env python
"""Generate synthetic historical backfill: ~80 RM transfers 2020-2025.

Writes data/backfill/rumores_historicos.jsonl — one JSON object per line.
Each object is a rumor dict ready to load into D1.

Design principles:
- Realistic chronology: rumors start weeks/months before the official announcement
- Journalist patterns: Romano/Ornstein are early with high confidence; tabloids are
  louder but earlier and sometimes wrong; MARCA amplifies; Mundo Deportivo is sceptical
- Outcomes are known (historical fact), so we can set outcome correctly
- Lexicon phrases are drawn from the actual curated lexicon (configs/lexicon/*.yaml)
  so extraction pipeline will detect them correctly
"""

from __future__ import annotations

import json
import os
import random
import sys
import uuid
from datetime import datetime, timedelta
from pathlib import Path

# Add src/ to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

random.seed(42)

# ── Transfer data ─────────────────────────────────────────────────────────────

TRANSFERS = [
    # ── FICHAJES efectivos ──────────────────────────────────────────────────
    {"nombre": "Jude Bellingham",    "tipo": "FICHAJE", "outcome": "FICHAJE_EFECTIVO",
     "club_origen": "Borussia Dortmund", "valor_m": 103.0,
     "fecha_oficial": "2023-06-14", "posicion": "MC", "edad": 19},

    {"nombre": "Kylian Mbappé",      "tipo": "FICHAJE", "outcome": "FICHAJE_EFECTIVO",
     "club_origen": "Paris Saint-Germain", "valor_m": 0.0,
     "fecha_oficial": "2024-06-03", "posicion": "DC", "edad": 25},

    {"nombre": "Endrick Felipe",     "tipo": "FICHAJE", "outcome": "FICHAJE_EFECTIVO",
     "club_origen": "Palmeiras", "valor_m": 60.0,
     "fecha_oficial": "2024-07-25", "posicion": "DC", "edad": 17},

    {"nombre": "Aurélien Tchouaméni","tipo": "FICHAJE", "outcome": "FICHAJE_EFECTIVO",
     "club_origen": "AS Monaco", "valor_m": 80.0,
     "fecha_oficial": "2022-06-14", "posicion": "MCD", "edad": 22},

    {"nombre": "Eduardo Camavinga",  "tipo": "FICHAJE", "outcome": "FICHAJE_EFECTIVO",
     "club_origen": "Stade Rennais", "valor_m": 31.0,
     "fecha_oficial": "2021-08-31", "posicion": "MC", "edad": 18},

    {"nombre": "David Alaba",        "tipo": "FICHAJE", "outcome": "FICHAJE_EFECTIVO",
     "club_origen": "Bayern Munich", "valor_m": 0.0,
     "fecha_oficial": "2021-07-01", "posicion": "DFC", "edad": 29},

    {"nombre": "Antonio Rüdiger",    "tipo": "FICHAJE", "outcome": "FICHAJE_EFECTIVO",
     "club_origen": "Chelsea", "valor_m": 0.0,
     "fecha_oficial": "2022-07-01", "posicion": "DFC", "edad": 29},

    {"nombre": "Éder Militão",       "tipo": "FICHAJE", "outcome": "FICHAJE_EFECTIVO",
     "club_origen": "FC Porto", "valor_m": 50.0,
     "fecha_oficial": "2019-07-01", "posicion": "DFC", "edad": 21},

    {"nombre": "Federico Valverde",  "tipo": "FICHAJE", "outcome": "FICHAJE_EFECTIVO",
     "club_origen": "Club Nacional", "valor_m": 5.0,
     "fecha_oficial": "2017-07-01", "posicion": "MC", "edad": 18},

    {"nombre": "Vinícius Júnior",    "tipo": "FICHAJE", "outcome": "FICHAJE_EFECTIVO",
     "club_origen": "CR Flamengo", "valor_m": 45.0,
     "fecha_oficial": "2018-07-01", "posicion": "ED", "edad": 17},

    {"nombre": "Rodrygo Goes",       "tipo": "FICHAJE", "outcome": "FICHAJE_EFECTIVO",
     "club_origen": "Santos FC", "valor_m": 45.0,
     "fecha_oficial": "2019-07-01", "posicion": "EI", "edad": 18},

    {"nombre": "Brahim Díaz",        "tipo": "FICHAJE", "outcome": "FICHAJE_EFECTIVO",
     "club_origen": "Manchester City", "valor_m": 17.0,
     "fecha_oficial": "2019-01-07", "posicion": "MO", "edad": 19},

    {"nombre": "Luka Jović",         "tipo": "FICHAJE", "outcome": "FICHAJE_EFECTIVO",
     "club_origen": "Eintracht Frankfurt", "valor_m": 60.0,
     "fecha_oficial": "2019-07-01", "posicion": "DC", "edad": 21},

    {"nombre": "Eden Hazard",        "tipo": "FICHAJE", "outcome": "FICHAJE_EFECTIVO",
     "club_origen": "Chelsea", "valor_m": 100.0,
     "fecha_oficial": "2019-06-13", "posicion": "ED", "edad": 28},

    {"nombre": "Thibaut Courtois",   "tipo": "FICHAJE", "outcome": "FICHAJE_EFECTIVO",
     "club_origen": "Chelsea", "valor_m": 35.0,
     "fecha_oficial": "2018-07-03", "posicion": "POR", "edad": 26},

    {"nombre": "Trent Alexander-Arnold", "tipo": "FICHAJE", "outcome": "FICHAJE_EFECTIVO",
     "club_origen": "Liverpool", "valor_m": 0.0,
     "fecha_oficial": "2025-07-01", "posicion": "LD", "edad": 26},

    {"nombre": "Dean Huijsen",       "tipo": "FICHAJE", "outcome": "FICHAJE_EFECTIVO",
     "club_origen": "AS Roma (cedido)", "valor_m": 18.0,
     "fecha_oficial": "2024-06-30", "posicion": "DFC", "edad": 19},

    {"nombre": "Arda Güler",         "tipo": "FICHAJE", "outcome": "FICHAJE_EFECTIVO",
     "club_origen": "Fenerbahçe", "valor_m": 20.0,
     "fecha_oficial": "2023-07-06", "posicion": "MO", "edad": 18},

    {"nombre": "Joselu",             "tipo": "FICHAJE", "outcome": "FICHAJE_EFECTIVO",
     "club_origen": "Deportivo Alavés (cedido)", "valor_m": 2.0,
     "fecha_oficial": "2023-06-14", "posicion": "DC", "edad": 33},

    {"nombre": "Kepa Arrizabalaga",  "tipo": "FICHAJE", "outcome": "FICHAJE_EFECTIVO",
     "club_origen": "Chelsea (cedido)", "valor_m": 0.0,
     "fecha_oficial": "2023-09-01", "posicion": "POR", "edad": 29},

    # ── SALIDAS efectivas ────────────────────────────────────────────────────
    {"nombre": "Eden Hazard",        "tipo": "SALIDA", "outcome": "SALIDA_EFECTIVA",
     "club_origen": "Real Madrid", "valor_m": 0.0,
     "fecha_oficial": "2023-07-01", "posicion": "ED", "edad": 32},

    {"nombre": "Gareth Bale",        "tipo": "SALIDA", "outcome": "SALIDA_EFECTIVA",
     "club_origen": "Real Madrid", "valor_m": 0.0,
     "fecha_oficial": "2022-07-01", "posicion": "EI", "edad": 32},

    {"nombre": "Isco Alarcón",       "tipo": "SALIDA", "outcome": "SALIDA_EFECTIVA",
     "club_origen": "Real Madrid", "valor_m": 0.0,
     "fecha_oficial": "2022-07-01", "posicion": "MC", "edad": 30},

    {"nombre": "Marcelo Vieira",     "tipo": "SALIDA", "outcome": "SALIDA_EFECTIVA",
     "club_origen": "Real Madrid", "valor_m": 0.0,
     "fecha_oficial": "2022-07-01", "posicion": "LI", "edad": 34},

    {"nombre": "Casemiro",           "tipo": "SALIDA", "outcome": "SALIDA_EFECTIVA",
     "club_origen": "Real Madrid", "valor_m": 70.0,
     "fecha_oficial": "2022-08-22", "posicion": "MCD", "edad": 30},

    {"nombre": "Toni Kroos",         "tipo": "SALIDA", "outcome": "SALIDA_EFECTIVA",
     "club_origen": "Real Madrid", "valor_m": 0.0,
     "fecha_oficial": "2024-07-01", "posicion": "MC", "edad": 34},

    {"nombre": "Sergio Ramos",       "tipo": "SALIDA", "outcome": "SALIDA_EFECTIVA",
     "club_origen": "Real Madrid", "valor_m": 0.0,
     "fecha_oficial": "2021-07-01", "posicion": "DFC", "edad": 35},

    {"nombre": "Raphael Varane",     "tipo": "SALIDA", "outcome": "SALIDA_EFECTIVA",
     "club_origen": "Real Madrid", "valor_m": 40.0,
     "fecha_oficial": "2021-07-01", "posicion": "DFC", "edad": 28},

    {"nombre": "Dani Ceballos",      "tipo": "SALIDA", "outcome": "SALIDA_EFECTIVA",
     "club_origen": "Real Madrid", "valor_m": 0.0,
     "fecha_oficial": "2023-07-01", "posicion": "MC", "edad": 27},

    {"nombre": "Mariano Díaz",       "tipo": "SALIDA", "outcome": "SALIDA_EFECTIVA",
     "club_origen": "Real Madrid", "valor_m": 0.0,
     "fecha_oficial": "2023-07-01", "posicion": "DC", "edad": 30},

    {"nombre": "Jesus Vallejo",      "tipo": "SALIDA", "outcome": "SALIDA_EFECTIVA",
     "club_origen": "Real Madrid", "valor_m": 0.0,
     "fecha_oficial": "2023-07-01", "posicion": "DFC", "edad": 26},

    {"nombre": "Marco Asensio",      "tipo": "SALIDA", "outcome": "SALIDA_EFECTIVA",
     "club_origen": "Real Madrid", "valor_m": 0.0,
     "fecha_oficial": "2023-07-01", "posicion": "MO", "edad": 27},

    {"nombre": "Nacho Fernández",    "tipo": "SALIDA", "outcome": "SALIDA_EFECTIVA",
     "club_origen": "Real Madrid", "valor_m": 0.0,
     "fecha_oficial": "2024-07-01", "posicion": "DFC", "edad": 34},

    {"nombre": "Joselu",             "tipo": "SALIDA", "outcome": "SALIDA_EFECTIVA",
     "club_origen": "Real Madrid", "valor_m": 0.0,
     "fecha_oficial": "2024-07-01", "posicion": "DC", "edad": 34},

    # ── Operaciones caídas (targets que NO ficharon) ─────────────────────────
    {"nombre": "Erling Haaland",     "tipo": "FICHAJE", "outcome": "OPERACION_CAIDA",
     "club_origen": "Borussia Dortmund", "valor_m": 0.0,
     "fecha_oficial": "2022-05-10", "posicion": "DC", "edad": 21},

    {"nombre": "Kylian Mbappé (2022)","tipo": "FICHAJE", "outcome": "OPERACION_CAIDA",
     "club_origen": "Paris Saint-Germain", "valor_m": 0.0,
     "fecha_oficial": "2022-05-21", "posicion": "DC", "edad": 23},

    {"nombre": "Mohamed Salah",      "tipo": "FICHAJE", "outcome": "OPERACION_CAIDA",
     "club_origen": "Liverpool", "valor_m": 0.0,
     "fecha_oficial": "2023-08-01", "posicion": "ED", "edad": 31},

    {"nombre": "Neymar Jr",          "tipo": "FICHAJE", "outcome": "OPERACION_CAIDA",
     "club_origen": "Paris Saint-Germain", "valor_m": 0.0,
     "fecha_oficial": "2022-08-01", "posicion": "EI", "edad": 30},

    {"nombre": "Lautaro Martínez",   "tipo": "FICHAJE", "outcome": "OPERACION_CAIDA",
     "club_origen": "Inter Milan", "valor_m": 0.0,
     "fecha_oficial": "2021-07-01", "posicion": "DC", "edad": 23},

    {"nombre": "Mbappé (2021)",      "tipo": "FICHAJE", "outcome": "OPERACION_CAIDA",
     "club_origen": "Paris Saint-Germain", "valor_m": 0.0,
     "fecha_oficial": "2021-08-10", "posicion": "DC", "edad": 22},

    {"nombre": "Paul Pogba",         "tipo": "FICHAJE", "outcome": "OPERACION_CAIDA",
     "club_origen": "Manchester United", "valor_m": 0.0,
     "fecha_oficial": "2022-07-01", "posicion": "MC", "edad": 29},

    {"nombre": "Bernardo Silva",     "tipo": "FICHAJE", "outcome": "OPERACION_CAIDA",
     "club_origen": "Manchester City", "valor_m": 0.0,
     "fecha_oficial": "2022-09-01", "posicion": "MO", "edad": 28},

    {"nombre": "Florian Wirtz",      "tipo": "FICHAJE", "outcome": "OPERACION_CAIDA",
     "club_origen": "Bayer Leverkusen", "valor_m": 0.0,
     "fecha_oficial": "2024-06-01", "posicion": "MO", "edad": 20},

    {"nombre": "Victor Osimhen",     "tipo": "FICHAJE", "outcome": "OPERACION_CAIDA",
     "club_origen": "Napoli", "valor_m": 0.0,
     "fecha_oficial": "2024-08-31", "posicion": "DC", "edad": 25},

    # ── Renovaciones efectivas ───────────────────────────────────────────────
    {"nombre": "Luka Modrić",        "tipo": "RENOVACION", "outcome": "RENOVACION_EFECTIVA",
     "club_origen": "Real Madrid", "valor_m": 0.0,
     "fecha_oficial": "2023-07-01", "posicion": "MC", "edad": 37},

    {"nombre": "Karim Benzema",      "tipo": "RENOVACION", "outcome": "RENOVACION_EFECTIVA",
     "club_origen": "Real Madrid", "valor_m": 0.0,
     "fecha_oficial": "2022-07-01", "posicion": "DC", "edad": 34},

    {"nombre": "Thibaut Courtois",   "tipo": "RENOVACION", "outcome": "RENOVACION_EFECTIVA",
     "club_origen": "Real Madrid", "valor_m": 0.0,
     "fecha_oficial": "2021-07-01", "posicion": "POR", "edad": 29},

    # ── Salidas caídas (rumores de salida que NO se materializaron) ──────────
    {"nombre": "Karim Benzema (2021)","tipo": "SALIDA", "outcome": "OPERACION_CAIDA",
     "club_origen": "Real Madrid", "valor_m": 0.0,
     "fecha_oficial": "2021-06-30", "posicion": "DC", "edad": 33},

    {"nombre": "Toni Kroos (2021)",  "tipo": "SALIDA", "outcome": "OPERACION_CAIDA",
     "club_origen": "Real Madrid", "valor_m": 0.0,
     "fecha_oficial": "2021-06-30", "posicion": "MC", "edad": 31},

    {"nombre": "Luka Modrić (2020)", "tipo": "SALIDA", "outcome": "OPERACION_CAIDA",
     "club_origen": "Real Madrid", "valor_m": 0.0,
     "fecha_oficial": "2020-08-01", "posicion": "MC", "edad": 34},

    {"nombre": "Marco Asensio (2020)","tipo": "SALIDA", "outcome": "OPERACION_CAIDA",
     "club_origen": "Real Madrid", "valor_m": 0.0,
     "fecha_oficial": "2020-07-01", "posicion": "MO", "edad": 24},

    # ── More fichajes to reach ~80 ────────────────────────────────────────────
    {"nombre": "Lucas Vázquez",      "tipo": "RENOVACION", "outcome": "RENOVACION_EFECTIVA",
     "club_origen": "Real Madrid", "valor_m": 0.0,
     "fecha_oficial": "2021-07-01", "posicion": "LD", "edad": 29},

    {"nombre": "Nacho Fernández (renov)", "tipo": "RENOVACION", "outcome": "RENOVACION_EFECTIVA",
     "club_origen": "Real Madrid", "valor_m": 0.0,
     "fecha_oficial": "2022-07-01", "posicion": "DFC", "edad": 32},

    {"nombre": "Dani Carvajal",      "tipo": "RENOVACION", "outcome": "RENOVACION_EFECTIVA",
     "club_origen": "Real Madrid", "valor_m": 0.0,
     "fecha_oficial": "2023-07-01", "posicion": "LD", "edad": 31},

    {"nombre": "Éder Militão (renov)", "tipo": "RENOVACION", "outcome": "RENOVACION_EFECTIVA",
     "club_origen": "Real Madrid", "valor_m": 0.0,
     "fecha_oficial": "2024-04-01", "posicion": "DFC", "edad": 26},

    {"nombre": "Vinicius Jr (renov)","tipo": "RENOVACION", "outcome": "RENOVACION_EFECTIVA",
     "club_origen": "Real Madrid", "valor_m": 0.0,
     "fecha_oficial": "2024-05-01", "posicion": "ED", "edad": 23},

    {"nombre": "Ferland Mendy",      "tipo": "RENOVACION", "outcome": "RENOVACION_EFECTIVA",
     "club_origen": "Real Madrid", "valor_m": 0.0,
     "fecha_oficial": "2022-04-01", "posicion": "LI", "edad": 27},

    {"nombre": "Andriy Lunin",       "tipo": "RENOVACION", "outcome": "RENOVACION_EFECTIVA",
     "club_origen": "Real Madrid", "valor_m": 0.0,
     "fecha_oficial": "2024-04-01", "posicion": "POR", "edad": 25},

    {"nombre": "Marco Asensio (renov 2021)", "tipo": "RENOVACION", "outcome": "OPERACION_CAIDA",
     "club_origen": "Real Madrid", "valor_m": 0.0,
     "fecha_oficial": "2021-06-01", "posicion": "MO", "edad": 25},

    {"nombre": "Álvaro Odriozola",   "tipo": "SALIDA", "outcome": "SALIDA_EFECTIVA",
     "club_origen": "Real Madrid", "valor_m": 3.0,
     "fecha_oficial": "2022-07-01", "posicion": "LD", "edad": 26},

    {"nombre": "James Rodríguez",    "tipo": "SALIDA", "outcome": "SALIDA_EFECTIVA",
     "club_origen": "Real Madrid", "valor_m": 15.0,
     "fecha_oficial": "2020-09-12", "posicion": "MO", "edad": 29},

    {"nombre": "Reinier Jesus",      "tipo": "SALIDA", "outcome": "SALIDA_EFECTIVA",
     "club_origen": "Real Madrid", "valor_m": 8.0,
     "fecha_oficial": "2023-07-01", "posicion": "MO", "edad": 21},

    {"nombre": "Martin Ødegaard",    "tipo": "SALIDA", "outcome": "SALIDA_EFECTIVA",
     "club_origen": "Real Madrid", "valor_m": 35.0,
     "fecha_oficial": "2021-08-18", "posicion": "MO", "edad": 22},

    {"nombre": "Gareth Bale (2020 cesión)", "tipo": "CESION", "outcome": "CESION_EFECTIVA",
     "club_origen": "Real Madrid", "valor_m": 0.0,
     "fecha_oficial": "2020-09-16", "posicion": "EI", "edad": 31},

    {"nombre": "Takefusa Kubo",      "tipo": "CESION", "outcome": "CESION_EFECTIVA",
     "club_origen": "Real Madrid", "valor_m": 0.0,
     "fecha_oficial": "2020-10-05", "posicion": "ED", "edad": 19},

    {"nombre": "Sergio Arribas",     "tipo": "SALIDA", "outcome": "SALIDA_EFECTIVA",
     "club_origen": "Real Madrid Castilla", "valor_m": 3.0,
     "fecha_oficial": "2023-07-01", "posicion": "MO", "edad": 21},

    {"nombre": "Miguel Gutiérrez",   "tipo": "SALIDA", "outcome": "SALIDA_EFECTIVA",
     "club_origen": "Real Madrid", "valor_m": 12.0,
     "fecha_oficial": "2023-07-01", "posicion": "LI", "edad": 21},

    {"nombre": "Ivan Zardadze",      "tipo": "FICHAJE", "outcome": "OPERACION_CAIDA",
     "club_origen": "Dinamo Batumi", "valor_m": 0.0,
     "fecha_oficial": "2024-01-15", "posicion": "DC", "edad": 19},

    {"nombre": "Gonçalo Ramos",      "tipo": "FICHAJE", "outcome": "OPERACION_CAIDA",
     "club_origen": "Paris Saint-Germain", "valor_m": 0.0,
     "fecha_oficial": "2024-08-01", "posicion": "DC", "edad": 23},

    {"nombre": "Jonathan David",     "tipo": "FICHAJE", "outcome": "OPERACION_CAIDA",
     "club_origen": "LOSC Lille", "valor_m": 0.0,
     "fecha_oficial": "2025-01-15", "posicion": "DC", "edad": 24},

    {"nombre": "Florentino Luís",    "tipo": "FICHAJE", "outcome": "OPERACION_CAIDA",
     "club_origen": "Benfica", "valor_m": 0.0,
     "fecha_oficial": "2024-06-01", "posicion": "MCD", "edad": 25},

    {"nombre": "Federico Valverde (renov)", "tipo": "RENOVACION", "outcome": "RENOVACION_EFECTIVA",
     "club_origen": "Real Madrid", "valor_m": 0.0,
     "fecha_oficial": "2023-01-15", "posicion": "MC", "edad": 24},

    {"nombre": "Eduardo Camavinga (renov)", "tipo": "RENOVACION", "outcome": "RENOVACION_EFECTIVA",
     "club_origen": "Real Madrid", "valor_m": 0.0,
     "fecha_oficial": "2023-12-01", "posicion": "MC", "edad": 21},

    {"nombre": "Aurélien Tchouaméni (renov)", "tipo": "RENOVACION", "outcome": "RENOVACION_EFECTIVA",
     "club_origen": "Real Madrid", "valor_m": 0.0,
     "fecha_oficial": "2024-06-01", "posicion": "MCD", "edad": 24},

    {"nombre": "Jude Bellingham (renov)", "tipo": "RENOVACION", "outcome": "RENOVACION_EFECTIVA",
     "club_origen": "Real Madrid", "valor_m": 0.0,
     "fecha_oficial": "2025-02-01", "posicion": "MC", "edad": 21},

    {"nombre": "Álvaro Morata",      "tipo": "FICHAJE", "outcome": "OPERACION_CAIDA",
     "club_origen": "Atlético de Madrid", "valor_m": 0.0,
     "fecha_oficial": "2023-07-01", "posicion": "DC", "edad": 30},

    {"nombre": "Harry Kane",         "tipo": "FICHAJE", "outcome": "OPERACION_CAIDA",
     "club_origen": "Tottenham Hotspur", "valor_m": 0.0,
     "fecha_oficial": "2023-08-12", "posicion": "DC", "edad": 30},

    {"nombre": "Rodrygo Goes (renov)", "tipo": "RENOVACION", "outcome": "RENOVACION_EFECTIVA",
     "club_origen": "Real Madrid", "valor_m": 0.0,
     "fecha_oficial": "2024-07-01", "posicion": "EI", "edad": 23},

    {"nombre": "Arda Güler (renov)", "tipo": "RENOVACION", "outcome": "RENOVACION_EFECTIVA",
     "club_origen": "Real Madrid", "valor_m": 0.0,
     "fecha_oficial": "2025-02-01", "posicion": "MO", "edad": 19},

    {"nombre": "Brahim Díaz (renov)", "tipo": "RENOVACION", "outcome": "RENOVACION_EFECTIVA",
     "club_origen": "Real Madrid", "valor_m": 0.0,
     "fecha_oficial": "2024-08-01", "posicion": "MO", "edad": 24},

    {"nombre": "Jesús Vallejo",       "tipo": "CESION", "outcome": "CESION_EFECTIVA",
     "club_origen": "Real Madrid", "valor_m": 0.0,
     "fecha_oficial": "2021-09-01", "posicion": "DFC", "edad": 24},

    {"nombre": "Dani Ceballos (cesión)", "tipo": "CESION", "outcome": "CESION_EFECTIVA",
     "club_origen": "Real Madrid", "valor_m": 0.0,
     "fecha_oficial": "2020-09-01", "posicion": "MC", "edad": 24},

    {"nombre": "Xabi Alonso",         "tipo": "FICHAJE", "outcome": "OPERACION_CAIDA",
     "club_origen": "Bayer Leverkusen", "valor_m": 0.0,
     "fecha_oficial": "2024-05-15", "posicion": "ENT", "edad": 42},
]

# ── Journalist patterns ────────────────────────────────────────────────────────

# (periodista_id, lead_days_min, lead_days_max, hit_rate_multiplier, n_rumors_min, n_rumors_max)
JOURNALIST_PATTERNS = [
    ("fabrizio-romano",    3,  30,  0.95, 2, 4),
    ("david-ornstein",     3,  25,  0.90, 1, 3),
    ("matteo-moretto",     5,  35,  0.87, 1, 3),
    ("gianluca-di-marzio", 5,  35,  0.85, 1, 3),
    ("florian-plettenberg",7,  40,  0.83, 1, 3),
    ("relevo-rm",          7,  45,  0.78, 1, 3),
    ("athletic-soccer",    5,  30,  0.82, 1, 2),
    ("marca-fichajes",    10,  60,  0.72, 1, 4),
    ("jose-felix-diaz",   10,  60,  0.65, 1, 3),
    ("edu-aguirre",        2,  90,  0.40, 1, 5),  # loud and early, often wrong
    ("pedrerol-Josep",     2, 100,  0.38, 1, 4),
    ("mundodeportivo-ed", 15,  80,  0.60, 0, 2),  # sceptical (fewer rumors)
    ("goal-spain",        10,  50,  0.68, 1, 3),
    ("cadena-ser-futbol",  5,  40,  0.70, 1, 3),
]

# Lexicon phrases by operation type and phase — drawn from lexicon seed
PHRASES_FICHAJE = {
    1: ["interés del Real Madrid", "Real Madrid apunta a", "en la agenda del Madrid",
        "sondeo del Real Madrid", "el Real Madrid quiere"],
    2: ["contactos directos", "el Madrid sigue al jugador", "primeros contactos"],
    3: ["negociaciones avanzadas", "oferta presentada", "oferta formal",
        "propuesta sobre la mesa", "primera oferta rechazada"],
    4: ["acuerdo personal alcanzado", "acuerdo con el jugador", "cifra acordada",
        "contraoferta enviada", "pendiente del acuerdo entre clubes"],
    5: ["acuerdo cerrado", "trato cerrado", "traspaso acordado", "revisión médica",
        "en camino a Madrid", "pasa el médico mañana"],
    6: ["aquí vamos", "acuerdo total alcanzado", "contrato firmado",
        "fichaje confirmado", "ya es oficial", "done deal"],
}

PHRASES_SALIDA = {
    1: ["quiere salir", "escucha ofertas", "puede salir en verano"],
    2: ["ha pedido la salida", "no renovará", "interés de otros clubes"],
    3: ["negociaciones para su salida", "se busca salida", "en el mercado"],
    4: ["acuerdo para su salida", "venta acordada", "se confirma su traspaso"],
    5: ["traspaso inminente", "rescisión de contrato", "sale libre en junio"],
    6: ["traspaso oficial confirmado", "fin de su etapa en el real madrid",
        "rescisión acordada", "salida libre"],
}

PHRASES_RENOVACION = {
    1: ["renovación en el horizonte", "quiere seguir en el Madrid"],
    2: ["negociaciones para renovar", "primer oferta de renovación"],
    3: ["acuerdo de renovación en proceso"],
    4: ["renovación avanzada", "acuerdo personal para renovar"],
    5: ["renovación inminente"],
    6: ["renovación firmada", "extiende su contrato", "continuará en el Madrid"],
}

PHRASES_CAIDA = {
    1: ["interés del Real Madrid", "en la agenda del Madrid"],
    2: ["contactos iniciales", "sondeo inicial"],
    3: ["negociaciones estancadas", "dificultades en el acuerdo"],
    4: ["alejándose del Madrid", "problemas en las negociaciones"],
    5: ["no habrá acuerdo", "operación descartada"],
    6: ["descartado definitivamente", "deal off", "fin del rumor"],
}


def _phrases_for(tipo: str, fase: int, outcome: str) -> list[str]:
    if outcome == "OPERACION_CAIDA" and fase >= 4:
        return PHRASES_CAIDA.get(fase, ["el acuerdo no se materializó"])
    if tipo == "FICHAJE":
        return PHRASES_FICHAJE.get(fase, ["nuevas noticias sobre el fichaje"])
    if tipo == "SALIDA":
        return PHRASES_SALIDA.get(fase, ["nuevas noticias sobre la salida"])
    if tipo in ("RENOVACION", "CESION"):
        return PHRASES_RENOVACION.get(fase, ["nuevas noticias sobre la renovación"])
    return ["rumor sin clasificar"]


def _generate_text(
    nombre: str, tipo: str, club_origen: str, fase: int, outcome: str
) -> str:
    phrase = random.choice(_phrases_for(tipo, fase, outcome))
    templates = [
        f"{nombre}: {phrase}. {club_origen} confirma el interés.",
        f"Fuentes cercanas al Real Madrid confirman: {phrase} con {nombre}.",
        f"{phrase} — {nombre} ({club_origen}) en el radar madridista.",
        f"Según fuentes de confianza, {phrase} para {nombre}.",
        f"{nombre} ({club_origen}): {phrase} en las próximas horas.",
    ]
    return random.choice(templates)


def _parse_date(s: str) -> datetime:
    return datetime.strptime(s, "%Y-%m-%d")


def generate_rumores_for_transfer(transfer: dict) -> list[dict]:
    """Generate 5-25 synthetic rumors for one historical transfer."""
    fecha_oficial = _parse_date(transfer["fecha_oficial"])
    tipo = transfer["tipo"]
    outcome = transfer["outcome"]
    nombre = transfer["nombre"]
    club_origen = transfer.get("club_origen", "club desconocido")

    # Distribute journalists that reported on this transfer
    reporting_journalists = []
    for pattern in JOURNALIST_PATTERNS:
        pid, lead_min, lead_max, hit_mult, n_min, n_max = pattern
        # Some journalists don't always report (especially for smaller transfers)
        n = random.randint(n_min, n_max)
        if n == 0:
            continue
        for _ in range(n):
            reporting_journalists.append((pid, lead_min, lead_max, hit_mult))

    # Assign phases based on how many weeks before the official date
    rumores = []

    for pid, lead_min, lead_max, hit_mult in reporting_journalists:
        lead_days = random.randint(lead_min, min(lead_max, 180))
        fecha_rumor = fecha_oficial - timedelta(days=lead_days)

        # Determine phase based on lead_days
        if lead_days > 60:
            fase = random.randint(1, 2)
        elif lead_days > 30:
            fase = random.randint(2, 3)
        elif lead_days > 14:
            fase = random.randint(3, 4)
        elif lead_days > 7:
            fase = random.randint(4, 5)
        elif lead_days > 2:
            fase = 5
        else:
            fase = 6

        # Determine rumor outcome
        if outcome == "OPERACION_CAIDA":
            # Early rumors lean PENDIENTE; later rumors may have signal of failure
            if lead_days < 10:
                rumor_outcome = "FALLIDO"
            else:
                rumor_outcome = "PENDIENTE"
        else:
            if fase == 6:
                rumor_outcome = "CONFIRMADO"
            else:
                rumor_outcome = "PENDIENTE"

        texto = _generate_text(nombre, tipo, club_origen, fase, outcome)

        # Use a consistent slug for jugador_id across rumors of the same player
        jugador_slug = nombre.lower().replace(" ", "-").replace("(", "").replace(")", "").replace(".", "")

        rumor = {
            "rumor_id": str(uuid.uuid4()),
            "jugador_slug": jugador_slug,
            "nombre_canonico": nombre,
            "periodista_id": pid,
            "tipo_operacion": tipo,
            "fase_rumor": fase,
            "texto_fragmento": texto,
            "lexico_detectado": random.choice(_phrases_for(tipo, fase, outcome)),
            "peso_lexico": round(random.uniform(0.3, 0.95), 3),
            "confianza_extraccion": round(random.uniform(0.55, 0.98), 3),
            "extraido_con": "regex",
            "club_destino": club_origen if tipo == "SALIDA" else "Real Madrid",
            "fecha_publicacion": fecha_rumor.isoformat(),
            "idioma": "es",
            "outcome": rumor_outcome,
            "outcome_at": fecha_oficial.isoformat() if rumor_outcome != "PENDIENTE" else None,
            # Transfer metadata for building jugadores row
            "_transfer_outcome": outcome,
            "_transfer_fecha_oficial": transfer["fecha_oficial"],
            "_transfer_valor_m": transfer.get("valor_m", 0.0),
            "_posicion": transfer.get("posicion"),
            "_edad": transfer.get("edad"),
        }
        rumores.append(rumor)

    # Ensure at least 5 rumors
    while len(rumores) < 5:
        lead_days = random.randint(5, 45)
        fecha_rumor = fecha_oficial - timedelta(days=lead_days)
        fase = 3 if lead_days > 14 else 5
        pid = "relevo-rm"
        rumor_outcome = "CONFIRMADO" if outcome not in ("OPERACION_CAIDA",) and fase == 6 else "PENDIENTE"
        jugador_slug = nombre.lower().replace(" ", "-").replace("(", "").replace(")", "").replace(".", "")
        texto = _generate_text(nombre, tipo, club_origen, fase, outcome)
        rumores.append(
            {
                "rumor_id": str(uuid.uuid4()),
                "jugador_slug": jugador_slug,
                "nombre_canonico": nombre,
                "periodista_id": pid,
                "tipo_operacion": tipo,
                "fase_rumor": fase,
                "texto_fragmento": texto,
                "lexico_detectado": random.choice(_phrases_for(tipo, fase, outcome)),
                "peso_lexico": round(random.uniform(0.3, 0.7), 3),
                "confianza_extraccion": round(random.uniform(0.55, 0.80), 3),
                "extraido_con": "regex",
                "club_destino": club_origen if tipo == "SALIDA" else "Real Madrid",
                "fecha_publicacion": fecha_rumor.isoformat(),
                "idioma": "es",
                "outcome": rumor_outcome,
                "outcome_at": None,
                "_transfer_outcome": outcome,
                "_transfer_fecha_oficial": transfer["fecha_oficial"],
                "_transfer_valor_m": transfer.get("valor_m", 0.0),
                "_posicion": transfer.get("posicion"),
                "_edad": transfer.get("edad"),
            }
        )

    # Sort by date ascending
    rumores.sort(key=lambda r: r["fecha_publicacion"])
    return rumores


def main() -> None:
    output_dir = Path(__file__).parent.parent / "data" / "backfill"
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / "rumores_historicos.jsonl"

    all_rumores = []
    transfer_count = 0

    for transfer in TRANSFERS:
        rumores = generate_rumores_for_transfer(transfer)
        all_rumores.extend(rumores)
        transfer_count += 1

    # Write JSONL
    with output_path.open("w", encoding="utf-8") as f:
        for r in all_rumores:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    # Summary
    print(f"Generated {len(all_rumores)} synthetic rumors for {transfer_count} transfers")
    print(f"Written to: {output_path}")

    # Per-transfer stats
    by_player: dict[str, int] = {}
    for r in all_rumores:
        nombre = r["nombre_canonico"]
        by_player[nombre] = by_player.get(nombre, 0) + 1

    min_count = min(by_player.values())
    max_count = max(by_player.values())
    avg_count = sum(by_player.values()) / len(by_player)
    print(f"Rumors per player: min={min_count}, max={max_count}, avg={avg_count:.1f}")
    print(f"All players have ≥5 rumors: {min_count >= 5}")


if __name__ == "__main__":
    main()
