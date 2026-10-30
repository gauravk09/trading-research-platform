"""
breakout.py — Setup 1: Breakout from Consolidation scanner

Prerequisites (all must pass):
  - Stock up 30–100%+ in last 1–3 months
  - Consolidating 2 weeks to 2 months with higher lows, tightening range
  - Price surfing the rising 10-day or 20-day MA
  - ADR > 4%
  - Above 50-day MA
  - In top RS percentile across universe

Entry trigger (not checked here — this is a PRE-SCAN):
  - Break above opening range high with volume ≥ 1.5× average

Reference: strategies/qullamaggie/SETUP_RULES.md — Setup 1
"""

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src"))

import pandas as pd
from storage import read_daily
from indicators.returns import month_return, n_day_return
from indicators.volatility import adr
from indicators.volume import avg_turnover_cr
from indicators.moving_averages import sma
from filters.momentum import breakout_return_filter, rs_rank_filter
from filters.trend import above_ma_filter, surfing_ma_filter, rising_ma_filter, young_trend_filter
from indicators.trend_stage import base_count, trend_age
from filters.volatility import min_adr_filter
from filters.consolidation import (
    tightening_range_filter,
    higher_lows_filter,
    price_near_high_filter,
    consolidation_duration_filter,
)
from filters.surveillance import surveillance_filter
from filters.liquidity import apply_min_turnover


def score_breakout_candidate(df: pd.DataFrame) -> dict:
    """
    Score a single stock against all breakout prerequisites.
    Returns a dict of metric values and filter results.
    Each filter key maps to True (passes) or False (fails).

    This function does NOT short-circuit — it evaluates every condition
    so you can see which ones pass/fail for analysis.
    """
    close  = df["close"]
    high   = df["high"]
    low    = df["low"]
    volume = df["volume"]

    r1mo = month_return(close, 1)
    r3mo = month_return(close, 3)
    r6mo = month_return(close, 6)
    stock_adr = adr(high, low, 20)
    turnover  = avg_turnover_cr(close, volume, 20)

    return {
        # --- Metrics (raw values for output) ---
        "close":           round(close.iloc[-1], 2),
        "trend_age_d":     trend_age(close),
        "base_count":      base_count(close, high, low),
        "r1mo_pct":        round(r1mo, 1) if pd.notna(r1mo) else None,
        "r3mo_pct":        round(r3mo, 1) if pd.notna(r3mo) else None,
        "r6mo_pct":        round(r6mo, 1) if pd.notna(r6mo) else None,
        "adr_pct":         round(stock_adr, 2) if pd.notna(stock_adr) else None,
        "ma10":            round(sma(close, 10), 2),
        "ma20":            round(sma(close, 20), 2),
        "ma50":            round(sma(close, 50), 2),
        "avg_turnover_cr": round(turnover, 1) if pd.notna(turnover) else None,

        # --- Filters (True = passes) ---
        "f_adr_gt4":         min_adr_filter(high, low, min_adr_pct=4.0),
        "f_above_ma50":      above_ma_filter(close, 50),
        "f_breakout_return": breakout_return_filter(close),
        "f_surfing_ma10":    surfing_ma_filter(close, 10),
        "f_surfing_ma20":    surfing_ma_filter(close, 20),
        "f_rising_ma20":     rising_ma_filter(close, 20),
        "f_tightening":      tightening_range_filter(high, low),
        "f_higher_lows":     higher_lows_filter(low),
        "f_near_high":       price_near_high_filter(close, high),
        "f_consol_duration": consolidation_duration_filter(close),
        "f_young_trend":     young_trend_filter(close, high, low),
    }


# All filters that must be True for a stock to appear in results
REQUIRED_FILTERS = [
    "f_adr_gt4",
    "f_above_ma50",
    "f_breakout_return",
    "f_near_high",
]

# Bonus filters — increase conviction but not strictly required
CONVICTION_FILTERS = [
    "f_surfing_ma10",
    "f_surfing_ma20",
    "f_rising_ma20",
    "f_tightening",
    "f_higher_lows",
    "f_consol_duration",
    "f_young_trend",
]


def scan(
    symbols:          list,
    rs_ranks:         pd.Series = None,
    residual_ranks:   pd.Series = None,
    min_turnover_cr:  float = 1.0,
    min_rs_pct:       float = 60.0,
    min_residual_pct: float = 80.0,
) -> pd.DataFrame:
    """
    Run the Breakout setup scan across a list of symbols.

    Args:
        symbols:          list of stock symbols to scan
        rs_ranks:         Series of RS ranks indexed by symbol (from relative_strength.py)
                          If None, RS rank filter is skipped.
        residual_ranks:   Series of residual (idiosyncratic) RS ranks indexed by symbol
                          (relative_strength.residual_rs_rank). If None, gate is skipped.
        min_turnover_cr:  minimum avg daily turnover in ₹ crore (liquidity filter)
        min_rs_pct:       minimum RS percentile to include (default 60 — top 40%)
        min_residual_pct: minimum residual-RS percentile — keeps only breakouts whose
                          strength is the stock's own, not its sector's (default 80).
                          Lenient on missing: a stock we could not score on residual is
                          NOT dropped on residual grounds; the other filters still decide.

    Returns:
        DataFrame of candidates sorted by conviction score (most filters passing first),
        then by 3-month return descending.
    """
    results = []
    total = len(symbols)

    for i, symbol in enumerate(symbols, start=1):
        if i % 200 == 0:
            print(f"  Scanning breakout [{i}/{total}]...")

        # Surveillance exclusion
        if not surveillance_filter(symbol):
            continue

        df = read_daily(symbol)
        if df.empty or len(df) < 130:
            continue

        scores = score_breakout_candidate(df)

        # Liquidity filter
        if scores["avg_turnover_cr"] is None or scores["avg_turnover_cr"] < min_turnover_cr:
            continue

        # Required filters — all must pass
        if not all(scores[f] for f in REQUIRED_FILTERS):
            continue

        # RS rank filter
        if rs_ranks is not None and not rs_rank_filter(symbol, rs_ranks, min_rs_pct):
            continue

        # Residual-RS gate — drops breakouts carried by their sector rather than their
        # own move. Lenient: only excludes when we have a score and it's below the cut.
        residual_rs = None
        if residual_ranks is not None:
            residual_rs = residual_ranks.get(symbol)
            if residual_rs is not None and residual_rs < min_residual_pct:
                continue

        # Conviction score = number of bonus filters passing
        conviction = sum(1 for f in CONVICTION_FILTERS if scores[f])

        scores["symbol"]      = symbol
        scores["residual_rs"] = round(residual_rs) if residual_rs is not None else None
        scores["conviction"]  = conviction
        results.append(scores)

    if not results:
        return pd.DataFrame()

    df_out = pd.DataFrame(results)
    df_out = df_out.sort_values(
        ["conviction", "r3mo_pct"], ascending=[False, False]
    ).reset_index(drop=True)

    return df_out
