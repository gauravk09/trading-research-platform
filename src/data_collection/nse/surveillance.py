"""
nse_surveillance.py — Download NSE surveillance lists (ASM and GSM)

ASM = Additional Surveillance Measure
GSM = Graded Surveillance Measure

Stocks in these lists have trading restrictions:
  - Higher margin requirements
  - Trade-to-trade only (no intraday in some stages)
  - Price band restrictions

For Qullamaggie setups (which require intraday breakout entries), stocks in
higher ASM/GSM stages should be EXCLUDED from the scanning universe.

Use this at SCAN time, not at data collection time — we still want history
for these stocks (they may exit surveillance and become tradeable again).
"""

import glob
import os

from data_collection.paths import ROOT_DIR
import requests
import pandas as pd
from datetime import date

RAW_DIR = os.path.join(ROOT_DIR, "data", "raw", "surveillance")
os.makedirs(RAW_DIR, exist_ok=True)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.nseindia.com/"
}

ASM_URL = "https://www.nseindia.com/api/reportASM"
GSM_URL = "https://www.nseindia.com/api/reportGSM"


def _fetch_json(url: str) -> dict:
    """Helper: fetch JSON from an NSE API endpoint with session cookies."""
    session = requests.Session()
    session.get("https://www.nseindia.com", headers=HEADERS, timeout=10)
    response = session.get(url, headers=HEADERS, timeout=30)
    response.raise_for_status()
    return response.json()


def download_asm(for_date: date = None) -> pd.DataFrame:
    """Download today's ASM list. Cached daily."""
    if for_date is None:
        for_date = date.today()

    save_path = os.path.join(RAW_DIR, f"asm_{for_date.isoformat()}.csv")
    if os.path.exists(save_path):
        return pd.read_csv(save_path)

    print(f"Downloading ASM list for {for_date}...")
    data = _fetch_json(ASM_URL)

    # ASM has two sub-lists: longterm and shortterm
    longterm = pd.DataFrame(data.get("longterm", {}).get("data", []))
    shortterm = pd.DataFrame(data.get("shortterm", {}).get("data", []))
    if not longterm.empty:
        longterm["asm_type"] = "longterm"
    if not shortterm.empty:
        shortterm["asm_type"] = "shortterm"

    df = pd.concat([longterm, shortterm], ignore_index=True)
    if df.empty:
        print("  No ASM data returned.")
        return df

    df.columns = [c.strip().lower() for c in df.columns]
    df.to_csv(save_path, index=False)
    print(f"  Saved {len(df)} stocks under ASM")
    return df


def download_gsm(for_date: date = None) -> pd.DataFrame:
    """Download today's GSM list. Cached daily."""
    if for_date is None:
        for_date = date.today()

    save_path = os.path.join(RAW_DIR, f"gsm_{for_date.isoformat()}.csv")
    if os.path.exists(save_path):
        return pd.read_csv(save_path)

    print(f"Downloading GSM list for {for_date}...")
    data = _fetch_json(GSM_URL)
    rows = data.get("data", []) if isinstance(data, dict) else data
    df = pd.DataFrame(rows)

    if df.empty:
        print("  No GSM data returned.")
        return df

    df.columns = [c.strip().lower() for c in df.columns]
    df.to_csv(save_path, index=False)
    print(f"  Saved {len(df)} stocks under GSM")
    return df


def get_excluded_symbols() -> set:
    """
    Return the set of symbols to EXCLUDE from any scan today
    (i.e. stocks under ASM or GSM surveillance).
    """
    excluded = set()

    asm = download_asm()
    if not asm.empty:
        symbol_col = next((c for c in asm.columns if "symbol" in c), None)
        if symbol_col:
            excluded.update(asm[symbol_col].dropna().str.strip().str.upper())

    gsm = download_gsm()
    if not gsm.empty:
        symbol_col = next((c for c in gsm.columns if "symbol" in c), None)
        if symbol_col:
            excluded.update(gsm[symbol_col].dropna().str.strip().str.upper())

    print(f"Total stocks under surveillance (ASM+GSM): {len(excluded)}")
    return excluded


if __name__ == "__main__":
    excluded = get_excluded_symbols()
    print(f"\nSample excluded: {list(excluded)[:10]}")


def load_cached_excluded() -> set:
    """ASM/GSM symbols from the newest cached surveillance CSVs (disk only, no download)."""
    excluded = set()
    for prefix in ("asm", "gsm"):
        files = sorted(glob.glob(os.path.join(RAW_DIR, f"{prefix}_*.csv")))
        if not files:
            continue
        try:
            df = pd.read_csv(files[-1])
        except (OSError, pd.errors.EmptyDataError):
            continue
        col = next((c for c in df.columns if "symbol" in c.lower()), None)
        if col:
            excluded.update(df[col].dropna().astype(str).str.strip().str.upper())
    return excluded
