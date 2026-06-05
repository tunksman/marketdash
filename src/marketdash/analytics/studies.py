"""
Registry of named studies. Each study is f(df, context) -> StudyResult dict.
df: daily OHLCV DataFrame (at minimum: close, high, low, volume columns).
context: dict with optional keys: 'spy_close', 'macro' (sub-DataFrame).
"""

import numpy as np
import pandas as pd
from typing import Any

from . import indicators as ind
from . import stats


def _result(name: str, group: str, value: Any, signal: str, score: float, note: str = "") -> dict:
    assert signal in ("bull", "neutral", "bear"), f"bad signal: {signal}"
    return {"name": name, "group": group, "value": value,
            "signal": signal, "score": score, "note": note}


def _sig(val: float, bull_thresh: float, bear_thresh: float,
         higher_is_bull: bool = True) -> str:
    if higher_is_bull:
        if val >= bull_thresh:
            return "bull"
        if val <= bear_thresh:
            return "bear"
        return "neutral"
    else:
        if val <= bull_thresh:
            return "bull"
        if val >= bear_thresh:
            return "bear"
        return "neutral"


# ── Trend Structure ─────────────────────────────────────────────────────────────

def ma_stack(df: pd.DataFrame, _ctx: dict) -> dict:
    close = df["close"]
    periods = [10, 20, 50, 100, 200]
    mas = {p: ind.sma(close, p).iloc[-1] for p in periods if len(close) >= p}
    last = close.iloc[-1]
    bullish = all(mas.get(p, last) <= mas.get(periods[i + 1], last)
                  for i, p in enumerate(periods[:-1]) if p in mas and periods[i + 1] in mas)
    score = sum(1 for p in mas if last > mas[p]) / len(mas) if mas else 0.5
    sig = "bull" if score >= 0.8 else "bear" if score <= 0.2 else "neutral"
    return _result("MA Stack/Alignment", "trend", score, sig, score,
                   f"Price above {int(score*len(mas))}/{len(mas)} MAs")


def price_vs_200(df: pd.DataFrame, _ctx: dict) -> dict:
    close = df["close"]
    if len(close) < 200:
        return _result("Price vs 200-DMA", "trend", None, "neutral", 0.5, "insufficient data")
    ma200 = ind.sma(close, 200).iloc[-1]
    pct = (close.iloc[-1] / ma200 - 1) * 100
    sig = _sig(pct, 5.0, -5.0)
    return _result("Price vs 200-DMA", "trend", round(pct, 2), sig,
                   float(np.clip((pct + 30) / 60, 0, 1)), f"{pct:.1f}% vs 200-DMA")


def ma_slope(df: pd.DataFrame, _ctx: dict) -> dict:
    close = df["close"]
    if len(close) < 55:
        return _result("MA Slope", "trend", None, "neutral", 0.5, "insufficient data")
    ma50 = ind.sma(close, 50)
    slope = (ma50.iloc[-1] - ma50.iloc[-5]) / ma50.iloc[-5] * 100
    sig = _sig(slope, 0.5, -0.5)
    return _result("MA Slope (50-DMA)", "trend", round(slope, 3), sig,
                   float(np.clip((slope + 3) / 6, 0, 1)), f"{slope:.2f}% per 5d")


def hh_hl_structure(df: pd.DataFrame, _ctx: dict) -> dict:
    close = df["close"]
    n = min(60, len(close))
    c = close.iloc[-n:].values
    highs = [c[i] for i in range(1, len(c) - 1) if c[i] > c[i-1] and c[i] > c[i+1]]
    lows = [c[i] for i in range(1, len(c) - 1) if c[i] < c[i-1] and c[i] < c[i+1]]
    hh = len(highs) > 1 and highs[-1] > highs[-2] if len(highs) >= 2 else False
    hl = len(lows) > 1 and lows[-1] > lows[-2] if len(lows) >= 2 else False
    score = (0.5 * hh + 0.5 * hl)
    sig = "bull" if hh and hl else "bear" if (not hh and not hl) else "neutral"
    return _result("HH/HL Structure", "trend", {"hh": hh, "hl": hl}, sig, score)


def adx_strength(df: pd.DataFrame, _ctx: dict) -> dict:
    if len(df) < 30:
        return _result("ADX Strength", "trend", None, "neutral", 0.5, "insufficient data")
    adx_df = ind.adx(df)
    adx_val = adx_df["adx"].iloc[-1]
    plus = adx_df["plus_di"].iloc[-1]
    minus = adx_df["minus_di"].iloc[-1]
    trending = adx_val > 25
    sig = "bull" if trending and plus > minus else "bear" if trending and minus > plus else "neutral"
    score = float(np.clip(adx_val / 50, 0, 1)) * (1 if plus > minus else -1) * 0.5 + 0.5
    return _result("ADX Strength", "trend", round(adx_val, 1), sig, score,
                   f"ADX={adx_val:.1f} +DI={plus:.1f} -DI={minus:.1f}")


def ichimoku_regime(df: pd.DataFrame, _ctx: dict) -> dict:
    if len(df) < 80:
        return _result("Ichimoku Regime", "trend", None, "neutral", 0.5, "insufficient data")
    ichi = ind.ichimoku(df)
    close = df["close"].iloc[-1]
    sen_a = ichi["senkou_a"].iloc[-1]
    sen_b = ichi["senkou_b"].iloc[-1]
    cloud_top = max(sen_a, sen_b) if pd.notna(sen_a) and pd.notna(sen_b) else None
    cloud_bot = min(sen_a, sen_b) if pd.notna(sen_a) and pd.notna(sen_b) else None
    if cloud_top and cloud_bot:
        sig = "bull" if close > cloud_top else "bear" if close < cloud_bot else "neutral"
        score = 0.8 if sig == "bull" else 0.2 if sig == "bear" else 0.5
    else:
        sig, score = "neutral", 0.5
    return _result("Ichimoku Regime", "trend", sig, sig, score)


# ── Momentum ────────────────────────────────────────────────────────────────────

def momentum_12_1(df: pd.DataFrame, _ctx: dict) -> dict:
    close = df["close"]
    if len(close) < 252:
        return _result("12-1m Academic Momentum", "momentum", None, "neutral", 0.5, "insufficient data")
    ret = (close.iloc[-21] / close.iloc[-252] - 1) * 100
    sig = _sig(ret, 10.0, -10.0)
    return _result("12-1m Academic Momentum", "momentum", round(ret, 2), sig,
                   float(np.clip((ret + 50) / 100, 0, 1)), f"{ret:.1f}%")


def roc_multi(df: pd.DataFrame, _ctx: dict) -> dict:
    close = df["close"]
    periods = [(21, "1m"), (63, "3m"), (126, "6m"), (252, "12m")]
    rocs = {}
    for p, label in periods:
        if len(close) > p:
            rocs[label] = (close.iloc[-1] / close.iloc[-p] - 1) * 100
    if not rocs:
        return _result("ROC Multi-Period", "momentum", None, "neutral", 0.5, "insufficient data")
    pos = sum(1 for v in rocs.values() if v > 0)
    score = pos / len(rocs)
    sig = "bull" if score >= 0.75 else "bear" if score <= 0.25 else "neutral"
    return _result("ROC Multi-Period", "momentum", rocs, sig, score,
                   " | ".join(f"{k}:{v:.1f}%" for k, v in rocs.items()))


def rsi_study(df: pd.DataFrame, _ctx: dict) -> dict:
    close = df["close"]
    if len(close) < 20:
        return _result("RSI", "momentum", None, "neutral", 0.5, "insufficient data")
    rsi_val = float(ind.rsi(close).iloc[-1])
    sig = "bull" if rsi_val > 50 else "bear" if rsi_val < 50 else "neutral"
    # overbought/oversold divergence flag
    if rsi_val > 70:
        note = "Overbought"
    elif rsi_val < 30:
        note = "Oversold"
    else:
        note = ""
    score = rsi_val / 100
    return _result("RSI", "momentum", round(rsi_val, 1), sig, score, note)


def macd_state(df: pd.DataFrame, _ctx: dict) -> dict:
    close = df["close"]
    if len(close) < 35:
        return _result("MACD State", "momentum", None, "neutral", 0.5, "insufficient data")
    m = ind.macd(close)
    hist = m["histogram"].iloc[-1]
    prev_hist = m["histogram"].iloc[-2]
    sig = "bull" if hist > 0 and hist > prev_hist else "bear" if hist < 0 and hist < prev_hist else "neutral"
    score = 0.7 if sig == "bull" else 0.3 if sig == "bear" else 0.5
    return _result("MACD State", "momentum", round(float(hist), 4), sig, score,
                   f"histogram={'rising' if hist > prev_hist else 'falling'}")


def high_52w_proximity(df: pd.DataFrame, _ctx: dict) -> dict:
    close = df["close"]
    n = min(252, len(close))
    hi = close.iloc[-n:].max()
    pct_off = (close.iloc[-1] / hi - 1) * 100
    sig = _sig(pct_off, -5.0, -20.0, higher_is_bull=True)
    score = float(np.clip(1 + pct_off / 50, 0, 1))
    return _result("52w High Proximity", "momentum", round(pct_off, 2), sig, score,
                   f"{pct_off:.1f}% off 52w high")


# ── Relative Strength ────────────────────────────────────────────────────────────

def relative_strength_spy(df: pd.DataFrame, ctx: dict) -> dict:
    spy = ctx.get("spy_close")
    if spy is None:
        return _result("RS vs SPY", "relative_strength", None, "neutral", 0.5, "no SPY data")
    close = df["close"]
    aligned = pd.concat([close, spy], axis=1).dropna()
    if len(aligned) < 63:
        return _result("RS vs SPY", "relative_strength", None, "neutral", 0.5, "insufficient overlap")
    rs_3m = (aligned.iloc[-1, 0] / aligned.iloc[-63, 0]) / (aligned.iloc[-1, 1] / aligned.iloc[-63, 1])
    sig = _sig(rs_3m, 1.05, 0.95)
    return _result("RS vs SPY (3m)", "relative_strength", round(float(rs_3m), 4), sig,
                   float(np.clip((rs_3m - 0.7) / 0.6, 0, 1)), f"RS={rs_3m:.3f}")


# ── Breakout ─────────────────────────────────────────────────────────────────────

def donchian_breakout(df: pd.DataFrame, _ctx: dict) -> dict:
    if len(df) < 55:
        return _result("Donchian 52w Breakout", "breakout", None, "neutral", 0.5, "insufficient data")
    don = ind.donchian(df, period=252 if len(df) >= 252 else len(df) - 1)
    close = df["close"].iloc[-1]
    upper = don["upper"].iloc[-2]  # prior bar's channel (no look-ahead)
    lower = don["lower"].iloc[-2]
    sig = "bull" if close >= upper else "bear" if close <= lower else "neutral"
    score = 0.8 if sig == "bull" else 0.2 if sig == "bear" else 0.5
    return _result("Donchian 52w Breakout", "breakout", {"close": round(close,2), "upper": round(float(upper),2)}, sig, score)


def volume_confirmed_breakout(df: pd.DataFrame, _ctx: dict) -> dict:
    if len(df) < 22:
        return _result("Volume-Confirmed Breakout", "breakout", None, "neutral", 0.5, "insufficient data")
    close = df["close"]
    vol = df["volume"]
    new_high = close.iloc[-1] >= close.iloc[-22:-1].max()
    vol_above = vol.iloc[-1] > vol.iloc[-22:-1].median() * 1.5
    sig = "bull" if new_high and vol_above else "neutral" if new_high or vol_above else "bear"
    score = 0.85 if sig == "bull" else 0.5 if sig == "neutral" else 0.3
    return _result("Volume-Confirmed Breakout", "breakout", {"new_high": new_high, "vol_surge": vol_above}, sig, score)


# ── Extension / Markup Risk ───────────────────────────────────────────────────────

def pct_above_200(df: pd.DataFrame, _ctx: dict) -> dict:
    close = df["close"]
    if len(close) < 200:
        return _result("% Above 200-DMA", "extension", None, "neutral", 0.5, "insufficient data")
    ma200 = ind.sma(close, 200).iloc[-1]
    pct = (close.iloc[-1] / ma200 - 1) * 100
    sig = _sig(pct, 0.0, -10.0, higher_is_bull=False) if pct > 30 else "bull" if pct > 0 else "neutral"
    if pct > 50:
        sig, note = "bear", f"Extended {pct:.1f}% above 200-DMA — markup risk"
    else:
        note = f"{pct:.1f}% above 200-DMA"
    score = float(np.clip(1 - pct / 80, 0, 1))
    return _result("% Above 200-DMA", "extension", round(pct, 2), sig, score, note)


def bb_extension(df: pd.DataFrame, _ctx: dict) -> dict:
    if len(df) < 25:
        return _result("Bollinger %B", "extension", None, "neutral", 0.5, "insufficient data")
    bb = ind.bollinger_bands(df["close"])
    pct_b = float(bb["pct_b"].iloc[-1])
    sig = _sig(pct_b, 0.5, 0.2, higher_is_bull=True)
    if pct_b > 1.0:
        sig, note = "bear", "Above upper band — overbought"
    elif pct_b < 0:
        sig, note = "bull", "Below lower band — oversold"
    else:
        note = f"%B={pct_b:.2f}"
    return _result("Bollinger %B", "extension", round(pct_b, 3), sig, float(np.clip(pct_b, 0, 1)), note)


def atr_distance_from_ma(df: pd.DataFrame, _ctx: dict) -> dict:
    if len(df) < 55:
        return _result("ATR Distance from MA50", "extension", None, "neutral", 0.5, "insufficient data")
    close = df["close"]
    atr_val = ind.atr(df).iloc[-1]
    ma50 = ind.sma(close, 50).iloc[-1]
    dist_atr = (close.iloc[-1] - ma50) / atr_val if atr_val > 0 else 0
    sig = "bear" if dist_atr > 3 else "bull" if dist_atr < -2 else "neutral"
    score = float(np.clip(1 - dist_atr / 5, 0, 1))
    return _result("ATR Distance from MA50", "extension", round(float(dist_atr), 2), sig, score,
                   f"{dist_atr:.1f} ATRs from 50-DMA")


def rsi_overbought_streak(df: pd.DataFrame, _ctx: dict) -> dict:
    close = df["close"]
    if len(close) < 20:
        return _result("RSI Overbought Streak", "extension", None, "neutral", 0.5, "insufficient data")
    rsi_series = ind.rsi(close)
    streak = int((rsi_series.iloc[-10:] > 70).sum())
    sig = "bear" if streak >= 7 else "neutral"
    score = float(np.clip(1 - streak / 10, 0, 1))
    return _result("RSI Overbought Streak", "extension", streak, sig, score,
                   f"{streak}/10 days RSI>70")


# ── Volatility Regime ─────────────────────────────────────────────────────────────

def vol_regime(df: pd.DataFrame, _ctx: dict) -> dict:
    close = df["close"]
    if len(close) < 60:
        return _result("Volatility Regime", "volatility", None, "neutral", 0.5, "insufficient data")
    rv = stats.rolling_vol(close, window=20)
    rv_pct = float(stats.percentile_rank(rv, window=252).iloc[-1]) if len(rv.dropna()) >= 30 else 0.5
    sig = "bear" if rv_pct > 0.8 else "bull" if rv_pct < 0.3 else "neutral"
    return _result("Volatility Regime (ATR %ile)", "volatility", round(rv_pct, 3), sig,
                   float(1 - rv_pct), f"{rv_pct*100:.0f}th percentile vol")


def drawdown_from_high(df: pd.DataFrame, _ctx: dict) -> dict:
    close = df["close"]
    hi = close.max()
    dd = (close.iloc[-1] / hi - 1) * 100
    sig = "bull" if dd > -10 else "bear" if dd < -30 else "neutral"
    score = float(np.clip(1 + dd / 50, 0, 1))
    return _result("Drawdown from ATH", "volatility", round(dd, 2), sig, score, f"{dd:.1f}% from ATH")


# ── Volume / Flow ─────────────────────────────────────────────────────────────────

def obv_trend(df: pd.DataFrame, _ctx: dict) -> dict:
    if len(df) < 22:
        return _result("OBV Trend", "volume", None, "neutral", 0.5, "insufficient data")
    obv = ind.obv(df)
    slope = (obv.iloc[-1] - obv.iloc[-21]) / max(abs(obv.iloc[-21]), 1)
    sig = _sig(float(slope), 0.05, -0.05)
    return _result("OBV Trend", "volume", round(float(slope), 4), sig,
                   float(np.clip((slope + 0.2) / 0.4, 0, 1)))


def cmf_study(df: pd.DataFrame, _ctx: dict) -> dict:
    if len(df) < 22:
        return _result("Chaikin Money Flow", "volume", None, "neutral", 0.5, "insufficient data")
    cmf_val = float(ind.chaikin_money_flow(df).iloc[-1])
    sig = _sig(cmf_val, 0.05, -0.05)
    return _result("Chaikin Money Flow", "volume", round(cmf_val, 4), sig,
                   float(np.clip((cmf_val + 0.5) / 1.0, 0, 1)))


# ── Statistical / Regime ────────────────────────────────────────────────────────

def hurst_exponent(df: pd.DataFrame, _ctx: dict) -> dict:
    close = df["close"]
    n = min(len(close), 500)
    if n < 50:
        return _result("Hurst Exponent", "statistical", None, "neutral", 0.5, "insufficient data")
    log_prices = np.log(close.iloc[-n:].values)
    lags = [2, 4, 8, 16, 32]
    rs_vals = []
    for lag in lags:
        segments = [log_prices[i:i+lag] for i in range(0, n - lag, lag)]
        rs_seg = []
        for seg in segments:
            mean_seg = np.mean(seg)
            dev = np.cumsum(seg - mean_seg)
            r = np.max(dev) - np.min(dev)
            s = np.std(seg, ddof=1)
            if s > 0:
                rs_seg.append(r / s)
        if rs_seg:
            rs_vals.append((np.log(lag), np.log(np.mean(rs_seg))))
    if len(rs_vals) < 3:
        return _result("Hurst Exponent", "statistical", None, "neutral", 0.5, "insufficient data")
    x, y = zip(*rs_vals)
    h = float(np.polyfit(x, y, 1)[0])
    sig = "bull" if h > 0.6 else "bear" if h < 0.4 else "neutral"
    return _result("Hurst Exponent", "statistical", round(h, 3), sig,
                   float(np.clip((h - 0.2) / 0.6, 0, 1)),
                   "trending" if h > 0.6 else "mean-reverting" if h < 0.4 else "random walk")


def momentum_persistence(df: pd.DataFrame, _ctx: dict) -> dict:
    close = df["close"]
    if len(close) < 30:
        return _result("Momentum Persistence", "statistical", None, "neutral", 0.5, "insufficient data")
    ret = stats.log_returns(close).dropna()
    autocorr = float(ret.autocorr(lag=1))
    sig = _sig(autocorr, 0.05, -0.05)
    return _result("Momentum Persistence (AC1)", "statistical", round(autocorr, 4), sig,
                   float(np.clip((autocorr + 0.3) / 0.6, 0, 1)))


# ── Risk of Entry ──────────────────────────────────────────────────────────────────

def rr_to_support(df: pd.DataFrame, _ctx: dict) -> dict:
    close = df["close"]
    if len(df) < 22:
        return _result("R/R to Support", "risk_of_entry", None, "neutral", 0.5, "insufficient data")
    atr_val = ind.atr(df).iloc[-1]
    swing_low = df["low"].iloc[-22:].min()
    stop = min(swing_low, close.iloc[-1] - 2 * atr_val)
    risk = close.iloc[-1] - stop
    target = risk * 2  # 2:1 R/R
    rr = float(target / risk) if risk > 0 else float("nan")
    sig = "bull" if rr >= 2.0 else "bear" if rr < 1.0 else "neutral"
    score = float(np.clip((rr - 0.5) / 3.5, 0, 1)) if pd.notna(rr) else 0.5
    return _result("R/R to Support", "risk_of_entry", round(rr, 2) if pd.notna(rr) else None, sig, score,
                   f"Stop={round(float(stop),2)}, ATR={round(float(atr_val),2)}")


# ── Registry ───────────────────────────────────────────────────────────────────────

STUDIES: list[callable] = [
    ma_stack, price_vs_200, ma_slope, hh_hl_structure, adx_strength, ichimoku_regime,
    momentum_12_1, roc_multi, rsi_study, macd_state, high_52w_proximity,
    relative_strength_spy,
    donchian_breakout, volume_confirmed_breakout,
    pct_above_200, bb_extension, atr_distance_from_ma, rsi_overbought_streak,
    vol_regime, drawdown_from_high,
    obv_trend, cmf_study,
    hurst_exponent, momentum_persistence,
    rr_to_support,
]
