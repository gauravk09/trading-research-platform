"""
build_sector_map.py — symbol → industry mapping for the NSE universe

Two sources, merged:
  1. niftyindices constituent CSVs (total market + microcap250) — clean
     official industry labels, ~1000 symbols.
  2. smIndustry from the announcements archive — covers everything else that
     ever filed an announcement (most of the remaining universe).

Output: data/processed/sector_map.csv with columns symbol, industry, source.
Re-run any time; it rebuilds from scratch.
"""

import os

from data_collection.paths import ROOT_DIR
import pandas as pd

import data_collection.nse.announcements_store as announcements_store
from data_collection.nse.universe import download_index

OUT_PATH = os.path.join(ROOT_DIR, "data", "processed", "sector_map.csv")


def from_index_lists() -> pd.DataFrame:
    frames = []
    for index_name in ["nifty_total_market", "nifty_microcap250"]:
        try:
            df = download_index(index_name)
            frames.append(df[["symbol", "industry"]])
        except Exception as e:
            print(f"  {index_name}: download failed ({type(e).__name__}) — "
                  "announcements smIndustry will cover the gap")
    if not frames:
        return pd.DataFrame(columns=["symbol", "industry", "source"])
    combined = pd.concat(frames).drop_duplicates(subset="symbol")
    combined["source"] = "niftyindices"
    return combined


def from_announcements() -> pd.DataFrame:
    df = announcements_store.load_range()
    if df.empty or "smindustry" not in df.columns:
        return pd.DataFrame(columns=["symbol", "industry", "source"])
    all_rows = df[["symbol", "smindustry"]].dropna()
    # a symbol's industry = its most frequent label across all filings
    industry = all_rows.groupby("symbol")["smindustry"].agg(lambda s: s.mode().iloc[0])
    out = industry.reset_index().rename(columns={"smindustry": "industry"})
    out["source"] = "announcements"
    return out


def main():
    index_map = from_index_lists()
    ann_map = from_announcements()

    gaps = ann_map[~ann_map["symbol"].isin(index_map["symbol"])]
    sector_map = pd.concat([index_map, gaps]).sort_values("symbol").reset_index(drop=True)
    sector_map["symbol"] = sector_map["symbol"].str.upper()

    sector_map.to_csv(OUT_PATH, index=False)
    print(f"Sector map: {len(sector_map)} symbols "
          f"({len(index_map)} from index lists, {len(gaps)} from announcements)")
    print(f"→ {OUT_PATH}")


if __name__ == "__main__":
    main()
