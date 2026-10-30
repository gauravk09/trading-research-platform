"""
filters/momentum.py — Momentum and relative strength filters

Qullamaggie scans for stocks that have already made a big move (30-100%+
in 1-3 months) AND are in the top 1-2% by relative strength.
"""

import pandas as pd
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from indicators.returns import n_day_return


def min_return_filter(close: pd.Series, n: int, min_pct: float) -> bool:
    """
    True if the stock has returned >= min_pct% over the last n trading days.
    Example: min_return_filter(close, 63, 30) → up 30%+ in last 3 months.

    Args:
        close:   Series of close prices
        n:       lookback in trading days
        min_pct: minimum return threshold in %
    """
    ret = n_day_return(close, n)
    if pd.isna(ret):
        return False
    return ret >= min_pct


def max_return_filter(close: pd.Series, n: int, max_pct: float) -> bool:
    """
    True if the stock has returned <= max_pct% over the last n trading days.
    Used to exclude stocks that have already run too far (parabolic).
    Example: max_return_filter(close, 63, 200) → not up more than 200% in 3 months.
    """
    ret = n_day_return(close, n)
    if pd.isna(ret):
        return False
    return ret <= max_pct


def rs_rank_filter(symbol: str, rs_ranks: pd.Series, min_percentile: float = 80.0) -> bool:
    """
    True if the stock's RS rank is in the top X percentile.
    Qullamaggie uses top 1-2% → set min_percentile=98 for strict filtering.

    Args:
        symbol:         stock to check
        rs_ranks:       Series of RS ranks indexed by symbol (from relative_strength.py)
        min_percentile: minimum rank required (default 80 = top 20%)
    """
    if symbol not in rs_ranks.index:
        return False
    return rs_ranks[symbol] >= min_percentile


def breakout_return_filter(close: pd.Series) -> bool:
    """
    Qullamaggie's breakout prerequisite: stock must be up 30-100% in 1-3 months.
    Returns True if any of these conditions hold:
      - 1-month return between 30% and 200%
      - 3-month return between 30% and 300%
    """
    r1mo = n_day_return(close, 21)
    r3mo = n_day_return(close, 63)

    passes_1mo = not pd.isna(r1mo) and 30 <= r1mo <= 200
    passes_3mo = not pd.isna(r3mo) and 30 <= r3mo <= 300

    return passes_1mo or passes_3mo
