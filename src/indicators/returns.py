"""
indicators/returns.py — Price return calculations

All functions take a pandas Series of close prices (sorted oldest→newest)
and return a float or Series depending on the function.

Design rule: every function is independent — no shared state, no side effects.
"""

import pandas as pd
import numpy as np


def n_day_return(close: pd.Series, n: int) -> float:
    """
    Return the percentage price change over the last n trading days.
    Returns NaN if there is insufficient data.

    Example:
        n_day_return(close, 21)   → 1-month return
        n_day_return(close, 63)   → 3-month return
        n_day_return(close, 126)  → 6-month return
    """
    if len(close) <= n:
        return float("nan")
    return (close.iloc[-1] / close.iloc[-1 - n] - 1) * 100


def month_return(close: pd.Series, months: int) -> float:
    """
    Return over the last N calendar months approximated as trading days.
    1 month ≈ 21 trading days, 3 months ≈ 63, 6 months ≈ 126.

    Args:
        close:  Series of close prices
        months: number of months (1, 3, 6, 12, etc.)
    """
    trading_days = months * 21
    return n_day_return(close, trading_days)


def rolling_return(close: pd.Series, n: int) -> pd.Series:
    """
    Return a Series of rolling n-day returns (one value per row).
    Useful for building charts or finding peaks.
    """
    return close.pct_change(periods=n) * 100


def cumulative_return(close: pd.Series) -> float:
    """
    Total return from the first available price to the latest.
    """
    if len(close) < 2:
        return float("nan")
    return (close.iloc[-1] / close.iloc[0] - 1) * 100
