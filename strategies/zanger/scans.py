"""scans.py — Dan Zanger breakout scan over the universe summary table.

Zanger buys the strongest leaders breaking out of a well-formed base to new highs
on a volume explosion, and dumps anything that doesn't move. This is the EOD
candidate finder for his core setup; confirm the base and take the entry intraday.
Pure and fast — no file or network I/O.
"""

import pandas as pd


def apply_base_filters(df, min_turnover_cr=1.0, min_price=0.0,
                       fo_only=False, excluded=None):
    """Liquidity, price, F&O and surveillance filters shared by every scan."""
    out = df[df["avg_turnover_cr"] >= min_turnover_cr]
    out = out[out["close"] >= min_price]
    if fo_only:
        out = out[out["is_fo"]]
    if excluded:
        out = out[~out["symbol"].isin(excluded)]
    return out.copy()


def breakout(df, max_from_high=5.0, min_vol_ratio=1.5, min_change=3.0,
             min_rs=70.0, require_close_strong=True, **base):
    """Zanger breakout: a leader breaking out near its highs on a volume explosion.

    - near the 52-week high:  pct_from_52w_high >= -max_from_high (not extended;
      Zanger never pays more than ~5% above the breakout point)
    - breakout-day up move:   chg_pct >= min_change
    - volume explosion:       volume_ratio >= min_vol_ratio (vs the 20-day average)
    - strong close:           range_pos >= 0.5 — closed in the upper half of the day
                              (require_close_strong)
    - leading stock:          rs_rank >= min_rs

    Ranked by RS rank, then volume ratio — strongest leaders on the biggest volume
    first.
    """
    out = apply_base_filters(df, **base)
    out = out[out["pct_from_52w_high"] >= -max_from_high]
    out = out[out["chg_pct"] >= min_change]
    out = out[out["volume_ratio"] >= min_vol_ratio]
    out = out[out["rs_rank"] >= min_rs]
    if require_close_strong:
        out = out[out["range_pos"] >= 0.5]
    return out.sort_values(["rs_rank", "volume_ratio"],
                           ascending=False).reset_index(drop=True)
