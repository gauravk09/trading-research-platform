"""tracker.py — "I started watching here" stamps for the live dashboard.

Clicking the ⊕ on any live scan row records the symbol with its LTP and the
clock at that instant. The User Picks tab then shows how far it moved SINCE
you picked it — which is the honest read on whether your intraday picks work.
Chg% can't answer that: it measures from yesterday's close, so it includes the
move that had already happened before you saw the row.

One CSV, rewritten in place: output/tracked.csv (symbol, date, time, price).
Only today's rows are shown; earlier days stay in the file as a record of what
you were watching and when, so the stamps are reviewable after the fact.
"""

import os

from data_collection.paths import ROOT_DIR
from datetime import datetime
from zoneinfo import ZoneInfo

import pandas as pd

IST = ZoneInfo("Asia/Kolkata")
PATH = os.path.join(ROOT_DIR, "output", "tracked.csv")
COLUMNS = ["symbol", "date", "time", "price"]


def _read(path):
    """The whole log. Missing file — or a hand-edited one missing columns —
    comes back as an empty/reindexed frame rather than raising."""
    if not os.path.exists(path):
        return pd.DataFrame(columns=COLUMNS)
    df = pd.read_csv(path, dtype={"symbol": str, "date": str, "time": str})
    return df.reindex(columns=COLUMNS)


def _write(df, path):
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    df.to_csv(path, index=False)


def load(path=PATH, day=None):
    """Today's stamps only — yesterday's price is not a reference for today."""
    day = day or str(datetime.now(IST).date())
    return _read(path)[lambda d: d["date"] == day].reset_index(drop=True)


def track(symbol, price, path=PATH, now=None):
    """Stamp `symbol` at `price`. A re-track replaces today's stamp."""
    now = now or datetime.now(IST)
    row = {"symbol": symbol, "date": str(now.date()),
           "time": now.strftime("%H:%M"), "price": round(float(price), 2)}
    df = _read(path)
    df = df[~((df["symbol"] == symbol) & (df["date"] == row["date"]))]
    new = pd.DataFrame([row])
    _write(new if df.empty else pd.concat([df, new], ignore_index=True), path)
    return row


def untrack(symbol, path=PATH, day=None):
    """Drop today's stamp for `symbol`. Earlier days are left alone."""
    day = day or str(datetime.now(IST).date())
    df = _read(path)
    _write(df[~((df["symbol"] == symbol) & (df["date"] == day))], path)
