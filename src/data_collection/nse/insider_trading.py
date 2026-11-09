"""nse_insider_trading.py — SEBI PIT (Reg 7) insider/promoter trading disclosures
from NSE corporate-filings, as a rolling per-stock parquet.

Insider *purchases* are the highest-evidence, slowest-decaying free India signal
(see docs/ALTERNATIVE_DATA_FACTORS.md §3-4): promoters/insiders buying their own
stock precedes positive abnormal returns; sells are noisy.

Source (free, no key): NSE's PIT report API, the same feed the website's
"Corporate Filings → Insider Trading (SEBI PIT)" page reads:
    https://www.nseindia.com/api/corporates-pit?index=equities&from_date=DD-MM-YYYY&to_date=DD-MM-YYYY
NSE blocks bare requests, so a homepage visit is used to mint the archive cookie
(same session pattern as nse_stock_oi.py).

LOOK-AHEAD (the single most important correctness property here):
Every row is anchored to `disclosure_date` — the exchange DISSEMINATION timestamp
(NSE's `date` field), i.e. when the filing became public. A trade is disclosed
days after it happens (txn_from_date/txn_to_date and intimation_date are earlier),
so a factor must key off `disclosure_date`, NOT the transaction date, or it reads
information that was not yet public and injects look-ahead bias. The transaction
and intimation dates are kept for reference only.

Stored long/tidy (one row per disclosure) at
data/processed/insider_trading.parquet. De-duped on `did` (NSE disclosure id).

    PYTHONPATH=src python -m data_collection.nse.insider_trading            # last ~10 days of disclosures
    PYTHONPATH=src python -m data_collection.nse.insider_trading 400        # ~400 days back (user backfill)
"""

import os

from data_collection.paths import ROOT_DIR
import sys
import time
from datetime import date, timedelta

import pandas as pd
import requests

PROCESSED = os.path.join(ROOT_DIR, "data", "processed")
STORE = os.path.join(PROCESSED, "insider_trading.parquet")

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/120 Safari/537.36",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept": "*/*",
    "Referer": "https://www.nseindia.com/companies-listing/corporate-filings-insider-trading",
}
PIT_URL = "https://www.nseindia.com/api/corporates-pit?index=equities"

# NSE field -> our column. `date` (dissemination) becomes disclosure_date below.
FIELD_MAP = {
    "symbol": "symbol", "company": "company", "acqName": "person_name",
    "personCategory": "person_category", "tdpTransactionType": "txn_type",
    "acqMode": "mode", "secType": "sec_type", "secAcq": "quantity", "secVal": "value",
    "buyQuantity": "buy_qty", "buyValue": "buy_val",
    "sellquantity": "sell_qty", "sellValue": "sell_val",
    "befAcqSharesPer": "pct_before", "afterAcqSharesPer": "pct_after",
    "acqfromDt": "txn_from_date", "acqtoDt": "txn_to_date", "intimDt": "intimation_date",
    "did": "did", "xbrl": "xbrl",
}
NUM_COLS = ["quantity", "value", "buy_qty", "buy_val", "sell_qty", "sell_val",
            "pct_before", "pct_after"]
DATE_COLS = ["txn_from_date", "txn_to_date", "intimation_date"]


def _session() -> requests.Session:
    s = requests.Session()
    s.get("https://www.nseindia.com", headers=HEADERS, timeout=15)
    return s


def _ist(series: pd.Series) -> pd.Series:
    """Parse NSE date strings to IST-aware timestamps (naive IST -> Asia/Kolkata)."""
    ts = pd.to_datetime(series, format="mixed", dayfirst=True, errors="coerce")
    return ts.dt.tz_localize("Asia/Kolkata")


def download_pit(from_d: date, to_d: date, session: requests.Session = None) -> pd.DataFrame:
    """PIT disclosures disseminated between from_d and to_d (inclusive). Tidy frame."""
    s = session or _session()
    url = f"{PIT_URL}&from_date={from_d:%d-%m-%Y}&to_date={to_d:%d-%m-%Y}"
    r = s.get(url, headers=HEADERS, timeout=40)
    r.raise_for_status()
    payload = r.json()
    rows = payload if isinstance(payload, list) else payload.get("data", [])
    if not rows:
        return pd.DataFrame()

    raw = pd.DataFrame(rows)
    out = pd.DataFrame()
    for src, dst in FIELD_MAP.items():
        out[dst] = raw[src] if src in raw.columns else pd.NA

    # LOOK-AHEAD ANCHOR: `date` is the exchange dissemination timestamp — the
    # moment the filing was public. All factor logic must align on this column.
    out["disclosure_date"] = _ist(raw["date"]) if "date" in raw.columns else pd.NaT
    for c in DATE_COLS:
        out[c] = _ist(out[c])
    for c in NUM_COLS:
        out[c] = pd.to_numeric(out[c], errors="coerce")  # explicit NaN, never 0
    out["symbol"] = out["symbol"].astype(str).str.strip()

    front = ["disclosure_date", "symbol", "company", "person_name", "person_category",
             "txn_type", "mode", "quantity", "value"]
    return out[front + [c for c in out.columns if c not in front]]


def load() -> pd.DataFrame:
    return pd.read_parquet(STORE) if os.path.exists(STORE) else pd.DataFrame()


def update(days: int = 10) -> None:
    """Fetch PIT disclosures from the last `days` calendar days and append.
    Idempotent: rows are de-duped on `did` (NSE disclosure id), so re-running a
    day already stored changes nothing. Safe to run nightly."""
    to_d = date.today()
    from_d = to_d - timedelta(days=days)
    try:
        fresh = download_pit(from_d, to_d)
    except Exception as e:                            # noqa: BLE001 — log & continue
        print(f"  insider_trading: fetch failed ({type(e).__name__})")
        return
    if fresh.empty:
        print("  insider_trading: nothing returned")
        return

    existing = load()
    combined = pd.concat([existing, fresh], ignore_index=True) if not existing.empty else fresh
    combined = combined.drop_duplicates(subset=["did"], keep="last") \
                       .sort_values(["disclosure_date", "symbol"]).reset_index(drop=True)
    os.makedirs(PROCESSED, exist_ok=True)
    combined.to_parquet(STORE, compression="snappy")
    print(f"  insider_trading {combined.shape}  "
          f"{combined['disclosure_date'].min().date()} → "
          f"{combined['disclosure_date'].max().date()}  (+{len(fresh)} fetched)")


if __name__ == "__main__":
    update(int(sys.argv[1]) if len(sys.argv) > 1 else 10)
