"""earnings_calendar.py — forthcoming results dates from NSE's event calendar.

NSE's event-calendar API lists board meetings ~2-3 weeks ahead with a purpose
field; rows whose purpose mentions "Financial Results" are the forthcoming
earnings dates. Fetched daily (step 2 of eod_update) and UPSERTED into a
rolling store, so a one-day API hiccup never blanks the calendar and past
meeting dates accumulate into a "last results date" history for free.

Store: data/processed/earnings_calendar.parquet
       [symbol, meeting_date (ISO), purpose, fetched_on (ISO)]

results_due_days() is the consumer-facing read: symbol → trading-blind
calendar days until the next known results meeting. Used by daily_state
(candidate flags + open trades) and the dashboard chart panel.

Run standalone to fetch and print the near-term calendar:
    python src/earnings_calendar.py
"""

import os
from datetime import date

import pandas as pd
import requests

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.nseindia.com/",
}
CALENDAR_URL = "https://www.nseindia.com/api/event-calendar"

STORE = os.path.join(os.path.dirname(__file__), "..", "data", "processed",
                     "earnings_calendar.parquet")


def fetch_calendar() -> pd.DataFrame:
    """Today's snapshot of upcoming results-purpose board meetings."""
    session = requests.Session()
    session.get("https://www.nseindia.com", headers=HEADERS, timeout=10)
    resp = session.get(CALENDAR_URL, headers=HEADERS, timeout=30)
    resp.raise_for_status()
    data = resp.json()
    rows = data if isinstance(data, list) else data.get("data", [])
    df = pd.DataFrame(rows)
    if df.empty or "symbol" not in df.columns:
        return pd.DataFrame(columns=["symbol", "meeting_date", "purpose"])
    df = df[df["purpose"].str.contains("Financial Results", case=False, na=False)]
    out = pd.DataFrame({
        "symbol": df["symbol"].astype(str).str.strip().str.upper(),
        "meeting_date": pd.to_datetime(df["date"], format="%d-%b-%Y")
                          .dt.date.astype(str),
        "purpose": df["purpose"].astype(str),
    })
    return out.dropna(subset=["meeting_date"]).reset_index(drop=True)


def update() -> pd.DataFrame:
    """Fetch and upsert into the store, keyed on (symbol, meeting_date)."""
    fresh = fetch_calendar()
    fresh["fetched_on"] = date.today().isoformat()
    if os.path.exists(STORE):
        old = pd.read_parquet(STORE)
        fresh = pd.concat([old, fresh], ignore_index=True) \
            .drop_duplicates(["symbol", "meeting_date"], keep="last")
    fresh = fresh.sort_values(["meeting_date", "symbol"]).reset_index(drop=True)
    fresh.to_parquet(STORE, index=False)
    upcoming = (fresh["meeting_date"] >= date.today().isoformat()).sum()
    print(f"Earnings calendar: {upcoming} upcoming results dates "
          f"({len(fresh)} total in store)")
    return fresh


def results_due_days(asof: date = None) -> pd.Series:
    """symbol → calendar days until its next known results meeting (>= asof).
    Symbols with no upcoming meeting are absent. Empty Series if no store."""
    if not os.path.exists(STORE):
        return pd.Series(dtype="float64")
    asof = asof or date.today()
    cal = pd.read_parquet(STORE, columns=["symbol", "meeting_date"])
    cal = cal[cal["meeting_date"] >= asof.isoformat()]
    if cal.empty:
        return pd.Series(dtype="float64")
    nxt = cal.groupby("symbol")["meeting_date"].min()
    return (pd.to_datetime(nxt) - pd.Timestamp(asof)).dt.days.astype("float64")


if __name__ == "__main__":
    cal = update()
    due = results_due_days()
    soon = due[due <= 7].sort_values()
    print(f"\nResults within 7 days: {len(soon)}")
    print(soon.head(25).astype(int).to_string())
