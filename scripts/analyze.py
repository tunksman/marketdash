#!/usr/bin/env python3
"""
Run the full quant battery for a symbol.
Usage: python scripts/analyze.py BTCUSDT
       python scripts/analyze.py NVDA
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import pandas as pd
from marketdash.access import aligned_frame, get_bars
from marketdash.analytics.report import print_report, run_battery


def analyze(symbol: str) -> None:
    print(f"Loading data for {symbol} ...")
    bars = get_bars(symbol, "1d")
    if not bars:
        print(f"No data found for {symbol}. Run the seed/backfill scripts first.")
        sys.exit(1)

    df = pd.DataFrame(bars)
    df["ts"] = pd.to_datetime(df["ts"])
    df = df.set_index("ts").sort_index()

    # Load SPY for relative-strength context (may be empty if not seeded)
    spy_close = None
    if symbol != "SPY":
        try:
            spy_bars = get_bars("SPY", "1d")
            if spy_bars:
                spy_df = pd.DataFrame(spy_bars)
                spy_df["ts"] = pd.to_datetime(spy_df["ts"])
                spy_close = spy_df.set_index("ts")["close"]
        except Exception:
            pass

    report = run_battery(df, spy_close=spy_close)
    print_report(symbol, report)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python scripts/analyze.py SYMBOL")
        sys.exit(1)
    analyze(sys.argv[1].upper())
