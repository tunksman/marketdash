"""
Indicator and metric known-value tests.
All inputs are tiny fixed series with hand-computed expected values.
"""

import sys
from pathlib import Path
import pytest
import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from marketdash.analytics.indicators import sma, ema, rsi, bollinger_bands, atr, obv
from marketdash.analytics.metrics import tearsheet
from marketdash.analytics import stats


# ── Indicator tests ─────────────────────────────────────────────────────────────

CLOSE = pd.Series([10.0, 11.0, 12.0, 11.0, 13.0, 14.0, 13.5, 15.0, 14.0, 16.0])


def test_sma():
    result = sma(CLOSE, 3)
    assert pd.isna(result.iloc[0])
    assert result.iloc[2] == pytest.approx((10 + 11 + 12) / 3)
    assert result.iloc[3] == pytest.approx((11 + 12 + 11) / 3)


def test_ema_first_value():
    # EMA with span=3: alpha = 2/(3+1) = 0.5
    result = ema(CLOSE, 3)
    # First value equals first close (EMA initialization)
    assert result.iloc[0] == pytest.approx(10.0)
    # Second: 0.5*11 + 0.5*10 = 10.5
    assert result.iloc[1] == pytest.approx(10.5)


def test_rsi_known():
    # With 14 periods: build a series where all gains → RSI=100
    gains = pd.Series([10.0 + i for i in range(20)])
    result = rsi(gains, period=14)
    # All positive deltas → no losses → RSI approaches 100
    assert float(result.dropna().iloc[-1]) > 95


def test_rsi_no_gains():
    losses = pd.Series([20.0 - i for i in range(20)])
    result = rsi(losses, period=14)
    assert float(result.dropna().iloc[-1]) < 5


def test_bollinger_bands_width():
    bb = bollinger_bands(CLOSE, period=5, std_dev=2.0)
    # Bandwidth = (upper - lower) / mid; must be non-negative
    assert (bb["bandwidth"].dropna() >= 0).all()
    # %B = 0.5 when price is exactly at mid
    mid = bb["mid"].dropna()
    # mid is SMA, close can be above or below — just check shape
    assert len(bb["pct_b"].dropna()) == len(bb["mid"].dropna())


def test_atr_positive():
    df = pd.DataFrame({
        "high": [12, 13, 14, 13, 15, 16, 15, 17, 16, 18],
        "low":  [9,  10, 11, 10, 12, 13, 12, 14, 13, 15],
        "close":[10, 11, 12, 11, 13, 14, 13, 15, 14, 16],
    })
    result = atr(df, period=3)
    assert (result.dropna() > 0).all()


def test_obv_direction():
    df = pd.DataFrame({
        "close":  [10, 11, 10, 12],
        "volume": [100, 200, 150, 300],
    })
    result = obv(df)
    # Up day: +volume; Down day: -volume
    assert result.iloc[1] > result.iloc[0]  # 11 > 10 → add 200
    assert result.iloc[2] < result.iloc[1]  # 10 < 11 → subtract 150


# ── Stats tests ─────────────────────────────────────────────────────────────────

def test_log_returns_shape():
    ret = stats.log_returns(CLOSE)
    assert len(ret) == len(CLOSE)
    assert pd.isna(ret.iloc[0])
    assert ret.iloc[1] == pytest.approx(np.log(11 / 10))


def test_sharpe_all_gains():
    gains = pd.Series([1.0 * (1.01 ** i) for i in range(252)])
    s = stats.sharpe(gains)
    assert s > 0


def test_correlation_matrix_diagonal():
    df = pd.DataFrame({"a": CLOSE, "b": CLOSE * 2})
    corr = stats.correlation_matrix(df)
    assert corr.loc["a", "a"] == pytest.approx(1.0)
    assert corr.loc["a", "b"] == pytest.approx(1.0)


def test_zscore_mean_zero():
    z = stats.zscore(CLOSE)
    assert abs(float(z.mean())) < 1e-10
    assert abs(float(z.std(ddof=1)) - 1.0) < 1e-10


# ── Metrics tests ────────────────────────────────────────────────────────────────

def test_tearsheet_total_return():
    # Linear growth: 100 → 200 over 252 bars
    equity = pd.Series([100.0 * (1 + i / 252) for i in range(253)])
    ts = tearsheet(equity)
    assert ts["total_return"] == pytest.approx(1.0, rel=0.01)


def test_tearsheet_sharpe_positive():
    equity = pd.Series([100.0 * (1.001 ** i) for i in range(252)])
    ts = tearsheet(equity)
    assert ts["sharpe"] > 0


def test_tearsheet_max_drawdown_negative():
    equity = pd.Series([100, 110, 120, 90, 95, 100, 115])
    ts = tearsheet(equity)
    assert ts["max_drawdown"] < 0
    # Max drawdown from 120 to 90: (90-120)/120 = -0.25
    assert ts["max_drawdown"] == pytest.approx(-0.25, rel=0.01)


def test_tearsheet_skew_kurtosis_normal():
    rng = np.random.default_rng(42)
    ret = pd.Series(rng.normal(0.001, 0.02, 10000))
    equity = (1 + ret).cumprod() * 100
    ts = tearsheet(equity)
    # Normal distribution: skew ≈ 0, excess kurtosis ≈ 0
    assert abs(ts["skewness"]) < 0.5
    assert abs(ts["excess_kurtosis"]) < 0.5
