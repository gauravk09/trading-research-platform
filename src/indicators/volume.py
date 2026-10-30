"""
indicators/volume.py — Volume metrics

Used in Qullamaggie setups to confirm breakouts:
  - Breakout setup: volume must be ≥ 1.5× 20-day average on breakout day
  - EP setup:       volume must be ≥ 2× average in the first 15-30 minutes
"""

import pandas as pd
import numpy as np


def avg_volume(volume: pd.Series, n: int = 20) -> float:
    """
    Average daily volume over the last n days.
    The most recent bar is typically today's partial volume — excluded by default.

    Args:
        volume: Series of daily volumes
        n:      lookback period (default 20)
    """
    if len(volume) < n + 1:
        return float("nan")
    # Exclude the last bar (today's incomplete volume) when looking at averages
    return volume.iloc[-n - 1:-1].mean()


def volume_ratio(volume: pd.Series, n: int = 20) -> float:
    """
    Today's volume as a multiple of the n-day average.
    Example: 2.5 means today's volume is 2.5× the 20-day average.

    Used to confirm: breakout volume ≥ 1.5×, EP volume ≥ 2×
    """
    avg = avg_volume(volume, n)
    if pd.isna(avg) or avg == 0:
        return float("nan")
    return volume.iloc[-1] / avg


def avg_turnover_cr(close: pd.Series, volume: pd.Series, n: int = 20) -> float:
    """
    Average daily turnover in ₹ crore over last n days.
    Turnover = close × volume / 1e7  (₹ → crore)

    Used in the liquidity filter: require ≥ ₹1 crore per day.
    """
    if len(close) < n + 1 or len(volume) < n + 1:
        return float("nan")
    daily_turnover = close.iloc[-n - 1:-1] * volume.iloc[-n - 1:-1] / 1e7
    return daily_turnover.mean()


def is_volume_surge(volume: pd.Series, min_ratio: float = 1.5, n: int = 20) -> bool:
    """
    True if today's volume is at least min_ratio × the n-day average.
    Default min_ratio=1.5 for breakout confirmation.
    """
    ratio = volume_ratio(volume, n)
    if pd.isna(ratio):
        return False
    return ratio >= min_ratio
