"""
episodic_pivot.py — Setup 2: Episodic Pivot (EP) scanner

EP is triggered by a major catalyst causing a gap up of ≥ 10%.
This scanner runs EOD to flag TODAY's EP candidates — stocks that
gapped up ≥10% with strong volume and a qualifying announcement.

Prerequisites (all must pass):
  - Gap up ≥ 10% at open vs prior close
  - Volume ≥ 2× 20-day average (first 30 min or full day)
  - Qualifying catalyst in NSE announcements (results, guidance, order_win, regulatory)
  - Stock was "neglected" before — ideally not in a parabolic run already
  - ADR > 4% (general rule for all setups)

Entry trigger (intraday — use intraday.py on the day):
  - Break above first 5-min or 15-min candle high

Reference: strategies/qullamaggie/SETUP_RULES.md — Setup 2
"""

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src"))

import pandas as pd
from data_collection.storage import read_daily
from indicators.volatility import adr
from indicators.volume import avg_volume, volume_ratio, avg_turnover_cr
from indicators.returns import n_day_return
from filters.volatility import min_adr_filter
from filters.surveillance import surveillance_filter
from data_collection.nse.bhavcopy import download_bhavcopy
from data_collection.nse.announcements import get_announcements_for_universe

# Catalysts that qualify an EP — in order of strength
EP_CATALYST_CATEGORIES = [
    "results",
    "guidance",
    "order_win",
    "regulatory",
    "acquisition",
]


def get_todays_gapups(bhavcopy_df: pd.DataFrame, min_gap_pct: float = 10.0) -> pd.DataFrame:
    """
    Find stocks that gapped up >= min_gap_pct% today using bhavcopy.

    We approximate gap% as: (today_open - prev_close) / prev_close * 100
    Since bhavcopy only has today's data, we use our stored Parquet for prev_close.

    Args:
        bhavcopy_df:   Today's NSE bhavcopy DataFrame
        min_gap_pct:   Minimum gap-up percentage (default 10%)

    Returns:
        DataFrame with: symbol, prev_close, today_open, gap_pct, today_volume, volume_ratio
    """
    if bhavcopy_df.empty:
        return pd.DataFrame()

    df = bhavcopy_df.copy()
    df.columns = [c.strip().lower() for c in df.columns]

    symbol_col = next((c for c in df.columns if c in ("tckrsymb", "symbol")), None)
    open_col   = next((c for c in df.columns if c in ("openpric", "open")), None)
    vol_col    = next((c for c in df.columns if "tottrdqty" in c or c == "volume"), None)

    if not all([symbol_col, open_col]):
        print("WARN: Could not find required columns in bhavcopy.")
        return pd.DataFrame()

    gapups = []
    for _, row in df.iterrows():
        symbol     = str(row[symbol_col]).strip().upper()
        today_open = pd.to_numeric(row[open_col], errors="coerce")

        if pd.isna(today_open):
            continue

        hist = read_daily(symbol, columns=["date", "close", "volume"])
        if hist.empty or len(hist) < 22:
            continue

        prev_close = hist["close"].iloc[-1]
        gap_pct    = (today_open - prev_close) / prev_close * 100

        if gap_pct < min_gap_pct:
            continue

        vol_20d    = avg_volume(hist["volume"], 20)
        today_vol  = pd.to_numeric(row.get(vol_col, 0), errors="coerce") if vol_col else None
        vol_ratio  = (today_vol / vol_20d) if (today_vol and vol_20d and vol_20d > 0) else None

        gapups.append({
            "symbol":       symbol,
            "prev_close":   round(prev_close, 2),
            "today_open":   round(today_open, 2),
            "gap_pct":      round(gap_pct, 1),
            "vol_20d_avg":  int(vol_20d) if pd.notna(vol_20d) else None,
            "today_volume": int(today_vol) if today_vol else None,
            "vol_ratio":    round(vol_ratio, 2) if vol_ratio else None,
        })

    return pd.DataFrame(gapups).sort_values("gap_pct", ascending=False).reset_index(drop=True)


def match_catalysts(gapup_df: pd.DataFrame, announcement_df: pd.DataFrame) -> pd.DataFrame:
    """
    Join gap-up stocks with today's NSE announcements.
    Tags each stock with its catalyst category (if found).

    Args:
        gapup_df:        Output of get_todays_gapups()
        announcement_df: Output of nse_announcements.get_announcements_for_universe()
    """
    if gapup_df.empty:
        return gapup_df

    if announcement_df.empty or "symbol" not in announcement_df.columns:
        gapup_df["catalyst"]  = None
        gapup_df["catalyst_subject"] = None
        return gapup_df

    # Keep only EP-qualifying announcement categories
    ep_ann = announcement_df[
        announcement_df.get("category", pd.Series()).isin(EP_CATALYST_CATEGORIES)
    ][["symbol", "category", "subject"]].drop_duplicates(subset="symbol")

    ep_ann = ep_ann.rename(columns={"category": "catalyst", "subject": "catalyst_subject"})

    merged = gapup_df.merge(ep_ann, on="symbol", how="left")
    return merged


def score_ep_candidate(symbol: str, row: dict) -> dict:
    """
    Score an EP candidate against all prerequisites.
    Returns the row dict enriched with filter results.
    """
    df = read_daily(symbol)
    if df.empty or len(df) < 25:
        row["f_adr_gt4"]      = False
        row["f_vol_2x"]       = False
        row["f_has_catalyst"] = False
        row["f_not_parabolic"] = False
        row["conviction"]     = 0
        return row

    close  = df["close"]
    high   = df["high"]
    low    = df["low"]

    r30d = n_day_return(close, 30)

    row["f_adr_gt4"]       = min_adr_filter(high, low, min_adr_pct=4.0)
    row["f_vol_2x"]        = (row.get("vol_ratio") or 0) >= 2.0
    row["f_has_catalyst"]  = row.get("catalyst") in EP_CATALYST_CATEGORIES
    row["f_not_parabolic"] = pd.isna(r30d) or r30d <= 100  # not already up 100%+ in 30 days
    row["r30d_pct"]        = round(r30d, 1) if pd.notna(r30d) else None
    row["adr_pct"]         = round(adr(high, low, 20), 2)
    row["conviction"]      = sum([
        row["f_adr_gt4"],
        row["f_vol_2x"],
        row["f_has_catalyst"],
        row["f_not_parabolic"],
    ])
    return row


def scan(
    symbols:         list,
    min_gap_pct:     float = 10.0,
    min_vol_ratio:   float = 2.0,
    min_turnover_cr: float = 1.0,
) -> pd.DataFrame:
    """
    Run the EP scan for today. Downloads bhavcopy + announcements automatically.

    Args:
        symbols:         list of symbols in universe
        min_gap_pct:     minimum gap-up % to qualify (default 10%)
        min_vol_ratio:   minimum volume ratio (default 2×)
        min_turnover_cr: minimum avg daily turnover (liquidity filter)

    Returns:
        DataFrame of EP candidates sorted by conviction score then gap_pct.
    """
    print("  Downloading bhavcopy for gap detection...")
    bhav = download_bhavcopy()

    print("  Finding gap-ups >= {min_gap_pct}%...")
    gapups = get_todays_gapups(bhav, min_gap_pct)

    if gapups.empty:
        print("  No gap-ups found today.")
        return pd.DataFrame()

    print(f"  Found {len(gapups)} gap-ups. Matching catalysts...")
    ann_df = get_announcements_for_universe(symbols)
    gapups = match_catalysts(gapups, ann_df)

    results = []
    for _, row in gapups.iterrows():
        symbol = row["symbol"]

        if not surveillance_filter(symbol):
            continue

        hist = read_daily(symbol, columns=["close", "volume"])
        if hist.empty:
            continue
        if avg_turnover_cr(hist["close"], hist["volume"]) < min_turnover_cr:
            continue

        scored = score_ep_candidate(symbol, row.to_dict())
        results.append(scored)

    if not results:
        return pd.DataFrame()

    df_out = pd.DataFrame(results)
    df_out = df_out.sort_values(
        ["conviction", "gap_pct"], ascending=[False, False]
    ).reset_index(drop=True)

    return df_out
