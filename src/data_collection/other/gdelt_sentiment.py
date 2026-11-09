"""gdelt_sentiment.py — daily macro news-sentiment for Indian markets from GDELT.

GDELT covers large-cap / index / macro India news well but single small-caps
poorly, so this is a MACRO REGIME OVERLAY, not a stock-level signal. For each
macro query it stores one row per IST day: the volume-weighted average news
tone and a relative volume figure.

Runs as its own EOD job (NOT part of run_daily.py — kept separate on purpose):
    PYTHONPATH=src python -m data_collection.other.gdelt_sentiment

GDELT's free DOC 2.0 API throttles bursts hard, so calls are spaced with a
short sleep. Today's (partial) day is excluded; a re-run the next day fills the
completed value. Re-running is safe — each (date, query) row is upserted.

Tone scale: GDELT "average tone" is roughly -10 (very negative) to +10 (very
positive); most real-world days sit between -5 and +2. Read trend, not level.
"""

import os

from data_collection.paths import ROOT_DIR
import time
from datetime import datetime, timezone

import pandas as pd
import requests
from zoneinfo import ZoneInfo

RAW_DIR = os.path.join(ROOT_DIR, "data", "raw", "gdelt")
os.makedirs(RAW_DIR, exist_ok=True)
CSV_PATH = os.path.join(RAW_DIR, "gdelt_sentiment.csv")

API = "https://api.gdeltproject.org/api/v2/doc/doc"
HEADERS = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"}
IST = ZoneInfo("Asia/Kolkata")

# Macro India queries. Restricted to Indian sources; each is one stored series.
MACRO_QUERIES = {
    "nifty":         '"Nifty" sourcecountry:IN',
    "sensex":        '"Sensex" sourcecountry:IN',
    "india_markets": '"Indian stock market" sourcecountry:IN',
    "india_economy": '"Indian economy" sourcecountry:IN',
}

LOOKBACK = "5d"       # fetch a short window so a missed day is backfilled next run
REQUEST_GAP_S = 6     # GDELT's free API 429s below one request / 5 seconds


def _timeline(query: str, mode: str) -> pd.DataFrame:
    """One GDELT timeline call -> DataFrame[ts_utc, value]. Empty on any error
    (throttled, malformed, no data) so one bad call never kills the job."""
    try:
        resp = requests.get(
            API,
            params={"query": query, "mode": mode, "timespan": LOOKBACK, "format": "json"},
            headers=HEADERS, timeout=30,
        )
    except requests.RequestException:
        return pd.DataFrame(columns=["ts_utc", "value"])
    if not resp.ok or not resp.text.strip().startswith("{"):
        return pd.DataFrame(columns=["ts_utc", "value"])
    tl = resp.json().get("timeline", [])
    if not tl:
        return pd.DataFrame(columns=["ts_utc", "value"])
    pts = tl[0]["data"]
    df = pd.DataFrame(pts)
    df["ts_utc"] = pd.to_datetime(df["date"], format="%Y%m%dT%H%M%SZ", utc=True)
    return df[["ts_utc", "value"]]


def _daily_sentiment(query: str) -> pd.DataFrame:
    """Volume-weighted daily tone for one query, aligned to IST days.

    tone timeline gives avg tone per sub-day bucket (0 when no articles); vol
    timeline gives that bucket's relative article volume. Weighting tone by
    volume makes empty buckets contribute nothing instead of dragging tone to 0.
    """
    tone = _timeline(query, "timelinetone").rename(columns={"value": "tone"})
    time.sleep(REQUEST_GAP_S)
    vol = _timeline(query, "timelinevol").rename(columns={"value": "vol"})
    if tone.empty or vol.empty:
        return pd.DataFrame(columns=["date", "avg_tone", "volume", "n_buckets"])

    df = tone.merge(vol, on="ts_utc", how="inner")
    df["date"] = df["ts_utc"].dt.tz_convert(IST).dt.date
    df["tone_x_vol"] = df["tone"] * df["vol"]

    g = df.groupby("date").agg(
        tone_x_vol=("tone_x_vol", "sum"),
        vol=("vol", "sum"),
        n_buckets=("vol", lambda s: int((s > 0).sum())),
    ).reset_index()

    g = g[g["vol"] > 0].copy()                       # drop days with no coverage
    g["avg_tone"] = (g["tone_x_vol"] / g["vol"]).round(3)
    g["volume"] = g["vol"].round(3)
    return g[["date", "avg_tone", "volume", "n_buckets"]]


def run() -> str:
    today_ist = datetime.now(IST).date()
    frames = []
    for name, query in MACRO_QUERIES.items():
        daily = _daily_sentiment(query)
        daily = daily[daily["date"] < today_ist]     # exclude partial current day
        if daily.empty:
            print(f"  {name}: no completed-day data (throttled or no coverage)")
        else:
            daily.insert(1, "query", name)
            frames.append(daily)
            latest = daily.iloc[-1]
            print(f"  {name}: {latest['date']} tone {latest['avg_tone']:+} (vol {latest['volume']})")
        time.sleep(REQUEST_GAP_S)

    if not frames:
        print("GDELT: nothing to write (all queries empty).")
        return CSV_PATH

    fresh = pd.concat(frames, ignore_index=True)
    fresh["date"] = fresh["date"].astype(str)

    if os.path.exists(CSV_PATH):
        old = pd.read_csv(CSV_PATH, dtype={"date": str})
        keys = set(zip(fresh["date"], fresh["query"]))
        old = old[~old.apply(lambda r: (r["date"], r["query"]) in keys, axis=1)]
        out = pd.concat([old, fresh], ignore_index=True)
    else:
        out = fresh

    out = out.sort_values(["date", "query"]).reset_index(drop=True)
    out.to_csv(CSV_PATH, index=False)
    print(f"GDELT sentiment: {len(fresh)} rows upserted ({len(out)} total) -> {CSV_PATH}")
    return CSV_PATH


if __name__ == "__main__":
    run()
