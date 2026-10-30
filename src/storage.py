"""
storage.py — Single source of truth for reading and writing market data

All data is stored as Parquet files, partitioned by symbol.
Layout: data/parquet/daily/<SYMBOL>.parquet

One file per stock. Each file contains the full daily OHLCV history for that stock.

Why Parquet over CSV:
  - 5-10× smaller on disk
  - 10-100× faster to read (columnar, typed, compressed)
  - Reads only the columns you ask for (no need to load full file for one indicator)

All other modules import from here — nobody else constructs file paths.
"""

import os
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
from typing import Optional

PARQUET_DAILY_DIR = os.path.join(os.path.dirname(__file__), "..", "data", "parquet", "daily")
os.makedirs(PARQUET_DAILY_DIR, exist_ok=True)

# Schema enforced on every write — keeps data types consistent
DAILY_SCHEMA = pa.schema([
    ("date",   pa.timestamp("ns", tz="Asia/Kolkata")),
    ("open",   pa.float32()),
    ("high",   pa.float32()),
    ("low",    pa.float32()),
    ("close",  pa.float32()),
    ("volume", pa.int64()),
    ("symbol", pa.string()),
])


def _parquet_path(symbol: str) -> str:
    return os.path.join(PARQUET_DAILY_DIR, f"{symbol}.parquet")


def write_daily(symbol: str, df: pd.DataFrame) -> None:
    """
    Write (or overwrite) the daily OHLCV parquet file for a symbol.
    Input df must have columns: date, open, high, low, close, volume, symbol
    """
    df = df.copy()
    df["date"] = pd.to_datetime(df["date"], utc=True).dt.tz_convert("Asia/Kolkata")
    # Kite's daily candles for ~2016-2018 carry junk intraday timestamps (09:15 etc.)
    # on otherwise-correct full-day bars. Floor to midnight IST so one date = one row;
    # sort BEFORE flooring so a real midnight bar wins the dedupe over a mis-stamped twin.
    df = df.sort_values("date")
    df["date"] = df["date"].dt.normalize()
    df = df.drop_duplicates(subset="date")

    for col in ["open", "high", "low", "close"]:
        df[col] = df[col].astype("float32")
    df["volume"] = df["volume"].astype("int64")
    df["symbol"] = symbol

    table = pa.Table.from_pandas(df[["date", "open", "high", "low", "close", "volume", "symbol"]], schema=DAILY_SCHEMA)
    pq.write_table(table, _parquet_path(symbol), compression="snappy")


def read_daily(symbol: str, columns: Optional[list] = None) -> pd.DataFrame:
    """
    Read the daily OHLCV parquet file for a symbol.

    Args:
        symbol:  e.g. "RELIANCE"
        columns: optional list to read only specific columns (faster)
                 e.g. ["date", "close", "volume"]

    Returns:
        DataFrame sorted by date ascending. Empty DataFrame if file not found.
    """
    path = _parquet_path(symbol)
    if not os.path.exists(path):
        return pd.DataFrame()

    df = pq.read_table(path, columns=columns).to_pandas()
    df["date"] = pd.to_datetime(df["date"])
    return df.sort_values("date").reset_index(drop=True)


def get_last_date(symbol: str) -> Optional[pd.Timestamp]:
    """Return the most recent date stored for a symbol, or None if not stored."""
    df = read_daily(symbol, columns=["date"])
    if df.empty:
        return None
    return df["date"].max()


def list_stored_symbols() -> list:
    """Return all symbols that have a parquet file."""
    files = os.listdir(PARQUET_DAILY_DIR)
    return [f.replace(".parquet", "") for f in files if f.endswith(".parquet")]


def read_universe_close(symbols: list, start_date: str = None) -> pd.DataFrame:
    """
    Read closing prices for a list of symbols into a wide DataFrame.
    Columns = symbols, Index = date. Useful for relative strength calculations.

    Args:
        symbols:    list of stock symbols
        start_date: optional "YYYY-MM-DD" to limit history loaded
    """
    frames = {}
    for symbol in symbols:
        df = read_daily(symbol, columns=["date", "close"])
        if df.empty:
            continue
        if start_date:
            df = df[df["date"] >= start_date]
        frames[symbol] = df.set_index("date")["close"]

    if not frames:
        return pd.DataFrame()

    return pd.DataFrame(frames).sort_index()
