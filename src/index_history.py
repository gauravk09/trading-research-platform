"""index_history.py — daily closes for the four benchmark NSE indices.

Feeds the Market Monitor's 10-year history view: index TI65 (7-DMA / 65-DMA,
Bonde's trend intensity) as analog-finder features, and index forward returns
shown next to the median-stock proxy. Fetched from Kite with the same chunked
helper the stock collector uses — index tradingsymbols ("NIFTY 50" etc.) live
in the same instrument master.

Stored under data/parquet/indices/ — deliberately NOT data/parquet/daily/, so
storage.list_stored_symbols() and everything downstream (close matrix, RS
ranks, scans) never mistake an index for a stock.

Run standalone (backfills from 2015 on first run, incremental after):
    python src/index_history.py
"""

import os

import pandas as pd

from historical import fetch_daily_ohlcv
from updater import last_completed_session

INDICES_DIR = os.path.join(os.path.dirname(__file__), "..", "data", "parquet", "indices")
START_DATE = "2015-01-01"

# slug (file name / column name) → Kite tradingsymbol
INDICES = {
    "nifty50": "NIFTY 50",
    "nifty500": "NIFTY 500",
    "midcap150": "NIFTY MIDCAP 150",
    "smallcap250": "NIFTY SMLCAP 250",
}


def _path(slug: str) -> str:
    return os.path.join(INDICES_DIR, f"{slug}.parquet")


def _save(slug: str, df: pd.DataFrame) -> None:
    df = df[["date", "open", "high", "low", "close"]].copy()
    df["date"] = pd.to_datetime(df["date"], utc=True).dt.tz_convert("Asia/Kolkata")
    df = df.sort_values("date").drop_duplicates(subset="date").reset_index(drop=True)
    os.makedirs(INDICES_DIR, exist_ok=True)
    df.to_parquet(_path(slug), compression="snappy", index=False)


def update() -> None:
    """Backfill from 2015 on first run; fetch only new days after."""
    today = last_completed_session().isoformat()
    for slug, tradingsymbol in INDICES.items():
        if os.path.exists(_path(slug)):
            stored = pd.read_parquet(_path(slug))
            start = (stored["date"].max() + pd.Timedelta(days=1)).date().isoformat()
            if start > today:
                print(f"  {tradingsymbol}: up to date")
                continue
        else:
            stored, start = pd.DataFrame(), START_DATE
        fresh = fetch_daily_ohlcv(tradingsymbol, start, today)
        if fresh.empty:
            print(f"  {tradingsymbol}: no new candles")
            continue
        _save(slug, pd.concat([stored, fresh]) if not stored.empty else fresh)
        print(f"  {tradingsymbol}: +{len(fresh)} rows "
              f"(total {len(stored) + len(fresh)})")


def load_closes() -> pd.DataFrame:
    """Wide close frame, index=date, columns=slugs. Empty if nothing stored."""
    frames = {}
    for slug in INDICES:
        if os.path.exists(_path(slug)):
            df = pd.read_parquet(_path(slug))
            frames[slug] = df.set_index("date")["close"]
    return pd.DataFrame(frames).sort_index() if frames else pd.DataFrame()


if __name__ == "__main__":
    update()
    closes = load_closes()
    if not closes.empty:
        print(f"\nindices {closes.shape}  "
              f"{closes.index.min().date()} → {closes.index.max().date()}")
        print(closes.tail(1).round(1).to_string())
