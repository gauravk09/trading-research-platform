"""episodic_pivot.py — Stockbee Episodic Pivot (EP) scan over the summary table.

EP = a neglected stock repriced violently on a catalyst: a large gap up on a
volume explosion. This is the EOD candidate finder; confirm the catalyst and
take the entry intraday. Catalyst tagging is attached separately, from the
cached NSE announcements feed (see attach_catalysts).
"""

import pandas as pd
from .scans import apply_base_filters


def episodic_pivot(df, min_gap=8.0, min_vol_ratio=3.0,
                   exclude_parabolic=True, **base):
    """Find today's episodic pivots.

    - gap up >= min_gap% at open vs prior close
    - today's volume >= min_vol_ratio x 20-day average
    - exclude names already up >100% in a month (no longer 'neglected')
    """
    out = apply_base_filters(df, **base)
    out = out[out["gap_pct"] >= min_gap]
    out = out[out["volume_ratio"] >= min_vol_ratio]
    if exclude_parabolic:
        out = out[out["r1mo_pct"].isna() | (out["r1mo_pct"] <= 100)]
    return out.sort_values(["gap_pct", "volume_ratio"],
                           ascending=False).reset_index(drop=True)


def attach_catalysts(scan_df, catalysts):
    """Left-join EP candidates with today's announcement catalysts.

    `catalysts` is a DataFrame with columns [symbol, category, subject], one row
    per symbol. Adds `catalyst` and `catalyst_subject` columns to the result.
    """
    out = scan_df.copy()
    if out.empty or catalysts is None or catalysts.empty:
        out["catalyst"] = None
        out["catalyst_subject"] = None
        return out
    cat = catalysts.rename(columns={"category": "catalyst",
                                     "subject": "catalyst_subject"})
    return out.merge(cat[["symbol", "catalyst", "catalyst_subject"]],
                     on="symbol", how="left")
