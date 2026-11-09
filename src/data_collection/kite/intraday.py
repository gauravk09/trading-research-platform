"""
intraday.py — Fetch intraday OHLCV candles from Kite (on-demand)

Use this when you need minute-level data, NOT for bulk-downloading the universe.

Kite history limits (per request):
  - 1-minute:  60 days
  - 3-min:    100 days
  - 5-min:    100 days
  - 15-min:   200 days
  - 60-min:   400 days

Typical usage:
  - Live trading day: pull 15-min for ~5-10 gap-up candidates
  - Backtest: pull 15-min for a specific stock + date

Episodic Pivot entry rule: buy on break of first 5-min or 15-min candle high.
"""

import os

from data_collection.paths import ROOT_DIR
import time
import pandas as pd
from datetime import date, timedelta
from data_collection.kite.auth import get_kite_client
from data_collection.kite.instruments import get_instrument_token

RAW_DIR = os.path.join(ROOT_DIR, "data", "raw", "intraday")
os.makedirs(RAW_DIR, exist_ok=True)

# Kite's max lookback per request (days) by interval
MAX_DAYS_BY_INTERVAL = {
    "minute":    60,
    "3minute":  100,
    "5minute":  100,
    "15minute": 200,
    "30minute": 200,
    "60minute": 400,
}


def fetch_intraday(symbol, from_date, to_date, interval="15minute", exchange="NSE"):
    """
    Fetch intraday candles for a single stock.

    Args:
        symbol:    e.g. "RELIANCE"
        from_date: "2026-05-01" (string) or date object
        to_date:   "2026-05-31"
        interval:  "minute", "5minute", "15minute", "60minute", etc.
        exchange:  "NSE" (default)

    Returns:
        DataFrame with columns: date, open, high, low, close, volume, symbol
    """
    if interval not in MAX_DAYS_BY_INTERVAL:
        raise ValueError(f"Unsupported interval: {interval}")

    kite = get_kite_client()
    token = get_instrument_token(symbol, exchange)

    start = date.fromisoformat(from_date) if isinstance(from_date, str) else from_date
    end = date.fromisoformat(to_date) if isinstance(to_date, str) else to_date

    max_days = MAX_DAYS_BY_INTERVAL[interval]
    all_candles = []
    chunk_start = start

    while chunk_start <= end:
        chunk_end = min(chunk_start + timedelta(days=max_days - 1), end)
        candles = kite.historical_data(
            instrument_token=token,
            from_date=chunk_start.isoformat(),
            to_date=chunk_end.isoformat(),
            interval=interval
        )
        all_candles.extend(candles)
        chunk_start = chunk_end + timedelta(days=1)
        time.sleep(0.15)

    df = pd.DataFrame(all_candles)
    if not df.empty:
        df["symbol"] = symbol
    return df


def fetch_intraday_and_save(symbol, from_date, to_date, interval="15minute"):
    """
    Fetch intraday candles and save to data/raw/intraday/<interval>/<symbol>.csv
    Returns the DataFrame.
    """
    folder = os.path.join(RAW_DIR, interval)
    os.makedirs(folder, exist_ok=True)
    save_path = os.path.join(folder, f"{symbol}.csv")

    df = fetch_intraday(symbol, from_date, to_date, interval)

    if df.empty:
        print(f"{symbol}: no {interval} data returned.")
        return df

    df.to_csv(save_path, index=False)
    print(f"{symbol}: saved {len(df)} {interval} candles to {save_path}")
    return df


def fetch_intraday_for_list(symbols, from_date, to_date, interval="15minute", delay_seconds=0.15):
    """
    Fetch intraday candles for a small list of stocks (e.g. today's gap-up candidates).
    DO NOT use this for the full 500-stock universe — Kite's intraday quota is limited.

    Args:
        symbols:  list of trading symbols
        from_date / to_date / interval: as above
    """
    total = len(symbols)
    for i, symbol in enumerate(symbols, start=1):
        print(f"[{i}/{total}] {symbol}")
        try:
            fetch_intraday_and_save(symbol, from_date, to_date, interval)
        except Exception as e:
            print(f"  ERROR fetching {symbol}: {e}")
        time.sleep(delay_seconds)


if __name__ == "__main__":
    # Example: fetch last 30 days of 15-min candles for RELIANCE
    from datetime import date, timedelta
    today = date.today()
    df = fetch_intraday_and_save(
        "RELIANCE",
        (today - timedelta(days=30)).isoformat(),
        today.isoformat(),
        interval="15minute"
    )
    if not df.empty:
        print(df.head())
        print(df.tail())
