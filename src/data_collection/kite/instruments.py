"""
instruments.py — Download and cache the Kite instrument master list

Kite provides a full dump of all tradeable instruments (NSE, BSE, etc.)
This file downloads it once per day and saves it locally as a CSV.

The instrument list is needed to map stock symbols (e.g. "RELIANCE")
to Kite's internal instrument_token (a number used in all API calls).
"""

import os

from data_collection.paths import ROOT_DIR
import glob
import pandas as pd
from datetime import date
from data_collection.kite.auth import get_kite_client

RAW_DIR = os.path.join(ROOT_DIR, "data", "raw")


def download_instruments(exchange="NSE"):
    """
    Download the full instrument list for the given exchange.
    Saves to data/raw/instruments_NSE_YYYY-MM-DD.csv
    Returns a DataFrame.
    """
    today = date.today().isoformat()
    save_path = os.path.join(RAW_DIR, f"instruments_{exchange}_{today}.csv")

    if os.path.exists(save_path):
        print(f"Instruments already downloaded for today: {save_path}")
        return pd.read_csv(save_path)

    print(f"Downloading {exchange} instrument list from Kite...")
    kite = get_kite_client()
    instruments = kite.instruments(exchange=exchange)

    df = pd.DataFrame(instruments)
    df.to_csv(save_path, index=False)
    print(f"Saved {len(df)} instruments to {save_path}")

    for old in glob.glob(os.path.join(RAW_DIR, f"instruments_{exchange}_*.csv")):
        if old != save_path:
            os.remove(old)
    return df


def get_instrument_token(symbol, exchange="NSE"):
    """
    Return the instrument_token for a given stock symbol.
    Example: get_instrument_token("RELIANCE") → 738561
    """
    df = download_instruments(exchange)
    match = df[df["tradingsymbol"] == symbol]

    if match.empty:
        raise ValueError(f"Symbol '{symbol}' not found in {exchange} instruments.")

    return int(match.iloc[0]["instrument_token"])


def get_equity_instruments(exchange="NSE"):
    """
    Return only equity (EQ) instruments — filters out futures, options, etc.
    """
    df = download_instruments(exchange)
    equities = df[df["instrument_type"] == "EQ"].copy()
    print(f"Found {len(equities)} equity instruments on {exchange}")
    return equities


if __name__ == "__main__":
    df = get_equity_instruments()
    print(df[["tradingsymbol", "name", "instrument_token"]].head(10))
