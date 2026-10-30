"""
filters/trend.py — Trend and moving average filters

Used in the Breakout setup to confirm the stock is in an uptrend
and consolidating properly near its MAs.
"""

import pandas as pd
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from indicators.moving_averages import is_above_ma, is_surfing_ma, sma, ma_slope
from indicators.trend_stage import base_count, trend_age, YOUNG_BARS


def above_ma_filter(close: pd.Series, n: int) -> bool:
    """
    True if latest close is above the n-period SMA.
    Example: above_ma_filter(close, 50) → stock is above 50-day MA.
    """
    return is_above_ma(close, n)


def surfing_ma_filter(close: pd.Series, n: int, lookback: int = 10, tolerance_pct: float = 3.0) -> bool:
    """
    True if the stock has been "surfing" the n-period MA — trading near
    and above it consistently over the last `lookback` bars.

    Qullamaggie looks for price surfing the 10-day or 20-day MA during consolidation.

    Args:
        close:         Series of close prices
        n:             MA period (use 10 or 20)
        lookback:      bars to check (default 10)
        tolerance_pct: max % above MA — keeps price from being too extended
    """
    return is_surfing_ma(close, n, lookback, tolerance_pct)


def rising_ma_filter(close: pd.Series, n: int, lookback: int = 5) -> bool:
    """
    True if the n-period MA has been rising over the last `lookback` bars.
    Confirms the underlying trend is upward, not just price bouncing.
    """
    slope = ma_slope(close, n, lookback)
    if pd.isna(slope):
        return False
    return slope > 0


def ma_stack_filter(close: pd.Series) -> bool:
    """
    True if MAs are stacked bullishly: price > 10-day > 20-day > 50-day.
    This is the ideal uptrend structure for breakout setups.
    """
    price  = close.iloc[-1]
    ma10   = sma(close, 10)
    ma20   = sma(close, 20)
    ma50   = sma(close, 50)

    if any(pd.isna(x) for x in [ma10, ma20, ma50]):
        return False

    return price > ma10 > ma20 > ma50


def young_trend_filter(close: pd.Series, high: pd.Series, low: pd.Series,
                       max_bases: int = 3) -> bool:
    """
    True if the stock is on its 1st-3rd base of a TI65-established trend —
    Bonde's 2LYNCH "Y" / Minervini base counting. Count 0 (no established
    trend yet — potentially day-one momentum) and unknown count (too little
    history) both pass through True rather than silently excluding them.
    """
    bases = base_count(close, high, low)
    return bases is None or bases <= max_bases


def young_momentum_filter(close: pd.Series, max_age: int = YOUNG_BARS) -> bool:
    """
    True if TI65 established the trend within the last `max_age` bars —
    Bonde's "Young TI65 Bullish" scan (avgc7/avgc65 >= 1.05 now, <= 1.05
    twenty-five bars ago). False when no trend is latched or it's older.
    """
    age = trend_age(close)
    return age is not None and age <= max_age
