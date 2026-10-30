"""
nse_bulk_deals.py — Download NSE bulk and block deals

Bulk deal:  A single transaction > 0.5% of a company's total shares
Block deal: Minimum 5 lakh shares or ₹5 crore (traded in special 35-min morning window)

Why this matters for Qullamaggie setups:
- Institutions accumulating via block deals before a breakout = strong signal
- Large bulk deals on EP (Episodic Pivot) days confirm institutional interest
"""

import io
import os
import requests
import pandas as pd
from datetime import date, timedelta

RAW_DIR = os.path.join(os.path.dirname(__file__), "..", "data", "raw", "bulk_deals")
os.makedirs(RAW_DIR, exist_ok=True)

PROCESSED = os.path.join(os.path.dirname(__file__), "..", "data", "processed")
DEALS_STORE = os.path.join(PROCESSED, "bulk_block_deals.parquet")

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.nseindia.com/"
}

BULK_DEALS_URL = "https://www.nseindia.com/api/snapshot-capital-market-largedeal"

# Daily bhavcopy-style archive files (one trading day each, more reliable and
# cleaner than the live JSON snapshot). These are what the rolling store reads.
ARCHIVE_URLS = {
    "bulk":  "https://nsearchives.nseindia.com/content/equities/bulk.csv",
    "block": "https://nsearchives.nseindia.com/content/equities/block.csv",
}


def download_bulk_deals(for_date: date = None) -> pd.DataFrame:
    """
    Download bulk and block deals for a given date.
    Defaults to today.

    Returns:
        DataFrame with deal details: symbol, client, buy/sell, quantity, price
    """
    if for_date is None:
        for_date = date.today()

    if for_date.weekday() >= 5:
        print(f"{for_date} is a weekend — skipping.")
        return pd.DataFrame()

    save_path = os.path.join(RAW_DIR, f"bulk_deals_{for_date.isoformat()}.csv")

    if os.path.exists(save_path):
        print(f"Bulk deals already downloaded for {for_date}")
        return pd.read_csv(save_path)

    print(f"Downloading bulk/block deals for {for_date}...")

    session = requests.Session()
    session.get("https://www.nseindia.com", headers=HEADERS, timeout=10)

    response = session.get(BULK_DEALS_URL, headers=HEADERS, timeout=30)
    response.raise_for_status()

    data = response.json()

    # NSE returns separate keys for bulk and block deals
    bulk = pd.DataFrame(data.get("data", {}).get("bulk", []))
    block = pd.DataFrame(data.get("data", {}).get("block", []))

    if not bulk.empty:
        bulk["deal_type"] = "bulk"
    if not block.empty:
        block["deal_type"] = "block"

    df = pd.concat([bulk, block], ignore_index=True)

    if df.empty:
        print(f"No bulk/block deals found for {for_date}")
        return df

    df["date"] = for_date.isoformat()
    df.to_csv(save_path, index=False)
    print(f"Saved {len(df)} deals to {save_path}")
    return df


def get_deals_for_symbol(symbol: str, days=30) -> pd.DataFrame:
    """
    Return all bulk/block deals for a specific stock over the last N days.
    Useful for checking if institutions were accumulating before a breakout.
    """
    frames = []
    today = date.today()

    for i in range(days):
        d = today - timedelta(days=i)
        df = download_bulk_deals(d)
        if not df.empty and "symbol" in df.columns:
            match = df[df["symbol"].str.upper() == symbol.upper()]
            if not match.empty:
                frames.append(match)

    if not frames:
        print(f"No bulk/block deals found for {symbol} in last {days} days.")
        return pd.DataFrame()

    return pd.concat(frames, ignore_index=True)


def _fetch_archive(session: requests.Session, kind: str) -> pd.DataFrame:
    """Read one daily archive CSV (bulk or block) into a normalized frame.

    Columns are standardized to: date, symbol, security_name, client_name,
    buy_sell, quantity, price, deal_type. `date` is the deal/disclosure day —
    bulk/block deals are disclosed same-day after close, so trade date and public
    disclosure date coincide and there is no look-ahead to guard against here."""
    r = session.get(ARCHIVE_URLS[kind], headers=HEADERS, timeout=30)
    r.raise_for_status()
    df = pd.read_csv(io.BytesIO(r.content))
    df.columns = [c.strip() for c in df.columns]
    rename = {
        "Date": "date", "Symbol": "symbol", "Security Name": "security_name",
        "Client Name": "client_name", "Buy/Sell": "buy_sell",
        "Quantity Traded": "quantity",
        "Trade Price / Wght. Avg. Price": "price",
    }
    df = df.rename(columns=rename)
    df["date"] = pd.to_datetime(df["date"], format="%d-%b-%Y", errors="coerce").dt.date.astype(str)
    df["deal_type"] = kind
    keep = [c for c in ["date", "symbol", "security_name", "client_name",
                        "buy_sell", "quantity", "price", "deal_type"] if c in df.columns]
    return df[keep]


def load_store() -> pd.DataFrame:
    """The accumulated bulk+block deal history. Empty frame if nothing stored."""
    return pd.read_parquet(DEALS_STORE) if os.path.exists(DEALS_STORE) else pd.DataFrame()


def update() -> None:
    """Append today's bulk and block deals to the rolling parquet history.

    The daily archive CSV holds only the latest trading day, so this accumulates
    history going forward — run it nightly. Idempotent: rows are de-duplicated on
    the full deal tuple, so re-running the same day (or a day already stored)
    changes nothing. NSE's dated historical bulk/block endpoint is edge-blocked
    (503) from server IPs, so past dates before this store began can't be
    backfilled from a free source — history builds from first run onward."""
    session = requests.Session()
    session.get("https://www.nseindia.com", headers=HEADERS, timeout=10)

    frames = []
    for kind in ARCHIVE_URLS:
        try:
            frames.append(_fetch_archive(session, kind))
        except Exception as e:                       # noqa: BLE001 — log & continue
            print(f"  {kind} deals: skipped ({type(e).__name__})")
    fresh = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
    if fresh.empty:
        print("  bulk/block deals: nothing fetched")
        return

    existing = load_store()
    combined = pd.concat([existing, fresh], ignore_index=True) if not existing.empty else fresh
    combined = combined.drop_duplicates().sort_values(["date", "symbol"]).reset_index(drop=True)
    os.makedirs(PROCESSED, exist_ok=True)
    combined.to_parquet(DEALS_STORE, compression="snappy")
    print(f"  bulk_block_deals {combined.shape}  "
          f"{combined['date'].min()} → {combined['date'].max()}  (+{len(fresh)} today)")


if __name__ == "__main__":
    update()
