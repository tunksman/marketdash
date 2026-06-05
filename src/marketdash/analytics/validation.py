"""
Overfitting controls: walk-forward CV, purged k-fold, DSR/PSR, PBO, Monte Carlo.
"""

import numpy as np
import pandas as pd
from scipy.stats import norm

from .backtest import run_backtest
from .metrics import tearsheet


# ── Walk-Forward ───────────────────────────────────────────────────────────────

def walk_forward(
    close: pd.Series,
    signal_fn,           # callable(close_train) -> signal_full (aligned to close)
    train_size: int = 504,
    test_size: int = 126,
    cost_pct: float = 0.001,
    slippage_pct: float = 0.0005,
) -> pd.DataFrame:
    """
    Rolling train/test walk-forward.
    signal_fn(close) should return a signal Series aligned to close.
    Returns DataFrame with IS and OOS Sharpe per fold.
    """
    results = []
    n = len(close)
    start = train_size
    while start + test_size <= n:
        train = close.iloc[:start]
        test_idx_start = start
        test_idx_end = start + test_size
        test = close.iloc[test_idx_start:test_idx_end]

        signal_all = signal_fn(close.iloc[:test_idx_end])
        signal_train = signal_all.iloc[:start]
        signal_test = signal_all.iloc[test_idx_start:test_idx_end]

        bt_is = run_backtest(train, signal_train, cost_pct=cost_pct, slippage_pct=slippage_pct)
        bt_oos = run_backtest(test, signal_test, cost_pct=cost_pct, slippage_pct=slippage_pct)

        ts_is = tearsheet(bt_is["equity"])
        ts_oos = tearsheet(bt_oos["equity"])

        results.append({
            "fold_start": close.index[test_idx_start],
            "fold_end": close.index[test_idx_end - 1],
            "is_sharpe": ts_is.get("sharpe", float("nan")),
            "oos_sharpe": ts_oos.get("sharpe", float("nan")),
            "is_max_dd": ts_is.get("max_drawdown", float("nan")),
            "oos_max_dd": ts_oos.get("max_drawdown", float("nan")),
        })
        start += test_size

    return pd.DataFrame(results)


# ── Purged K-Fold ──────────────────────────────────────────────────────────────

def purged_kfold_splits(
    n: int, k: int = 5, embargo: int = 10
) -> list[tuple[np.ndarray, np.ndarray]]:
    """
    Returns list of (train_indices, test_indices) with purging and embargo.
    Purging: remove train samples that overlap with test period.
    Embargo: remove train samples just after each test fold.
    """
    fold_size = n // k
    splits = []
    for i in range(k):
        test_start = i * fold_size
        test_end = test_start + fold_size if i < k - 1 else n
        test_idx = np.arange(test_start, test_end)
        # Embargo: exclude fold_start - embargo .. test_end + embargo from train
        purge_start = max(0, test_start - embargo)
        purge_end = min(n, test_end + embargo)
        train_idx = np.array([
            j for j in range(n)
            if j < purge_start or j >= purge_end
        ])
        splits.append((train_idx, test_idx))
    return splits


# ── DSR / PSR ──────────────────────────────────────────────────────────────────

def probabilistic_sharpe(
    sharpe_obs: float, sharpe_ref: float, n: int,
    skewness: float = 0.0, excess_kurtosis: float = 0.0
) -> float:
    """P(SR* > sharpe_ref) given observed Sharpe and return distribution shape."""
    denom = np.sqrt(1 - skewness * sharpe_obs + (excess_kurtosis - 1) / 4 * sharpe_obs ** 2)
    if denom <= 0:
        return float("nan")
    z = (sharpe_obs - sharpe_ref) * np.sqrt(n - 1) / denom
    return float(norm.cdf(z))


def deflated_sharpe(
    sharpe_obs: float, n: int, n_trials: int,
    skewness: float = 0.0, excess_kurtosis: float = 0.0
) -> float:
    """
    DSR: deflates observed Sharpe by the expected max Sharpe across n_trials.
    Returns P(true SR > 0) after accounting for multiple testing.
    """
    # Expected max of n_trials iid N(0,1) via Euler–Mascheroni approximation
    euler_mascheroni = 0.5772156649
    expected_max = (
        (1 - euler_mascheroni) * norm.ppf(1 - 1 / n_trials)
        + euler_mascheroni * norm.ppf(1 - 1 / (n_trials * np.e))
    )
    sharpe_ref = expected_max / np.sqrt(n)
    return probabilistic_sharpe(sharpe_obs, sharpe_ref, n, skewness, excess_kurtosis)


# ── PBO — Probability of Backtest Overfitting ─────────────────────────────────

def pbo(
    close: pd.Series,
    signal_fn,
    n_splits: int = 16,
    cost_pct: float = 0.001,
    slippage_pct: float = 0.0005,
) -> float:
    """
    Combinatorial Symmetric Cross-Validation PBO estimate.
    Returns P(IS-best strategy underperforms OOS median).
    Simplified: use IS-best vs OOS degradation across purged folds.
    """
    splits = purged_kfold_splits(len(close), k=n_splits, embargo=5)
    oos_sharpes = []
    for train_idx, test_idx in splits:
        train_close = close.iloc[train_idx]
        test_close = close.iloc[test_idx]
        sig_all = signal_fn(close)
        sig_test = sig_all.iloc[test_idx]
        bt = run_backtest(test_close, sig_test, cost_pct=cost_pct, slippage_pct=slippage_pct)
        ts = tearsheet(bt["equity"])
        oos_sharpes.append(ts.get("sharpe", 0.0))

    oos = np.array(oos_sharpes)
    pbo_est = float((oos < np.median(oos)).mean())
    return pbo_est


# ── Monte Carlo ────────────────────────────────────────────────────────────────

def monte_carlo_returns(
    strategy_returns: pd.Series,
    n_simulations: int = 1000,
    initial_capital: float = 10_000.0,
) -> pd.DataFrame:
    """
    Block-bootstrap of strategy returns to generate confidence bands.
    Returns DataFrame with percentile equity curves (5th, 25th, 50th, 75th, 95th).
    """
    ret = strategy_returns.dropna().values
    n = len(ret)
    block_size = max(10, int(np.sqrt(n)))
    curves = []
    rng = np.random.default_rng(42)
    for _ in range(n_simulations):
        # Block bootstrap
        blocks = []
        while sum(len(b) for b in blocks) < n:
            start = rng.integers(0, max(1, n - block_size))
            blocks.append(ret[start:start + block_size])
        sim_ret = np.concatenate(blocks)[:n]
        equity = initial_capital * np.cumprod(1 + sim_ret)
        curves.append(equity)

    mat = np.array(curves)
    pctiles = [5, 25, 50, 75, 95]
    result = pd.DataFrame(
        np.percentile(mat, pctiles, axis=0).T,
        columns=[f"p{p}" for p in pctiles],
    )
    return result
