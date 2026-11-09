"""
parabolic.py — Setup 3: Parabolic Short (and Long bounce) scanner

This scans for stocks that have gone parabolic (100%+ in days/weeks)
and are showing signs of exhaustion — candidates for a short or a bounce.

SHORT prerequisites:
  - Stock up 100%+ in a short period (30–60 days)
  - Recent blow-off candle: large range, high volume
  - Exhaustion signals: long upper wicks, fading volume on recent bars
  - Today's candle is red or inside bar after the blow-off

LONG BOUNCE prerequisites (parabolic that has crashed):
  - Stock dropped 50–60%+ from its recent peak in a few days
  - Now showing a potential reversal (first green candle or ORB setup)

Reference: strategies/qullamaggie/SETUP_RULES.md — Setup 3
"""

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src"))

import pandas as pd
import numpy as np
from data_collection.storage import read_daily
from indicators.returns import n_day_return
from indicators.volatility import adr
from indicators.volume import avg_volume, volume_ratio
from filters.surveillance import surveillance_filter
from filters.liquidity import apply_min_turnover


def _upper_wick_ratio(open_: float, high: float, close: float) -> float:
    """Upper wick as % of total candle range. High ratio = rejection at highs."""
    total_range = high - min(open_, close)
    if total_range == 0:
        return 0
    upper_wick = high - max(open_, close)
    return upper_wick / total_range


def detect_blowoff(df: pd.DataFrame, lookback: int = 5) -> dict:
    """
    Detect blow-off top characteristics in the last `lookback` bars.

    Signals:
      - Largest single-day range in the recent trend
      - Volume spike (≥2× average)
      - Long upper wick on peak candle
      - Subsequent price fading below the blow-off candle's open

    Returns dict of signals.
    """
    if len(df) < lookback + 20:
        return {}

    recent       = df.iloc[-lookback:]
    peak_idx     = recent["high"].values.argmax()
    peak_bar     = recent.iloc[peak_idx]
    latest_bar   = df.iloc[-1]
    vol_20       = avg_volume(df["volume"], 20)

    daily_ranges  = (df["high"] - df["low"]).iloc[-60:]
    peak_range    = peak_bar["high"] - peak_bar["low"]
    is_largest    = peak_range >= daily_ranges.quantile(0.85)

    vol_at_peak   = recent["volume"].iloc[peak_idx]
    vol_spike     = (vol_at_peak / vol_20) if vol_20 > 0 else 0

    wick          = _upper_wick_ratio(peak_bar["open"], peak_bar["high"], peak_bar["close"])
    price_fading  = latest_bar["close"] < peak_bar["open"]

    # Volume fading: last 2 bars have lower volume than the peak
    vol_fading    = (recent["volume"].iloc[-2:] < vol_at_peak).all()

    return {
        "peak_high":       round(peak_bar["high"], 2),
        "bars_since_peak": lookback - 1 - peak_idx,
        "vol_spike_ratio": round(vol_spike, 2),
        "upper_wick_ratio": round(wick, 2),
        "is_largest_range": bool(is_largest),
        "price_fading":    bool(price_fading),
        "vol_fading":      bool(vol_fading),
    }


def score_parabolic_short(symbol: str, df: pd.DataFrame) -> dict:
    """Score a stock as a parabolic short candidate."""
    close  = df["close"]
    high   = df["high"]
    low    = df["low"]
    open_  = df["open"]
    volume = df["volume"]

    r30d = n_day_return(close, 30)
    r60d = n_day_return(close, 60)
    blowoff = detect_blowoff(df)

    # Exhaustion score: count how many signals are present
    signals = [
        bool(pd.notna(r30d) and r30d >= 100),   # up 100%+ in 30 days
        blowoff.get("is_largest_range", False),
        blowoff.get("vol_spike_ratio", 0) >= 2,
        blowoff.get("upper_wick_ratio", 0) >= 0.4,
        blowoff.get("price_fading", False),
        blowoff.get("vol_fading", False),
    ]

    return {
        "symbol":          symbol,
        "close":           round(close.iloc[-1], 2),
        "r30d_pct":        round(r30d, 1) if pd.notna(r30d) else None,
        "r60d_pct":        round(r60d, 1) if pd.notna(r60d) else None,
        "adr_pct":         round(adr(high, low, 20), 2),
        "vol_ratio":       round(volume_ratio(volume, 20), 2),
        **blowoff,
        "setup":           "parabolic_short",
        "conviction":      sum(signals),
    }


def score_parabolic_long_bounce(symbol: str, df: pd.DataFrame) -> dict:
    """Score a stock as a parabolic long bounce candidate."""
    close  = df["close"]
    high   = df["high"]
    low    = df["low"]

    # Find peak in last 20 bars
    peak_close = close.iloc[-20:].max()
    current    = close.iloc[-1]
    drop_pct   = (peak_close - current) / peak_close * 100

    # First green day?
    last_bar_green = close.iloc[-1] > df["open"].iloc[-1]

    return {
        "symbol":          symbol,
        "close":           round(current, 2),
        "peak_close":      round(peak_close, 2),
        "drop_from_peak":  round(drop_pct, 1),
        "adr_pct":         round(adr(high, low, 20), 2),
        "last_bar_green":  last_bar_green,
        "setup":           "parabolic_long_bounce",
        "conviction":      sum([
            drop_pct >= 50,
            drop_pct <= 80,   # not completely destroyed
            last_bar_green,
        ]),
    }


def scan(
    symbols:         list,
    min_r30d_pct:    float = 100.0,
    min_drop_pct:    float = 50.0,
    min_turnover_cr: float = 1.0,
    include_shorts:  bool = True,
    include_bounces: bool = True,
) -> pd.DataFrame:
    """
    Run the Parabolic scan across a list of symbols.

    Args:
        symbols:         list of symbols to scan
        min_r30d_pct:    minimum 30-day return to qualify as parabolic (default 100%)
        min_drop_pct:    minimum % drop from peak to qualify as a bounce (default 50%)
        min_turnover_cr: minimum avg daily turnover (liquidity filter)
        include_shorts:  scan for parabolic short setups
        include_bounces: scan for post-parabolic long bounce setups

    Returns:
        DataFrame of candidates sorted by conviction, setup type, then return.
    """
    results = []
    total   = len(symbols)

    for i, symbol in enumerate(symbols, start=1):
        if i % 200 == 0:
            print(f"  Scanning parabolic [{i}/{total}]...")

        if not surveillance_filter(symbol):
            continue

        df = read_daily(symbol)
        if df.empty or len(df) < 80:
            continue

        close  = df["close"]
        high   = df["high"]
        low    = df["low"]
        volume = df["volume"]

        from indicators.volume import avg_turnover_cr
        if avg_turnover_cr(close, volume, 20) < min_turnover_cr:
            continue

        r30d = n_day_return(close, 30)

        # Parabolic short: up 100%+ recently
        if include_shorts and pd.notna(r30d) and r30d >= min_r30d_pct:
            scored = score_parabolic_short(symbol, df)
            if scored["conviction"] >= 2:
                results.append(scored)

        # Parabolic long bounce: crashed 50%+ from recent peak
        if include_bounces:
            peak = close.iloc[-20:].max()
            current = close.iloc[-1]
            drop = (peak - current) / peak * 100
            if drop >= min_drop_pct:
                scored = score_parabolic_long_bounce(symbol, df)
                if scored["conviction"] >= 2:
                    results.append(scored)

    if not results:
        return pd.DataFrame()

    df_out = pd.DataFrame(results)
    df_out = df_out.sort_values(
        ["conviction", "r30d_pct"], ascending=[False, False]
    ).reset_index(drop=True)

    return df_out
