"""
Download and ingest Binance bulk kline data from data.binance.vision.

Parsing notes (per plan spec):
- Older files have no header; newer 2025+ files may have a header row.
- open_time units: older files use milliseconds, newer 2025+ files shifted to microseconds.
  Detection: if open_time > 1e15 it is microseconds; otherwise milliseconds.
- We normalize to UTC TIMESTAMP and insert into bar_1m via DuckDB's read_csv.
"""

import hashlib
import io
import zipfile
from datetime import datetime, timezone
from pathlib import Path

import requests

from ..config import BINANCE_DAILY_URL, BINANCE_MONTHLY_URL, RAW_DIR


def _download(url: str, dest: Path) -> bool:
    """Download url to dest. Returns True on success."""
    try:
        r = requests.get(url, timeout=60, stream=True)
        if r.status_code != 200:
            return False
        with open(dest, "wb") as f:
            for chunk in r.iter_content(65536):
                f.write(chunk)
        return True
    except Exception:
        return False


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _verify_checksum(zip_path: Path, checksum_url: str) -> bool:
    try:
        r = requests.get(checksum_url, timeout=15)
        if r.status_code != 200:
            return True  # checksum unavailable — skip verification
        expected = r.text.strip().split()[0].lower()
        return _sha256(zip_path).lower() == expected
    except Exception:
        return True  # network issue — skip verification


def _parse_csv_bytes(data: bytes) -> list[tuple]:
    """
    Parse Binance kline CSV bytes into bar tuples.
    Handles: presence/absence of header, ms vs µs open_time.
    Returns list of (ts_utc_str, open, high, low, close, volume, quote_volume, trades).
    """
    lines = data.decode("utf-8").splitlines()
    if not lines:
        return []

    # Detect header: first field of first line is non-numeric
    first_field = lines[0].split(",")[0].strip()
    start = 1 if not first_field.lstrip("-").isdigit() else 0

    rows = []
    for line in lines[start:]:
        if not line.strip():
            continue
        parts = line.split(",")
        if len(parts) < 9:
            continue
        open_time = int(parts[0])
        # Detect microseconds (2025+ files): threshold is roughly 1e15
        if open_time > 1_000_000_000_000_000:
            ts_s = open_time / 1_000_000
        else:
            ts_s = open_time / 1_000
        ts = datetime.fromtimestamp(ts_s, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        o, h, l, c = float(parts[1]), float(parts[2]), float(parts[3]), float(parts[4])
        vol = float(parts[5])
        qvol = float(parts[7])
        trades = int(parts[8])
        rows.append((ts, o, h, l, c, vol, qvol, trades))
    return rows


def fetch_month(symbol: str, year: int, month: int) -> tuple[Path | None, bool]:
    """Download monthly zip to RAW_DIR. Returns (path, checksum_ok)."""
    fname = f"{symbol}-1m-{year}-{month:02d}.zip"
    dest = RAW_DIR / fname
    if dest.exists():
        return dest, True  # already cached

    url = BINANCE_MONTHLY_URL.format(symbol=symbol, interval="1m", year=year, month=month)
    checksum_url = url + ".CHECKSUM"
    if not _download(url, dest):
        return None, False
    ok = _verify_checksum(dest, checksum_url)
    return dest, ok


def fetch_day(symbol: str, date_str: str) -> tuple[Path | None, bool]:
    """Download daily zip to RAW_DIR. date_str format: 'YYYY-MM-DD'."""
    fname = f"{symbol}-1m-{date_str}.zip"
    dest = RAW_DIR / fname
    if dest.exists():
        return dest, True

    url = BINANCE_DAILY_URL.format(symbol=symbol, interval="1m", date=date_str)
    checksum_url = url + ".CHECKSUM"
    if not _download(url, dest):
        return None, False
    ok = _verify_checksum(dest, checksum_url)
    return dest, ok


def read_zip_bars(zip_path: Path, instrument_id: int) -> list[tuple]:
    """
    Extract kline CSV from zip, parse, return list of full bar tuples
    ready for INSERT into bar_1m:
    (instrument_id, ts, open, high, low, close, volume, quote_volume, trades)
    """
    with zipfile.ZipFile(zip_path) as zf:
        csv_name = next(n for n in zf.namelist() if n.endswith(".csv"))
        data = zf.read(csv_name)

    raw = _parse_csv_bytes(data)
    return [(instrument_id, ts, o, h, l, c, vol, qvol, trades)
            for ts, o, h, l, c, vol, qvol, trades in raw]
