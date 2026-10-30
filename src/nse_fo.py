"""
nse_fo.py — Download and store NSE F&O (Futures & Options) stock list

F&O stocks are important because:
  - Shorting is only allowed in F&O stocks (via futures)
  - F&O stocks have leverage available
  - The list changes monthly (on the last Thursday = expiry day)

Source: NSE fo_mktlots.csv — published daily, contains all F&O stocks with lot sizes.

Storage: one file per month at data/raw/fo/fo_YYYY-MM.csv
This gives us a historical record of which stocks were in F&O each month,
useful for backtesting (you can only backtest shorts on stocks that were
in F&O at that point in time).
"""

import os
import io
import requests
import pandas as pd
from datetime import date, datetime, timedelta

RAW_DIR = os.path.join(os.path.dirname(__file__), "..", "data", "raw", "fo")
os.makedirs(RAW_DIR, exist_ok=True)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.nseindia.com/"
}

FO_MKTLOTS_URL = "https://nsearchives.nseindia.com/content/fo/fo_mktlots.csv"


def download_fo_list(for_month: str = None, force: bool = False,
                     max_age_hours: int = 24) -> pd.DataFrame:
    """
    Download the current F&O stock list from NSE.

    Args:
        for_month: "YYYY-MM" string. Defaults to current month.
                   Used only for the filename — NSE always serves the latest list.

    Returns:
        DataFrame with columns: symbol, lot_size, month
    """
    if for_month is None:
        today = date.today()
        for_month = today.strftime("%Y-%m")

    save_path = os.path.join(RAW_DIR, f"fo_{for_month}.csv")

    # NSE can revise the market-lot file during a contract month.  A monthly
    # cache silently misses those additions/removals, so the nightly update
    # refreshes files older than a day while retaining the last good copy if
    # NSE is temporarily unavailable.
    if os.path.exists(save_path) and not force:
        modified = datetime.fromtimestamp(os.path.getmtime(save_path))
        if datetime.now() - modified < timedelta(hours=max_age_hours):
            print(f"F&O list is current for {for_month}")
            return pd.read_csv(save_path)

    print(f"Downloading NSE F&O stock list for {for_month}...")

    session = requests.Session()
    try:
        session.get("https://www.nseindia.com", headers=HEADERS, timeout=10)
        response = session.get(FO_MKTLOTS_URL, headers=HEADERS, timeout=30)
        response.raise_for_status()
    except requests.RequestException:
        if os.path.exists(save_path):
            print(f"  WARNING: NSE refresh failed; using cached {save_path}")
            return pd.read_csv(save_path)
        raise

    # fo_mktlots.csv has a multi-row header — first few rows are metadata
    # Real data starts after the header rows; symbol is in the first column
    raw = response.content.decode("utf-8", errors="ignore")
    lines = [l for l in raw.splitlines() if l.strip()]

    # Find the header row (contains "SYMBOL" or "Symbol")
    header_idx = next(
        (i for i, l in enumerate(lines) if "SYMBOL" in l.upper()),
        0
    )

    df = pd.read_csv(
        io.StringIO("\n".join(lines[header_idx:])),
        header=0
    )

    df.columns = [c.strip().upper() for c in df.columns]

    # Keep only the symbol and current month lot size
    symbol_col = next((c for c in df.columns if "SYMBOL" in c), None)
    if symbol_col is None:
        print("  ERROR: Could not find SYMBOL column in F&O lot file.")
        return pd.DataFrame()

    # Lot size columns are named by month (e.g. "JAN 2026")
    lot_cols = [c for c in df.columns if c != symbol_col and c.strip()]

    result_rows = []
    for _, row in df.iterrows():
        symbol = str(row[symbol_col]).strip().upper()
        if not symbol or symbol in ("SYMBOL", "NaN", "nan", ""):
            continue

        # Use the first non-zero lot size column as current lot size
        lot_size = None
        for col in lot_cols:
            val = pd.to_numeric(str(row[col]).replace(",", "").strip(), errors="coerce")
            if pd.notna(val) and val > 0:
                lot_size = int(val)
                break

        if lot_size:
            result_rows.append({"symbol": symbol, "lot_size": lot_size, "month": for_month})

    result = pd.DataFrame(result_rows)
    result.to_csv(save_path, index=False)
    print(f"  Saved {len(result)} F&O stocks for {for_month} → {save_path}")
    return result


def get_fo_symbols(for_month: str = None) -> set:
    """
    Return the set of F&O stock symbols for a given month.
    Defaults to current month.
    """
    df = download_fo_list(for_month)
    if df.empty:
        return set()
    return set(df["symbol"].str.upper())


def get_fo_with_lotsize(for_month: str = None) -> dict:
    """
    Return a dict of {symbol: lot_size} for the given month.
    Useful for position sizing with futures.
    """
    df = download_fo_list(for_month)
    if df.empty:
        return {}
    return dict(zip(df["symbol"].str.upper(), df["lot_size"]))


if __name__ == "__main__":
    df = download_fo_list()
    print(f"\nTotal F&O stocks: {len(df)}")
    print(df.head(10))
