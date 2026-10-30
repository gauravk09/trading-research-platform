"""
filters/liquidity.py — Liquidity filters

Applied at SCAN time. We collect history for all stocks regardless,
but only scan liquid ones so we can actually trade the signals.
"""

import pandas as pd
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from indicators.volume import avg_turnover_cr


def min_turnover_filter(df: pd.DataFrame, min_cr: float = 1.0, n: int = 20) -> pd.Series:
    """
    Keep stocks with average daily turnover >= min_cr crore.
    Returns a boolean mask (True = passes filter).

    Args:
        df:     OHLCV DataFrame with columns: close, volume
        min_cr: minimum turnover in ₹ crore (default 1.0)
        n:      lookback days for average (default 20)
    """
    turnover = avg_turnover_cr(df["close"], df["volume"], n)
    return pd.Series([turnover >= min_cr], index=[True])


def apply_min_turnover(universe_df: pd.DataFrame, min_cr: float = 1.0) -> pd.DataFrame:
    """
    Filter a universe summary DataFrame that already has an avg_turnover_cr column.
    Use this when you have a pre-computed summary (faster than re-reading all files).

    Args:
        universe_df: DataFrame with at least columns: symbol, avg_turnover_cr
        min_cr:      minimum ₹ crore/day
    """
    return universe_df[universe_df["avg_turnover_cr"] >= min_cr].copy()
