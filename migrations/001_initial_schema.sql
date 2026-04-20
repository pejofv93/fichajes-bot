-- Cloudflare D1 schema v3.1
-- Sin PRAGMA WAL (D1 lo gestiona internamente)
-- Sin sequences (usar TEXT uuid o INTEGER autoincrement)

-- ────────────────────────────────────────────────────────────────────────────
-- 1. fuentes — RSS feeds, Bluesky handles, web scrapers
-- ────────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS fuentes (
    fuente_id         TEXT PRIMARY KEY,
    tipo              TEXT NOT NULL CHECK(tipo IN ('rss','bluesky','web_selectolax')),
    tier              TEXT NOT NULL CHECK(tier IN ('S','A','B','C')),
    url               TEXT,
    bluesky_handle    TEXT,
    periodista_id     TEXT,
    idioma            TEXT DEFAULT 'es',
    sesgo             TEXT DEFAULT 'neutral',
    factor_fichaje_positivo   REAL DEFAULT 1.0,
    factor_salida_positiva    REAL DEFAULT 1.0,
    polling_minutes   INTEGER DEFAULT 120,
    rate_limit_seconds INTEGER DEFAULT 0,
    entidades         TEXT DEFAULT '[]',
    is_disabled       INTEGER DEFAULT 0,
    consecutive_errors INTEGER DEFAULT 0,
    last_fetched_at   TEXT,
    last_etag         TEXT,
    last_modified     TEXT,
    nota              TEXT,
    created_at        TEXT DEFAULT (datetime('now')),
    updated_at        TEXT DEFAULT (datetime('now'))
);

-- ────────────────────────────────────────────────────────────────────────────
-- 2. periodistas
-- ────────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS periodistas (
    periodista_id         TEXT PRIMARY KEY,
    nombre_completo       TEXT NOT NULL,
    tier                  TEXT NOT NULL CHECK(tier IN ('S','A','B','C')),
    medio_principal       TEXT,
    idioma                TEXT DEFAULT 'en',
    reliability_global    REAL DEFAULT 0.5,
    alpha_global          REAL DEFAULT 1.0,
    beta_global           REAL DEFAULT 1.0,
    n_predicciones_global INTEGER DEFAULT 0,
    n_aciertos_global     INTEGER DEFAULT 0,
    reliability_rm        REAL,
    alpha_rm              REAL DEFAULT 1.0,
    beta_rm               REAL DEFAULT 1.0,
    n_predicciones_rm     INTEGER DEFAULT 0,
    n_aciertos_rm         INTEGER DEFAULT 0,
    bluesky_handle        TEXT,
    twitter_handle        TEXT,
    notas                 TEXT,
    created_at            TEXT DEFAULT (datetime('now')),
    updated_at            TEXT DEFAULT (datetime('now'))
);

-- ────────────────────────────────────────────────────────────────────────────
-- 3. rumores_raw — contenido sin procesar
-- ────────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS rumores_raw (
    raw_id            TEXT PRIMARY KEY,
    fuente_id         TEXT NOT NULL REFERENCES fuentes(fuente_id),
    url_canonico      TEXT,
    titulo            TEXT,
    texto_completo    TEXT,
    html_crudo        TEXT,
    fecha_publicacion TEXT,
    fecha_ingesta     TEXT DEFAULT (datetime('now')),
    idioma_detectado  TEXT,
    hash_dedup        TEXT UNIQUE,
    procesado         INTEGER DEFAULT 0,
    descartado        INTEGER DEFAULT 0,
    motivo_descarte   TEXT
);
CREATE INDEX IF NOT EXISTS idx_rumores_raw_procesado ON rumores_raw(procesado, fecha_ingesta);
CREATE INDEX IF NOT EXISTS idx_rumores_raw_hash ON rumores_raw(hash_dedup);

-- ────────────────────────────────────────────────────────────────────────────
-- 4. jugadores — estado actual de cada jugador en el radar
-- ────────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS jugadores (
    jugador_id                TEXT PRIMARY KEY,
    nombre_canonico           TEXT NOT NULL,
    slug                      TEXT UNIQUE,
    posicion                  TEXT,
    club_actual               TEXT,
    club_origen               TEXT,
    edad                      INTEGER,
    nacionalidad              TEXT,
    valor_mercado_m           REAL,
    tipo_operacion_principal  TEXT CHECK(tipo_operacion_principal IN ('FICHAJE','SALIDA','RENOVACION','CESION')),
    entidad                   TEXT DEFAULT 'primer_equipo' CHECK(entidad IN ('primer_equipo','castilla','juvenil_a','cedido')),
    score_raw                 REAL DEFAULT 0.0,
    score_smoothed            REAL DEFAULT 0.0,
    score_anterior            REAL DEFAULT 0.0,
    kalman_P                  REAL DEFAULT 1.0,
    factores_actuales         TEXT DEFAULT '{}',
    fase_dominante            INTEGER DEFAULT 1,
    flags                     TEXT DEFAULT '[]',
    primera_mencion_at        TEXT,
    ultima_actualizacion_at   TEXT DEFAULT (datetime('now')),
    n_fuentes_distintas       INTEGER DEFAULT 0,
    n_rumores_total           INTEGER DEFAULT 0,
    is_active                 INTEGER DEFAULT 1,
    created_at                TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_jugadores_score ON jugadores(score_smoothed DESC);
CREATE INDEX IF NOT EXISTS idx_jugadores_tipo ON jugadores(tipo_operacion_principal, entidad);

-- ────────────────────────────────────────────────────────────────────────────
-- 5. rumores — rumores procesados y asociados a jugadores
-- ────────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS rumores (
    rumor_id          TEXT PRIMARY KEY,
    raw_id            TEXT REFERENCES rumores_raw(raw_id),
    jugador_id        TEXT REFERENCES jugadores(jugador_id),
    periodista_id     TEXT REFERENCES periodistas(periodista_id),
    fuente_id         TEXT REFERENCES fuentes(fuente_id),
    tipo_operacion    TEXT CHECK(tipo_operacion IN ('FICHAJE','SALIDA','RENOVACION','CESION')),
    club_destino      TEXT,
    club_origen_rumor TEXT,
    fase_rumor        INTEGER DEFAULT 1 CHECK(fase_rumor BETWEEN 1 AND 6),
    lexico_detectado  TEXT,
    peso_lexico       REAL DEFAULT 0.0,
    confianza_extraccion REAL DEFAULT 0.0,
    extraido_con      TEXT CHECK(extraido_con IN ('regex','gemini')),
    es_globo_sonda    INTEGER DEFAULT 0,
    retractado        INTEGER DEFAULT 0,
    retractado_at     TEXT,
    outcome           TEXT CHECK(outcome IN ('CONFIRMADO','FALLIDO','PENDIENTE')),
    outcome_at        TEXT,
    fecha_publicacion TEXT,
    idioma            TEXT,
    texto_fragmento   TEXT,
    created_at        TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_rumores_jugador ON rumores(jugador_id, retractado, fecha_publicacion DESC);
CREATE INDEX IF NOT EXISTS idx_rumores_periodista ON rumores(periodista_id, fecha_publicacion DESC);

-- ────────────────────────────────────────────────────────────────────────────
-- 6. score_history — historial de cambios de score
-- ────────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS score_history (
    history_id        TEXT PRIMARY KEY,
    jugador_id        TEXT NOT NULL REFERENCES jugadores(jugador_id),
    score_anterior    REAL,
    score_nuevo       REAL,
    delta             REAL,
    razon_cambio      TEXT,
    explicacion_humana TEXT,
    factores_snapshot TEXT DEFAULT '{}',
    timestamp         TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_score_history_jugador ON score_history(jugador_id, timestamp DESC);

-- ────────────────────────────────────────────────────────────────────────────
-- 7. eventos_pending — cola de eventos entre jobs
-- ────────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS eventos_pending (
    evento_id         TEXT PRIMARY KEY,
    tipo              TEXT NOT NULL,
    payload           TEXT DEFAULT '{}',
    procesado         INTEGER DEFAULT 0,
    created_at        TEXT DEFAULT (datetime('now')),
    procesado_at      TEXT
);
CREATE INDEX IF NOT EXISTS idx_eventos_pending_tipo ON eventos_pending(tipo, procesado);

-- ────────────────────────────────────────────────────────────────────────────
-- 8. alertas_log — historial de alertas enviadas
-- ────────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS alertas_log (
    log_id            TEXT PRIMARY KEY,
    jugador_id        TEXT,
    tipo_alerta       TEXT,
    mensaje_enviado   TEXT,
    score_snapshot    REAL,
    enviada_at        TEXT DEFAULT (datetime('now')),
    feedback_usuario  TEXT,
    telegram_msg_id   INTEGER
);

-- ────────────────────────────────────────────────────────────────────────────
-- 9. metricas_sistema — KPIs del sistema
-- ────────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS metricas_sistema (
    metric_id         TEXT PRIMARY KEY,
    metric_name       TEXT NOT NULL,
    value             TEXT,
    value_num         REAL,
    timestamp         TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_metricas_name ON metricas_sistema(metric_name, timestamp DESC);

-- ────────────────────────────────────────────────────────────────────────────
-- 10. flags_sistema — flags de control del sistema
-- ────────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS flags_sistema (
    flag_name         TEXT PRIMARY KEY,
    estado            TEXT DEFAULT 'OFF',
    valor             TEXT,
    descripcion       TEXT,
    actualizado_at    TEXT DEFAULT (datetime('now'))
);

-- ────────────────────────────────────────────────────────────────────────────
-- 11. modelo_economico — estado económico del RM
-- ────────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS modelo_economico (
    econ_id                       TEXT PRIMARY KEY,
    temporada                     TEXT,
    tope_laliga_rm                REAL,
    masa_salarial_actual          REAL,
    margen_salarial               REAL,
    presupuesto_fichajes_estimado REAL,
    presupuesto_fichajes_restante REAL,
    plusvalias_acumuladas         REAL DEFAULT 0.0,
    regla_actual                  TEXT,
    politica_edad_max             INTEGER DEFAULT 30,
    activo                        INTEGER DEFAULT 1,
    fecha_actualizacion           TEXT DEFAULT (datetime('now')),
    fuente                        TEXT,
    confianza                     REAL DEFAULT 0.5
);

-- ────────────────────────────────────────────────────────────────────────────
-- 12. lexicon_entries — léxico curado cargado desde YAML
-- ────────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS lexicon_entries (
    entry_id          TEXT PRIMARY KEY,
    frase             TEXT NOT NULL,
    idioma            TEXT NOT NULL,
    categoria         TEXT NOT NULL,
    fase_rumor        INTEGER,
    tipo_operacion    TEXT,
    peso_base         REAL DEFAULT 0.5,
    periodista_id     TEXT,
    origen            TEXT DEFAULT 'curado_manual',
    peso_aprendido    REAL,
    n_ocurrencias     INTEGER DEFAULT 0,
    n_aciertos        INTEGER DEFAULT 0,
    created_at        TEXT DEFAULT (datetime('now')),
    updated_at        TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_lexicon_idioma ON lexicon_entries(idioma, categoria);

-- ────────────────────────────────────────────────────────────────────────────
-- 13. llm_cache — cache de llamadas Gemini
-- ────────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS llm_cache (
    cache_id          TEXT PRIMARY KEY,
    input_hash        TEXT UNIQUE NOT NULL,
    modelo            TEXT,
    prompt_hash       TEXT,
    response_json     TEXT,
    tokens_used       INTEGER,
    created_at        TEXT DEFAULT (datetime('now')),
    expires_at        TEXT
);
CREATE INDEX IF NOT EXISTS idx_llm_cache_hash ON llm_cache(input_hash);
CREATE INDEX IF NOT EXISTS idx_llm_cache_expires ON llm_cache(expires_at);

-- ────────────────────────────────────────────────────────────────────────────
-- 14. calibracion_periodistas — historial detallado de calibración
-- ────────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS calibracion_periodistas (
    cal_id            TEXT PRIMARY KEY,
    periodista_id     TEXT NOT NULL REFERENCES periodistas(periodista_id),
    rumor_id          TEXT REFERENCES rumores(rumor_id),
    prediccion        REAL,
    outcome_real      INTEGER,
    brier_contribution REAL,
    fecha_prediccion  TEXT,
    fecha_outcome     TEXT,
    contexto          TEXT DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_cal_periodista ON calibracion_periodistas(periodista_id, fecha_outcome DESC);

-- ────────────────────────────────────────────────────────────────────────────
-- 15. substitution_graph — grafo de sustitución entre jugadores
-- ────────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS substitution_graph (
    edge_id           TEXT PRIMARY KEY,
    jugador_origen_id TEXT NOT NULL,
    jugador_destino_id TEXT NOT NULL,
    tipo_relacion     TEXT CHECK(tipo_relacion IN ('SUSTITUYE','ALTERNATIVA','COMPLEMENTARIO')),
    peso_relacion     REAL DEFAULT 0.5,
    posicion_relevante TEXT,
    fuente_relacion   TEXT DEFAULT 'manual',
    created_at        TEXT DEFAULT (datetime('now')),
    updated_at        TEXT DEFAULT (datetime('now')),
    UNIQUE(jugador_origen_id, jugador_destino_id)
);

-- ────────────────────────────────────────────────────────────────────────────
-- 16. cantera_jugadores — jugadores del Castilla y Juvenil A
-- ────────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS cantera_jugadores (
    jugador_id        TEXT PRIMARY KEY,
    nombre_canonico   TEXT NOT NULL,
    slug              TEXT UNIQUE,
    posicion          TEXT,
    edad              INTEGER,
    nacionalidad      TEXT,
    nivel             TEXT CHECK(nivel IN ('castilla','juvenil_a')),
    estado            TEXT CHECK(estado IN ('activo','cedido','ascendido','salida')) DEFAULT 'activo',
    club_cesion       TEXT,
    score_debut       REAL DEFAULT 0.0,
    score_fichaje_ext REAL DEFAULT 0.0,
    score_salida      REAL DEFAULT 0.0,
    flags             TEXT DEFAULT '[]',
    created_at        TEXT DEFAULT (datetime('now')),
    updated_at        TEXT DEFAULT (datetime('now'))
);

-- ────────────────────────────────────────────────────────────────────────────
-- 17. cedidos — rastro de cesiones activas
-- ────────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS cedidos (
    cesion_id         TEXT PRIMARY KEY,
    jugador_id        TEXT NOT NULL,
    club_cesion       TEXT NOT NULL,
    liga_cesion       TEXT,
    fecha_inicio      TEXT,
    fecha_fin         TEXT,
    opcion_compra_m   REAL,
    opcion_compra_activa INTEGER DEFAULT 0,
    rendimiento_nota  REAL,
    probabilidad_retorno REAL DEFAULT 0.5,
    probabilidad_venta REAL DEFAULT 0.2,
    probabilidad_extension REAL DEFAULT 0.3,
    activa            INTEGER DEFAULT 1,
    updated_at        TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_cedidos_activa ON cedidos(activa, jugador_id);

-- ────────────────────────────────────────────────────────────────────────────
-- 18. retractaciones — retractaciones documentadas
-- ────────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS retractaciones (
    retractacion_id   TEXT PRIMARY KEY,
    rumor_id          TEXT REFERENCES rumores(rumor_id),
    jugador_id        TEXT REFERENCES jugadores(jugador_id),
    periodista_id     TEXT REFERENCES periodistas(periodista_id),
    texto_original    TEXT,
    texto_retractacion TEXT,
    fuente_retractacion TEXT,
    fecha_original    TEXT,
    fecha_retractacion TEXT,
    tipo              TEXT CHECK(tipo IN ('DESMENTIDO_OFICIAL','RETRACTACION_PERIODISTA','SILENCIO_PROLONGADO','OTRO')),
    impacto_score     REAL DEFAULT -0.3,
    procesado         INTEGER DEFAULT 0,
    created_at        TEXT DEFAULT (datetime('now'))
);
