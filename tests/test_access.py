"""
Tests: rollup correctness and idempotency on a small fixture dataset.
"""

import sys
from pathlib import Path
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import duckdb
import pandas as pd

from marketdash.db import connect, init_db
from marketdash.config import DB_PATH
from marketdash.access import get_bars, data_quality, latest_ts


FIXTURE_BARS = [
    # (instrument_id, ts, open, high, low, close, volume, quote_volume, trades)
    (1, "2017-08-17 00:00:00", 4285.08, 4285.08, 4200.74, 4261.48, 7.20, 30680.0, 42),
    (1, "2017-08-17 00:01:00", 4261.48, 4261.48, 4200.00, 4220.00, 3.10, 13100.0, 18),
    (1, "2017-08-17 00:02:00", 4220.00, 4250.00, 4210.00, 4240.00, 5.50, 23250.0, 30),
]


@pytest.fixture(scope="module", autouse=True)
def setup_db(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("data")
    import marketdash.config as cfg
    cfg.DB_PATH = tmp / "test.duckdb"
    init_db()
    con = connect()
    con.executemany("""
        INSERT INTO bar_1m
            (instrument_id, ts, open, high, low, close, volume, quote_volume, trades)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT DO NOTHING
    """, FIXTURE_BARS)
    con.close()
    yield


def test_get_bars_1m():
    bars = get_bars("BTCUSDT", "1m")
    assert len(bars) == 3
    assert bars[0]["close"] == pytest.approx(4261.48)


def test_rollup_5m():
    bars = get_bars("BTCUSDT", "5m")
    assert len(bars) == 1
    b = bars[0]
    assert b["open"] == pytest.approx(4285.08)
    assert b["high"] == pytest.approx(4285.08)
    assert b["low"] == pytest.approx(4200.00)
    assert b["close"] == pytest.approx(4240.00)
    assert b["volume"] == pytest.approx(7.20 + 3.10 + 5.50)


def test_idempotency():
    con = connect()
    before = con.execute("SELECT count(*) FROM bar_1m WHERE instrument_id=1").fetchone()[0]
    con.executemany("""
        INSERT INTO bar_1m
            (instrument_id, ts, open, high, low, close, volume, quote_volume, trades)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT DO NOTHING
    """, FIXTURE_BARS)
    after = con.execute("SELECT count(*) FROM bar_1m WHERE instrument_id=1").fetchone()[0]
    con.close()
    assert before == after, "Re-insert changed row count (idempotency broken)"


def test_data_quality():
    dq = data_quality("BTCUSDT")
    assert dq["total_bars"] == 3
    assert dq["missing_bars"] == 0  # 3 consecutive minutes → no gaps


def test_latest_ts():
    ts = latest_ts("BTCUSDT")
    assert ts is not None
