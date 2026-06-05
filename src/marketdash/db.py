import duckdb
from pathlib import Path
from . import config

_SCHEMA = Path(__file__).parent / "schema.sql"


def connect(read_only: bool = False) -> duckdb.DuckDBPyConnection:
    # Always read config.DB_PATH at call time so test fixtures can override it.
    return duckdb.connect(str(config.DB_PATH), read_only=read_only)


def init_db() -> None:
    con = connect()
    con.execute(_SCHEMA.read_text())

    # Seed BTCUSDT instrument row
    con.execute("""
        INSERT OR IGNORE INTO instrument
            (instrument_id, symbol, display_symbol, asset_class, base, quote,
             exchange, source, currency, native_granularity)
        VALUES (1, 'BTCUSDT', 'BTC/USDT', 'crypto', 'BTC', 'USDT',
                'binance', 'binance', 'USDT', '1m')
    """)

    # Seed equity instruments (daily)
    equities = [
        (2, "SPY",  "SPY",  "equity", "SPY",  None, "nasdaq", "twelvedata", "USD", "1d"),
        (3, "MU",   "MU",   "equity", "MU",   None, "nasdaq", "twelvedata", "USD", "1d"),
        (4, "NVDA", "NVDA", "equity", "NVDA", None, "nasdaq", "twelvedata", "USD", "1d"),
        (5, "SNDK", "SNDK", "equity", "SNDK", None, "nasdaq", "twelvedata", "USD", "1d"),
    ]
    for row in equities:
        con.execute("""
            INSERT OR IGNORE INTO instrument
                (instrument_id, symbol, display_symbol, asset_class, base, quote,
                 exchange, source, currency, native_granularity)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, row)

    # Seed macro series
    for series_id, name, category, source, frequency, units in config.MACRO_SERIES:
        con.execute("""
            INSERT OR IGNORE INTO macro_series
                (series_id, name, category, source, frequency, units)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (series_id, name, category, source, frequency, units))

    con.close()
    print(f"DB initialized at {config.DB_PATH}")


if __name__ == "__main__":
    init_db()
