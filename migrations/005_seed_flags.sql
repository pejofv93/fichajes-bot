-- Seed: flags del sistema, todos en OFF por defecto

INSERT OR IGNORE INTO flags_sistema (flag_name, estado, descripcion) VALUES
('alertas_realtime',         'ENFORCE_HARD', 'Alertas en tiempo real al chat de Telegram'),
('modo_silencio',            'OFF',          'Silenciar todas las alertas temporalmente'),
('debug_mode',               'OFF',          'Logging verboso en todos los jobs'),
('gemini_enabled',           'ON',           'Activar llamadas a Gemini Flash'),
('bluesky_scraping_enabled', 'ON',           'Activar scraping de Bluesky'),
('web_scraping_enabled',     'ON',           'Activar scraping web selectolax'),
('calibration_enabled',      'ON',           'Activar auto-calibración Bayesiana'),
('backtesting_enabled',      'OFF',          'Activar módulo de backtesting'),
('cantera_enabled',          'ON',           'Activar extensión cantera'),
('dashboard_enabled',        'ON',           'Activar generación de dashboard GitHub Pages'),
('mercado_activo',           'OFF',          'Modo mercado activo: incrementa frecuencia de alertas'),
('emergencia_minutos',       'OFF',          'Reducir intervalos a modo emergencia (verano cierre mercado)'),
('trial_balloon_filter',     'ON',           'Activar filtro de globos sonda'),
('bias_correction_enabled',  'ON',           'Activar corrección de sesgo mediático'),
('economic_validator',       'ON',           'Activar validador económico en scoring'),
('substitution_propagation', 'ON',           'Activar propagación de sustitución en scoring');

-- Valor inicial del modelo económico (placeholder hasta primera ejecución del cold-loop)
INSERT OR IGNORE INTO modelo_economico (
    econ_id, temporada, tope_laliga_rm, masa_salarial_actual,
    margen_salarial, presupuesto_fichajes_estimado,
    presupuesto_fichajes_restante, regla_actual,
    politica_edad_max, activo, fuente, confianza
) VALUES (
    'econ-2025-26', '2025-26',
    800000000, 650000000, 150000000, 200000000, 200000000,
    'LaLiga Financial Fair Play', 30, 1,
    'placeholder_bootstrap', 0.3
);
