"""
commodity_store.py — Parquet read/write for commodity series.

Deliberately separate from storage.py: that module's list_stored_symbols() feeds
the NSE equity scanners, and dropping GOLD/CL=F into the same folder would leak
commodities into every stock scan.

Layout: data/parquet/commodities/<market>/<SYMBOL>.parquet
        market = global | spot | mcx

Only `date`, `close` and `symbol` are required. Spot benchmarks (LBMA gold fix,
EIA WTI) publish ONE price per day — there is no open/high/low. Fabricating
o=h=l=c to satisfy a fixed schema would let a range or gap rule "work" on a
series that has no intraday range at all, so those columns are simply absent
and any caller needing them must fail loudly instead.

Dates are stored tz-naive (the exchange's own trading date). Global futures and
MCX close hours apart; pretending both are IST-aware timestamps would invite a
silent off-by-one when the two are joined. Alignment is handled explicitly at
join time, not smuggled into the storage layer.
"""

import os
import pandas as pd

COMMODITY_DIR = os.path.join(os.path.dirname(__file__), "..", "data", "parquet", "commodities")

REQUIRED = ["date", "close", "symbol"]
PREFERRED_ORDER = ["date", "open", "high", "low", "close", "volume", "symbol"]


def _path(market: str, symbol: str) -> str:
    d = os.path.join(COMMODITY_DIR, market)
    os.makedirs(d, exist_ok=True)
    return os.path.join(d, f"{symbol.replace('=', '_').replace('/', '_')}.parquet")


def write(market: str, symbol: str, df: pd.DataFrame) -> None:
    df = df.copy()
    df["date"] = pd.to_datetime(df["date"]).dt.tz_localize(None).dt.normalize()
    df["symbol"] = symbol
    df = df.sort_values("date").drop_duplicates(subset="date")

    missing = [c for c in REQUIRED if c not in df.columns]
    if missing:
        raise ValueError(f"{market}/{symbol}: missing required columns {missing}")

    ordered = [c for c in PREFERRED_ORDER if c in df.columns]
    extras = [c for c in df.columns if c not in ordered]
    df[ordered + extras].to_parquet(_path(market, symbol), compression="snappy", index=False)


def read(market: str, symbol: str) -> pd.DataFrame:
    path = _path(market, symbol)
    if not os.path.exists(path):
        return pd.DataFrame(columns=REQUIRED)
    return pd.read_parquet(path)


def list_symbols(market: str) -> list:
    d = os.path.join(COMMODITY_DIR, market)
    if not os.path.exists(d):
        return []
    return sorted(f[:-8] for f in os.listdir(d) if f.endswith(".parquet"))
