-- pragma: foreign_keys=off
-- 003_domains.sql
-- Cierra los dominios que quedaron como TEXT libre en 001 (§3 no los enumera).
--
-- SQLite no permite agregar un CHECK con ALTER TABLE: hay que reconstruir la
-- tabla. Se sigue el procedimiento documentado -- crear con nombre temporal,
-- copiar, borrar, renombrar -- con foreign_keys apagado y un foreign_key_check
-- antes del commit, que el runner ejecuta por la directiva de la primera linea.
--
-- Decisiones que fija esta migracion:
--   event_type          -> las 11 clases de classify/event_types.py (§5.2)
--   surprise_direction  -> ABOVE / BELOW / INLINE / NO_CONSENSUS (§5.4)
--   source_tier         -> TIER1 / TIER2 / TIER3
--   narrative_alignment -> CONFIRMS / CONTRADICTS / NEUTRAL (§8.1, §10)
--   data_quality        -> OK / PARTIAL / STALE / NO_BENCHMARK / MISSING
--   calls               -> UNIQUE(event_id, asset, horizon): un call por
--                          evento/activo/horizonte. Re-scorear no puede
--                          duplicar filas y inflar el n de §9.1 sin que
--                          alguien lo decida explicitamente.

-- ---------------------------------------------------------------------------
-- events_archive
-- ---------------------------------------------------------------------------
CREATE TABLE events_archive_new (
    event_id           TEXT PRIMARY KEY,
    occurred_at_utc    TEXT NOT NULL
                       CHECK (occurred_at_utc GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]T[0-9][0-9]:[0-9][0-9]:[0-9][0-9]Z'),
    ingested_at_utc    TEXT NOT NULL
                       CHECK (ingested_at_utc GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]T[0-9][0-9]:[0-9][0-9]:[0-9][0-9]Z'),
    lag_minutes        INTEGER CHECK (lag_minutes IS NULL OR lag_minutes >= 0),
    event_type         TEXT NOT NULL CHECK (event_type IN (
                           'MACRO_DATA','MONETARY_POLICY','CREDIT_EVENT','GEOPOLITICAL',
                           'COMMODITY_SUPPLY','MARKET_STRUCTURE','FX_REGIME','REGULATORY_FISCAL',
                           'CORPORATE_EARNINGS','CORPORATE_ACTION','DISASTER_HEALTH')),
    headline           TEXT NOT NULL CHECK (length(trim(headline)) > 0),
    description        TEXT,
    entities_json      TEXT CHECK (entities_json IS NULL OR json_valid(entities_json)),
    severity           INTEGER CHECK (severity IS NULL OR severity BETWEEN 1 AND 5),
    surprise_direction TEXT CHECK (surprise_direction IS NULL OR
                                   surprise_direction IN ('ABOVE','BELOW','INLINE','NO_CONSENSUS')),
    consensus_value    REAL,
    actual_value       REAL,
    regime_id          TEXT REFERENCES regimes(regime_id) ON DELETE RESTRICT,
    market_state_json  TEXT NOT NULL CHECK (json_valid(market_state_json)),
    embedding          BLOB,
    source             TEXT,
    source_tier        TEXT CHECK (source_tier IS NULL OR source_tier IN ('TIER1','TIER2','TIER3')),
    duplicate_count    INTEGER NOT NULL DEFAULT 1 CHECK (duplicate_count >= 1),
    is_seed            INTEGER NOT NULL DEFAULT 0 CHECK (is_seed IN (0,1)),
    auto_detected      INTEGER NOT NULL DEFAULT 0 CHECK (auto_detected IN (0,1)),
    -- Un consenso sin valor no es 'en linea': es informacion faltante (§5.4).
    CHECK (surprise_direction <> 'NO_CONSENSUS' OR consensus_value IS NULL)
);

INSERT INTO events_archive_new SELECT * FROM events_archive;
DROP TABLE events_archive;
ALTER TABLE events_archive_new RENAME TO events_archive;

CREATE INDEX idx_ev_type_date ON events_archive(event_type, occurred_at_utc);
CREATE INDEX idx_ev_regime    ON events_archive(regime_id);
CREATE INDEX idx_ev_sev       ON events_archive(severity);
CREATE INDEX idx_ev_occurred  ON events_archive(occurred_at_utc);

-- ---------------------------------------------------------------------------
-- outcomes
-- ---------------------------------------------------------------------------
CREATE TABLE outcomes_new (
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
    data_quality       TEXT CHECK (data_quality IS NULL OR
                                   data_quality IN ('OK','PARTIAL','STALE','NO_BENCHMARK','MISSING')),
    -- Sin benchmark no hay exceso. Un exceso calculado contra nada es un retorno
    -- crudo disfrazado (§6.3).
    CHECK (benchmark IS NOT NULL OR (excess_1d IS NULL AND excess_5d IS NULL AND excess_20d IS NULL)),
    PRIMARY KEY (event_id, asset)
);

INSERT INTO outcomes_new SELECT * FROM outcomes;
DROP TABLE outcomes;
ALTER TABLE outcomes_new RENAME TO outcomes;

CREATE INDEX idx_outcomes_asset ON outcomes(asset);

-- ---------------------------------------------------------------------------
-- calls
-- ---------------------------------------------------------------------------
CREATE TABLE calls_new (
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
    narrative_alignment    TEXT CHECK (narrative_alignment IS NULL OR
                                       narrative_alignment IN ('CONFIRMS','CONTRADICTS','NEUTRAL')),
    analogs_used_json      TEXT CHECK (analogs_used_json IS NULL OR json_valid(analogs_used_json)),
    counterargument        TEXT NOT NULL CHECK (length(trim(counterargument)) > 0),
    invalidation_condition TEXT NOT NULL CHECK (length(trim(invalidation_condition)) > 0),
    created_at_utc         TEXT NOT NULL
                           CHECK (created_at_utc GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]T[0-9][0-9]:[0-9][0-9]:[0-9][0-9]Z'),
    evaluate_after         TEXT NOT NULL
                           CHECK (evaluate_after GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]T[0-9][0-9]:[0-9][0-9]:[0-9][0-9]Z'),
    CHECK (magnitude_low IS NULL OR magnitude_high IS NULL OR magnitude_low < magnitude_high),
    CHECK (evaluate_after > created_at_utc),
    CHECK (regime_match_quality IS NULL OR regime_match_quality <> 'FORCED' OR confidence = 'LOW'),
    -- Un call por evento, activo y horizonte.
    UNIQUE (event_id, asset, horizon)
);

INSERT INTO calls_new SELECT * FROM calls;
DROP TABLE calls;
ALTER TABLE calls_new RENAME TO calls;

CREATE INDEX idx_calls_eval  ON calls(evaluate_after);
CREATE INDEX idx_calls_event ON calls(event_id);
