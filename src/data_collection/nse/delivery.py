"""nse_delivery.py — daily security-wise delivery % from NSE (stock-level
institutional-intent proxy).

Institutions are delivery-bound — their mandates bar intraday churn — so a stock's
delivery % (the share of the day's traded quantity that actually settled as
delivery) is the cleanest free proxy on NSE for genuine institutional conviction
in THAT specific name. The pattern desks watch: several sessions of above-average
delivery in a tight price range on declining volume = quiet accumulation.

Source (free, no key): NSE's security-wise "full bhavdata" file, which carries the
DELIV_PER column the plain bhavcopy (nse_bhavcopy.py) does not:
  https://nsearchives.nseindia.com/products/content/sec_bhavdata_full_DDMMYYYY.csv

Stored as a wide matrix (date × symbol, values = delivery %), mirroring
close_matrix / volume_matrix, so "delivery vs its own N-day average" is a single
vectorized rolling op. EQ series only — the tradeable universe. This is a
stock-scan-quality signal, NOT a market-regime signal.

    PYTHONPATH=src python -m data_collection.nse.delivery            # fetch the last ~10 trading days
    PYTHONPATH=src python -m data_collection.nse.delivery 120        # backfill ~120 calendar days back
"""

import io
import os

from data_collection.paths import ROOT_DIR
import sys
import time
from datetime import date, timedelta

import pandas as pd
import requests

PROCESSED = os.path.join(ROOT_DIR, "data", "processed")
DELIVERY_MATRIX = os.path.join(PROCESSED, "delivery_matrix.parquet")

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.nseindia.com/",
}
URL = "https://nsearchives.nseindia.com/products/content/sec_bhavdata_full_{}.csv"


def _session() -> requests.Session:
    """NSE needs a homepage visit first to hand out the cookie the archive checks."""
    s = requests.Session()
    s.get("https://www.nseindia.com", headers=HEADERS, timeout=10)
    return s


def download_delivery(for_date: date, session: requests.Session = None) -> pd.Series:
    """EQ delivery % for one day as a symbol→pct Series. Empty on weekend/holiday.

    DELIV_PER is non-numeric ("-") for some rows, so it's coerced and dropped; EQ
    is the only series kept, to match the tradeable universe the scans use."""
    if for_date.weekday() >= 5:
        return pd.Series(dtype=float)
    s = session or _session()
    r = s.get(URL.format(for_date.strftime("%d%m%Y")), headers=HEADERS, timeout=30)
    if r.status_code == 404:
        return pd.Series(dtype=float)
    r.raise_for_status()
    df = pd.read_csv(io.BytesIO(r.content))
    df.columns = [c.strip() for c in df.columns]
    df["SERIES"] = df["SERIES"].astype(str).str.strip()
    eq = df[df["SERIES"] == "EQ"].copy()
    eq["DELIV_PER"] = pd.to_numeric(eq["DELIV_PER"], errors="coerce")
    return eq.set_index(eq["SYMBOL"].str.strip())["DELIV_PER"].dropna()


def load() -> pd.DataFrame:
    """Delivery-% matrix (date × symbol). Empty frame if nothing stored yet."""
    return pd.read_parquet(DELIVERY_MATRIX) if os.path.exists(DELIVERY_MATRIX) else pd.DataFrame()


def update(days: int = 10) -> None:
    """Fetch delivery for the last `days` calendar days not already stored and
    append them. Idempotent — stored dates are skipped, so it's safe to re-run and
    to call nightly. One bad day is logged and skipped, never aborts the backfill."""
    existing = load()
    have = set(existing.index) if not existing.empty else set()
    s = _session()
    rows = {}
    for i in range(days):
        d = date.today() - timedelta(days=i)
        ts = pd.Timestamp(d, tz="Asia/Kolkata")
        if d.weekday() >= 5 or ts in have:
            continue
        try:
            ser = download_delivery(d, s)
        except Exception as e:                       # noqa: BLE001 — log & continue
            print(f"  {d}: skipped ({type(e).__name__})")
            continue
        if not ser.empty:
            rows[ts] = ser
            print(f"  {d}: {len(ser)} EQ symbols")
        time.sleep(0.4)                              # be polite to NSE
    if not rows:
        print("  delivery: up to date")
        return
    fresh = pd.DataFrame(rows).T.sort_index()
    combined = fresh if existing.empty else pd.concat([existing, fresh])
    combined = combined[~combined.index.duplicated(keep="last")].sort_index()
    os.makedirs(PROCESSED, exist_ok=True)
    combined.to_parquet(DELIVERY_MATRIX, compression="snappy")
    print(f"  delivery_matrix {combined.shape}  "
          f"{combined.index.min().date()} → {combined.index.max().date()}")


if __name__ == "__main__":
    update(int(sys.argv[1]) if len(sys.argv) > 1 else 10)
