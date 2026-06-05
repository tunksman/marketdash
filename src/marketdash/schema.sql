-- Instruments registry
CREATE TABLE IF NOT EXISTS instrument (
    instrument_id   INTEGER PRIMARY KEY,
    symbol          VARCHAR NOT NULL,
    display_symbol  VARCHAR NOT NULL,
    asset_class     VARCHAR NOT NULL,  -- crypto/equity/commodity/fx/index
    base            VARCHAR,
    quote           VARCHAR,
    exchange        VARCHAR,
    source          VARCHAR NOT NULL,
    currency        VARCHAR NOT NULL DEFAULT 'USD',
    native_granularity VARCHAR NOT NULL DEFAULT '1m',  -- 1m crypto / 1d equity
    active          BOOLEAN NOT NULL DEFAULT TRUE,
    created_at      TIMESTAMP NOT NULL DEFAULT NOW(),
    UNIQUE (source, symbol)
);

-- Minute bars (crypto primary; equity intraday future)
CREATE TABLE IF NOT EXISTS bar_1m (
    instrument_id   INTEGER NOT NULL REFERENCES instrument(instrument_id),
    ts              TIMESTAMP NOT NULL,  -- UTC, minute open time
    open            DOUBLE NOT NULL,
    high            DOUBLE NOT NULL,
    low             DOUBLE NOT NULL,
    close           DOUBLE NOT NULL,
    volume          DOUBLE NOT NULL,        -- base volume (BTC)
    quote_volume    DOUBLE NOT NULL,        -- dollar volume (USDT)
    trades          INTEGER NOT NULL,
    PRIMARY KEY (instrument_id, ts)
);

-- Universal daily bars (crypto rollup + equity direct)
CREATE TABLE IF NOT EXISTS bar_1d (
    instrument_id   INTEGER NOT NULL REFERENCES instrument(instrument_id),
    ts              DATE NOT NULL,          -- calendar date
    open            DOUBLE NOT NULL,
    high            DOUBLE NOT NULL,
    low             DOUBLE NOT NULL,
    close           DOUBLE NOT NULL,
    adj_close       DOUBLE,                 -- NULL for crypto
    volume          DOUBLE NOT NULL,
    quote_volume    DOUBLE,                 -- NULL for equity
    trades          INTEGER,                -- NULL for equity
    PRIMARY KEY (instrument_id, ts)
);

-- Ingest tracking for resumable backfill
CREATE TABLE IF NOT EXISTS ingest_log (
    source          VARCHAR NOT NULL,
    symbol          VARCHAR NOT NULL,
    granularity     VARCHAR NOT NULL,
    period          VARCHAR NOT NULL,       -- e.g. '2021-03' or '2021-03-15'
    rows            INTEGER,
    checksum_ok     BOOLEAN,
    status          VARCHAR NOT NULL,       -- ok/error/skipped
    ingested_at     TIMESTAMP NOT NULL DEFAULT NOW(),
    PRIMARY KEY (source, symbol, granularity, period)
);

-- Macro series metadata
CREATE TABLE IF NOT EXISTS macro_series (
    series_id   VARCHAR PRIMARY KEY,
    name        VARCHAR NOT NULL,
    category    VARCHAR NOT NULL,  -- liquidity/rates/inflation/risk/equity/fx/commodity/labor
    source      VARCHAR NOT NULL DEFAULT 'fred',
    frequency   VARCHAR NOT NULL,  -- D/W/M
    units       VARCHAR,
    active      BOOLEAN NOT NULL DEFAULT TRUE
);

-- Macro observations (long/tidy)
CREATE TABLE IF NOT EXISTS macro_observation (
    series_id   VARCHAR NOT NULL REFERENCES macro_series(series_id),
    ts          DATE NOT NULL,
    value       DOUBLE,  -- NULL for FRED '.' gaps
    PRIMARY KEY (series_id, ts)
);

-- Intraday rollup views over bar_1m
CREATE OR REPLACE VIEW bar_5m AS
SELECT
    instrument_id,
    time_bucket(INTERVAL '5 minutes', ts) AS ts,
    first(open  ORDER BY ts) AS open,
    max(high)                AS high,
    min(low)                 AS low,
    last(close  ORDER BY ts) AS close,
    sum(volume)              AS volume,
    sum(quote_volume)        AS quote_volume,
    sum(trades)              AS trades
FROM bar_1m
GROUP BY instrument_id, time_bucket(INTERVAL '5 minutes', ts);

CREATE OR REPLACE VIEW bar_15m AS
SELECT
    instrument_id,
    time_bucket(INTERVAL '15 minutes', ts) AS ts,
    first(open  ORDER BY ts) AS open,
    max(high)                AS high,
    min(low)                 AS low,
    last(close  ORDER BY ts) AS close,
    sum(volume)              AS volume,
    sum(quote_volume)        AS quote_volume,
    sum(trades)              AS trades
FROM bar_1m
GROUP BY instrument_id, time_bucket(INTERVAL '15 minutes', ts);

CREATE OR REPLACE VIEW bar_1h AS
SELECT
    instrument_id,
    time_bucket(INTERVAL '1 hour', ts) AS ts,
    first(open  ORDER BY ts) AS open,
    max(high)                AS high,
    min(low)                 AS low,
    last(close  ORDER BY ts) AS close,
    sum(volume)              AS volume,
    sum(quote_volume)        AS quote_volume,
    sum(trades)              AS trades
FROM bar_1m
GROUP BY instrument_id, time_bucket(INTERVAL '1 hour', ts);

CREATE OR REPLACE VIEW bar_4h AS
SELECT
    instrument_id,
    time_bucket(INTERVAL '4 hours', ts) AS ts,
    first(open  ORDER BY ts) AS open,
    max(high)                AS high,
    min(low)                 AS low,
    last(close  ORDER BY ts) AS close,
    sum(volume)              AS volume,
    sum(quote_volume)        AS quote_volume,
    sum(trades)              AS trades
FROM bar_1m
GROUP BY instrument_id, time_bucket(INTERVAL '4 hours', ts);
