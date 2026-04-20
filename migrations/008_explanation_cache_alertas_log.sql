-- Migration 008: explanation_cache + alertas_log extensions

-- ── explanation_cache — pre-generated /explain responses ─────────────────────
CREATE TABLE IF NOT EXISTS explanation_cache (
    jugador_id      TEXT PRIMARY KEY,
    contenido       TEXT NOT NULL,
    generado_at     TEXT DEFAULT (datetime('now')),
    valido_hasta    TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_explanation_cache_valido ON explanation_cache(valido_hasta);

-- ── alertas_log — add missing columns ───────────────────────────────────────
-- alertas_log already exists from migration 001
-- D1 silently ignores ALTER TABLE ADD COLUMN when column already exists
ALTER TABLE alertas_log ADD COLUMN alert_type TEXT;
ALTER TABLE alertas_log ADD COLUMN chunks_enviados INTEGER DEFAULT 0;
ALTER TABLE alertas_log ADD COLUMN chunks_totales INTEGER DEFAULT 0;
