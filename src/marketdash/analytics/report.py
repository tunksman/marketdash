"""
Runs the full study battery against a symbol and produces a structured report.
Output: momentum-intact score, extension/markup gauge, regime label, per-study results.
"""

import pandas as pd
from typing import Optional

from .studies import STUDIES


_EXTENSION_STUDIES = {"pct_above_200", "bb_extension", "atr_distance_from_ma", "rsi_overbought_streak"}
_BEAR_PENALTY = {"extension": 1.5}  # weight extension bear signals heavier


def run_battery(
    df: pd.DataFrame,
    spy_close: Optional[pd.Series] = None,
    macro_df: Optional[pd.DataFrame] = None,
) -> dict:
    """
    df: daily OHLCV DataFrame with columns: open, high, low, close, volume (+ adj_close optional).
    Returns a structured report dict.
    """
    context = {}
    if spy_close is not None:
        context["spy_close"] = spy_close
    if macro_df is not None:
        context["macro"] = macro_df

    results = []
    for study_fn in STUDIES:
        try:
            result = study_fn(df, context)
            results.append(result)
        except Exception as e:
            results.append({
                "name": study_fn.__name__,
                "group": "error",
                "value": None,
                "signal": "neutral",
                "score": 0.5,
                "note": f"error: {e}",
            })

    # ── Momentum-Intact Score ──────────────────────────────────────────────────
    momentum_groups = {"trend", "momentum", "relative_strength", "breakout", "statistical"}
    momentum_results = [r for r in results if r["group"] in momentum_groups]
    if momentum_results:
        bull_count = sum(1 for r in momentum_results if r["signal"] == "bull")
        bear_count = sum(1 for r in momentum_results if r["signal"] == "bear")
        total = len(momentum_results)
        momentum_score = bull_count / total if total > 0 else 0.5
    else:
        momentum_score = 0.5

    # ── Extension / Markup Gauge ───────────────────────────────────────────────
    ext_results = [r for r in results if r["group"] == "extension"]
    if ext_results:
        ext_bear = sum(1 for r in ext_results if r["signal"] == "bear")
        ext_score = ext_bear / len(ext_results)  # 0=not extended, 1=fully extended
    else:
        ext_score = 0.0

    # ── Regime Label ───────────────────────────────────────────────────────────
    hurst_r = next((r for r in results if r["name"] == "Hurst Exponent"), None)
    vol_r = next((r for r in results if r["name"] == "Volatility Regime (ATR %ile)"), None)
    adx_r = next((r for r in results if r["name"] == "ADX Strength"), None)

    hurst_val = hurst_r["value"] if hurst_r and hurst_r["value"] is not None else 0.5
    vol_pct = vol_r["value"] if vol_r and vol_r["value"] is not None else 0.5
    adx_val = adx_r["value"] if adx_r and adx_r["value"] is not None else 20

    if isinstance(adx_val, (int, float)) and adx_val > 25 and isinstance(hurst_val, (int, float)) and hurst_val > 0.55:
        regime = "trending"
    elif isinstance(vol_pct, (int, float)) and vol_pct > 0.75:
        regime = "high_volatility"
    elif isinstance(hurst_val, (int, float)) and hurst_val < 0.45:
        regime = "mean_reverting"
    else:
        regime = "range_bound"

    # ── Summary ────────────────────────────────────────────────────────────────
    bull_pct = sum(1 for r in results if r["signal"] == "bull") / len(results) * 100 if results else 50
    bear_pct = sum(1 for r in results if r["signal"] == "bear") / len(results) * 100 if results else 50

    return {
        "momentum_intact_score": round(momentum_score, 3),
        "extension_score": round(ext_score, 3),
        "regime": regime,
        "bull_pct": round(bull_pct, 1),
        "bear_pct": round(bear_pct, 1),
        "n_studies": len(results),
        "studies": results,
    }


def print_report(symbol: str, report: dict) -> None:
    print(f"\n{'='*60}")
    print(f"  {symbol} — Quant Battery Report")
    print(f"{'='*60}")
    print(f"  Momentum Intact Score : {report['momentum_intact_score']:.1%}")
    print(f"  Extension/Markup Risk : {report['extension_score']:.1%}")
    print(f"  Regime                : {report['regime']}")
    print(f"  Bull/Bear             : {report['bull_pct']:.0f}% / {report['bear_pct']:.0f}%")
    print(f"  Studies run           : {report['n_studies']}")
    print()

    by_group: dict[str, list] = {}
    for r in report["studies"]:
        by_group.setdefault(r["group"], []).append(r)

    icons = {"bull": "▲", "neutral": "─", "bear": "▼"}
    for group, studies in sorted(by_group.items()):
        print(f"  [{group.upper()}]")
        for s in studies:
            icon = icons[s["signal"]]
            val = f"{s['value']}" if s["value"] is not None else "N/A"
            note = f"  {s['note']}" if s.get("note") else ""
            print(f"    {icon} {s['name']:<35} {val:<12}{note}")
        print()
