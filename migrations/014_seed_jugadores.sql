-- Migration 014: seed plantilla Real Madrid 2025-26 + objetivos mercado verano 2026
-- Usa INSERT OR IGNORE para ser idempotente

-- ── PLANTILLA ACTUAL REAL MADRID 2025-26 ─────────────────────────────────────

INSERT OR IGNORE INTO jugadores
    (jugador_id, nombre_canonico, slug, posicion, club_actual, club_origen,
     edad, nacionalidad, valor_mercado_m,
     tipo_operacion_principal, entidad, score_raw, score_smoothed, is_active)
VALUES
-- Porteros
('courtois-thibaut',     'Thibaut Courtois',          'courtois-thibaut',     'POR', 'Real Madrid', 'Real Madrid',  32, 'Belga',     30.0, 'RENOVACION', 'primer_equipo', 0.01, 0.01, 1),
('lunin-andriy',         'Andriy Lunin',               'lunin-andriy',         'POR', 'Real Madrid', 'Real Madrid',  25, 'Ucraniano', 18.0, 'RENOVACION', 'primer_equipo', 0.01, 0.01, 1),

-- Defensas centrales
('militao-eder',         'Éder Militão',               'militao-eder',         'DEF', 'Real Madrid', 'Real Madrid',  27, 'Brasileño', 60.0, 'RENOVACION', 'primer_equipo', 0.01, 0.01, 1),
('alaba-david',          'David Alaba',                'alaba-david',          'DEF', 'Real Madrid', 'Real Madrid',  33, 'Austríaco', 10.0, 'RENOVACION', 'primer_equipo', 0.01, 0.01, 1),
('rudiger-antonio',      'Antonio Rüdiger',            'rudiger-antonio',      'DEF', 'Real Madrid', 'Real Madrid',  32, 'Alemán',    22.0, 'RENOVACION', 'primer_equipo', 0.01, 0.01, 1),
('vallejo-jesus',        'Jesús Vallejo',              'vallejo-jesus',        'DEF', 'Real Madrid', 'Real Madrid',  28, 'Español',    3.0, 'SALIDA',     'primer_equipo', 0.01, 0.01, 1),

-- Laterales
('carvajal-dani',        'Dani Carvajal',              'carvajal-dani',        'DEF', 'Real Madrid', 'Real Madrid',  33, 'Español',   20.0, 'RENOVACION', 'primer_equipo', 0.01, 0.01, 1),
('vazquez-lucas',        'Lucas Vázquez',              'vazquez-lucas',        'DEF', 'Real Madrid', 'Real Madrid',  34, 'Español',    5.0, 'RENOVACION', 'primer_equipo', 0.01, 0.01, 1),
('alexander-arnold-trent','Trent Alexander-Arnold',   'alexander-arnold-trent','DEF','Real Madrid', 'Liverpool',    27, 'Inglés',    75.0, 'RENOVACION', 'primer_equipo', 0.01, 0.01, 1),
('mendy-ferland',        'Ferland Mendy',              'mendy-ferland',        'DEF', 'Real Madrid', 'Real Madrid',  30, 'Francés',   35.0, 'RENOVACION', 'primer_equipo', 0.01, 0.01, 1),
('garcia-fran',          'Fran García',                'garcia-fran',          'DEF', 'Real Madrid', 'Real Madrid',  25, 'Español',   18.0, 'RENOVACION', 'primer_equipo', 0.01, 0.01, 1),

-- Centrocampistas
('tchouameni-aurelien',  'Aurélien Tchouaméni',        'tchouameni-aurelien',  'MED', 'Real Madrid', 'Real Madrid',  25, 'Francés',   70.0, 'RENOVACION', 'primer_equipo', 0.01, 0.01, 1),
('camavinga-eduardo',    'Eduardo Camavinga',          'camavinga-eduardo',    'MED', 'Real Madrid', 'Real Madrid',  22, 'Francés',   80.0, 'RENOVACION', 'primer_equipo', 0.01, 0.01, 1),
('valverde-fede',        'Federico Valverde',          'valverde-fede',        'MED', 'Real Madrid', 'Real Madrid',  27, 'Uruguayo',  90.0, 'RENOVACION', 'primer_equipo', 0.01, 0.01, 1),
('bellingham-jude',      'Jude Bellingham',            'bellingham-jude',      'MED', 'Real Madrid', 'Real Madrid',  22, 'Inglés',   180.0, 'RENOVACION', 'primer_equipo', 0.01, 0.01, 1),
('modric-luka',          'Luka Modrić',                'modric-luka',          'MED', 'Real Madrid', 'Real Madrid',  40, 'Croata',     5.0, 'RENOVACION', 'primer_equipo', 0.01, 0.01, 1),
('ceballos-dani',        'Dani Ceballos',              'ceballos-dani',        'MED', 'Real Madrid', 'Real Madrid',  29, 'Español',   20.0, 'RENOVACION', 'primer_equipo', 0.01, 0.01, 1),

-- Delanteros
('vinicius-jr',          'Vinícius Jr',                'vinicius-jr',          'DEL', 'Real Madrid', 'Real Madrid',  25, 'Brasileño', 200.0, 'RENOVACION', 'primer_equipo', 0.01, 0.01, 1),
('mbappe-kylian',        'Kylian Mbappé',              'mbappe-kylian',        'DEL', 'Real Madrid', 'PSG',          27, 'Francés',   200.0, 'RENOVACION', 'primer_equipo', 0.01, 0.01, 1),
('rodrygo-goes',         'Rodrygo Goes',               'rodrygo-goes',         'DEL', 'Real Madrid', 'Real Madrid',  25, 'Brasileño', 100.0, 'RENOVACION', 'primer_equipo', 0.01, 0.01, 1),
('brahim-diaz',          'Brahim Díaz',                'brahim-diaz',          'DEL', 'Real Madrid', 'Real Madrid',  26, 'Español',   35.0,  'RENOVACION', 'primer_equipo', 0.01, 0.01, 1),
('endrick',              'Endrick',                    'endrick',              'DEL', 'Real Madrid', 'Palmeiras',    19, 'Brasileño', 60.0,  'RENOVACION', 'primer_equipo', 0.01, 0.01, 1),

-- ── OBJETIVOS FICHAJE VERANO 2026 ─────────────────────────────────────────────

('haaland-erling',       'Erling Haaland',             'haaland-erling',       'DEL', 'Manchester City',  'Manchester City',  26, 'Noruego',  200.0, 'FICHAJE', 'primer_equipo', 0.01, 0.01, 1),
('salah-mohamed',        'Mohamed Salah',              'salah-mohamed',        'DEL', 'Liverpool',        'Liverpool',        34, 'Egipcio',   50.0, 'FICHAJE', 'primer_equipo', 0.01, 0.01, 1),
('wirtz-florian',        'Florian Wirtz',              'wirtz-florian',        'MED', 'Bayer Leverkusen', 'Bayer Leverkusen', 22, 'Alemán',   150.0, 'FICHAJE', 'primer_equipo', 0.01, 0.01, 1),
('gyokeres-viktor',      'Viktor Gyökeres',            'gyokeres-viktor',      'DEL', 'Sporting CP',      'Sporting CP',      28, 'Sueco',    100.0, 'FICHAJE', 'primer_equipo', 0.01, 0.01, 1),
('kane-harry',           'Harry Kane',                 'kane-harry',           'DEL', 'Bayern München',   'Bayern München',   33, 'Inglés',    80.0, 'FICHAJE', 'primer_equipo', 0.01, 0.01, 1),
('davies-alphonso',      'Alphonso Davies',            'davies-alphonso',      'DEF', 'Bayern München',   'Bayern München',   25, 'Canadiense',70.0, 'FICHAJE', 'primer_equipo', 0.01, 0.01, 1),
('simons-xavi',          'Xavi Simons',                'simons-xavi',          'MED', 'PSG',              'PSG',              23, 'Neerlandés',90.0, 'FICHAJE', 'primer_equipo', 0.01, 0.01, 1),
('williams-nico',        'Nico Williams',              'williams-nico',        'DEL', 'Athletic Club',    'Athletic Club',    23, 'Español',  100.0, 'FICHAJE', 'primer_equipo', 0.01, 0.01, 1),
('zubimendi-martin',     'Martin Zubimendi',           'zubimendi-martin',     'MED', 'Real Sociedad',    'Real Sociedad',    26, 'Español',   60.0, 'FICHAJE', 'primer_equipo', 0.01, 0.01, 1),
('david-jonathan',       'Jonathan David',             'david-jonathan',       'DEL', 'Lille',            'Lille',            25, 'Canadiense',60.0, 'FICHAJE', 'primer_equipo', 0.01, 0.01, 1),
('olmo-dani',            'Dani Olmo',                  'olmo-dani',            'MED', 'FC Barcelona',     'FC Barcelona',     27, 'Español',   70.0, 'FICHAJE', 'primer_equipo', 0.01, 0.01, 1),
('huijsen-dean',         'Dean Huijsen',               'huijsen-dean',         'DEF', 'Bournemouth',      'Bournemouth',      20, 'Neerlandés',45.0, 'FICHAJE', 'primer_equipo', 0.01, 0.01, 1),
('merino-mikel',         'Mikel Merino',               'merino-mikel',         'MED', 'Arsenal',          'Arsenal',          29, 'Español',   45.0, 'FICHAJE', 'primer_equipo', 0.01, 0.01, 1),
('yamal-lamine',         'Lamine Yamal',               'yamal-lamine',         'DEL', 'FC Barcelona',     'FC Barcelona',     18, 'Español',  200.0, 'FICHAJE', 'primer_equipo', 0.01, 0.01, 1),
('lukeba-castello',      'Castello Lukeba',            'lukeba-castello',      'DEF', 'RB Leipzig',       'RB Leipzig',       23, 'Francés',   50.0, 'FICHAJE', 'primer_equipo', 0.01, 0.01, 1);
