"""
indicators/volatility.py — Volatility metrics: ADR and ATR

ADR (Average Daily Range): average of (high - low) / low * 100 over n days.
ATR (Average True Range):  accounts for gaps between sessions.

Both are used in Qullamaggie setups to:
  1. Filter stocks: ADR > 4% is required for all setups
  2. Size stops: stop must not exceed 1× ADR/ATR
"""

import pandas as pd
import numpy as np


def adr(high: pd.Series, low: pd.Series, n: int = 20) -> float:
    """
    Average Daily Range as a percentage over last n days.
    Formula: mean((high - low) / low * 100) over n bars.

    Args:
        high: Series of daily highs
        low:  Series of daily lows
        n:    lookback period (default 20 days)

    Returns:
        ADR as a percentage float (e.g. 4.5 means 4.5%)
    """
    if len(high) < n:
        return float("nan")
    daily_range_pct = (high.iloc[-n:] - low.iloc[-n:]) / low.iloc[-n:] * 100
    return daily_range_pct.mean()


def adr_value(high: pd.Series, low: pd.Series, close: pd.Series, n: int = 20) -> float:
    """
    Average Daily Range in price units (rupees) over last n days.
    Useful for computing max stop distance in ₹ terms.
    """
    if len(high) < n:
        return float("nan")
    return (high.iloc[-n:] - low.iloc[-n:]).mean()


def atr(high: pd.Series, low: pd.Series, close: pd.Series, n: int = 14) -> float:
    """
    Average True Range over n periods.
    True Range = max(high-low, abs(high-prev_close), abs(low-prev_close))

    Returns the latest ATR in price units.
    """
    if len(close) < n + 1:
        return float("nan")

    prev_close = close.shift(1)
    tr = pd.concat([
        high - low,
        (high - prev_close).abs(),
        (low  - prev_close).abs()
    ], axis=1).max(axis=1)

    return tr.ewm(span=n, adjust=False).mean().iloc[-1]


def atr_series(high: pd.Series, low: pd.Series, close: pd.Series, n: int = 14) -> pd.Series:
    """Full rolling ATR series — one value per bar."""
    prev_close = close.shift(1)
    tr = pd.concat([
        high - low,
        (high - prev_close).abs(),
        (low  - prev_close).abs()
    ], axis=1).max(axis=1)
    return tr.ewm(span=n, adjust=False).mean()


def max_stop_distance(close: pd.Series, high: pd.Series, low: pd.Series, n: int = 20) -> float:
    """
    Maximum allowable stop distance in ₹ based on 1× ADR rule.
    stop_distance = entry_price × (ADR% / 100)
    """
    adr_pct = adr(high, low, n)
    if pd.isna(adr_pct):
        return float("nan")
    return close.iloc[-1] * (adr_pct / 100)
