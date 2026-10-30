"""
nse_bhavcopy.py — Download NSE equity bhavcopy (EOD data for all stocks)

NSE publishes a daily bhavcopy CSV with OHLCV + 52-week H/L for every listed stock.
This is free and does not require any API key.

File URL pattern:
  https://nsearchives.nseindia.com/content/cm/BhavCopy_NSE_CM_0_0_0_YYYYMMDD_F_0000.csv.zip
"""

import os
import io
import zipfile
import requests
import pandas as pd
from datetime import date, timedelta

RAW_DIR = os.path.join(os.path.dirname(__file__), "..", "data", "raw", "bhavcopy")
os.makedirs(RAW_DIR, exist_ok=True)

# NSE requires a browser-like User-Agent to avoid 403 errors
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.nseindia.com/"
}


def build_bhavcopy_url(for_date: date) -> str:
    """Build the download URL for a given date."""
    date_str = for_date.strftime("%Y%m%d")
    return (
        f"https://nsearchives.nseindia.com/content/cm/"
        f"BhavCopy_NSE_CM_0_0_0_{date_str}_F_0000.csv.zip"
    )


def download_bhavcopy(for_date: date = None) -> pd.DataFrame:
    """
    Download and return the bhavcopy for a given date.
    Defaults to today. Skips weekends automatically.

    Returns:
        DataFrame with columns: symbol, open, high, low, close, volume, 52wk_high, 52wk_low, etc.
    """
    if for_date is None:
        for_date = date.today()

    # Skip weekends
    if for_date.weekday() >= 5:
        print(f"{for_date} is a weekend — skipping.")
        return pd.DataFrame()

    save_path = os.path.join(RAW_DIR, f"bhavcopy_{for_date.isoformat()}.csv")

    if os.path.exists(save_path):
        print(f"Bhavcopy already exists for {for_date}: {save_path}")
        return pd.read_csv(save_path)

    url = build_bhavcopy_url(for_date)
    print(f"Downloading bhavcopy for {for_date}...")

    # NSE requires a session cookie — get one by hitting the homepage first
    session = requests.Session()
    session.get("https://www.nseindia.com", headers=HEADERS, timeout=10)

    response = session.get(url, headers=HEADERS, timeout=30)

    if response.status_code == 404:
        print(f"No bhavcopy found for {for_date} (likely a market holiday).")
        return pd.DataFrame()

    response.raise_for_status()

    # Unzip and read the CSV
    with zipfile.ZipFile(io.BytesIO(response.content)) as z:
        csv_filename = z.namelist()[0]
        with z.open(csv_filename) as f:
            df = pd.read_csv(f)

    # Standardize column names to lowercase with underscores
    df.columns = [c.strip().lower().replace(" ", "_") for c in df.columns]

    df.to_csv(save_path, index=False)
    print(f"Saved {len(df)} rows to {save_path}")
    return df


def download_last_n_days(n=5) -> None:
    """Download bhavcopy for the last N calendar days (skips weekends and holidays)."""
    today = date.today()
    for i in range(n):
        d = today - timedelta(days=i)
        download_bhavcopy(d)


if __name__ == "__main__":
    df = download_bhavcopy()
    if not df.empty:
        print(df.head())
        print(f"\nColumns: {list(df.columns)}")
