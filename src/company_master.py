"""
company_master.py — nightly refresh of shares outstanding in company_master.parquet

The master (one row per symbol: name, industry taxonomy, face value,
shares_out, about) feeds mcap_cr in the universe summary. NSE's per-symbol
quote API is bot-blocked for scripts, but BSE publishes full market cap for
every active scrip in ONE open API call, and NSE's EQUITY_L.csv maps our
symbols to ISINs. So: shares_out = BSE full mcap / our latest NSE close
(BSE and NSE closes differ <1% — irrelevant at mcap granularity).

Covers ~95% of the universe; NSE-only listings keep their previous
shares_out (original 2026-07-15 NSE quote-API build). Identity fields
(name, sector taxonomy, about) are preserved as-is for existing rows.
Symbols in the summary that are on NSE's equity list but missing from the
master (new IPOs, re-listings after a rename/merger) get an identity row
from EQUITY_L, and listed rows without a sector are then classified from
their screener.in page (bounded per run). Symbols gone from NSE entirely
(delisted/renamed away) are reported for manual backfill.

Run automatically from eod_update.py, or manually:
    python src/company_master.py              # normal refresh
    python src/company_master.py GUJENERGY    # force re-classify symbols
"""

import html as html_lib
import io
import os
import random
import re
import sys
import time
from datetime import date

import pandas as pd
import requests

sys.path.insert(0, os.path.dirname(__file__))
from nse_announcements import HEADERS

PROCESSED_DIR = os.path.join(os.path.dirname(__file__), "..", "data", "processed")
MASTER_PATH = os.path.join(PROCESSED_DIR, "company_master.parquet")
SUMMARY_PATH = os.path.join(PROCESSED_DIR, "universe_summary.parquet")
SHARES_HISTORY_PATH = os.path.join(PROCESSED_DIR, "shares_out_history.parquet")

EQUITY_L_URL = "https://nsearchives.nseindia.com/content/equities/EQUITY_L.csv"
BSE_URL = ("https://api.bseindia.com/BseIndiaAPI/api/ListofScripData/w"
           "?Group=&Scripcode=&industry=&segment=Equity&status=Active")
BSE_HEADERS = {"User-Agent": HEADERS["User-Agent"],
               "Referer": "https://www.bseindia.com/"}
SCREENER_HEADERS = {"User-Agent": HEADERS["User-Agent"],
                    "Accept-Language": "en-US,en;q=0.9"}

# screener.in breadcrumb <a title="..."> → our column name (NSE/AMFI taxonomy)
TAXONOMY_LEVELS = {
    "Broad Sector": "macro_sector",
    "Sector": "sector",
    "Broad Industry": "broad_industry",
    "Industry": "industry",
}


def _nse_symbol_isin():
    """symbol → isin/name/face_value from NSE's equity master list."""
    r = requests.get(EQUITY_L_URL, headers=HEADERS, timeout=30)
    r.raise_for_status()
    df = pd.read_csv(io.StringIO(r.text))
    df.columns = [c.strip() for c in df.columns]
    return df.rename(columns={"SYMBOL": "symbol", "ISIN NUMBER": "isin",
                              "NAME OF COMPANY": "name",
                              "FACE VALUE": "face_value"})[
        ["symbol", "isin", "name", "face_value"]]


def _bse_mcap_by_isin():
    """isin → full market cap in ₹ Cr, whole exchange in one call."""
    r = requests.get(BSE_URL, headers=BSE_HEADERS, timeout=60)
    r.raise_for_status()
    df = pd.DataFrame(r.json())
    df["mcap_cr"] = pd.to_numeric(df["Mktcap"], errors="coerce")
    df = df.dropna(subset=["mcap_cr"]).drop_duplicates("ISIN_NUMBER")
    return df.set_index("ISIN_NUMBER")["mcap_cr"]


def _clean_text(fragment: str) -> str:
    fragment = re.sub(r"<[^>]+>", " ", fragment)
    return re.sub(r"\s+", " ", html_lib.unescape(fragment)).strip()


def _fetch_taxonomy(symbol: str) -> dict:
    """name + 4-level classification from screener.in; None if no page (404)."""
    r = requests.get(f"https://www.screener.in/company/{symbol}/",
                     headers=SCREENER_HEADERS, timeout=30)
    if r.status_code == 404:
        return None
    r.raise_for_status()
    row = {}
    match = re.search(r"<h1[^>]*>(.*?)</h1>", r.text, re.S)
    if match:
        row["name"] = _clean_text(match.group(1))
    for title, column in TAXONOMY_LEVELS.items():
        match = re.search(rf'title="{title}"\s*>(.*?)</a>', r.text, re.S)
        row[column] = _clean_text(match.group(1)) if match else None
    return row


def _fill_missing_taxonomy(m, listed_symbols, force=(), limit=10):
    """Classify currently-listed master rows that have no sector — new IPOs
    and re-listings after a rename/merger. Bounded per run; delisted symbols
    are skipped (their screener pages are gone — backfill those by hand)."""
    missing = [s for s in m.index[m["sector"].isna()]
               if s in listed_symbols and s not in force]
    random.shuffle(missing)  # a persistent 404 can't hog the nightly budget
    targets = (list(force) + missing)[:max(limit, len(force))]
    for symbol in targets:
        try:
            row = _fetch_taxonomy(symbol)
        except Exception as exc:
            print(f"Company master: screener fetch stopped at {symbol}: {exc}")
            break
        if row:
            for column, value in row.items():
                m.loc[symbol, column] = value
            print(f"Company master: classified {symbol} → {row.get('industry')}")
        else:
            print(f"Company master: {symbol} has no screener page — "
                  f"left unclassified")
        time.sleep(2 + random.random())


def refresh(force_taxonomy=()):
    """Update shares_out for every BSE-matched symbol; returns count updated."""
    summary = pd.read_parquet(SUMMARY_PATH, columns=["symbol", "close"])
    df = summary.merge(_nse_symbol_isin(), on="symbol", how="left")
    df["shares_out"] = df["isin"].map(_bse_mcap_by_isin()) * 1e7 / df["close"]
    got = df.dropna(subset=["shares_out"]).set_index("symbol")
    if got.empty:
        print("Company master: no BSE mcap matches — kept existing file")
        return 0
    got["fetched_at"] = str(date.today())

    master = (pd.read_parquet(MASTER_PATH) if os.path.exists(MASTER_PATH)
              else pd.DataFrame(columns=["symbol", "fetched_at", "name",
                                         "face_value", "shares_out"]
                                        + list(TAXONOMY_LEVELS.values())))
    m = master.set_index("symbol")
    # original build stored shares_out as int64; derived values are float
    m["shares_out"] = m["shares_out"].astype("float64")
    m.update(got[["shares_out", "fetched_at"]])
    new = got.index.difference(m.index)
    m = pd.concat([m, got.loc[new, ["fetched_at", "name", "face_value",
                                    "shares_out"]]])

    # On NSE's equity list but never BSE-matched (NSE-only IPOs, re-listed
    # renames): add an identity row so the symbol doesn't stay absent forever.
    listed = df.dropna(subset=["isin"]).set_index("symbol")
    stubs = listed.index.difference(m.index)
    if len(stubs):
        m = pd.concat([m, listed.loc[stubs, ["name", "face_value"]]
                       .assign(fetched_at=str(date.today()))])

    _fill_missing_taxonomy(m, set(listed.index), force=force_taxonomy)

    gone = summary.loc[~summary["symbol"].isin(m.index), "symbol"]
    if len(gone):
        print(f"Company master: {len(gone)} stored symbols no longer on NSE "
              f"and absent from master — backfill by hand if their history "
              f"matters: {', '.join(gone)}")

    m.sort_index().reset_index().to_parquet(MASTER_PATH, compression="snappy",
                                            index=False)

    # Point-in-time shares_out archive — today's mcap÷(1+r) approximation in
    # the sector monitor assumes constant shares; this snapshot makes true
    # historical mcap reconstructable from here on (it can't be backfilled).
    snap = got.reset_index()[["symbol", "shares_out"]]
    snap.insert(0, "date", str(date.today()))
    if os.path.exists(SHARES_HISTORY_PATH):
        hist = pd.read_parquet(SHARES_HISTORY_PATH)
        # re-runs on the same day replace, not duplicate
        snap = pd.concat([hist[hist["date"] != snap["date"].iloc[0]], snap])
    snap.to_parquet(SHARES_HISTORY_PATH, compression="snappy", index=False)

    print(f"Company master: shares_out refreshed for {len(got)}/{len(summary)} "
          f"symbols ({len(new)} new listings added, "
          f"{len(summary) - len(got)} unmatched keep previous values)")
    return len(got)


if __name__ == "__main__":
    refresh(force_taxonomy=[s.upper() for s in sys.argv[1:]])
