"""build_vol_curve.py — measure the NSE intraday cumulative-volume curve.

Averages, across the ~40 most liquid names over the last ~10 sessions, the
fraction of the full day's volume traded by each minute of the session. The
result (minute -> fraction) is what live_scanner.session_fraction() divides by
to project today's cumulative volume to a full day — NSE volume is U-shaped,
so dividing by elapsed time instead overstates RVOL ~2-3x in the first hour.

Run occasionally (the shape is stable; a refresh every few months is plenty):
    PYTHONPATH=src python -m preprocessing.build_vol_curve
"""

import os

from data_collection.paths import ROOT_DIR
import time
from datetime import datetime, timedelta

import pandas as pd

from data_collection.kite.auth import get_kite_client
from data_collection.kite.instruments import download_instruments

ROOT = ROOT_DIR
SUMMARY_PATH = os.path.join(ROOT, "data", "processed", "universe_summary.parquet")
OUT_PATH = os.path.join(ROOT, "data", "processed", "intraday_vol_curve.json")

N_SYMBOLS = 40
LOOKBACK_DAYS = 16          # calendar days, ~10 trading sessions
SESSION_MIN = 375


def main():
    kite = get_kite_client()
    summary = pd.read_parquet(SUMMARY_PATH)
    top = summary.nlargest(N_SYMBOLS, "avg_turnover_cr")["symbol"].tolist()
    inst = download_instruments("NSE")
    inst = inst[(inst["tradingsymbol"].isin(top)) & (inst["instrument_type"] == "EQ")]

    frm = datetime.now() - timedelta(days=LOOKBACK_DAYS)
    to = datetime.now().replace(hour=0, minute=0)   # exclude today's partial session

    curves = []
    for sym, tok in zip(inst["tradingsymbol"], inst["instrument_token"]):
        try:
            raw = kite.historical_data(int(tok), frm, to, "minute")
        except Exception as e:
            print(f"  {sym}: {e}")
            continue
        df = pd.DataFrame(raw)
        if df.empty:
            continue
        df["day"] = df["date"].dt.date
        df["min_of_day"] = df["date"].dt.hour * 60 + df["date"].dt.minute - (9 * 60 + 15)
        df = df[(df["min_of_day"] >= 0) & (df["min_of_day"] < SESSION_MIN)]
        for _, g in df.groupby("day"):
            total = g["volume"].sum()
            if total < 10000:
                continue
            cum = g.set_index("min_of_day")["volume"].cumsum() / total
            curves.append(cum.reindex(range(SESSION_MIN)).ffill().fillna(0))
        time.sleep(0.34)    # Kite historical API: 3 requests/second

    avg = pd.concat(curves, axis=1).mean(axis=1)
    avg.round(4).to_json(OUT_PATH)
    print(f"{len(curves)} symbol-days -> {OUT_PATH}")


if __name__ == "__main__":
    main()
