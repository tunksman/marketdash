"""
Full evaluation suite / tearsheet.
Produces a dict that the dashboard can render.
All scipy/numpy — no quantstats/vectorbt (RAM constraint).
"""

import numpy as np
import pandas as pd
from scipy.stats import jarque_bera, kurtosis, norm, skew


def _annualize_factor(periods: int) -> float:
    return np.sqrt(periods)


def tearsheet(
    equity: pd.Series,
    benchmark: pd.Series | None = None,
    risk_free: float = 0.0,
    periods: int = 252,
) -> dict:
    """
    equity: daily equity curve (price/NAV series, not returns).
    benchmark: optional benchmark equity curve for relative metrics.
    periods: trading periods per year (252 daily / 365 crypto / 525600 minute).
    """
    ret = equity.pct_change().dropna()
    log_ret = np.log(equity / equity.shift(1)).dropna()
    n = len(ret)
    if n < 2:
        return {}

    # ── Return ──────────────────────────────────────────────────────────────
    total_return = float(equity.iloc[-1] / equity.iloc[0] - 1)
    years = n / periods
    cagr = float((1 + total_return) ** (1 / years) - 1) if years > 0 else float("nan")
    ann_return = float(log_ret.mean() * periods)

    # ── Risk-adjusted ────────────────────────────────────────────────────────
    ann_vol = float(log_ret.std(ddof=1) * _annualize_factor(periods))
    excess = log_ret - risk_free / periods
    sharpe = float(excess.mean() / excess.std(ddof=1) * _annualize_factor(periods)) if excess.std(ddof=1) > 0 else 0.0

    downside = excess[excess < 0].std(ddof=1)
    sortino = float(excess.mean() / downside * _annualize_factor(periods)) if downside > 0 else float("nan")

    # ── Drawdown ─────────────────────────────────────────────────────────────
    roll_max = equity.cummax()
    dd = (equity - roll_max) / roll_max
    max_dd = float(dd.min())

    calmar = float(cagr / abs(max_dd)) if max_dd != 0 else float("nan")

    # drawdown duration
    underwater = (dd < 0)
    dd_runs = underwater.astype(int).groupby((~underwater).cumsum())
    dd_durations = dd_runs.sum()
    max_dd_dur = int(dd_durations.max()) if len(dd_durations) > 0 else 0

    # Ulcer index
    ulcer = float(np.sqrt((dd ** 2).mean()))

    # ── VaR / CVaR ───────────────────────────────────────────────────────────
    var_95 = float(np.percentile(ret, 5))
    var_99 = float(np.percentile(ret, 1))
    cvar_95 = float(ret[ret <= var_95].mean()) if (ret <= var_95).any() else float("nan")

    # ── Distribution ─────────────────────────────────────────────────────────
    ret_skew = float(skew(ret.values))
    ret_kurt = float(kurtosis(ret.values, fisher=True))  # excess kurtosis
    jb_stat, jb_pval = jarque_bera(ret.values)
    tail_ratio = float(
        np.percentile(ret, 95) / abs(np.percentile(ret, 5))
    ) if np.percentile(ret, 5) != 0 else float("nan")
    gain_pain = float(ret[ret > 0].sum() / abs(ret[ret < 0].sum())) if (ret < 0).any() else float("nan")
    autocorr = float(ret.autocorr(lag=1))

    # ── Probabilistic Sharpe / Deflated Sharpe ───────────────────────────────
    psr = float(norm.cdf(
        (sharpe - 0) * np.sqrt(n - 1) /
        np.sqrt(1 - ret_skew * sharpe + (ret_kurt - 1) / 4 * sharpe ** 2)
    )) if (1 - ret_skew * sharpe + (ret_kurt - 1) / 4 * sharpe ** 2) > 0 else float("nan")

    # ── Benchmark-relative ────────────────────────────────────────────────────
    alpha = beta_val = r2 = tracking_err = up_capture = down_capture = float("nan")
    information_ratio = float("nan")
    if benchmark is not None:
        bret = benchmark.pct_change().dropna()
        aligned = pd.concat([ret, bret], axis=1).dropna()
        if len(aligned) > 2:
            ar, br = aligned.iloc[:, 0], aligned.iloc[:, 1]
            cov_mat = np.cov(ar, br)
            beta_val = float(cov_mat[0, 1] / cov_mat[1, 1]) if cov_mat[1, 1] != 0 else float("nan")
            alpha = float(ar.mean() - beta_val * br.mean()) * periods
            corr = float(np.corrcoef(ar, br)[0, 1])
            r2 = corr ** 2
            active_ret = ar - br
            tracking_err = float(active_ret.std(ddof=1) * _annualize_factor(periods))
            information_ratio = float(active_ret.mean() / active_ret.std(ddof=1) * _annualize_factor(periods)) if active_ret.std(ddof=1) > 0 else float("nan")
            up_mask = br > 0
            down_mask = br < 0
            up_capture = float(ar[up_mask].mean() / br[up_mask].mean()) if up_mask.any() and br[up_mask].mean() != 0 else float("nan")
            down_capture = float(ar[down_mask].mean() / br[down_mask].mean()) if down_mask.any() and br[down_mask].mean() != 0 else float("nan")

    return {
        # Return
        "total_return": total_return,
        "cagr": cagr,
        "ann_return": ann_return,
        # Risk-adjusted
        "sharpe": sharpe,
        "sortino": sortino,
        "calmar": calmar,
        "ann_vol": ann_vol,
        # Drawdown
        "max_drawdown": max_dd,
        "max_dd_duration_bars": max_dd_dur,
        "ulcer_index": ulcer,
        # VaR
        "var_95": var_95,
        "var_99": var_99,
        "cvar_95": cvar_95,
        # Distribution
        "skewness": ret_skew,
        "excess_kurtosis": ret_kurt,
        "jarque_bera_stat": float(jb_stat),
        "jarque_bera_pval": float(jb_pval),
        "tail_ratio": tail_ratio,
        "gain_pain_ratio": gain_pain,
        "return_autocorr": autocorr,
        # PSR
        "probabilistic_sharpe": psr,
        # Benchmark
        "alpha": alpha,
        "beta": beta_val,
        "r_squared": r2,
        "tracking_error": tracking_err,
        "information_ratio": information_ratio,
        "up_capture": up_capture,
        "down_capture": down_capture,
    }


def trade_metrics(trades: pd.DataFrame) -> dict:
    """
    trades: DataFrame with columns ['pnl', 'entry', 'exit'] at minimum.
    pnl: per-trade profit/loss as a fraction (e.g. 0.05 for 5%).
    """
    if trades.empty:
        return {}
    pnl = trades["pnl"]
    wins = pnl[pnl > 0]
    losses = pnl[pnl < 0]
    n = len(pnl)
    win_rate = float(len(wins) / n) if n > 0 else float("nan")
    profit_factor = float(wins.sum() / abs(losses.sum())) if losses.any() else float("nan")
    expectancy = float(pnl.mean())
    payoff = float(wins.mean() / abs(losses.mean())) if losses.any() and wins.any() else float("nan")
    avg_win = float(wins.mean()) if len(wins) > 0 else float("nan")
    avg_loss = float(losses.mean()) if len(losses) > 0 else float("nan")

    # Max consecutive wins/losses
    streaks = (pnl > 0).astype(int)
    max_consec_wins = int(streaks.groupby((streaks != streaks.shift()).cumsum()).cumcount().max() + 1) if n > 0 else 0
    streaks_l = (pnl < 0).astype(int)
    max_consec_losses = int(streaks_l.groupby((streaks_l != streaks_l.shift()).cumsum()).cumcount().max() + 1) if n > 0 else 0

    return {
        "num_trades": n,
        "win_rate": win_rate,
        "profit_factor": profit_factor,
        "expectancy": expectancy,
        "payoff_ratio": payoff,
        "avg_win": avg_win,
        "avg_loss": avg_loss,
        "max_consec_wins": max_consec_wins,
        "max_consec_losses": max_consec_losses,
    }
