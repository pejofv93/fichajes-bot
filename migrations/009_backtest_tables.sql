-- Migration 009: backtesting tables

-- ── backtest_runs — metadata for each backtest execution ─────────────────────
CREATE TABLE IF NOT EXISTS backtest_runs (
    run_id          TEXT PRIMARY KEY,
    started_at      TEXT DEFAULT (datetime('now')),
    completed_at    TEXT,
    metrics_json    TEXT DEFAULT '{}',
    config_json     TEXT DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_backtest_runs_started ON backtest_runs(started_at DESC);

-- ── backtest_results — individual predictions per window ─────────────────────
CREATE TABLE IF NOT EXISTS backtest_results (
    result_id           TEXT PRIMARY KEY,
    run_id              TEXT NOT NULL REFERENCES backtest_runs(run_id),
    window_start        TEXT NOT NULL,
    window_end          TEXT NOT NULL,
    jugador_id          TEXT NOT NULL,
    predicted_score     REAL NOT NULL,
    actual_outcome      INTEGER NOT NULL,
    tipo                TEXT,
    periodista_principal TEXT,
    created_at          TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_backtest_results_run   ON backtest_results(run_id);
CREATE INDEX IF NOT EXISTS idx_backtest_results_window ON backtest_results(window_start, window_end);
CREATE INDEX IF NOT EXISTS idx_backtest_results_jugador ON backtest_results(jugador_id);
