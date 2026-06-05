"""
Vectorized technical indicators. Each function takes a DataFrame with
OHLCV columns and returns a Series (or DataFrame for multi-output indicators).
All inputs expected as pandas Series/DataFrame; no DuckDB calls here.
"""

import numpy as np
import pandas as pd


# ── Trend ──────────────────────────────────────────────────────────────────────

def sma(close: pd.Series, period: int) -> pd.Series:
    return close.rolling(period).mean()


def ema(close: pd.Series, period: int) -> pd.Series:
    return close.ewm(span=period, adjust=False).mean()


def wma(close: pd.Series, period: int) -> pd.Series:
    weights = np.arange(1, period + 1, dtype=float)
    return close.rolling(period).apply(lambda x: (x * weights).sum() / weights.sum(), raw=True)


def macd(close: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9) -> pd.DataFrame:
    fast_ema = ema(close, fast)
    slow_ema = ema(close, slow)
    macd_line = fast_ema - slow_ema
    signal_line = ema(macd_line, signal)
    histogram = macd_line - signal_line
    return pd.DataFrame({"macd": macd_line, "signal": signal_line, "histogram": histogram})


def adx(df: pd.DataFrame, period: int = 14) -> pd.DataFrame:
    """Returns DataFrame with adx, plus_di, minus_di columns."""
    high, low, close = df["high"], df["low"], df["close"]
    prev_close = close.shift(1)
    tr = pd.concat([
        high - low,
        (high - prev_close).abs(),
        (low - prev_close).abs(),
    ], axis=1).max(axis=1)
    plus_dm = high.diff()
    minus_dm = -low.diff()
    plus_dm = plus_dm.where((plus_dm > minus_dm) & (plus_dm > 0), 0.0)
    minus_dm = minus_dm.where((minus_dm > plus_dm) & (minus_dm > 0), 0.0)

    atr_ = tr.ewm(span=period, adjust=False).mean()
    plus_di = 100 * plus_dm.ewm(span=period, adjust=False).mean() / atr_
    minus_di = 100 * minus_dm.ewm(span=period, adjust=False).mean() / atr_
    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)
    adx_val = dx.ewm(span=period, adjust=False).mean()
    return pd.DataFrame({"adx": adx_val, "plus_di": plus_di, "minus_di": minus_di})


def parabolic_sar(df: pd.DataFrame, af_step: float = 0.02, af_max: float = 0.2) -> pd.Series:
    high, low = df["high"].values, df["low"].values
    n = len(high)
    sar = np.full(n, np.nan)
    bull = True
    af = af_step
    ep = low[0]
    sar[0] = high[0]
    for i in range(1, n):
        prev_sar = sar[i - 1]
        if bull:
            sar[i] = prev_sar + af * (ep - prev_sar)
            sar[i] = min(sar[i], low[i - 1], low[i - 2] if i > 1 else low[i - 1])
            if low[i] < sar[i]:
                bull = False
                sar[i] = ep
                ep = low[i]
                af = af_step
            else:
                if high[i] > ep:
                    ep = high[i]
                    af = min(af + af_step, af_max)
        else:
            sar[i] = prev_sar + af * (ep - prev_sar)
            sar[i] = max(sar[i], high[i - 1], high[i - 2] if i > 1 else high[i - 1])
            if high[i] > sar[i]:
                bull = True
                sar[i] = ep
                ep = high[i]
                af = af_step
            else:
                if low[i] < ep:
                    ep = low[i]
                    af = min(af + af_step, af_max)
    return pd.Series(sar, index=df.index, name="sar")


def ichimoku(df: pd.DataFrame,
             tenkan: int = 9, kijun: int = 26,
             senkou_b: int = 52, chikou: int = 26) -> pd.DataFrame:
    high, low, close = df["high"], df["low"], df["close"]
    tenkan_sen = (high.rolling(tenkan).max() + low.rolling(tenkan).min()) / 2
    kijun_sen = (high.rolling(kijun).max() + low.rolling(kijun).min()) / 2
    senkou_a = ((tenkan_sen + kijun_sen) / 2).shift(kijun)
    senkou_b_val = ((high.rolling(senkou_b).max() + low.rolling(senkou_b).min()) / 2).shift(kijun)
    chikou_span = close.shift(-chikou)
    return pd.DataFrame({
        "tenkan_sen": tenkan_sen,
        "kijun_sen": kijun_sen,
        "senkou_a": senkou_a,
        "senkou_b": senkou_b_val,
        "chikou_span": chikou_span,
    })


def golden_cross(close: pd.Series, fast: int = 50, slow: int = 200) -> pd.Series:
    """Returns +1 at golden cross, -1 at death cross, 0 otherwise."""
    f = sma(close, fast)
    s = sma(close, slow)
    above = (f > s).astype(int)
    return above.diff().fillna(0).astype(int)


# ── Momentum ───────────────────────────────────────────────────────────────────

def rsi(close: pd.Series, period: int = 14) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0).ewm(alpha=1 / period, adjust=False).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1 / period, adjust=False).mean()
    rs = gain / loss.where(loss > 0, np.nan)
    rsi_val = 100 - (100 / (1 + rs))
    # loss==0, gain>0 → RSI=100; loss==0, gain==0 → RSI=50
    rsi_val = rsi_val.where(loss > 0, np.where(gain > 0, 100.0, 50.0))
    return rsi_val


def stochastic(df: pd.DataFrame, k_period: int = 14, d_period: int = 3) -> pd.DataFrame:
    high, low, close = df["high"], df["low"], df["close"]
    lowest = low.rolling(k_period).min()
    highest = high.rolling(k_period).max()
    k = 100 * (close - lowest) / (highest - lowest).replace(0, np.nan)
    d = k.rolling(d_period).mean()
    return pd.DataFrame({"%K": k, "%D": d})


def williams_r(df: pd.DataFrame, period: int = 14) -> pd.Series:
    high, low, close = df["high"], df["low"], df["close"]
    highest = high.rolling(period).max()
    lowest = low.rolling(period).min()
    return -100 * (highest - close) / (highest - lowest).replace(0, np.nan)


def roc(close: pd.Series, period: int = 10) -> pd.Series:
    return 100 * close.pct_change(period)


def cci(df: pd.DataFrame, period: int = 20) -> pd.Series:
    tp = (df["high"] + df["low"] + df["close"]) / 3
    mean_dev = tp.rolling(period).apply(lambda x: np.abs(x - x.mean()).mean(), raw=True)
    return (tp - tp.rolling(period).mean()) / (0.015 * mean_dev)


def tsi(close: pd.Series, long_period: int = 25, short_period: int = 13) -> pd.Series:
    delta = close.diff()
    double_smoothed = (
        delta.ewm(span=long_period, adjust=False).mean()
              .ewm(span=short_period, adjust=False).mean()
    )
    abs_double_smoothed = (
        delta.abs().ewm(span=long_period, adjust=False).mean()
                   .ewm(span=short_period, adjust=False).mean()
    )
    return 100 * double_smoothed / abs_double_smoothed.replace(0, np.nan)


# ── Volatility ─────────────────────────────────────────────────────────────────

def bollinger_bands(close: pd.Series, period: int = 20, std_dev: float = 2.0) -> pd.DataFrame:
    mid = sma(close, period)
    std = close.rolling(period).std(ddof=0)
    upper = mid + std_dev * std
    lower = mid - std_dev * std
    pct_b = (close - lower) / (upper - lower).replace(0, np.nan)
    bandwidth = (upper - lower) / mid.replace(0, np.nan)
    return pd.DataFrame({
        "upper": upper, "mid": mid, "lower": lower,
        "pct_b": pct_b, "bandwidth": bandwidth,
    })


def atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    high, low, close = df["high"], df["low"], df["close"]
    prev_close = close.shift(1)
    tr = pd.concat([
        high - low,
        (high - prev_close).abs(),
        (low - prev_close).abs(),
    ], axis=1).max(axis=1)
    return tr.ewm(span=period, adjust=False).mean()


def keltner(df: pd.DataFrame, period: int = 20, atr_mult: float = 2.0) -> pd.DataFrame:
    mid = ema(df["close"], period)
    atr_ = atr(df, period)
    return pd.DataFrame({
        "upper": mid + atr_mult * atr_,
        "mid": mid,
        "lower": mid - atr_mult * atr_,
    })


def donchian(df: pd.DataFrame, period: int = 20) -> pd.DataFrame:
    upper = df["high"].rolling(period).max()
    lower = df["low"].rolling(period).min()
    return pd.DataFrame({"upper": upper, "lower": lower, "mid": (upper + lower) / 2})


def realized_vol(close: pd.Series, period: int = 20, annualize: int = 252) -> pd.Series:
    log_ret = np.log(close / close.shift(1))
    return log_ret.rolling(period).std(ddof=1) * np.sqrt(annualize)


# ── Volume / Flow ──────────────────────────────────────────────────────────────

def obv(df: pd.DataFrame) -> pd.Series:
    direction = np.sign(df["close"].diff()).fillna(0)
    return (direction * df["volume"]).cumsum()


def vwap(df: pd.DataFrame) -> pd.Series:
    tp = (df["high"] + df["low"] + df["close"]) / 3
    cum_tp_vol = (tp * df["volume"]).cumsum()
    cum_vol = df["volume"].cumsum()
    return cum_tp_vol / cum_vol.replace(0, np.nan)


def mfi(df: pd.DataFrame, period: int = 14) -> pd.Series:
    tp = (df["high"] + df["low"] + df["close"]) / 3
    mf = tp * df["volume"]
    pos = mf.where(tp > tp.shift(1), 0.0).rolling(period).sum()
    neg = mf.where(tp < tp.shift(1), 0.0).rolling(period).sum()
    return 100 - (100 / (1 + pos / neg.replace(0, np.nan)))


def accumulation_distribution(df: pd.DataFrame) -> pd.Series:
    clv = ((df["close"] - df["low"]) - (df["high"] - df["close"])) / (
        (df["high"] - df["low"]).replace(0, np.nan)
    )
    return (clv * df["volume"]).cumsum()


def chaikin_money_flow(df: pd.DataFrame, period: int = 20) -> pd.Series:
    clv = ((df["close"] - df["low"]) - (df["high"] - df["close"])) / (
        (df["high"] - df["low"]).replace(0, np.nan)
    )
    return (clv * df["volume"]).rolling(period).sum() / df["volume"].rolling(period).sum().replace(0, np.nan)
