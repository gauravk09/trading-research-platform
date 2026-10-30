"""
filters/volatility.py — Volatility filters

Qullamaggie rule: ADR must be > 4% for any setup.
Stop must not be wider than 1× ADR — if it is, skip the trade.
"""

import pandas as pd
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from indicators.volatility import adr


def min_adr_filter(high: pd.Series, low: pd.Series, min_adr_pct: float = 4.0, n: int = 20) -> bool:
    """
    True if the stock's ADR >= min_adr_pct over last n days.
    Qullamaggie requires ADR > 4% for any setup.

    Args:
        high:        Series of daily highs
        low:         Series of daily lows
        min_adr_pct: minimum ADR threshold in % (default 4.0)
        n:           lookback days (default 20)
    """
    stock_adr = adr(high, low, n)
    if pd.isna(stock_adr):
        return False
    return stock_adr >= min_adr_pct


def max_adr_filter(high: pd.Series, low: pd.Series, max_adr_pct: float = 15.0, n: int = 20) -> bool:
    """
    True if ADR is <= max_adr_pct.
    Optionally exclude stocks that are too volatile (e.g. parabolic/erratic).

    Args:
        max_adr_pct: maximum ADR threshold (default 15%)
    """
    stock_adr = adr(high, low, n)
    if pd.isna(stock_adr):
        return False
    return stock_adr <= max_adr_pct


def stop_within_adr(entry: float, stop: float, high: pd.Series, low: pd.Series, n: int = 20) -> bool:
    """
    True if the proposed stop distance is within 1× ADR.
    Qullamaggie rule: if stop > 1× ADR, skip the trade.

    Args:
        entry: proposed entry price
        stop:  proposed stop price
        high / low: OHLCV series for ADR computation
    """
    stock_adr = adr(high, low, n)
    if pd.isna(stock_adr):
        return False
    stop_distance_pct = abs(entry - stop) / entry * 100
    return stop_distance_pct <= stock_adr
