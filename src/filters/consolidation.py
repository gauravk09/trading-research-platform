"""
filters/consolidation.py — Consolidation pattern filters

Qullamaggie breakout setup requires:
  - Consolidation of 2 weeks to 2 months
  - Higher lows forming during the consolidation
  - Range tightening (lower volatility than the prior trend)

These filters look at the recent price structure to detect this pattern.
"""

import pandas as pd
import numpy as np
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from indicators.volatility import adr


def tightening_range_filter(high: pd.Series, low: pd.Series,
                             consolidation_bars: int = 20,
                             trend_bars: int = 60) -> bool:
    """
    True if the recent consolidation range is tighter than the prior trend range.
    Detects the squeeze that precedes a Qullamaggie breakout.

    Method: compare ADR of the last `consolidation_bars` to ADR of the
    `trend_bars` before that.

    Args:
        high / low:          OHLCV series
        consolidation_bars:  bars in the consolidation window (default 20 = ~1 month)
        trend_bars:          bars in the prior trend window (default 60 = ~3 months)
    """
    total_needed = consolidation_bars + trend_bars
    if len(high) < total_needed:
        return False

    consol_high = high.iloc[-consolidation_bars:]
    consol_low  = low.iloc[-consolidation_bars:]
    trend_high  = high.iloc[-total_needed:-consolidation_bars]
    trend_low   = low.iloc[-total_needed:-consolidation_bars]

    consol_adr = (consol_high - consol_low).mean() / consol_low.mean() * 100
    trend_adr  = (trend_high  - trend_low).mean()  / trend_low.mean()  * 100

    if pd.isna(consol_adr) or pd.isna(trend_adr) or trend_adr == 0:
        return False

    return consol_adr < trend_adr


def higher_lows_filter(low: pd.Series, lookback: int = 20, min_higher: int = 3) -> bool:
    """
    True if at least `min_higher` of the recent swing lows are higher than
    the previous swing low — a sign of accumulation and bullish structure.

    Method: compare each bar's low to the lowest low of the prior 5 bars.
    A "higher low" is when today's low > 5-bar trailing minimum.

    Args:
        low:          Series of daily lows
        lookback:     bars to check (default 20)
        min_higher:   minimum number of higher lows required (default 3)
    """
    if len(low) < lookback + 5:
        return False

    recent_lows = low.iloc[-lookback:]
    trailing_min = recent_lows.rolling(5).min().shift(1)
    higher_lows = (recent_lows > trailing_min).sum()

    return int(higher_lows) >= min_higher


def price_near_high_filter(close: pd.Series, high: pd.Series,
                            lookback: int = 20, within_pct: float = 10.0) -> bool:
    """
    True if the current close is within `within_pct`% of the highest high
    over the last `lookback` bars — stock is consolidating near the top,
    not falling away from it.

    Args:
        within_pct: maximum % below the recent high (default 10%)
    """
    if len(close) < lookback:
        return False

    period_high = high.iloc[-lookback:].max()
    current_close = close.iloc[-1]
    dist_from_high = (period_high - current_close) / period_high * 100

    return dist_from_high <= within_pct


def consolidation_duration_filter(close: pd.Series,
                                   min_bars: int = 10,
                                   max_bars: int = 40) -> bool:
    """
    True if the stock appears to have been consolidating for between
    min_bars and max_bars trading days.

    Method: find how many bars since the stock made its highest close
    (high-of-range). If that's within min_bars to max_bars, it's
    consolidating in the right time window.

    Qullamaggie: 2 weeks (10 bars) to 2 months (40 bars).
    """
    if len(close) < max_bars + 10:
        return False

    recent_close = close.iloc[-max_bars - 10:]
    peak_idx = recent_close.values.argmax()
    bars_since_peak = len(recent_close) - 1 - peak_idx

    return min_bars <= bars_since_peak <= max_bars
