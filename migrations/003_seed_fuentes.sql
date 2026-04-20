-- Seed: fuentes basadas en configs/sources.yaml

INSERT OR IGNORE INTO fuentes (fuente_id, tipo, tier, url, bluesky_handle, periodista_id, idioma, sesgo, factor_fichaje_positivo, factor_salida_positiva, polling_minutes, nota) VALUES

-- TIER S Bluesky
('romano_bluesky',      'bluesky', 'S', NULL, 'fabrizioromano.bsky.social',  'fabrizio-romano',    'en', 'neutral', 1.0, 1.0, 120, 'Primary. Breaking news con delay vs Twitter.'),
('ornstein_bluesky',    'bluesky', 'S', NULL, 'davidornstein.bsky.social',   'david-ornstein',     'en', 'neutral', 1.0, 1.0, 120, NULL),

-- TIER S RSS
('romano_rss_relevo',   'rss', 'S', 'https://www.relevo.com/rss/autores/fabrizio-romano.xml', NULL, 'fabrizio-romano',    'es', 'neutral', 1.0, 1.0, 120, 'Fallback si Bluesky no tiene el post.'),
('athletic_rss',        'rss', 'S', 'https://www.nytimes.com/athletic/rss/soccer',            NULL, 'athletic-soccer',    'en', 'neutral', 1.0, 1.0, 120, 'The Athletic = Ornstein + tier-S internacionales.'),
('relevo_rss',          'rss', 'S', 'https://www.relevo.com/rss',                             NULL, 'matteo-moretto',     'es', 'neutral', 1.0, 1.0, 120, NULL),
('dimarzio_rss',        'rss', 'S', 'https://www.gianlucadimarzio.com/en/feed',               NULL, 'gianluca-di-marzio', 'it', 'neutral', 1.0, 1.0, 120, NULL),
('skysport_de_rss',     'rss', 'S', 'https://www.skysport.de/rss/transfernews',               NULL, 'florian-plettenberg','de', 'neutral', 1.0, 1.0, 120, NULL),
('realmadrid_noticias_rss', 'rss', 'S', 'https://www.realmadrid.com/rss/noticias',            NULL, 'marca-rm-oficial',   'es', 'oficial', 1.0, 1.0, 120, 'Comunicados oficiales RM.'),

-- TIER A RSS
('relevo_general_rss',  'rss', 'A', 'https://www.relevo.com/rss',                             NULL, NULL, 'es', 'neutral', 1.0, 1.0, 240, NULL),
('bbc_sport_rss',       'rss', 'A', 'http://feeds.bbci.co.uk/sport/football/rss.xml',         NULL, NULL, 'en', 'neutral', 1.0, 1.0, 240, NULL),
('lequipe_rss',         'rss', 'A', 'https://www.lequipe.fr/rss/actu_rss.xml',                NULL, NULL, 'fr', 'neutral', 1.0, 1.0, 240, NULL),
('gazzetta_rss',        'rss', 'A', 'https://www.gazzetta.it/rss/Home.xml',                   NULL, NULL, 'it', 'neutral', 1.0, 1.0, 240, NULL),
('kicker_rss',          'rss', 'A', 'https://newsfeed.kicker.de/news/aktuell',                NULL, NULL, 'de', 'neutral', 1.0, 1.0, 240, NULL),
('balague_blog_rss',    'rss', 'A', 'https://www.guillembalague.com/feed',                    NULL, 'guillem-balague', 'en', 'neutral', 1.0, 1.0, 240, NULL),
('sky_sports_rss',      'rss', 'A', 'https://www.skysports.com/rss/12040',                    NULL, NULL, 'en', 'neutral', 1.0, 1.0, 240, NULL),

-- TIER B RSS (sesgo documentado)
('marca_rss',    'rss', 'B', 'https://e00-marca.uecdn.es/rss/portada.xml',    NULL, NULL, 'es', 'pro-rm',    0.75, 1.0, 240, NULL),
('as_rss',       'rss', 'B', 'https://as.com/rss/actualidad/portada.xml',     NULL, NULL, 'es', 'pro-rm',    0.70, 1.0, 240, NULL),
('md_rss',       'rss', 'B', 'https://www.mundodeportivo.com/rss/home.xml',   NULL, NULL, 'es', 'pro-barca', 0.90, 0.65, 240, NULL),
('sport_rss',    'rss', 'B', 'https://www.sport.es/es/rss/futbol/rss.xml',    NULL, NULL, 'es', 'pro-barca', 0.90, 0.60, 240, NULL),
('cope_rss',     'rss', 'B', 'https://www.cope.es/rss/deportes',              NULL, NULL, 'es', 'neutral',   0.72, 0.90, 240, NULL),
('cadena_ser_rss','rss','B', 'https://cadenaser.com/rss',                     NULL, NULL, 'es', 'neutral',   0.72, 0.90, 240, NULL),

-- WEB SCRAPING selectolax (cold-loop only)
('transfermarkt_rm',    'web_selectolax', 'A', 'https://www.transfermarkt.com/real-madrid/transfers/verein/418', NULL, NULL, 'en', 'neutral', 1.0, 1.0, 720,   'Rate limit 5s.'),
('capology_rm',         'web_selectolax', 'A', 'https://www.capology.com/club/real-madrid/salaries',            NULL, NULL, 'en', 'neutral', 1.0, 1.0, 10080, NULL),
('laliga_transparencia','web_selectolax', 'S', 'https://www.laliga.com/transparencia/limites-coste-plantilla',  NULL, NULL, 'es', 'oficial', 1.0, 1.0, 10080, NULL),

-- CANTERA RSS
('realmadrid_canteras_rss', 'rss', 'S', 'https://www.realmadrid.com/rss/canteras',      NULL, NULL, 'es', 'neutral', 1.0, 1.0, 240, NULL),
('canteradelrealmadrid_rss','rss', 'A', 'https://canteradelrealmadrid.com/feed',         NULL, NULL, 'es', 'neutral', 1.0, 1.0, 240, NULL),
('rfef_juv_web',            'web_selectolax','S','https://www.rfef.es/competiciones/juvenil-division-honor', NULL, NULL, 'es', 'neutral', 1.0, 1.0, 1440, NULL);
