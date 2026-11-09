"""
nse_fii_dii.py — Download daily FII/DII buy/sell activity from NSE

FII (Foreign Institutional Investors) and DII (Domestic Institutional Investors)
data tells us if big money is flowing into or out of the market.

Qullamaggie setup context:
- Strong FII net buying = bullish regime → favor breakout longs
- FII net selling for multiple days = bearish regime → be cautious with longs

NSE publishes this data daily after market close.
"""

import os

from data_collection.paths import ROOT_DIR
import io
import requests
import pandas as pd
from datetime import date, timedelta

RAW_DIR = os.path.join(ROOT_DIR, "data", "raw", "fii_dii")
os.makedirs(RAW_DIR, exist_ok=True)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.nseindia.com/"
}

FII_DII_API_URL = "https://www.nseindia.com/api/fiidiiTradeReact"


def download_fii_dii(for_date: date = None) -> pd.DataFrame:
    """
    Download FII/DII activity for a given date.
    Defaults to today.

    Returns:
        DataFrame with columns: category, buy_value, sell_value, net_value
    """
    if for_date is None:
        for_date = date.today()

    if for_date.weekday() >= 5:
        print(f"{for_date} is a weekend — skipping.")
        return pd.DataFrame()

    save_path = os.path.join(RAW_DIR, f"fii_dii_{for_date.isoformat()}.csv")

    if os.path.exists(save_path):
        print(f"FII/DII data already exists for {for_date}")
        return pd.read_csv(save_path)

    print(f"Downloading FII/DII data for {for_date}...")

    session = requests.Session()
    session.get("https://www.nseindia.com", headers=HEADERS, timeout=10)

    response = session.get(FII_DII_API_URL, headers=HEADERS, timeout=30)
    response.raise_for_status()

    data = response.json()
    df = pd.DataFrame(data)
    df["date"] = for_date.isoformat()

    df.to_csv(save_path, index=False)
    print(f"Saved FII/DII data to {save_path}")
    return df


def get_recent_fii_sentiment(days=10) -> pd.DataFrame:
    """
    Download FII/DII data for the last N trading days and return combined DataFrame.
    Useful for checking if we are in a bullish or bearish institutional flow regime.
    """
    frames = []
    today = date.today()

    for i in range(days * 2):  # Go back further to account for weekends/holidays
        d = today - timedelta(days=i)
        df = download_fii_dii(d)
        if not df.empty:
            frames.append(df)
        if len(frames) >= days:
            break

    if not frames:
        return pd.DataFrame()

    combined = pd.concat(frames, ignore_index=True)
    return combined


if __name__ == "__main__":
    df = download_fii_dii()
    if not df.empty:
        print(df)
