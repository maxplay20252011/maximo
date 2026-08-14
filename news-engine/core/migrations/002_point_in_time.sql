-- 002_point_in_time.sql
-- Almacen point-in-time (§2). Tres tablas, una por agujero de §2.1.
--
-- (a) prices.close_raw es SIN AJUSTAR. Los ajustes viven en corporate_actions con
--     la fecha en que se hicieron publicos. Nunca se sobreescribe un close historico.
-- (b) macro_observations guarda vintages de ALFRED: el mismo obs_date tiene tantas
--     filas como veces se reviso la serie. Nunca se pisa un vintage viejo.
-- (c) El sesgo de supervivencia no se arregla con schema: se acota el universo a
--     ETFs e indices (config/universe.yaml) y se declara en el header del reporte.

-- ---------------------------------------------------------------------------
-- prices: cierres diarios crudos
-- Visibilidad: el cierre de la fecha D se considera publico a las D 23:59:59Z.
-- Regla conservadora y uniforme; refinar por horario de cada mercado es trabajo
-- posterior y solo puede ampliar la visibilidad, nunca adelantarla.
-- ---------------------------------------------------------------------------
CREATE TABLE prices (
    asset          TEXT NOT NULL CHECK (length(trim(asset)) > 0),
    price_date     TEXT NOT NULL CHECK (price_date GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]'),
    close_raw      REAL NOT NULL CHECK (close_raw > 0),
    open_raw       REAL CHECK (open_raw IS NULL OR open_raw > 0),
    high_raw       REAL CHECK (high_raw IS NULL OR high_raw > 0),
    low_raw        REAL CHECK (low_raw IS NULL OR low_raw > 0),
    volume         REAL CHECK (volume IS NULL OR volume >= 0),
    source         TEXT NOT NULL,
    fetched_at_utc TEXT NOT NULL
                   CHECK (fetched_at_utc GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]T[0-9][0-9]:[0-9][0-9]:[0-9][0-9]Z'),
    PRIMARY KEY (asset, price_date)
);

CREATE INDEX idx_prices_date ON prices(price_date);

-- ---------------------------------------------------------------------------
-- corporate_actions: splits y dividendos con fecha de anuncio
-- announced_at_utc es la columna que hace point-in-time al ajuste. Si la fuente
-- no informa fecha de anuncio, el cargador usa el ex_date: eso atrasa el ajuste
-- respecto de la realidad, que es el lado seguro (adelantarlo seria look-ahead).
-- split_ratio = acciones nuevas por accion vieja (2.0 en un split 2:1).
-- ---------------------------------------------------------------------------
CREATE TABLE corporate_actions (
    action_id        TEXT PRIMARY KEY,
    asset            TEXT NOT NULL CHECK (length(trim(asset)) > 0),
    kind             TEXT NOT NULL CHECK (kind IN ('SPLIT','DIVIDEND')),
    ex_date          TEXT NOT NULL CHECK (ex_date GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]'),
    announced_at_utc TEXT NOT NULL
                     CHECK (announced_at_utc GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]T[0-9][0-9]:[0-9][0-9]:[0-9][0-9]Z'),
    split_ratio      REAL CHECK (split_ratio IS NULL OR split_ratio > 0),
    dividend_amount  REAL CHECK (dividend_amount IS NULL OR dividend_amount >= 0),
    source           TEXT NOT NULL,
    fetched_at_utc   TEXT NOT NULL
                     CHECK (fetched_at_utc GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]T[0-9][0-9]:[0-9][0-9]:[0-9][0-9]Z'),
    CHECK (kind <> 'SPLIT'    OR split_ratio IS NOT NULL),
    CHECK (kind <> 'DIVIDEND' OR dividend_amount IS NOT NULL),
    -- Nada se anuncia despues de ejecutarse.
    CHECK (announced_at_utc <= ex_date || 'T23:59:59Z')
);

CREATE UNIQUE INDEX idx_ca_unique   ON corporate_actions(asset, kind, ex_date);
CREATE INDEX        idx_ca_asset_ex ON corporate_actions(asset, ex_date);

-- ---------------------------------------------------------------------------
-- macro_observations: vintages de ALFRED
-- obs_date     = periodo que mide el dato (marzo 2020)
-- vintage_date = dia en que ese valor fue publico (realtime_start de ALFRED)
-- value NULL   = la fuente publico '.' (dato faltante). No es cero.
-- ---------------------------------------------------------------------------
CREATE TABLE macro_observations (
    series_id      TEXT NOT NULL CHECK (length(trim(series_id)) > 0),
    obs_date       TEXT NOT NULL CHECK (obs_date GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]'),
    vintage_date   TEXT NOT NULL CHECK (vintage_date GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]'),
    value          REAL,
    source         TEXT NOT NULL,
    fetched_at_utc TEXT NOT NULL
                   CHECK (fetched_at_utc GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]T[0-9][0-9]:[0-9][0-9]:[0-9][0-9]Z'),
    -- Un dato no puede ser publico antes del periodo que mide.
    CHECK (vintage_date >= obs_date),
    PRIMARY KEY (series_id, obs_date, vintage_date)
);

CREATE INDEX idx_macro_vintage ON macro_observations(series_id, vintage_date);
CREATE INDEX idx_macro_obs     ON macro_observations(series_id, obs_date);
