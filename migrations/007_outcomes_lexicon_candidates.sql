-- Migration 007: outcome tracking columns + outcomes_historicos + lexicon_candidates

-- ── Extend jugadores with outcome tracking ────────────────────────────────────
ALTER TABLE jugadores ADD COLUMN outcome_clasificado TEXT
    CHECK(outcome_clasificado IN (
        'FICHAJE_EFECTIVO','SALIDA_EFECTIVA','RENOVACION_EFECTIVA',
        'CESION_EFECTIVA','OPERACION_CAIDA','PENDIENTE'
    ));
ALTER TABLE jugadores ADD COLUMN fecha_outcome TEXT;
ALTER TABLE jugadores ADD COLUMN fuente_confirmacion TEXT;

-- ── outcomes_historicos ───────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS outcomes_historicos (
    outcome_id          TEXT PRIMARY KEY,
    jugador_id          TEXT NOT NULL REFERENCES jugadores(jugador_id),
    outcome_tipo        TEXT NOT NULL CHECK(outcome_tipo IN (
                            'FICHAJE_EFECTIVO','SALIDA_EFECTIVA','RENOVACION_EFECTIVA',
                            'CESION_EFECTIVA','OPERACION_CAIDA'
                        )),
    fecha               TEXT NOT NULL,
    club_destino        TEXT,
    valor_traspaso_m    REAL,
    salario_bruto_m     REAL,
    fuente_confirmacion TEXT,
    rumor_id_trigger    TEXT REFERENCES rumores(rumor_id),
    created_at          TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_outcomes_jugador ON outcomes_historicos(jugador_id);
CREATE INDEX IF NOT EXISTS idx_outcomes_fecha   ON outcomes_historicos(fecha DESC);

-- ── lexicon_candidates ────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS lexicon_candidates (
    candidate_id        TEXT PRIMARY KEY,
    frase               TEXT NOT NULL,
    idioma              TEXT NOT NULL DEFAULT 'es',
    n_observaciones     INTEGER DEFAULT 0,
    n_aciertos          INTEGER DEFAULT 0,
    hit_rate_empirico   REAL,
    peso_sugerido       REAL,
    tipo_operacion      TEXT,
    fase_sugerida       INTEGER,
    estado              TEXT DEFAULT 'pending_review'
                            CHECK(estado IN ('pending_review','aceptado','rechazado')),
    origen              TEXT DEFAULT 'aprendido_candidato',
    ejemplo_rumor_id    TEXT REFERENCES rumores(rumor_id),
    created_at          TEXT DEFAULT (datetime('now')),
    UNIQUE(frase, idioma)
);
CREATE INDEX IF NOT EXISTS idx_candidates_estado ON lexicon_candidates(estado, hit_rate_empirico DESC);
