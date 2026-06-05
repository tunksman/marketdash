"""
Stable access layer — the frozen interface for the dashboard and analytics layer.
All heavy work is done inside DuckDB; pandas only sees small result frames.
"""

from datetime import date, datetime
from typing import Optional

import pandas as pd

from .db import connect

_TIMEFRAME_VIEW = {
    "1m":  "bar_1m",
    "5m":  "bar_5m",
    "15m": "bar_15m",
    "1h":  "bar_1h",
    "4h":  "bar_4h",
    "1d":  "bar_1d",
}
_EQUITY_TIMEFRAMES = {"1d"}  # equities have no intraday data yet


def list_instruments(asset_class: Optional[str] = None) -> list[dict]:
    con = connect()
    q = "SELECT * FROM instrument WHERE active=TRUE"
    params = []
    if asset_class:
        q += " AND asset_class=?"
        params.append(asset_class)
    cur = con.execute(q, params)
    cols = [d[0] for d in cur.description]
    rows = cur.fetchall()
    con.close()
    return [dict(zip(cols, r)) for r in rows]


def _get_instrument(con, symbol: str) -> dict:
    cur = con.execute(
        "SELECT instrument_id, native_granularity, asset_class FROM instrument WHERE symbol=? AND active=TRUE",
        (symbol,)
    )
    row = cur.fetchone()
    if not row:
        raise ValueError(f"Unknown instrument: {symbol}")
    return {"instrument_id": row[0], "native_granularity": row[1], "asset_class": row[2]}


def get_bars(symbol: str, timeframe: str, start=None, end=None) -> list[dict]:
    """
    Returns OHLCV bars for symbol at the given timeframe.
    timeframe: '1m','5m','15m','1h','4h','1d'
    start/end: date-like strings or datetime objects (optional).
    Routes to bar_1m/rollup views/bar_1d transparently.
    """
    if timeframe not in _TIMEFRAME_VIEW:
        raise ValueError(f"Unknown timeframe: {timeframe}")

    con = connect()
    inst = _get_instrument(con, symbol)
    instrument_id = inst["instrument_id"]
    native = inst["native_granularity"]

    # Equities: only daily timeframes available
    if native == "1d" and timeframe not in _EQUITY_TIMEFRAMES:
        raise ValueError(f"{symbol} only supports daily timeframe (got {timeframe})")

    table = _TIMEFRAME_VIEW[timeframe]

    # bar_1d uses DATE for ts; others use TIMESTAMP
    ts_cast = "CAST(ts AS VARCHAR)" if timeframe == "1d" else "CAST(ts AS VARCHAR)"

    conditions = ["instrument_id = ?"]
    params: list = [instrument_id]
    if start:
        conditions.append("ts >= ?")
        params.append(str(start))
    if end:
        conditions.append("ts <= ?")
        params.append(str(end))

    where = " AND ".join(conditions)
    q = f"SELECT ts, open, high, low, close, volume FROM {table} WHERE {where} ORDER BY ts"
    cur = con.execute(q, params)
    cols = [d[0] for d in cur.description]
    rows = cur.fetchall()
    con.close()
    return [dict(zip(cols, r)) for r in rows]


def latest_ts(symbol: str) -> Optional[datetime]:
    """Return the timestamp of the most recent bar for this symbol."""
    con = connect()
    inst = _get_instrument(con, symbol)
    instrument_id = inst["instrument_id"]
    native = inst["native_granularity"]
    table = "bar_1d" if native == "1d" else "bar_1m"
    row = con.execute(
        f"SELECT max(ts) FROM {table} WHERE instrument_id=?", (instrument_id,)
    ).fetchone()
    con.close()
    return row[0] if row else None


def data_quality(symbol: str) -> dict:
    """
    Returns gap/quality metrics for an instrument.
    Crypto (1m native): queries bar_1m for minute-level gap analysis.
    Equities (1d native): queries bar_1d for daily bar count.
    """
    con = connect()
    inst = _get_instrument(con, symbol)
    instrument_id = inst["instrument_id"]
    native = inst["native_granularity"]

    if native == "1d":
        row = con.execute("""
            SELECT
                count(*)           AS total_bars,
                min(ts)            AS first_ts,
                max(ts)            AS last_ts,
                NULL               AS expected_bars,
                NULL               AS missing_bars
            FROM bar_1d
            WHERE instrument_id = ?
        """, (instrument_id,)).fetchone()
    else:
        row = con.execute("""
            SELECT
                count(*)                                                  AS total_bars,
                min(ts)                                                   AS first_ts,
                max(ts)                                                   AS last_ts,
                CAST(epoch(max(ts) - min(ts)) / 60 AS INTEGER) + 1       AS expected_bars,
                CAST(epoch(max(ts) - min(ts)) / 60 AS INTEGER) + 1
                  - count(*)                                              AS missing_bars
            FROM bar_1m
            WHERE instrument_id = ?
        """, (instrument_id,)).fetchone()
    con.close()
    return {
        "symbol": symbol,
        "total_bars": row[0],
        "first_ts": row[1],
        "last_ts": row[2],
        "expected_bars": row[3],
        "missing_bars": row[4],
    }


def get_macro(series_id: str, start=None, end=None) -> list[dict]:
    con = connect()
    conditions = ["series_id = ?"]
    params: list = [series_id]
    if start:
        conditions.append("ts >= ?")
        params.append(str(start))
    if end:
        conditions.append("ts <= ?")
        params.append(str(end))
    where = " AND ".join(conditions)
    cur = con.execute(
        f"SELECT ts, value FROM macro_observation WHERE {where} ORDER BY ts", params
    )
    rows = cur.fetchall()
    con.close()
    return [{"ts": r[0], "value": r[1]} for r in rows]


def aligned_frame(
    symbol: str,
    series_ids: list[str],
    timeframe: str = "1d",
    start=None,
    end=None,
) -> pd.DataFrame:
    """
    Returns a date-aligned DataFrame with price OHLCV + chosen macro factors.
    Macro is forward-filled to the bar grid.
    Volume columns included so analytics can use them as factors.
    """
    bars = get_bars(symbol, timeframe, start, end)
    if not bars:
        return pd.DataFrame()

    df = pd.DataFrame(bars)
    df["ts"] = pd.to_datetime(df["ts"])
    df = df.set_index("ts").sort_index()

    for sid in series_ids:
        macro = get_macro(sid, start, end)
        if not macro:
            df[sid] = float("nan")
            continue
        mdf = pd.DataFrame(macro)
        mdf["ts"] = pd.to_datetime(mdf["ts"])
        mdf = mdf.set_index("ts").rename(columns={"value": sid})
        df = df.join(mdf[[sid]], how="left")
        df[sid] = df[sid].ffill()

    return df
