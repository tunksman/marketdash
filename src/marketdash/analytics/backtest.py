"""
Lightweight vectorized numpy/pandas backtester.
No look-ahead: signals are shifted one bar before fill.
Models transaction costs, slippage, position sizing.
"""

import numpy as np
import pandas as pd


def run_backtest(
    close: pd.Series,
    signal: pd.Series,
    cost_pct: float = 0.001,
    slippage_pct: float = 0.0005,
    sizing: str = "full",         # 'full' | 'fractional'
    fraction: float = 1.0,
    initial_capital: float = 10_000.0,
    allow_short: bool = False,
) -> dict:
    """
    signal: Series of +1 (long), 0 (flat), -1 (short if allowed) aligned with close.
    Returns dict with equity curve, positions, trades DataFrame, and tearsheet inputs.
    """
    # Shift signal by 1: trade fills at next bar's open ≈ close
    pos = signal.shift(1).fillna(0)
    if not allow_short:
        pos = pos.clip(lower=0)
    if sizing == "fractional":
        pos = pos * fraction

    # Daily returns
    price_ret = close.pct_change().fillna(0)

    # Cost on position change (entry/exit)
    pos_change = pos.diff().fillna(pos.iloc[0])
    trade_cost = pos_change.abs() * (cost_pct + slippage_pct)

    strat_ret = pos * price_ret - trade_cost
    equity = (1 + strat_ret).cumprod() * initial_capital

    # Build trades table
    entries = pos_change[pos_change != 0].index
    trades = _build_trades(close, pos, cost_pct + slippage_pct)

    return {
        "equity": equity,
        "positions": pos,
        "strategy_returns": strat_ret,
        "price_returns": price_ret,
        "trades": trades,
    }


def _build_trades(
    close: pd.Series, positions: pd.Series, total_cost: float
) -> pd.DataFrame:
    trades = []
    in_trade = False
    entry_price = entry_date = side = None

    prev_pos = 0.0
    for date, pos in positions.items():
        if not in_trade and pos != 0:
            in_trade = True
            entry_price = close[date]
            entry_date = date
            side = int(np.sign(pos))
        elif in_trade and (pos == 0 or np.sign(pos) != side):
            exit_price = close[date]
            raw_pnl = side * (exit_price / entry_price - 1)
            pnl = raw_pnl - total_cost * 2  # entry + exit
            trades.append({
                "entry": entry_date,
                "exit": date,
                "side": "long" if side == 1 else "short",
                "entry_price": entry_price,
                "exit_price": exit_price,
                "pnl": pnl,
            })
            if pos != 0:
                entry_price = close[date]
                entry_date = date
                side = int(np.sign(pos))
            else:
                in_trade = False
        prev_pos = pos

    return pd.DataFrame(trades)


def event_study(
    close: pd.Series, event_dates: pd.DatetimeIndex, window: int = 20
) -> pd.DataFrame:
    """
    Average price path around event dates.
    Returns DataFrame indexed -window..+window with mean/std return.
    """
    log_ret = np.log(close / close.shift(1))
    paths = []
    for d in event_dates:
        try:
            idx = close.index.get_loc(d)
        except KeyError:
            continue
        start, end = idx - window, idx + window + 1
        if start < 0 or end > len(log_ret):
            continue
        segment = log_ret.iloc[start:end].values
        paths.append(segment)
    if not paths:
        return pd.DataFrame()
    mat = np.array(paths)
    lags = np.arange(-window, window + 1)
    return pd.DataFrame({
        "lag": lags,
        "mean_ret": mat.mean(axis=0),
        "std_ret": mat.std(axis=0, ddof=1),
    }).set_index("lag")


def apply_regime_mask(signal: pd.Series, regime: pd.Series) -> pd.Series:
    """Zero out signal when regime is False/0 (e.g. bear market filter)."""
    return signal.where(regime.astype(bool), 0)
