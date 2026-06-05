"""
Quant statistics: returns, correlations, regressions, Granger, ADF, cointegration.
Operates on small pandas DataFrames produced by access.aligned_frame().
"""

import numpy as np
import pandas as pd
from scipy import stats as scipy_stats
from statsmodels.tsa.stattools import adfuller, coint, grangercausalitytests
from statsmodels.regression.linear_model import OLS
from statsmodels.tools import add_constant


# ── Returns ────────────────────────────────────────────────────────────────────

def simple_returns(close: pd.Series) -> pd.Series:
    return close.pct_change()


def log_returns(close: pd.Series) -> pd.Series:
    return np.log(close / close.shift(1))


def multi_horizon_returns(close: pd.Series, periods: list[int]) -> pd.DataFrame:
    return pd.DataFrame({f"ret_{p}d": close.pct_change(p) for p in periods})


def cumulative_returns(close: pd.Series) -> pd.Series:
    ret = simple_returns(close).dropna()
    return (1 + ret).cumprod() - 1


def rolling_vol(close: pd.Series, window: int = 20, annualize: int = 252) -> pd.Series:
    lr = log_returns(close)
    return lr.rolling(window).std(ddof=1) * np.sqrt(annualize)


def drawdown_series(close: pd.Series) -> pd.Series:
    roll_max = close.cummax()
    return (close - roll_max) / roll_max


def max_drawdown(close: pd.Series) -> float:
    return float(drawdown_series(close).min())


def sharpe(close: pd.Series, risk_free: float = 0.0, periods: int = 252) -> float:
    ret = log_returns(close).dropna()
    excess = ret - risk_free / periods
    if excess.std(ddof=1) == 0:
        return 0.0
    return float(excess.mean() / excess.std(ddof=1) * np.sqrt(periods))


def sortino(close: pd.Series, risk_free: float = 0.0, periods: int = 252) -> float:
    ret = log_returns(close).dropna()
    excess = ret - risk_free / periods
    downside = excess[excess < 0].std(ddof=1)
    if downside == 0:
        return 0.0
    return float(excess.mean() / downside * np.sqrt(periods))


def beta(asset: pd.Series, benchmark: pd.Series) -> float:
    a = log_returns(asset).dropna()
    b = log_returns(benchmark).dropna()
    aligned = pd.concat([a, b], axis=1).dropna()
    if len(aligned) < 2:
        return float("nan")
    cov = np.cov(aligned.iloc[:, 0], aligned.iloc[:, 1])
    return float(cov[0, 1] / cov[1, 1]) if cov[1, 1] != 0 else float("nan")


# ── Correlation ────────────────────────────────────────────────────────────────

def correlation_matrix(df: pd.DataFrame, method: str = "pearson") -> pd.DataFrame:
    return df.corr(method=method)


def rolling_correlation(
    a: pd.Series, b: pd.Series, window: int = 60
) -> pd.Series:
    return a.rolling(window).corr(b)


def lead_lag_correlation(
    a: pd.Series, b: pd.Series, max_lag: int = 20
) -> pd.Series:
    """Cross-correlation at lags -max_lag..+max_lag. Positive lag = a leads b."""
    a_z = (a - a.mean()) / a.std()
    b_z = (b - b.mean()) / b.std()
    n = len(a_z)
    lags = range(-max_lag, max_lag + 1)
    corrs = {}
    for lag in lags:
        if lag >= 0:
            corrs[lag] = float(np.corrcoef(a_z.iloc[:n - lag].values,
                                           b_z.iloc[lag:].values)[0, 1])
        else:
            corrs[lag] = float(np.corrcoef(a_z.iloc[-lag:].values,
                                           b_z.iloc[:n + lag].values)[0, 1])
    return pd.Series(corrs, name="cross_corr")


# ── Volume features ────────────────────────────────────────────────────────────

def volume_zscore(volume: pd.Series, window: int = 20) -> pd.Series:
    mu = volume.rolling(window).mean()
    sigma = volume.rolling(window).std(ddof=1)
    return (volume - mu) / sigma.replace(0, np.nan)


def volume_price_divergence(close: pd.Series, volume: pd.Series, window: int = 20) -> pd.Series:
    """Positive: price rising but volume declining (divergence)."""
    price_trend = close.pct_change(window)
    volume_trend = volume.pct_change(window)
    return price_trend - volume_trend


def volume_confirmed_move(close: pd.Series, volume: pd.Series, window: int = 20) -> pd.Series:
    """1 if price and volume both moved in the same direction above their medians."""
    p_up = (close.pct_change() > 0).astype(int)
    v_above = (volume > volume.rolling(window).median()).astype(int)
    return (p_up * v_above + (1 - p_up) * v_above * -1)


def dollar_volume_trend(close: pd.Series, volume: pd.Series, window: int = 20) -> pd.Series:
    dv = close * volume
    return dv.rolling(window).mean()


# ── Regression ─────────────────────────────────────────────────────────────────

def ols_regression(y: pd.Series, X: pd.DataFrame) -> dict:
    """Multi-factor OLS. Returns dict with params, r2, residuals."""
    aligned = pd.concat([y, X], axis=1).dropna()
    if len(aligned) < len(X.columns) + 2:
        return {}
    y_ = aligned.iloc[:, 0]
    X_ = add_constant(aligned.iloc[:, 1:])
    model = OLS(y_, X_).fit()
    return {
        "params": model.params.to_dict(),
        "pvalues": model.pvalues.to_dict(),
        "r2": model.rsquared,
        "adj_r2": model.rsquared_adj,
        "residuals": model.resid,
    }


def rolling_beta_ols(
    y: pd.Series, x: pd.Series, window: int = 60
) -> pd.Series:
    betas = []
    for i in range(len(y)):
        if i < window - 1:
            betas.append(np.nan)
            continue
        y_w = y.iloc[i - window + 1:i + 1].values
        x_w = x.iloc[i - window + 1:i + 1].values
        if np.std(x_w) == 0:
            betas.append(np.nan)
            continue
        b = np.cov(y_w, x_w)[0, 1] / np.var(x_w)
        betas.append(b)
    return pd.Series(betas, index=y.index)


# ── Stationarity / Cointegration ───────────────────────────────────────────────

def adf_test(series: pd.Series) -> dict:
    """Augmented Dickey-Fuller test. p < 0.05 → stationary."""
    clean = series.dropna()
    result = adfuller(clean, autolag="AIC")
    return {
        "adf_stat": result[0],
        "p_value": result[1],
        "lags": result[2],
        "stationary": result[1] < 0.05,
        "critical_values": result[4],
    }


def granger_causality(
    y: pd.Series, x: pd.Series, max_lag: int = 5
) -> dict:
    """Test whether x Granger-causes y. Returns p-values per lag."""
    df = pd.concat([y, x], axis=1).dropna()
    result = grangercausalitytests(df.values, maxlag=max_lag, verbose=False)
    return {lag: v[0]["ssr_ftest"][1] for lag, v in result.items()}


def engle_granger_coint(a: pd.Series, b: pd.Series) -> dict:
    """Engle-Granger cointegration test."""
    aligned = pd.concat([a, b], axis=1).dropna()
    score, pvalue, _ = coint(aligned.iloc[:, 0], aligned.iloc[:, 1])
    return {"score": score, "p_value": pvalue, "cointegrated": pvalue < 0.05}


# ── Transforms ────────────────────────────────────────────────────────────────

def zscore(series: pd.Series, window: int = 0) -> pd.Series:
    """Rolling z-score if window > 0, else full-series z-score."""
    if window > 0:
        mu = series.rolling(window).mean()
        sigma = series.rolling(window).std(ddof=1)
    else:
        mu = series.mean()
        sigma = series.std(ddof=1)
    denom = sigma if isinstance(sigma, pd.Series) else (float(sigma) if sigma != 0 else float("nan"))
    if isinstance(denom, pd.Series):
        denom = denom.replace(0, np.nan)
    return (series - mu) / denom


def percentile_rank(series: pd.Series, window: int = 252) -> pd.Series:
    return series.rolling(window).apply(
        lambda x: scipy_stats.percentileofscore(x[:-1], x[-1]) / 100, raw=True
    )


def yoy_change(series: pd.Series, freq_per_year: int = 252) -> pd.Series:
    return series.pct_change(freq_per_year)


def mom_change(series: pd.Series, freq_per_month: int = 21) -> pd.Series:
    return series.pct_change(freq_per_month)
