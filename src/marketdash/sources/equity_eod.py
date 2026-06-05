"""
Provider-pluggable equity EOD (daily adjusted) source.
Default provider: Twelve Data.
Swap provider by setting EQUITY_PROVIDER env var.
All providers normalize to the same adjusted OHLCV columns for bar_1d.
"""

import requests
from datetime import date
from typing import Iterator

from ..config import EQUITY_API_KEY, EQUITY_PROVIDER


class TwelveDataAdapter:
    BASE = "https://api.twelvedata.com"

    def __init__(self, api_key: str):
        self.api_key = api_key

    def fetch_daily(self, symbol: str, outputsize: int = 5000) -> list[tuple]:
        """
        Returns list of (date_str, open, high, low, close, adj_close, volume).
        Twelve Data returns newest-first; we return oldest-first.
        """
        r = requests.get(
            f"{self.BASE}/time_series",
            params={
                "symbol": symbol,
                "interval": "1day",
                "outputsize": outputsize,
                "adjust": "true",
                "apikey": self.api_key,
            },
            timeout=30,
        )
        r.raise_for_status()
        data = r.json()
        if data.get("status") == "error":
            raise RuntimeError(f"Twelve Data error for {symbol}: {data.get('message')}")
        values = data.get("values", [])
        rows = []
        for v in reversed(values):  # oldest first
            rows.append((
                v["datetime"],          # date string YYYY-MM-DD
                float(v["open"]),
                float(v["high"]),
                float(v["low"]),
                float(v["close"]),
                float(v.get("adjusted_close", v["close"])),
                float(v["volume"]),
            ))
        return rows


def get_adapter():
    if EQUITY_PROVIDER == "twelvedata":
        if not EQUITY_API_KEY:
            raise RuntimeError(
                "EQUITY_API_KEY env var is required for Twelve Data. "
                "Get a free key at https://twelvedata.com and set it before running."
            )
        return TwelveDataAdapter(EQUITY_API_KEY)
    raise RuntimeError(f"Unknown EQUITY_PROVIDER: {EQUITY_PROVIDER}")


def fetch_equity_bars(
    symbol: str, instrument_id: int
) -> list[tuple]:
    """
    Returns list of bar_1d tuples for one equity symbol:
    (instrument_id, ts, open, high, low, close, adj_close, volume, quote_volume, trades)
    """
    adapter = get_adapter()
    rows = adapter.fetch_daily(symbol)
    return [
        (instrument_id, date_str, o, h, l, c, adj, vol, None, None)
        for date_str, o, h, l, c, adj, vol in rows
    ]
