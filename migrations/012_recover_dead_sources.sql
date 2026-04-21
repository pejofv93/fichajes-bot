-- Disable dead RSS sources (broken endpoints, WAF blocked)
UPDATE fuentes SET is_disabled=1, updated_at=datetime('now') WHERE fuente_id='realmadrid_noticias_rss';
UPDATE fuentes SET is_disabled=1, updated_at=datetime('now') WHERE fuente_id='realmadrid_canteras_rss';
UPDATE fuentes SET is_disabled=1, updated_at=datetime('now') WHERE fuente_id='skysport_de_rss';

-- Replace realmadrid_noticias_rss with web_selectolax (SSR Angular page, .rm-news__list selector)
-- Runs in cold-loop via scrape_web.py (web_selectolax sources are excluded from hot-loop)
INSERT OR IGNORE INTO fuentes (fuente_id, tipo, tier, url, idioma, sesgo, factor_fichaje_positivo, polling_minutes, nota)
VALUES (
    'realmadrid_web_noticias',
    'web_selectolax',
    'S',
    'https://www.realmadrid.com/es-ES/noticias',
    'es',
    'oficial',
    1.0,
    120,
    'Reemplaza realmadrid_noticias_rss (RSS muerto). SSR Angular, selector .rm-news__list.'
);

-- Replace realmadrid_canteras_rss with web_selectolax for the youth academy section
INSERT OR IGNORE INTO fuentes (fuente_id, tipo, tier, url, idioma, sesgo, factor_fichaje_positivo, polling_minutes, entidades, nota)
VALUES (
    'realmadrid_web_canteras',
    'web_selectolax',
    'S',
    'https://www.realmadrid.com/es-ES/futbol/cantera-masculina',
    'es',
    'oficial',
    0.8,
    240,
    '["castilla","juvenil_a"]',
    'Reemplaza realmadrid_canteras_rss (RSS muerto). 14+ artículos cantera SSR.'
);

-- Promote kicker_rss tier A→S so it enters hot-loop
-- NOTE: scrape.py (hot-loop) filters by tier, not polling_minutes.
-- Lowering polling_minutes alone has no effect on hot-loop inclusion for RSS sources.
UPDATE fuentes
SET tier='S', polling_minutes=120, updated_at=datetime('now')
WHERE fuente_id='kicker_rss';
