-- Migration 015: añadir fuentes RSS específicas de Real Madrid via Google News
-- Verificadas 200 el 2026-04-22. Las URLs de marca.com/as.com/relevo.com
-- para RM específico devuelven 404 — se usan búsquedas Google News en su lugar.
-- Estos items ya contienen "Real Madrid" + palabra de fichaje → pasan el prefilter.

INSERT OR IGNORE INTO fuentes
    (fuente_id, tipo, tier, url, idioma, sesgo,
     factor_fichaje_positivo, factor_salida_positiva,
     polling_minutes, is_disabled, created_at, updated_at)
VALUES
    (
        'rm_fichajes_gn_es',
        'rss',
        'B',
        'https://news.google.com/rss/search?q=%22Real+Madrid%22+fichaje+OR+traspaso+OR+renovacion&hl=es&gl=ES&ceid=ES:es',
        'es',
        'neutral',
        1.0, 1.0,
        60,
        0,
        datetime('now'), datetime('now')
    ),
    (
        'rm_transfers_gn_en',
        'rss',
        'B',
        'https://news.google.com/rss/search?q=%22Real+Madrid%22+transfer+OR+signing+OR+deal&hl=en&gl=ES&ceid=ES:en',
        'en',
        'neutral',
        1.0, 1.0,
        60,
        0,
        datetime('now'), datetime('now')
    );
