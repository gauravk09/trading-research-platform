"""
backfill_announcements.py — One-time historical backfill of NSE announcements

The daily updater (nse_announcements.py) only captures announcements from the
day it runs, so the archive starts 2025-07-01. NSE's API accepts date ranges
and serves history back to 2015, so this script walks weekly chunks backwards
and writes one CSV per day into the same data/raw/announcements/ archive.

Saved columns: symbol, subject, category, an_dt, smindustry
(trimmed — attachment text/URLs are dropped to keep the archive small).
Days that already have a file are skipped, so re-running resumes cleanly.

Usage:
    python src/backfill_announcements.py --start 2015-01-01 --end 2025-06-30
"""

import os
import sys
import time
import argparse
import requests
import pandas as pd
from datetime import date, timedelta

sys.path.insert(0, os.path.dirname(__file__))
import announcements_store as store
from nse_announcements import HEADERS, ANNOUNCEMENTS_URL, categorize

KEEP_COLS = ["symbol", "subject", "category", "an_dt", "smindustry"]


def new_session() -> requests.Session:
    s = requests.Session()
    s.get("https://www.nseindia.com", headers=HEADERS, timeout=10)
    return s


def fetch_range(session: requests.Session, frm: date, to: date) -> pd.DataFrame:
    d1, d2 = frm.strftime("%d-%m-%Y"), to.strftime("%d-%m-%Y")
    r = session.get(f"{ANNOUNCEMENTS_URL}&from_date={d1}&to_date={d2}",
                    headers=HEADERS, timeout=90)
    r.raise_for_status()
    data = r.json()
    rows = data if isinstance(data, list) else data.get("data", [])
    df = pd.DataFrame(rows)
    if df.empty:
        return df
    df.columns = [c.strip().lower() for c in df.columns]
    subject_col = next((c for c in ["desc", "sm_desc", "subject"] if c in df.columns), None)
    df["subject"] = df[subject_col] if subject_col else ""
    df["category"] = df["subject"].apply(categorize)
    if "smindustry" not in df.columns:
        df["smindustry"] = ""
    return df[[c for c in KEEP_COLS if c in df.columns]]


def week_chunks(start: date, end: date):
    cur = end
    while cur >= start:
        frm = max(start, cur - timedelta(days=6))
        yield frm, cur
        cur = frm - timedelta(days=1)


def backfill(start: date, end: date) -> None:
    session = new_session()
    chunks = list(week_chunks(start, end))
    written = skipped = 0

    done = store.archived_dates()

    for i, (frm, to) in enumerate(chunks, start=1):
        days = [frm + timedelta(days=n) for n in range((to - frm).days + 1)]
        if all(d.isoformat() in done for d in days):
            skipped += len(days)
            continue

        for attempt in range(1, 4):
            try:
                df = fetch_range(session, frm, to)
                break
            except Exception as e:
                print(f"  [{i}/{len(chunks)}] {frm}..{to} attempt {attempt} failed: {e}")
                time.sleep(5 * attempt)
                session = new_session()
        else:
            print(f"  [{i}/{len(chunks)}] {frm}..{to} GAVE UP — re-run to resume")
            continue

        if not df.empty:
            df["_day"] = pd.to_datetime(df["an_dt"], errors="coerce").dt.date
        for d in days:
            if d.isoformat() in done:
                continue
            day_df = df[df["_day"] == d].drop(columns="_day") if not df.empty else pd.DataFrame()
            if not day_df.empty:
                store.save_day(day_df, d)
            written += 1

        if i % 20 == 0:
            print(f"  [{i}/{len(chunks)}] up to {frm} — {written} day files written")
        time.sleep(1.0)

    print(f"Done: {written} day files written, {skipped} days already present.")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--start", default="2015-01-01", help="YYYY-MM-DD")
    parser.add_argument("--end", default="2025-06-30", help="YYYY-MM-DD (archive already covers 2025-07-01+)")
    args = parser.parse_args()
    backfill(date.fromisoformat(args.start), date.fromisoformat(args.end))


if __name__ == "__main__":
    main()
