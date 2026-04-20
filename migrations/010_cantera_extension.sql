-- Migration 010: cantera extension — Castilla + Juvenil A + cedidos

-- ── New columns in jugadores ──────────────────────────────────────────────────
-- Note: SQLite does not support IF NOT EXISTS in ALTER TABLE.
-- These statements are idempotent via the conftest execute_file error handling.

ALTER TABLE jugadores ADD COLUMN entidad_actual TEXT;
ALTER TABLE jugadores ADD COLUMN entidad_destino_probable TEXT;
ALTER TABLE jugadores ADD COLUMN minutos_castilla_temporada INTEGER DEFAULT 0;
ALTER TABLE jugadores ADD COLUMN rating_medio_cesion REAL;

-- Backfill entidad_actual from entidad for existing rows
UPDATE jugadores SET entidad_actual = entidad WHERE entidad_actual IS NULL;

CREATE INDEX IF NOT EXISTS idx_jugadores_entidad_actual ON jugadores(entidad_actual);

-- ── progresiones_historicas ───────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS progresiones_historicas (
    progresion_id   TEXT PRIMARY KEY,
    jugador_id      TEXT NOT NULL REFERENCES jugadores(jugador_id),
    from_entity     TEXT NOT NULL,
    to_entity       TEXT NOT NULL,
    fecha           TEXT DEFAULT (date('now')),
    tipo            TEXT NOT NULL,         -- PROMOCION | CESION_O_SALIDA
    permanencia_dias INTEGER,              -- days spent in from_entity before move
    notas           TEXT
);

CREATE INDEX IF NOT EXISTS idx_progresiones_jugador ON progresiones_historicas(jugador_id);
CREATE INDEX IF NOT EXISTS idx_progresiones_fecha   ON progresiones_historicas(fecha DESC);
CREATE INDEX IF NOT EXISTS idx_progresiones_tipo    ON progresiones_historicas(tipo);

-- ── rendimiento_cedidos ───────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS rendimiento_cedidos (
    cedido_id       TEXT PRIMARY KEY DEFAULT (lower(hex(randomblob(16)))),
    jugador_id      TEXT NOT NULL REFERENCES jugadores(jugador_id),
    club_cesion     TEXT NOT NULL,
    temporada       TEXT NOT NULL,         -- e.g. '2025-26'
    partidos        INTEGER DEFAULT 0,
    minutos         INTEGER DEFAULT 0,
    goles           INTEGER DEFAULT 0,
    asistencias     INTEGER DEFAULT 0,
    rating_medio    REAL,                  -- Sofascore-style 0-10
    lesion_larga    INTEGER DEFAULT 0,     -- 1 if prolonged injury this season
    actualizado_at  TEXT DEFAULT (datetime('now')),
    UNIQUE(jugador_id, temporada)
);

CREATE INDEX IF NOT EXISTS idx_rendimiento_cedidos_jugador  ON rendimiento_cedidos(jugador_id);
CREATE INDEX IF NOT EXISTS idx_rendimiento_cedidos_temporada ON rendimiento_cedidos(temporada);
CREATE INDEX IF NOT EXISTS idx_rendimiento_cedidos_rating   ON rendimiento_cedidos(rating_medio DESC);
