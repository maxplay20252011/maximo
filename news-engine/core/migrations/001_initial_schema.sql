-- 001_initial_schema.sql
-- Esquema inicial. 8 tablas de dominio segun §3, con los dominios de §4 (regimenes),
-- §7.1 (calidad de match) y §8.2 (reglas de scoring) codificados como CHECK.
--
-- Convenciones de tiempo:
--   *_utc / created_at / computed_at / started_at : 'YYYY-MM-DDTHH:MM:SSZ' (UTC, segundos)
--   start_date / end_date                          : 'YYYY-MM-DD'
-- El formato se verifica con GLOB en cada columna. Es rigido a proposito: un timestamp
-- naive o en hora local escrito por error es exactamente la clase de bug que produce
-- look-ahead silencioso (§2).
--
-- PRAGMA foreign_keys se activa en core/db.py::connect(); dentro de una transaccion
-- (que es como corre esta migracion) el PRAGMA es no-op.

-- ---------------------------------------------------------------------------
-- regimes (§4)
-- Episodios contiguos. Se cierra uno y se abre otro cuando cambia una dimension.
-- ---------------------------------------------------------------------------
CREATE TABLE regimes (
    regime_id        TEXT PRIMARY KEY,
    regime_label     TEXT NOT NULL,
    start_date       TEXT NOT NULL UNIQUE
                     CHECK (start_date GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]'),
    end_date         TEXT
                     CHECK (end_date IS NULL OR
                            (end_date GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]'
                             AND end_date > start_date)),
    rate_regime      TEXT NOT NULL CHECK (rate_regime IN ('ZIRP','HIKING','CUTTING','HIGH_STABLE')),
    vol_regime       TEXT NOT NULL CHECK (vol_regime IN ('LOW','NORMAL','STRESSED','CRISIS')),
    inflation_regime TEXT NOT NULL CHECK (inflation_regime IN ('DEFLATIONARY','ANCHORED','ELEVATED','RUNAWAY')),
    usd_trend        TEXT NOT NULL CHECK (usd_trend IN ('STRONG','WEAK','NEUTRAL')),
    credit_regime    TEXT NOT NULL CHECK (credit_regime IN ('TIGHT','NORMAL','WIDE','STRESS')),
    vix_pctile       REAL CHECK (vix_pctile IS NULL OR vix_pctile BETWEEN 0 AND 1),
    hy_oas_pctile    REAL CHECK (hy_oas_pctile IS NULL OR hy_oas_pctile BETWEEN 0 AND 1)
);

CREATE INDEX idx_regimes_span ON regimes(start_date, end_date);

-- A lo sumo un regimen abierto: la linea de tiempo tiene un solo presente.
CREATE UNIQUE INDEX idx_regimes_single_open
    ON regimes((end_date IS NULL)) WHERE end_date IS NULL;

-- ---------------------------------------------------------------------------
-- events_archive (§3, §6)
-- ---------------------------------------------------------------------------
CREATE TABLE events_archive (
    event_id           TEXT PRIMARY KEY,
    occurred_at_utc    TEXT NOT NULL
                       CHECK (occurred_at_utc GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]T[0-9][0-9]:[0-9][0-9]:[0-9][0-9]Z'),
    ingested_at_utc    TEXT NOT NULL
                       CHECK (ingested_at_utc GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]T[0-9][0-9]:[0-9][0-9]:[0-9][0-9]Z'),
    lag_minutes        INTEGER CHECK (lag_minutes IS NULL OR lag_minutes >= 0),
    event_type         TEXT NOT NULL CHECK (length(trim(event_type)) > 0),
    headline           TEXT NOT NULL CHECK (length(trim(headline)) > 0),
    description        TEXT,
    entities_json      TEXT CHECK (entities_json IS NULL OR json_valid(entities_json)),
    severity           INTEGER CHECK (severity IS NULL OR severity BETWEEN 1 AND 5),
    surprise_direction TEXT,
    consensus_value    REAL,
    actual_value       REAL,
    regime_id          TEXT REFERENCES regimes(regime_id) ON DELETE RESTRICT,
    market_state_json  TEXT NOT NULL CHECK (json_valid(market_state_json)),
    embedding          BLOB,
    source             TEXT,
    source_tier        TEXT,
    duplicate_count    INTEGER NOT NULL DEFAULT 1 CHECK (duplicate_count >= 1),
    is_seed            INTEGER NOT NULL DEFAULT 0 CHECK (is_seed IN (0,1)),
    auto_detected      INTEGER NOT NULL DEFAULT 0 CHECK (auto_detected IN (0,1))
);

CREATE INDEX idx_ev_type_date ON events_archive(event_type, occurred_at_utc);
CREATE INDEX idx_ev_regime    ON events_archive(regime_id);
CREATE INDEX idx_ev_sev       ON events_archive(severity);
-- Barrido por fecha sola: el walk-forward del backtest filtra occurred_at < T
-- sin conocer el tipo, y idx_ev_type_date no sirve para eso.
CREATE INDEX idx_ev_occurred  ON events_archive(occurred_at_utc);

-- ---------------------------------------------------------------------------
-- raw_news (§3, §5.3)
-- ---------------------------------------------------------------------------
CREATE TABLE raw_news (
    news_id          TEXT PRIMARY KEY,
    published_at_utc TEXT
                     CHECK (published_at_utc IS NULL OR
                            published_at_utc GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]T[0-9][0-9]:[0-9][0-9]:[0-9][0-9]Z'),
    fetched_at_utc   TEXT NOT NULL
                     CHECK (fetched_at_utc GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]T[0-9][0-9]:[0-9][0-9]:[0-9][0-9]Z'),
    source           TEXT,
    url              TEXT,
    title            TEXT,
    body             TEXT,
    content_hash     TEXT,
    duplicate_of     TEXT REFERENCES raw_news(news_id) ON DELETE SET NULL,
    event_id         TEXT REFERENCES events_archive(event_id) ON DELETE SET NULL,
    classified       INTEGER NOT NULL DEFAULT 0 CHECK (classified IN (0,1)),
    CHECK (duplicate_of IS NULL OR duplicate_of <> news_id)
);

CREATE INDEX idx_news_hash  ON raw_news(content_hash);
CREATE INDEX idx_news_pub   ON raw_news(published_at_utc);
CREATE INDEX idx_news_event ON raw_news(event_id);
CREATE INDEX idx_news_dup   ON raw_news(duplicate_of);
-- Cola de clasificacion (§5.2): indice parcial, solo lo pendiente.
CREATE INDEX idx_news_unclassified
    ON raw_news(published_at_utc) WHERE classified = 0;

-- ---------------------------------------------------------------------------
-- outcomes (§3, §6.3)
-- Convencion de signo: max_drawdown_20d <= 0.
-- ---------------------------------------------------------------------------
CREATE TABLE outcomes (
    event_id           TEXT NOT NULL REFERENCES events_archive(event_id) ON DELETE CASCADE,
    asset              TEXT NOT NULL CHECK (length(trim(asset)) > 0),
    benchmark          TEXT,
    ret_1d             REAL,
    ret_5d             REAL,
    ret_20d            REAL,
    excess_1d          REAL,
    excess_5d          REAL,
    excess_20d         REAL,
    max_drawdown_20d   REAL CHECK (max_drawdown_20d IS NULL OR max_drawdown_20d <= 0),
    vol_realized_5d    REAL CHECK (vol_realized_5d IS NULL OR vol_realized_5d >= 0),
    vol_ratio_vs_prior REAL CHECK (vol_ratio_vs_prior IS NULL OR vol_ratio_vs_prior > 0),
    computed_at        TEXT
                       CHECK (computed_at IS NULL OR
                              computed_at GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]T[0-9][0-9]:[0-9][0-9]:[0-9][0-9]Z'),
    data_quality       TEXT,
    PRIMARY KEY (event_id, asset)
);

CREATE INDEX idx_outcomes_asset ON outcomes(asset);

-- ---------------------------------------------------------------------------
-- calls (§3, §8)
-- ---------------------------------------------------------------------------
CREATE TABLE calls (
    call_id                TEXT PRIMARY KEY,
    event_id               TEXT NOT NULL REFERENCES events_archive(event_id) ON DELETE RESTRICT,
    asset                  TEXT NOT NULL CHECK (length(trim(asset)) > 0),
    direction_bias         TEXT NOT NULL CHECK (direction_bias IN ('UP','DOWN','UNCLEAR')),
    probability            REAL NOT NULL CHECK (probability BETWEEN 0 AND 1),
    horizon                TEXT NOT NULL CHECK (horizon IN ('1d','5d','20d')),
    magnitude_low          REAL,
    magnitude_high         REAL,
    confidence             TEXT NOT NULL CHECK (confidence IN ('LOW','MEDIUM','HIGH')),
    priced_in_flag         INTEGER CHECK (priced_in_flag IS NULL OR priced_in_flag IN (0,1)),
    n_analogs              INTEGER CHECK (n_analogs IS NULL OR n_analogs >= 0),
    directional_agreement  REAL CHECK (directional_agreement IS NULL OR directional_agreement BETWEEN 0 AND 1),
    outcome_dispersion     REAL CHECK (outcome_dispersion IS NULL OR outcome_dispersion >= 0),
    regime_match_quality   TEXT CHECK (regime_match_quality IS NULL OR
                                       regime_match_quality IN ('EXACT','PARTIAL','FORCED')),
    narrative_alignment    TEXT,
    analogs_used_json      TEXT CHECK (analogs_used_json IS NULL OR json_valid(analogs_used_json)),
    counterargument        TEXT NOT NULL CHECK (length(trim(counterargument)) > 0),
    invalidation_condition TEXT NOT NULL CHECK (length(trim(invalidation_condition)) > 0),
    created_at_utc         TEXT NOT NULL
                           CHECK (created_at_utc GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]T[0-9][0-9]:[0-9][0-9]:[0-9][0-9]Z'),
    evaluate_after         TEXT NOT NULL
                           CHECK (evaluate_after GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]T[0-9][0-9]:[0-9][0-9]:[0-9][0-9]Z'),
    -- §8.3: la magnitud es un rango, nunca un punto.
    CHECK (magnitude_low IS NULL OR magnitude_high IS NULL OR magnitude_low < magnitude_high),
    CHECK (evaluate_after > created_at_utc),
    -- §7.1 / §8.2: FORCED fuerza LOW. Sin umbral numerico: los umbrales viven en
    -- config/thresholds.yaml, este es un invariante, no un parametro.
    CHECK (regime_match_quality IS NULL OR regime_match_quality <> 'FORCED' OR confidence = 'LOW')
);

CREATE INDEX idx_calls_eval  ON calls(evaluate_after);
CREATE INDEX idx_calls_event ON calls(event_id);

-- ---------------------------------------------------------------------------
-- call_results (§3, §9.4)
-- hit NULL = movimiento < 0.3%, excluido del hit rate. No es 0.
-- ---------------------------------------------------------------------------
CREATE TABLE call_results (
    call_id             TEXT PRIMARY KEY REFERENCES calls(call_id) ON DELETE CASCADE,
    realized_return     REAL,
    realized_excess     REAL,
    hit                 INTEGER CHECK (hit IS NULL OR hit IN (0,1)),
    brier_contribution  REAL CHECK (brier_contribution IS NULL OR brier_contribution BETWEEN 0 AND 1),
    evaluated_at        TEXT
                        CHECK (evaluated_at IS NULL OR
                               evaluated_at GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]T[0-9][0-9]:[0-9][0-9]:[0-9][0-9]Z')
);

-- ---------------------------------------------------------------------------
-- narrative_state (§10)
-- Append-only: cada update es una version nueva, nunca un UPDATE.
-- ---------------------------------------------------------------------------
CREATE TABLE narrative_state (
    version                 INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at              TEXT NOT NULL
                            CHECK (created_at GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]T[0-9][0-9]:[0-9][0-9]:[0-9][0-9]Z'),
    dominant_narrative      TEXT NOT NULL CHECK (length(trim(dominant_narrative)) > 0),
    market_is_pricing_json  TEXT CHECK (market_is_pricing_json IS NULL OR json_valid(market_is_pricing_json)),
    consensus_positioning   TEXT,
    upcoming_catalysts_json TEXT CHECK (upcoming_catalysts_json IS NULL OR json_valid(upcoming_catalysts_json)),
    what_would_break_it     TEXT
);

-- ---------------------------------------------------------------------------
-- runs (§C.7: healthcheck y doctor leen esta tabla)
-- ---------------------------------------------------------------------------
CREATE TABLE runs (
    run_id          TEXT PRIMARY KEY,
    stage           TEXT NOT NULL CHECK (length(trim(stage)) > 0),
    started_at      TEXT NOT NULL
                    CHECK (started_at GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]T[0-9][0-9]:[0-9][0-9]:[0-9][0-9]Z'),
    finished_at     TEXT
                    CHECK (finished_at IS NULL OR
                           (finished_at GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]T[0-9][0-9]:[0-9][0-9]:[0-9][0-9]Z'
                            AND finished_at >= started_at)),
    status          TEXT NOT NULL CHECK (status IN ('RUNNING','OK','FAILED','PARTIAL')),
    items_processed INTEGER CHECK (items_processed IS NULL OR items_processed >= 0),
    error           TEXT,
    CHECK (status <> 'FAILED' OR error IS NOT NULL)
);

CREATE INDEX idx_runs_stage ON runs(stage, started_at);
