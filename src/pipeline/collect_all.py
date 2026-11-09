"""
collect_data.py — Master script: run this every day after market close (3:30 PM IST)

What it does (in order):
  1. Download Nifty 500 constituent list (our universe)
  2. Download NSE bhavcopy (EOD data for all stocks)
  3. Download FII/DII activity (market regime check)
  4. Download bulk/block deals (institutional accumulation signals)
  5. Download NSE corporate announcements (EP catalysts)
  6. Fetch daily OHLCV from Kite for the full universe

Run:
  PYTHONPATH=src python -m pipeline.collect_all
"""

import os

# Allow imports from the src/ directory

from data_collection.nse.universe import get_all_nse_eq_symbols
from data_collection.nse.bhavcopy import download_bhavcopy
from data_collection.nse.fii_dii import download_fii_dii
from data_collection.nse.bulk_deals import download_bulk_deals
from data_collection.nse.announcements import get_announcements_for_universe
from data_collection.nse.fo import download_fo_list
from data_collection.kite.updater import run as update_prices
from preprocessing.precompute import run as precompute


def run():
    print("=" * 60)
    print("DAILY DATA COLLECTION")
    print("=" * 60)

    print("\n[1/6] Building stock universe (all NSE EQ-series stocks)...")
    symbols = get_all_nse_eq_symbols()
    print(f"      Universe size: {len(symbols)} stocks")
    print("      (Liquidity / ASM / GSM filters are applied at SCAN time, not here)")

    print("\n[2/6] Downloading NSE Bhavcopy (EOD data)...")
    download_bhavcopy()

    print("\n[3/6] Downloading FII/DII activity...")
    download_fii_dii()

    print("\n[4/6] Downloading Bulk/Block deals...")
    download_bulk_deals()

    print("\n[5/7] Downloading NSE F&O stock list (monthly snapshot)...")
    download_fo_list()

    print("\n[6/7] Downloading NSE corporate announcements...")
    get_announcements_for_universe(symbols)

    print("\n[7/8] Fetching Kite daily OHLCV for the universe...")
    print("      This will take a few minutes due to rate limits...")
    update_prices(symbols)

    print("\n[7/7] Pre-computing dashboard summary + close matrix...")
    precompute()

    print("\n" + "=" * 60)
    print("Data collection complete.")
    print("=" * 60)


if __name__ == "__main__":
    run()
