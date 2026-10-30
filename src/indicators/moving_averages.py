"""
indicators/moving_averages.py — Moving average calculations

All functions take a pandas Series of close prices (sorted oldest→newest).
Returns are either a float (latest value) or a Series (full history).

Design rule: every function is independent — no shared state, no side effects.
"""

import pandas as pd
import numpy as np


def sma(close: pd.Series, n: int) -> float:
    """
    Simple Moving Average of the last n periods.
    Returns the latest value as a float, or NaN if insufficient data.
    """
    if len(close) < n:
        return float("nan")
    return close.iloc[-n:].mean()


def ema(close: pd.Series, n: int) -> float:
    """
    Exponential Moving Average over n periods.
    Returns the latest value as a float.
    """
    if len(close) < n:
        return float("nan")
    return close.ewm(span=n, adjust=False).mean().iloc[-1]


def sma_series(close: pd.Series, n: int) -> pd.Series:
    """Full rolling SMA series — one value per bar."""
    return close.rolling(window=n).mean()


def ema_series(close: pd.Series, n: int) -> pd.Series:
    """Full rolling EMA series — one value per bar."""
    return close.ewm(span=n, adjust=False).mean()


def is_above_ma(close: pd.Series, n: int) -> bool:
    """
    True if the latest close is above the n-period SMA.
    Example: is_above_ma(close, 50) → stock is above 50-day MA
    """
    ma_value = sma(close, n)
    if pd.isna(ma_value):
        return False
    return close.iloc[-1] > ma_value


def is_surfing_ma(close: pd.Series, n: int, lookback: int = 10, tolerance_pct: float = 3.0) -> bool:
    """
    True if the stock has been consistently near and above the n-period MA
    over the last `lookback` bars — the "surfing the MA" pattern.

    Definition: for the last `lookback` bars, close stays within `tolerance_pct`%
    above the MA (never too far, never below).

    Args:
        close:         Series of close prices
        n:             MA period (e.g. 10 or 20)
        lookback:      bars to check (default 10)
        tolerance_pct: max % above MA allowed (default 3% — stays close but not too extended)
    """
    if len(close) < n + lookback:
        return False

    ma = sma_series(close, n).iloc[-lookback:]
    recent_close = close.iloc[-lookback:]

    above_ma = (recent_close >= ma).all()
    within_range = ((recent_close - ma) / ma * 100 <= tolerance_pct).all()

    return bool(above_ma and within_range)


def ma_slope(close: pd.Series, n: int, lookback: int = 5) -> float:
    """
    Percentage slope of the n-period MA over the last `lookback` bars.
    Positive = rising MA, negative = falling MA.
    """
    ma = sma_series(close, n)
    if len(ma.dropna()) < lookback + 1:
        return float("nan")
    recent = ma.dropna().iloc[-lookback - 1:]
    return (recent.iloc[-1] / recent.iloc[0] - 1) * 100
