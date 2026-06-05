"""
FastAPI application — thin wrapper around access.py.
All DB logic lives in access.py; this module only handles HTTP concerns.

Backfill runs in a background thread within this process so it shares the
DuckDB connection context — DuckDB allows multiple connections from the same
process, only one write connection at a time across processes.
"""

import threading
from pathlib import Path
from typing import Optional

import pandas as pd
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .access import (
    data_quality,
    get_bars,
    get_macro,
    latest_ts,
    list_instruments,
)
from .analytics.report import run_battery

_STATIC = Path(__file__).parent.parent.parent / "static"

app = FastAPI(title="marketdash", version="0.1.0")

# ── Background backfill state ──────────────────────────────────────────────────
_backfill_state: dict = {"running": False, "log": []}
_backfill_lock = threading.Lock()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET"],
    allow_headers=["*"],
)

if _STATIC.exists():
    app.mount("/static", StaticFiles(directory=str(_STATIC)), name="static")


@app.get("/", include_in_schema=False)
def index():
    f = _STATIC / "index.html"
    if not f.exists():
        raise HTTPException(404, "index.html not found")
    return FileResponse(str(f))


@app.get("/instruments")
def instruments_endpoint(asset_class: Optional[str] = None):
    return list_instruments(asset_class)


@app.get("/bars/{symbol}")
def bars_endpoint(
    symbol: str,
    timeframe: str = Query("1d", pattern="^(1m|5m|15m|1h|4h|1d)$"),
    start: Optional[str] = None,
    end: Optional[str] = None,
):
    symbol = symbol.upper()
    try:
        bars = get_bars(symbol, timeframe, start, end)
    except ValueError as e:
        raise HTTPException(400, str(e))

    # TradingView Lightweight Charts expects {time, open, high, low, close, value}
    # time must be a Unix timestamp (seconds) for candlestick series
    result = []
    for b in bars:
        ts = b["ts"]
        if hasattr(ts, "timestamp"):
            t = int(ts.timestamp())
        else:
            t = int(pd.Timestamp(str(ts)).timestamp())
        result.append({
            "time": t,
            "open": b["open"],
            "high": b["high"],
            "low": b["low"],
            "close": b["close"],
        })
    return result


@app.get("/macro/{series_id}")
def macro_endpoint(
    series_id: str,
    start: Optional[str] = None,
    end: Optional[str] = None,
):
    obs = get_macro(series_id.upper(), start, end)
    result = []
    for o in obs:
        if o["value"] is None:
            continue
        ts = o["ts"]
        t = int(pd.Timestamp(str(ts)).timestamp())
        result.append({"time": t, "value": o["value"]})
    return result


@app.get("/quality/{symbol}")
def quality_endpoint(symbol: str):
    try:
        return data_quality(symbol.upper())
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.get("/analyze/{symbol}")
def analyze_endpoint(symbol: str):
    symbol = symbol.upper()
    try:
        bars = get_bars(symbol, "1d")
    except ValueError as e:
        raise HTTPException(400, str(e))

    if not bars:
        raise HTTPException(404, f"No data for {symbol}")

    df = pd.DataFrame(bars)
    df["ts"] = pd.to_datetime(df["ts"])
    df = df.set_index("ts").sort_index()

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

    return _jsonify(report)


def _jsonify(obj):
    """Recursively convert numpy/pandas scalars to native Python types."""
    import numpy as np
    if isinstance(obj, dict):
        return {k: _jsonify(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_jsonify(v) for v in obj]
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, (np.floating,)):
        return float(obj)
    if isinstance(obj, (np.bool_,)):
        return bool(obj)
    if isinstance(obj, float) and (obj != obj):  # NaN
        return None
    return obj


# ── Backfill management (runs in-process to share DuckDB connection context) ───

def _run_backfill_thread():
    from .ingest import backfill_btc as _backfill
    import io, contextlib

    _backfill_state["running"] = True
    _backfill_state["log"] = []
    buf = io.StringIO()
    try:
        with contextlib.redirect_stdout(buf):
            _backfill()
        _backfill_state["log"] = buf.getvalue().splitlines()
    except Exception as e:
        _backfill_state["log"].append(f"ERROR: {e}")
    finally:
        _backfill_state["running"] = False


@app.post("/backfill/start")
def backfill_start():
    """Start the BTC backfill in a background thread (idempotent)."""
    with _backfill_lock:
        if _backfill_state["running"]:
            return {"status": "already_running"}
        t = threading.Thread(target=_run_backfill_thread, daemon=True)
        t.start()
    return {"status": "started"}


@app.get("/backfill/status")
def backfill_status():
    return {
        "running": _backfill_state["running"],
        "recent_log": _backfill_state["log"][-20:],
    }
