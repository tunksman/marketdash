# marketdash — Bloomberg-style Dashboard + Quant Analytics

Host: `bloomclone` | 1 GB RAM, 1 CPU, 26 GB disk (DigitalOcean Premium Intel)

## Machine health — check before heavy work

Run this before starting any memory-intensive task (full backfill, analytics, batch analysis):

```bash
free -h                          # available RAM — warn if <150 MB available
df -h /home/backstaff             # disk — warn if <5 GB free
du -sh /home/backstaff/marketdash/data/   # DB size (target: <2 GB)
nproc && uptime                  # CPU count + load average
```

**Current baseline (2026-06-05):** 1 CPU, 967 MB RAM, 26 GB disk free, DB=25 MB (growing).

**Upgrade triggers — consider moving to a larger droplet if:**
- Available RAM consistently <150 MB (swap thrashing slows everything down)
- BTC backfill takes >12 hours or OOM-kills processes
- `analyze.py` on a full aligned frame takes >30 seconds
- DB size exceeds ~2 GB (DuckDB handles it but queries get slower on 1 GB RAM)

**Recommended next tier:** DO Premium Intel 2 GB RAM / 1 CPU (~$12/mo) or 2 GB / 2 CPU
— doubles RAM headroom without changing any code (DuckDB and FastAPI scale up automatically).
The code is already RAM-disciplined (daily frames only in analytics; no bulk 4.6M-row pandas loads).

## Architecture

```
Binance bulk dumps ─┐
FRED keyless CSV    ├─► sources/*.py ─► ingest.py ─► DuckDB (market.duckdb)
Twelve Data (key)  ─┘                                    │
                                                          ▼
                                                    access.py (stable API)
                                                          │
                                              ┌───────────┴───────────┐
                                         analytics/              [future]
                                     indicators, stats,        FastAPI +
                                     metrics, backtest,    TradingView Charts
                                     validation, studies,
                                     report
```

## Key decisions

- **DuckDB** (embedded columnar): zero server overhead, native CSV/Parquet, larger-than-RAM queries.
- **RAM discipline**: analytics run on daily/windowed frames from `access.py`. Never load all 4.6M minute bars into pandas.
- **UTC everywhere**. `ts` in `bar_1m` = minute open time (TIMESTAMP). `bar_1d.ts` = DATE.
- **Idempotent ingest**: all inserts use `ON CONFLICT DO NOTHING`. Re-running is safe.
- **Equities**: daily bars only (no free intraday). Twelve Data adjusted OHLCV via `EQUITY_API_KEY`.
- **Binance**: live REST geoblocked here; use bulk dumps (`data.binance.vision`). Live websocket deferred.
- **FRED**: keyless `fredgraph.csv` endpoint. 15 curated macro series.
- **`access.py` is the frozen interface**: FastAPI will wrap it later, unchanged.

## Extension points

- **New asset**: `INSERT INTO instrument`; create `sources/new_feed.py` implementing `Source` ABC.
- **New macro series**: `INSERT INTO macro_series`; call `FredSource.iter_observations()`.
- **New indicator**: add `f(df) -> Series` to `analytics/indicators.py`.
- **New study**: add entry to `STUDIES` list in `analytics/studies.py`.

## Run commands

```bash
# Activate venv
source .venv/bin/activate

# Backfill BTC (Aug 2017 → now; ~107 monthly files, several GB download)
python scripts/backfill_btc.py

# Seed macro (15 FRED series, no API key needed)
python scripts/seed_macro.py

# Seed equities (needs Twelve Data free key)
EQUITY_API_KEY=<your_key> python scripts/seed_equities.py

# Analyze any symbol
python scripts/analyze.py BTCUSDT
python scripts/analyze.py NVDA

# Daily incremental update
python scripts/update.py

# Tests
python -m pytest tests/ -v
```

## Backfill note

Full BTC backfill takes significant time and download (~5 GB). Start a smoke test with
a single month: modify `backfill_btc.py` to stop after 2017-08 and validate row count
is ~44,640 (31 days × 24h × 60m), then run the full backfill.

## Resume State

**Checkpointed:** 2026-06-05 (session 3)

**Last completed:**
- Volume histogram added to main chart (bottom 18%, green/red candle-matched).
- Macro overlay line series on main chart (left price scale, dropdown-controlled).
- POST /seed/macro + GET /seed/macro/status endpoints wired (in-server thread with 3s inter-series delay).
- POST /refresh/bar1d endpoint — re-aggregates daily bars from minute data (safe during backfill).
- POST /update + GET /update/status — incremental daily refresh for all instruments.
- Live backfill log: backfill_btc() now accepts log list for real-time progress via GET /backfill/status.
- FRED: empty string values handled as None; 404 is non-retryable; GOLDAMGBD228NLBM replaced with DFII10.
- BTC backfill at ~2018-07 (491K bars), running in background. ~90% of history still needed.
- Dashboard: NVDA analyze → Momentum Intact 68.8%, 25/25 studies, regime=trending. ✓
- Dashboard: ↻ 1D button triggers bar1d refresh. Backfill progress shown live in header.
- All changes pushed to GitHub (tunksman/marketdash).

**Status:** Server running at localhost:8000. BTC backfill running in-process (hours remaining). FRED macro partially seeded (M2SL, WALCL, PCEPILFE confirmed; DFF/DGS10/DGS2/VIX timing out — FRED rate-limiting daily series).

**Exact next step:**
1. Wait for BTC backfill (GET /backfill/status shows progress). After completion run POST /refresh/bar1d to get full daily chart.
2. Re-trigger POST /seed/macro until DFF/DGS10/DGS2/VIXCLS succeed — FRED may need to be tried at off-peak hours.
3. Run GET /analyze/BTCUSDT with full history once backfill completes.
4. (Optional) Add more chart interactivity: crosshair OHLC tooltip, keyboard shortcuts.

**Run the server:**
```bash
source .venv/bin/activate
EQUITY_API_KEY=d0b1f2415e8749809a49649fe186cb48 python scripts/serve.py &
curl -X POST http://localhost:8000/backfill/start
curl -X POST http://localhost:8000/seed/macro
```

**Gotchas:**
- **DuckDB concurrency:** Run backfill via POST /backfill/start (in-server thread), never as a separate OS process while the server is up — DuckDB file lock will conflict.
- `db.py` uses `from . import config` (not `from .config import DB_PATH`) so test fixtures can override `config.DB_PATH` at runtime.
- access.py uses `connect()` not `connect(read_only=True)` — mixing modes in the same process causes DuckDB ConnectionException.
- Binance `data.binance.vision` monthly dump for 2017-08 has ~21,360 bars (not ~44,640) because BTC/USDT launched Aug 17, not Aug 1.
- FRED rate-limits large daily series (DFF, DGS10, VIX); retry at off-peak or increase timeout further.
- bar_1d is only updated by _refresh_bar_1d_from_1m() — call POST /refresh/bar1d mid-backfill to get daily charts.
- Twelve Data free tier: 800 calls/day. Each symbol costs ~1 call for 5,000-bar history.
- GOLDAMGBD228NLBM is 404 on FRED; replaced with DFII10 (10Y TIPS real yield) in config.
