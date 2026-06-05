"""
Orchestrates idempotent backfill + incremental update.
Uses ingest_log to skip already-loaded periods.
DuckDB does all filtering — no pandas in the ingest path.

Connection discipline: open/close per period so the DB lock is held only
during the insert, not across the entire backfill. This lets read-only
queries and other writers (seed_macro, seed_equities) access the DB
between files without conflicts.
"""

from calendar import monthrange
from datetime import date, datetime, timedelta, timezone

from .config import BINANCE_START_MONTH, BINANCE_START_YEAR
from .db import connect, init_db
from .sources.binance_dumps import fetch_day, fetch_month, read_zip_bars


def _already_ingested(source: str, symbol: str, granularity: str, period: str) -> bool:
    con = connect()
    row = con.execute(
        "SELECT status FROM ingest_log WHERE source=? AND symbol=? AND granularity=? AND period=?",
        (source, symbol, granularity, period),
    ).fetchone()
    con.close()
    return row is not None and row[0] == "ok"


def _log_ingest(source, symbol, granularity, period, rows, checksum_ok, status):
    con = connect()
    con.execute("""
        INSERT INTO ingest_log (source, symbol, granularity, period, rows, checksum_ok, status)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT (source, symbol, granularity, period)
        DO UPDATE SET rows=excluded.rows, checksum_ok=excluded.checksum_ok,
                      status=excluded.status, ingested_at=NOW()
    """, (source, symbol, granularity, period, rows, checksum_ok, status))
    con.close()


def _insert_bars(bars: list[tuple]) -> int:
    if not bars:
        return 0
    con = connect()
    con.executemany("""
        INSERT INTO bar_1m
            (instrument_id, ts, open, high, low, close, volume, quote_volume, trades)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT DO NOTHING
    """, bars)
    con.close()
    return len(bars)


def backfill_btc(symbol: str = "BTCUSDT", instrument_id: int = 1,
                 verbose: bool = True, max_months: int | None = None) -> None:
    init_db()

    now = datetime.now(timezone.utc)
    current_year, current_month = now.year, now.month

    year, month = BINANCE_START_YEAR, BINANCE_START_MONTH
    months_processed = 0
    while (year, month) < (current_year, current_month):
        period = f"{year}-{month:02d}"
        if _already_ingested("binance", symbol, "1m", period):
            if verbose:
                print(f"  skip {period} (already loaded)")
        else:
            if verbose:
                print(f"  fetch {period} ...", end=" ", flush=True)
            # Download happens outside DB lock window
            zip_path, checksum_ok = fetch_month(symbol, year, month)
            if zip_path is None:
                if verbose:
                    print("FAILED (download error)")
                _log_ingest("binance", symbol, "1m", period, 0, False, "error")
            else:
                bars = read_zip_bars(zip_path, instrument_id)
                n = _insert_bars(bars)
                _log_ingest("binance", symbol, "1m", period, n, checksum_ok, "ok")
                if verbose:
                    print(f"{n} bars {'(checksum ok)' if checksum_ok else '(checksum SKIP)'}")

        months_processed += 1
        if max_months is not None and months_processed >= max_months:
            if verbose:
                print(f"  (stopping after {max_months} month(s) — smoke mode)")
            break

        month += 1
        if month > 12:
            month = 1
            year += 1

    if max_months is not None:
        # Smoke mode: skip daily dumps and bar_1d refresh
        _refresh_bar_1d_from_1m(instrument_id, symbol, verbose)
        print("BTC backfill complete.")
        return

    # Current month: use daily dumps
    today = now.date()
    day = date(current_year, current_month, 1)
    while day < today:
        date_str = day.strftime("%Y-%m-%d")
        if _already_ingested("binance", symbol, "1m", date_str):
            if verbose:
                print(f"  skip {date_str} (already loaded)")
        else:
            if verbose:
                print(f"  fetch daily {date_str} ...", end=" ", flush=True)
            zip_path, checksum_ok = fetch_day(symbol, date_str)
            if zip_path is None:
                if verbose:
                    print("FAILED")
                _log_ingest("binance", symbol, "1m", date_str, 0, False, "error")
            else:
                bars = read_zip_bars(zip_path, instrument_id)
                n = _insert_bars(bars)
                _log_ingest("binance", symbol, "1m", date_str, n, checksum_ok, "ok")
                if verbose:
                    print(f"{n} bars")
        day += timedelta(days=1)

    _refresh_bar_1d_from_1m(instrument_id, symbol, verbose)
    print("BTC backfill complete.")


def _refresh_bar_1d_from_1m(instrument_id: int, symbol: str, verbose: bool = True) -> None:
    """Upsert daily bars for crypto from the minute table."""
    if verbose:
        print(f"  refreshing bar_1d for {symbol} ...", end=" ", flush=True)
    con = connect()
    con.execute("""
        INSERT INTO bar_1d
            (instrument_id, ts, open, high, low, close, adj_close,
             volume, quote_volume, trades)
        SELECT
            instrument_id,
            CAST(time_bucket(INTERVAL '1 day', ts) AS DATE) AS ts,
            first(open  ORDER BY ts),
            max(high),
            min(low),
            last(close  ORDER BY ts),
            NULL AS adj_close,
            sum(volume),
            sum(quote_volume),
            sum(trades)
        FROM bar_1m
        WHERE instrument_id = ?
        GROUP BY instrument_id, time_bucket(INTERVAL '1 day', ts)
        ON CONFLICT (instrument_id, ts) DO UPDATE SET
            open        = excluded.open,
            high        = excluded.high,
            low         = excluded.low,
            close       = excluded.close,
            volume      = excluded.volume,
            quote_volume= excluded.quote_volume,
            trades      = excluded.trades
    """, (instrument_id,))
    row = con.execute(
        "SELECT count(*) FROM bar_1d WHERE instrument_id=?", (instrument_id,)
    ).fetchone()
    con.close()
    if verbose:
        print(f"{row[0]} daily bars total")
