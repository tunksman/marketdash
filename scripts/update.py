#!/usr/bin/env python3
"""
Incremental update: pull new daily Binance dumps + refresh macro + equities.
Usage: python scripts/update.py
"""
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from marketdash.access import latest_ts
from marketdash.db import connect, init_db
from marketdash.ingest import _insert_bars, _log_ingest, _refresh_bar_1d_from_1m
from marketdash.sources.binance_dumps import fetch_day, read_zip_bars


def update_btc(symbol: str = "BTCUSDT", instrument_id: int = 1) -> None:
    init_db()
    con = connect()
    last = latest_ts(symbol)
    if last is None:
        print("No BTC data yet — run backfill_btc.py first.")
        return
    start_date = last.date() + timedelta(days=1)
    today = date.today()
    d = start_date
    while d < today:
        date_str = d.strftime("%Y-%m-%d")
        print(f"  fetch {date_str} ...", end=" ", flush=True)
        zip_path, checksum_ok = fetch_day(symbol, date_str)
        if zip_path is None:
            print("FAILED (not yet available?)")
        else:
            bars = read_zip_bars(zip_path, instrument_id)
            n = _insert_bars(con, bars)
            _log_ingest(con, "binance", symbol, "1m", date_str, n, checksum_ok, "ok")
            print(f"{n} bars")
        d += timedelta(days=1)
    _refresh_bar_1d_from_1m(con, instrument_id, symbol)
    con.close()


def update_macro() -> None:
    from marketdash.config import MACRO_SERIES
    from marketdash.sources.fred import FredSource
    con = connect()
    src = FredSource()
    for series_id, name, *_ in MACRO_SERIES:
        print(f"  refresh {series_id} ...", end=" ", flush=True)
        obs = list(src.iter_observations(series_id))
        con.executemany("""
            INSERT INTO macro_observation (series_id, ts, value) VALUES (?, ?, ?)
            ON CONFLICT (series_id, ts) DO NOTHING
        """, obs)
        print(f"{len(obs)} rows")
    con.close()


def update_equities() -> None:
    from marketdash.config import EQUITY_SYMBOLS
    from marketdash.sources.equity_eod import fetch_equity_bars
    SYMBOL_TO_ID = {"SPY": 2, "MU": 3, "NVDA": 4, "SNDK": 5}
    con = connect()
    for symbol in EQUITY_SYMBOLS:
        iid = SYMBOL_TO_ID[symbol]
        print(f"  refresh {symbol} ...", end=" ", flush=True)
        try:
            bars = fetch_equity_bars(symbol, iid)
            con.executemany("""
                INSERT INTO bar_1d
                    (instrument_id, ts, open, high, low, close, adj_close, volume, quote_volume, trades)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT (instrument_id, ts) DO UPDATE SET
                    close=excluded.close, adj_close=excluded.adj_close, volume=excluded.volume
            """, bars)
            print(f"{len(bars)} rows")
        except RuntimeError as e:
            print(f"SKIP ({e})")
    con.close()


if __name__ == "__main__":
    update_btc()
    update_macro()
    update_equities()
    print("Update complete.")
