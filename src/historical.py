"""
historical.py — Fetch daily OHLCV candles from Kite Connect

Kite provides up to 25+ years of daily candle data.
This module fetches and saves daily candles for a list of stocks.

Rate limit: 10 requests/second. We add a small delay between calls.
"""

import os
import time
import pandas as pd
from datetime import date, timedelta
from auth import get_kite_client
from instruments import get_instrument_token

RAW_DIR = os.path.join(os.path.dirname(__file__), "..", "data", "raw", "historical")
os.makedirs(RAW_DIR, exist_ok=True)


# Kite limits a single daily-candle request to 2000 days
KITE_DAILY_MAX_DAYS = 2000


def _to_date(d):
    """Accept either a string 'YYYY-MM-DD' or a date object and return a date."""
    if isinstance(d, str):
        return date.fromisoformat(d)
    return d


def fetch_daily_ohlcv(symbol, from_date, to_date, exchange="NSE"):
    """
    Fetch daily OHLCV candles for a stock between from_date and to_date.
    Automatically chunks requests if the range exceeds Kite's 2000-day limit.

    Args:
        symbol:    e.g. "RELIANCE"
        from_date: e.g. "2020-01-01"
        to_date:   e.g. "2024-12-31"
        exchange:  "NSE" (default)

    Returns:
        DataFrame with columns: date, open, high, low, close, volume, symbol
    """
    kite = get_kite_client()
    token = get_instrument_token(symbol, exchange)

    start = _to_date(from_date)
    end = _to_date(to_date)

    all_candles = []
    chunk_start = start

    while chunk_start <= end:
        chunk_end = min(chunk_start + timedelta(days=KITE_DAILY_MAX_DAYS - 1), end)
        candles = kite.historical_data(
            instrument_token=token,
            from_date=chunk_start.isoformat(),
            to_date=chunk_end.isoformat(),
            interval="day"
        )
        all_candles.extend(candles)
        chunk_start = chunk_end + timedelta(days=1)
        time.sleep(0.15)  # stay under 10 req/sec

    df = pd.DataFrame(all_candles)
    if not df.empty:
        df["symbol"] = symbol
    return df


def fetch_and_save(symbol, from_date, to_date, exchange="NSE"):
    """
    Fetch daily candles and save to data/raw/historical/SYMBOL.csv
    If the file exists, only fetch new data since the last saved date.
    Returns the full DataFrame.
    """
    save_path = os.path.join(RAW_DIR, f"{symbol}.csv")

    if os.path.exists(save_path):
        existing = pd.read_csv(save_path, parse_dates=["date"])
        last_date = existing["date"].max().date()

        # Only fetch what's new
        new_from = (last_date + timedelta(days=1)).isoformat()
        if new_from > to_date:
            print(f"{symbol}: Already up to date.")
            return existing

        print(f"{symbol}: Fetching new data from {new_from} to {to_date}...")
        new_data = fetch_daily_ohlcv(symbol, new_from, to_date, exchange)
        df = pd.concat([existing, new_data], ignore_index=True)
    else:
        print(f"{symbol}: Fetching full history from {from_date} to {to_date}...")
        df = fetch_daily_ohlcv(symbol, from_date, to_date, exchange)

    df.to_csv(save_path, index=False)
    print(f"{symbol}: Saved {len(df)} rows to {save_path}")
    return df


def fetch_universe(symbols, from_date="2015-01-01", delay_seconds=0.15):
    """
    Fetch daily candles for a list of symbols.
    Adds a delay between requests to stay within the 10 req/sec rate limit.

    Args:
        symbols:        List of stock symbols e.g. ["RELIANCE", "TCS", "INFY"]
        from_date:      Start date for history
        delay_seconds:  Pause between each API call (default 0.15s = ~6 req/sec)
    """
    today = date.today().isoformat()
    total = len(symbols)

    for i, symbol in enumerate(symbols, start=1):
        print(f"[{i}/{total}] {symbol}")
        try:
            fetch_and_save(symbol, from_date, today)
        except Exception as e:
            print(f"  ERROR fetching {symbol}: {e}")
        time.sleep(delay_seconds)

    print("\nDone fetching historical data.")


if __name__ == "__main__":
    # Quick test with 3 stocks
    fetch_universe(["RELIANCE", "TCS", "INFY"], from_date="2020-01-01")
