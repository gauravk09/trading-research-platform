"""
global_commodities.py — Daily OHLCV history for the global benchmark futures
that MCX metals/energy contracts track (COMEX/NYMEX), plus USDINR.

Source: Yahoo's public chart endpoint via plain requests — same approach already
used by global_markets.py, no API key, no yfinance dependency.

CAVEAT — these are FRONT-MONTH CONTINUOUS series, spliced at each roll and NOT
back-adjusted. On roll day the series jumps by the calendar spread, which is not
a return. Any strategy that reads a daily return off this series will book those
roll gaps as free P&L. Treat roll days as untradeable or model on the ratio to
MCX (which rolls on its own schedule) rather than on raw closes.

CLI:
    PYTHONPATH=src python -m data_collection.other.global_commodities            # incremental update
    PYTHONPATH=src python -m data_collection.other.global_commodities --full     # full history refresh
"""

import sys
import time

import pandas as pd
import requests

import data_collection.commodity_store as commodity_store
from data_collection.commodity_map import global_symbols

_CHART_URL = "https://query1.finance.yahoo.com/v8/finance/chart/{}"
_HEADERS = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"}


def fetch_daily(symbol: str, since: str = "2000-01-01") -> pd.DataFrame:
    """Daily OHLCV for one Yahoo symbol from `since` to now.

    Uses explicit period1/period2 epochs rather than range=: Yahoo silently
    downgrades range=max to MONTHLY bars while still reporting interval=1d, so
    a range-based call returns ~270 rows that look like 26 years of daily data.
    """
    params = {"period1": int(pd.Timestamp(since).timestamp()),
              "period2": int(time.time()),
              "interval": "1d"}
    resp = requests.get(_CHART_URL.format(symbol), params=params,
                        headers=_HEADERS, timeout=20)
    resp.raise_for_status()
    result = resp.json()["chart"]["result"][0]
    quote = result["indicators"]["quote"][0]

    df = pd.DataFrame({
        "date":   pd.to_datetime(result["timestamp"], unit="s", utc=True),
        "open":   quote["open"],
        "high":   quote["high"],
        "low":    quote["low"],
        "close":  quote["close"],
        "volume": quote["volume"],
    })
    df["date"] = df["date"].dt.tz_convert(None).dt.normalize()
    df = df.dropna(subset=["open", "high", "low", "close"])
    df["volume"] = df["volume"].fillna(0).astype("int64")
    return df.reset_index(drop=True)


def update(full: bool = False) -> dict:
    """Fetch every mapped global series into data/parquet/commodities/global/."""
    out = {}
    for symbol in global_symbols():
        existing = commodity_store.read("global", symbol)
        since = "2000-01-01" if (full or existing.empty) else \
                (existing["date"].max() - pd.Timedelta(days=10)).strftime("%Y-%m-%d")
        try:
            fresh = fetch_daily(symbol, since)
        except (requests.RequestException, KeyError, IndexError, ValueError) as e:
            print(f"{symbol:8} FAILED  {type(e).__name__}: {e}")
            continue

        # On --full, REPLACE. Concatenating would keep stale rows whose dates
        # collide with fresh ones (drop_duplicates keeps the first), which is how
        # a bad earlier pull survives the refresh meant to fix it.
        merged = fresh if (full or existing.empty) else pd.concat([existing, fresh], ignore_index=True)
        commodity_store.write("global", symbol, merged)
        stored = commodity_store.read("global", symbol)
        print(f"{symbol:8} {len(stored):>6} rows  "
              f"{stored['date'].min():%Y-%m-%d} -> {stored['date'].max():%Y-%m-%d}  "
              f"last close {stored['close'].iloc[-1]:.4g}")
        out[symbol] = stored
        time.sleep(0.3)
    return out


if __name__ == "__main__":
    update(full="--full" in sys.argv)
