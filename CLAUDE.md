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

**Checkpointed:** 2026-06-05 (session 2)

**Last completed:**
- Smoke-tested BTC 2017-08: 21,360 bars, OHLC sane, idempotency confirmed.
- Full BTC backfill running in server background (POST /backfill/start) — currently ~43,700 bars, progressing through 2017.
- Equities seeded: SPY/MU/NVDA (5,000 bars each), SNDK (328 bars from Feb 2025). ✓
- Macro: M2SL + WALCL seeded (808 + 1,225 rows). DFF and rest failed due to FRED outage — **re-run `seed_macro.py` when FRED recovers**.
- Dashboard (Phase 1) built and running: FastAPI at `http://localhost:8000`, TradingView candlestick chart, instrument selector, momentum panel, macro overlay, backfill controls.
- Battery tested live: NVDA → Momentum Intact 62.5%, 25 studies firing correctly.
- 20/20 tests passing.

**Status:** Dashboard is live. Full BTC backfill in progress (hours remaining). FRED macro partial.

**Exact next step:** Wait for BTC backfill to complete (check via GET /backfill/status). Then:
1. Re-run `python scripts/seed_macro.py` to fill remaining 13 FRED series.
2. Verify `python scripts/analyze.py BTCUSDT` with full history.
3. Dashboard: add volume chart pane below candlestick, add macro overlay line on main chart.
4. (Optional) Add `/update` endpoint to refresh data incrementally.

**Gotchas:**
- **DuckDB concurrency:** Run backfill via POST /backfill/start (in-server thread), never as a separate OS process while the server is up — DuckDB file lock will conflict.
- `db.py` uses `from . import config` (not `from .config import DB_PATH`) so test fixtures can override `config.DB_PATH` at runtime.
- access.py uses `connect()` not `connect(read_only=True)` — mixing modes in the same process causes DuckDB ConnectionException.
- Binance `data.binance.vision` monthly dump for 2017-08 has ~21,360 bars (not ~44,640) because BTC/USDT launched Aug 17, not Aug 1.
- FRED is occasionally rate-limited or down; `seed_macro.py` now skips failed series and reports them.
- Twelve Data free tier: 800 calls/day. Each symbol costs ~1 call for 5,000-bar history.
