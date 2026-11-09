"""breadth.py — market breadth (the Stockbee Market Monitor), display data only.

The market RISK regime that sets position sizing lives in risk/regime.py (the
validated HMM crash-risk dial). This module only computes the breadth counts
behind the Market Monitor tab; nothing here feeds sizing.
"""

import os

from data_collection.paths import ROOT_DIR

import pandas as pd

_PROCESSED = os.path.join(ROOT_DIR, "data", "processed")
CLOSE_MATRIX = os.path.join(_PROCESSED, "close_matrix.parquet")
VOLUME_MATRIX = os.path.join(_PROCESSED, "volume_matrix.parquet")


def compute_market_monitor(cm: pd.DataFrame, vm: pd.DataFrame = None) -> pd.DataFrame:
    """Stockbee Market Monitor over the full close-matrix history.

    Column guide, per https://stockbee.blogspot.com/p/mm.html:
      up4 / dn4        4%+ movers on volume > prior day
      ratio5, ratio10  sum(up4)/sum(dn4) over 5/10 days — >2 bullish, <0.5 bearish
      up25q / dn25q    25%+ movers over a quarter (65 bars) — his most important
      up25m / dn25m    25%+ movers over a month (21 bars)
      up50m / dn50m    50%+ movers over a month
      up13 / dn13      13%+ movers over 34 bars
      pct40ma          T2108 equivalent: % of stocks above 40 DMA; <20 marks bottoms
      up20_5d/dn20_5d  Bonde's 20%-in-5-days oscillator (TraderLion 2026 — now
                       his primary situational-awareness/timing tool, a role
                       distinct from the Market Monitor's slower 25%-quarter
                       "Primary Indicator" below): stocks ±20% in 5
                       sessions, close ≥ ₹30. High extremes → pullback within
                       5-10 days, UNLESS coming off a pct40ma<20 washout (then
                       expansion is expected). Display/awareness only.

    A stock only counts on days it actually traded (close present on both ends
    of each lookback), so suspended/delisted names drop out of the counts.
    NOTE: Bonde now calls the ratio columns "bloatware" and reads raw up/dn
    counts + the 20% study instead; ratios kept here by explicit user choice
    (2026-07-12) pending the regime-calibration backtest.
    """
    chg1 = cm.pct_change(fill_method=None)
    mm = pd.DataFrame(index=cm.index)

    # Bonde's 4% counts also require volume > prior day (v > v1). Fall back to
    # price-only when no volume matrix is available.
    if vm is not None:
        vol_up = vm.reindex_like(cm) > vm.reindex_like(cm).shift(1)
        mm["up4"] = ((chg1 > 0.04) & vol_up).sum(axis=1)
        mm["dn4"] = ((chg1 < -0.04) & vol_up).sum(axis=1)
    else:
        mm["up4"] = (chg1 > 0.04).sum(axis=1)
        mm["dn4"] = (chg1 < -0.04).sum(axis=1)

    up5, dn5 = mm["up4"].rolling(5).sum(), mm["dn4"].rolling(5).sum()
    up10, dn10 = mm["up4"].rolling(10).sum(), mm["dn4"].rolling(10).sum()
    mm["ratio5"] = (up5 / dn5.clip(lower=1)).round(2)
    mm["ratio10"] = (up10 / dn10.clip(lower=1)).round(2)

    for label, days, move in (("25q", 65, 0.25), ("25m", 21, 0.25),
                              ("50m", 21, 0.50), ("13", 34, 0.13)):
        chg = cm.pct_change(days, fill_method=None)
        mm[f"up{label}"] = (chg > move).sum(axis=1)
        mm[f"dn{label}"] = (chg < -move).sum(axis=1)

    # Denominator counts only stocks whose 40-DMA exists (same "both close and
    # MA present" convention as pct20ma) — otherwise recent listings sit in the
    # denominator but can never be above a MA they don't have yet.
    ma40 = cm.rolling(40).mean()
    active40 = cm.notna() & ma40.notna()
    mm["pct40ma"] = ((cm > ma40).sum(axis=1) / active40.sum(axis=1) * 100).round(1)

    chg5 = cm.pct_change(5, fill_method=None)
    priced = cm >= 30                       # Bonde's "$3 floor", rupee-fied
    mm["up20_5d"] = ((chg5 > 0.20) & priced).sum(axis=1)
    mm["dn20_5d"] = ((chg5 < -0.20) & priced).sum(axis=1)

    return mm
