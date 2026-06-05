#!/usr/bin/env python3
"""
Pull adjusted daily bars for SPY, MU, NVDA, SNDK from Twelve Data.
Requires EQUITY_API_KEY environment variable.
Usage: EQUITY_API_KEY=your_key python scripts/seed_equities.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from marketdash.config import EQUITY_SYMBOLS
from marketdash.db import connect, init_db
from marketdash.sources.equity_eod import fetch_equity_bars


SYMBOL_TO_ID = {"SPY": 2, "MU": 3, "NVDA": 4, "SNDK": 5}


def seed_equities(verbose: bool = True) -> None:
    init_db()
    con = connect()

    for symbol in EQUITY_SYMBOLS:
        instrument_id = SYMBOL_TO_ID[symbol]
        if verbose:
            print(f"  fetching {symbol} ...", end=" ", flush=True)
        try:
            bars = fetch_equity_bars(symbol, instrument_id)
        except RuntimeError as e:
            print(f"SKIP ({e})")
            continue

        con.executemany("""
            INSERT INTO bar_1d
                (instrument_id, ts, open, high, low, close, adj_close,
                 volume, quote_volume, trades)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (instrument_id, ts) DO UPDATE SET
                open      = excluded.open,
                high      = excluded.high,
                low       = excluded.low,
                close     = excluded.close,
                adj_close = excluded.adj_close,
                volume    = excluded.volume
        """, bars)
        if verbose:
            print(f"{len(bars)} bars")

    con.close()
    print("Equity seed complete.")


if __name__ == "__main__":
    seed_equities()
