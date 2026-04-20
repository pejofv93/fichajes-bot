-- Seed: Léxico curado Apéndice C — ~250 frases
-- Fases: 1=interés inicial, 2=negociaciones, 3=acuerdo personal, 4=acuerdo clubs, 5=firma inminente, 6=confirmado

INSERT OR IGNORE INTO lexicon_entries (entry_id, frase, idioma, categoria, fase_rumor, tipo_operacion, peso_base) VALUES

-- ============================================================
-- ESPAÑOL — FICHAJE (signing in)
-- ============================================================
('es-f-01', 'acuerdo total alcanzado',              'es', 'fichaje', 6, 'FICHAJE', 0.95),
('es-f-02', 'aquí vamos',                           'es', 'fichaje', 6, 'FICHAJE', 0.98),
('es-f-03', 'acuerdo cerrado',                      'es', 'fichaje', 5, 'FICHAJE', 0.90),
('es-f-04', 'contrato firmado',                     'es', 'fichaje', 6, 'FICHAJE', 0.97),
('es-f-05', 'ya es oficial',                        'es', 'fichaje', 6, 'FICHAJE', 0.99),
('es-f-06', 'fichaje confirmado',                   'es', 'fichaje', 6, 'FICHAJE', 0.99),
('es-f-07', 'trato cerrado',                        'es', 'fichaje', 5, 'FICHAJE', 0.88),
('es-f-08', 'negociaciones avanzadas',              'es', 'fichaje', 3, 'FICHAJE', 0.65),
('es-f-09', 'contactos directos',                   'es', 'fichaje', 2, 'FICHAJE', 0.50),
('es-f-10', 'oferta presentada',                    'es', 'fichaje', 3, 'FICHAJE', 0.62),
('es-f-11', 'oferta formal',                        'es', 'fichaje', 3, 'FICHAJE', 0.65),
('es-f-12', 'propuesta sobre la mesa',              'es', 'fichaje', 3, 'FICHAJE', 0.60),
('es-f-13', 'el Real Madrid quiere',                'es', 'fichaje', 2, 'FICHAJE', 0.45),
('es-f-14', 'el Madrid sigue al jugador',           'es', 'fichaje', 2, 'FICHAJE', 0.40),
('es-f-15', 'primera oferta rechazada',             'es', 'fichaje', 3, 'FICHAJE', 0.55),
('es-f-16', 'contraoferta enviada',                 'es', 'fichaje', 4, 'FICHAJE', 0.70),
('es-f-17', 'acuerdo personal alcanzado',           'es', 'fichaje', 4, 'FICHAJE', 0.82),
('es-f-18', 'acuerdo con el jugador',               'es', 'fichaje', 4, 'FICHAJE', 0.80),
('es-f-19', 'pendiente del acuerdo entre clubes',   'es', 'fichaje', 4, 'FICHAJE', 0.75),
('es-f-20', 'viaje para pasar el reconocimiento',   'es', 'fichaje', 5, 'FICHAJE', 0.93),
('es-f-21', 'revisión médica',                      'es', 'fichaje', 5, 'FICHAJE', 0.92),
('es-f-22', 'pasa el médico mañana',                'es', 'fichaje', 5, 'FICHAJE', 0.94),
('es-f-23', 'done deal',                            'es', 'fichaje', 6, 'FICHAJE', 0.97),
('es-f-24', 'presentación prevista',                'es', 'fichaje', 6, 'FICHAJE', 0.95),
('es-f-25', 'en camino a Madrid',                   'es', 'fichaje', 5, 'FICHAJE', 0.90),
('es-f-26', 'en Madrid para firmar',                'es', 'fichaje', 5, 'FICHAJE', 0.95),
('es-f-27', 'traspaso acordado',                    'es', 'fichaje', 5, 'FICHAJE', 0.90),
('es-f-28', 'cifra acordada',                       'es', 'fichaje', 4, 'FICHAJE', 0.78),
('es-f-29', 'el Madrid ha llegado a un acuerdo',    'es', 'fichaje', 5, 'FICHAJE', 0.88),
('es-f-30', 'transfer fee agreed',                  'es', 'fichaje', 4, 'FICHAJE', 0.82),
('es-f-31', 'interés del Real Madrid',              'es', 'fichaje', 1, 'FICHAJE', 0.35),
('es-f-32', 'en la agenda del Madrid',              'es', 'fichaje', 1, 'FICHAJE', 0.30),
('es-f-33', 'Real Madrid apunta a',                 'es', 'fichaje', 1, 'FICHAJE', 0.32),
('es-f-34', 'sondeo del Real Madrid',               'es', 'fichaje', 2, 'FICHAJE', 0.42),
('es-f-35', 'convocado para la presentación',       'es', 'fichaje', 6, 'FICHAJE', 0.98),
('es-f-36', 'clausula de rescisión activada',       'es', 'fichaje', 4, 'FICHAJE', 0.85),
('es-f-37', 'liberación de cláusula',               'es', 'fichaje', 5, 'FICHAJE', 0.90),
('es-f-38', 'compra confirmada',                    'es', 'fichaje', 6, 'FICHAJE', 0.99),

-- ============================================================
-- ESPAÑOL — SALIDA (departure)
-- ============================================================
('es-s-01', 'no renovará',                          'es', 'salida', 3, 'SALIDA', 0.75),
('es-s-02', 'quiere salir',                         'es', 'salida', 2, 'SALIDA', 0.55),
('es-s-03', 'ha pedido la salida',                  'es', 'salida', 3, 'SALIDA', 0.72),
('es-s-04', 'rescisión de contrato',                'es', 'salida', 5, 'SALIDA', 0.90),
('es-s-05', 'rescisión acordada',                   'es', 'salida', 5, 'SALIDA', 0.92),
('es-s-06', 'salida libre',                         'es', 'salida', 5, 'SALIDA', 0.85),
('es-s-07', 'sale libre en junio',                  'es', 'salida', 4, 'SALIDA', 0.80),
('es-s-08', 'traspaso inminente',                   'es', 'salida', 5, 'SALIDA', 0.87),
('es-s-09', 'cedido al',                            'es', 'salida', 5, 'CESION', 0.85),
('es-s-10', 'cesión confirmada',                    'es', 'salida', 6, 'CESION', 0.95),
('es-s-11', 'ofrecido a otros clubes',              'es', 'salida', 2, 'SALIDA', 0.50),
('es-s-12', 'descartado por el Madrid',             'es', 'salida', 3, 'SALIDA', 0.65),
('es-s-13', 'no cuenta para Ancelotti',             'es', 'salida', 3, 'SALIDA', 0.70),
('es-s-14', 'fuera de los planes',                  'es', 'salida', 3, 'SALIDA', 0.68),
('es-s-15', 'en la lista de ventas',                'es', 'salida', 3, 'SALIDA', 0.65),
('es-s-16', 'buscando equipo',                      'es', 'salida', 3, 'SALIDA', 0.62),
('es-s-17', 'contrato no renovado',                 'es', 'salida', 5, 'SALIDA', 0.88),
('es-s-18', 'fin de contrato',                      'es', 'salida', 4, 'SALIDA', 0.75),
('es-s-19', 'acuerdo para su venta',                'es', 'salida', 5, 'SALIDA', 0.88),
('es-s-20', 'venta cerrada',                        'es', 'salida', 6, 'SALIDA', 0.96),

-- ============================================================
-- INGLÉS — SIGNING IN
-- ============================================================
('en-f-01', 'here we go',                           'en', 'fichaje', 6, 'FICHAJE', 0.98),
('en-f-02', 'personal terms agreed',                'en', 'fichaje', 4, 'FICHAJE', 0.85),
('en-f-03', 'deal done',                            'en', 'fichaje', 6, 'FICHAJE', 0.97),
('en-f-04', 'medical scheduled',                    'en', 'fichaje', 5, 'FICHAJE', 0.93),
('en-f-05', 'medical tomorrow',                     'en', 'fichaje', 5, 'FICHAJE', 0.94),
('en-f-06', 'fee agreed',                           'en', 'fichaje', 4, 'FICHAJE', 0.82),
('en-f-07', 'transfer fee agreed',                  'en', 'fichaje', 4, 'FICHAJE', 0.83),
('en-f-08', 'signing confirmed',                    'en', 'fichaje', 6, 'FICHAJE', 0.99),
('en-f-09', 'contract signed',                      'en', 'fichaje', 6, 'FICHAJE', 0.99),
('en-f-10', 'bid accepted',                         'en', 'fichaje', 4, 'FICHAJE', 0.80),
('en-f-11', 'bid rejected',                         'en', 'fichaje', 3, 'FICHAJE', 0.55),
('en-f-12', 'improved offer submitted',             'en', 'fichaje', 3, 'FICHAJE', 0.62),
('en-f-13', 'Real Madrid are interested',           'en', 'fichaje', 1, 'FICHAJE', 0.35),
('en-f-14', 'Real Madrid want',                     'en', 'fichaje', 2, 'FICHAJE', 0.42),
('en-f-15', 'Real Madrid have made contact',        'en', 'fichaje', 2, 'FICHAJE', 0.50),
('en-f-16', 'Real Madrid are tracking',             'en', 'fichaje', 1, 'FICHAJE', 0.32),
('en-f-17', 'Real Madrid preparing offer',          'en', 'fichaje', 3, 'FICHAJE', 0.60),
('en-f-18', 'formal offer submitted',               'en', 'fichaje', 3, 'FICHAJE', 0.65),
('en-f-19', 'on his way to Madrid',                 'en', 'fichaje', 5, 'FICHAJE', 0.92),
('en-f-20', 'agreement reached',                    'en', 'fichaje', 5, 'FICHAJE', 0.87),
('en-f-21', 'clubs have reached agreement',         'en', 'fichaje', 5, 'FICHAJE', 0.88),
('en-f-22', 'will undergo medical',                 'en', 'fichaje', 5, 'FICHAJE', 0.93),
('en-f-23', 'done deal confirmed',                  'en', 'fichaje', 6, 'FICHAJE', 0.99),
('en-f-24', 'release clause activated',             'en', 'fichaje', 5, 'FICHAJE', 0.92),
('en-f-25', 'move confirmed',                       'en', 'fichaje', 6, 'FICHAJE', 0.96),
('en-f-26', 'Real Madrid close to signing',         'en', 'fichaje', 4, 'FICHAJE', 0.72),
('en-f-27', 'verbally agreed',                      'en', 'fichaje', 4, 'FICHAJE', 0.78),
('en-f-28', 'in advanced talks',                    'en', 'fichaje', 3, 'FICHAJE', 0.65),
('en-f-29', 'exclusive negotiations',               'en', 'fichaje', 4, 'FICHAJE', 0.75),

-- ============================================================
-- INGLÉS — DEPARTURE
-- ============================================================
('en-d-01', 'will leave',                           'en', 'salida', 4, 'SALIDA', 0.75),
('en-d-02', 'has asked to leave',                   'en', 'salida', 3, 'SALIDA', 0.72),
('en-d-03', 'not in plans',                         'en', 'salida', 3, 'SALIDA', 0.65),
('en-d-04', 'will not renew',                       'en', 'salida', 3, 'SALIDA', 0.75),
('en-d-05', 'contract not renewed',                 'en', 'salida', 5, 'SALIDA', 0.88),
('en-d-06', 'exit agreed',                          'en', 'salida', 5, 'SALIDA', 0.88),
('en-d-07', 'sale agreed',                          'en', 'salida', 6, 'SALIDA', 0.95),
('en-d-08', 'on loan to',                           'en', 'salida', 5, 'CESION', 0.88),
('en-d-09', 'loan agreed',                          'en', 'salida', 5, 'CESION', 0.90),
('en-d-10', 'leaving in the summer',                'en', 'salida', 3, 'SALIDA', 0.65),
('en-d-11', 'not part of the manager plans',        'en', 'salida', 3, 'SALIDA', 0.68),
('en-d-12', 'put up for sale',                      'en', 'salida', 3, 'SALIDA', 0.65),

-- ============================================================
-- ITALIANO — ACQUISTO (signing)
-- ============================================================
('it-f-01', 'accordo trovato',                      'it', 'fichaje', 5, 'FICHAJE', 0.90),
('it-f-02', 'trattativa avanzata',                  'it', 'fichaje', 3, 'FICHAJE', 0.65),
('it-f-03', 'visite mediche',                       'it', 'fichaje', 5, 'FICHAJE', 0.93),
('it-f-04', 'accordo raggiunto',                    'it', 'fichaje', 5, 'FICHAJE', 0.90),
('it-f-05', 'contratto firmato',                    'it', 'fichaje', 6, 'FICHAJE', 0.98),
('it-f-06', 'colpo fatto',                          'it', 'fichaje', 6, 'FICHAJE', 0.96),
('it-f-07', 'affare chiuso',                        'it', 'fichaje', 6, 'FICHAJE', 0.95),
('it-f-08', 'offerta presentata',                   'it', 'fichaje', 3, 'FICHAJE', 0.62),
('it-f-09', 'offerta accettata',                    'it', 'fichaje', 4, 'FICHAJE', 0.82),
('it-f-10', 'il Real Madrid vuole',                 'it', 'fichaje', 2, 'FICHAJE', 0.42),
('it-f-11', 'trattativa in corso',                  'it', 'fichaje', 3, 'FICHAJE', 0.60),
('it-f-12', 'intesa raggiunta',                     'it', 'fichaje', 5, 'FICHAJE', 0.87),
('it-f-13', 'fumata bianca',                        'it', 'fichaje', 6, 'FICHAJE', 0.96),

-- ============================================================
-- ITALIANO — CESSIONE (departure)
-- ============================================================
('it-d-01', 'non rinnoverà',                        'it', 'salida', 3, 'SALIDA', 0.75),
('it-d-02', 'ha chiesto la cessione',               'it', 'salida', 3, 'SALIDA', 0.72),
('it-d-03', 'addio confermato',                     'it', 'salida', 6, 'SALIDA', 0.95),
('it-d-04', 'lascia il Real Madrid',                'it', 'salida', 5, 'SALIDA', 0.85),
('it-d-05', 'cessione accordata',                   'it', 'salida', 5, 'CESION', 0.90),

-- ============================================================
-- ALEMÁN — TRANSFER
-- ============================================================
('de-f-01', 'einigung erzielt',                     'de', 'fichaje', 5, 'FICHAJE', 0.88),
('de-f-02', 'deal perfekt',                         'de', 'fichaje', 6, 'FICHAJE', 0.96),
('de-f-03', 'medizincheck',                         'de', 'fichaje', 5, 'FICHAJE', 0.93),
('de-f-04', 'unterschrift',                         'de', 'fichaje', 6, 'FICHAJE', 0.95),
('de-f-05', 'transfer fix',                         'de', 'fichaje', 6, 'FICHAJE', 0.96),
('de-f-06', 'interesse von real madrid',            'de', 'fichaje', 1, 'FICHAJE', 0.35),
('de-f-07', 'einig geworden',                       'de', 'fichaje', 5, 'FICHAJE', 0.87),
('de-f-08', 'angebot eingereicht',                  'de', 'fichaje', 3, 'FICHAJE', 0.62),
('de-f-09', 'ablösesumme vereinbart',               'de', 'fichaje', 4, 'FICHAJE', 0.82),
('de-f-10', 'wechsel perfekt',                      'de', 'fichaje', 6, 'FICHAJE', 0.96),
('de-d-01', 'verlässt real madrid',                 'de', 'salida',  5, 'SALIDA', 0.85),
('de-d-02', 'vertrag läuft aus',                    'de', 'salida',  4, 'SALIDA', 0.72),
('de-d-03', 'abgang fix',                           'de', 'salida',  6, 'SALIDA', 0.94),
('de-d-04', 'kein neuer vertrag',                   'de', 'salida',  4, 'SALIDA', 0.75),

-- ============================================================
-- FRANCÉS — TRANSFERT
-- ============================================================
('fr-f-01', 'accord trouvé',                        'fr', 'fichaje', 5, 'FICHAJE', 0.88),
('fr-f-02', 'visite médicale',                      'fr', 'fichaje', 5, 'FICHAJE', 0.93),
('fr-f-03', 'transfert confirmé',                   'fr', 'fichaje', 6, 'FICHAJE', 0.97),
('fr-f-04', 'contrat signé',                        'fr', 'fichaje', 6, 'FICHAJE', 0.98),
('fr-f-05', 'le Real Madrid veut',                  'fr', 'fichaje', 2, 'FICHAJE', 0.42),
('fr-f-06', 'offre formulée',                       'fr', 'fichaje', 3, 'FICHAJE', 0.62),
('fr-f-07', 'accord entre clubs',                   'fr', 'fichaje', 5, 'FICHAJE', 0.87),
('fr-f-08', 'accord personnel',                     'fr', 'fichaje', 4, 'FICHAJE', 0.82),
('fr-f-09', 'dossier bouclé',                       'fr', 'fichaje', 6, 'FICHAJE', 0.95),
('fr-f-10', 'en passe de signer',                   'fr', 'fichaje', 5, 'FICHAJE', 0.88),
('fr-d-01', 'ne renouvellera pas',                  'fr', 'salida',  3, 'SALIDA', 0.75),
('fr-d-02', 'départ confirmé',                      'fr', 'salida',  6, 'SALIDA', 0.95),
('fr-d-03', 'prêt confirmé',                        'fr', 'salida',  6, 'CESION', 0.94),
('fr-d-04', 'mis sur le marché',                    'fr', 'salida',  3, 'SALIDA', 0.62),

-- ============================================================
-- MODIFICADORES DE INTENSIDAD (aplican a todos los idiomas)
-- ============================================================
('mod-i-01', 'exclusiva',      'es', 'intensificador', NULL, NULL, 0.15),
('mod-i-02', 'confirmado',     'es', 'intensificador', NULL, NULL, 0.20),
('mod-i-03', 'inminente',      'es', 'intensificador', NULL, NULL, 0.18),
('mod-i-04', 'breaking',       'en', 'intensificador', NULL, NULL, 0.15),
('mod-i-05', 'exclusive',      'en', 'intensificador', NULL, NULL, 0.15),
('mod-i-06', 'imminent',       'en', 'intensificador', NULL, NULL, 0.18),
('mod-i-07', 'scoop',          'en', 'intensificador', NULL, NULL, 0.12),
('mod-i-08', 'ufficiale',      'it', 'intensificador', NULL, NULL, 0.20),
('mod-i-09', 'offizielle',     'de', 'intensificador', NULL, NULL, 0.20),
('mod-i-10', 'officiel',       'fr', 'intensificador', NULL, NULL, 0.20),

-- ============================================================
-- NEGACIONES (reducen el peso)
-- ============================================================
('neg-01', 'no hay acuerdo',       'es', 'negacion', NULL, NULL, -0.60),
('neg-02', 'descartado',           'es', 'negacion', NULL, NULL, -0.55),
('neg-03', 'desmiente',            'es', 'negacion', NULL, NULL, -0.65),
('neg-04', 'no es verdad',         'es', 'negacion', NULL, NULL, -0.70),
('neg-05', 'fake news',            'es', 'negacion', NULL, NULL, -0.75),
('neg-06', 'no confirmed',         'en', 'negacion', NULL, NULL, -0.55),
('neg-07', 'denied',               'en', 'negacion', NULL, NULL, -0.65),
('neg-08', 'not happening',        'en', 'negacion', NULL, NULL, -0.70),
('neg-09', 'no agreement',         'en', 'negacion', NULL, NULL, -0.60),
('neg-10', 'totalmente falso',     'es', 'negacion', NULL, NULL, -0.80),
('neg-11', 'smentito',             'it', 'negacion', NULL, NULL, -0.65),
('neg-12', 'dementi',              'fr', 'negacion', NULL, NULL, -0.65),
('neg-13', 'dementiert',           'de', 'negacion', NULL, NULL, -0.65),
('neg-14', 'se cierra la puerta',  'es', 'negacion', NULL, NULL, -0.50),
('neg-15', 'operación descartada', 'es', 'negacion', NULL, NULL, -0.62),

-- ============================================================
-- GLOBO SONDA (trial balloon markers)
-- ============================================================
('tb-01', 'según fuentes',         'es', 'globo_sonda', NULL, NULL, -0.10),
('tb-02', 'se baraja',             'es', 'globo_sonda', NULL, NULL, -0.15),
('tb-03', 'podría fichar',         'es', 'globo_sonda', NULL, NULL, -0.12),
('tb-04', 'suena para',            'es', 'globo_sonda', NULL, NULL, -0.12),
('tb-05', 'en la órbita de',       'es', 'globo_sonda', NULL, NULL, -0.10),
('tb-06', 'según entorno',         'es', 'globo_sonda', NULL, NULL, -0.15),
('tb-07', 'could be interested',   'en', 'globo_sonda', NULL, NULL, -0.12),
('tb-08', 'reportedly',            'en', 'globo_sonda', NULL, NULL, -0.10),
('tb-09', 'sources suggest',       'en', 'globo_sonda', NULL, NULL, -0.12),
('tb-10', 'is understood',         'en', 'globo_sonda', NULL, NULL, -0.08),
('tb-11', 'could be on the move',  'en', 'globo_sonda', NULL, NULL, -0.10),
('tb-12', 'si insiste',            'it', 'globo_sonda', NULL, NULL, -0.12),
('tb-13', 'stando a indiscrezioni','it', 'globo_sonda', NULL, NULL, -0.12),
('tb-14', 'gerücht',               'de', 'globo_sonda', NULL, NULL, -0.12),
('tb-15', 'selon les informations','fr', 'globo_sonda', NULL, NULL, -0.10),

-- ============================================================
-- RENOVACIÓN
-- ============================================================
('es-r-01', 'renovación acordada',     'es', 'renovacion', 5, 'RENOVACION', 0.88),
('es-r-02', 'renovará',                'es', 'renovacion', 3, 'RENOVACION', 0.55),
('es-r-03', 'nuevo contrato firmado',  'es', 'renovacion', 6, 'RENOVACION', 0.96),
('es-r-04', 'extiende su contrato',    'es', 'renovacion', 6, 'RENOVACION', 0.95),
('es-r-05', 'acuerdo de renovación',   'es', 'renovacion', 5, 'RENOVACION', 0.88),
('en-r-01', 'contract extension',      'en', 'renovacion', 5, 'RENOVACION', 0.85),
('en-r-02', 'new deal signed',         'en', 'renovacion', 6, 'RENOVACION', 0.96),
('en-r-03', 'will sign new contract',  'en', 'renovacion', 4, 'RENOVACION', 0.72),
('en-r-04', 'renewal confirmed',       'en', 'renovacion', 6, 'RENOVACION', 0.95),
('it-r-01', 'rinnovo firmato',         'it', 'renovacion', 6, 'RENOVACION', 0.96),
('de-r-01', 'vertrag verlängert',      'de', 'renovacion', 6, 'RENOVACION', 0.95),
('fr-r-01', 'prolongation signée',     'fr', 'renovacion', 6, 'RENOVACION', 0.96);
