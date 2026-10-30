"""
update_financials.py — Daily incremental update of quarterly financials

Two-part strategy (results after Dec-2024 only exist as Integrated Filings,
whose global feed shows today's filings and ignores date-range params):

1. Today's integrated-filing feed → symbols that filed results today.
2. A rotating fifth of the Nifty 500 → weekend/missed-day backstop, so every
   symbol gets reconciled at least weekly even if a cron run is skipped.

For each candidate symbol the integrated listing is re-pulled and the
symbol's rows are rebuilt (raw filings are cached, so only genuinely new
XBRLs are downloaded) and swapped into financials.parquet.

Run standalone (python update_financials.py) or via eod_update.py.
"""

import os
from datetime import date

import pandas as pd

from nse_financial_results import _get, dedupe_filings, fetch_symbol_financials, make_session
from nse_universe import get_all_nse_eq_symbols

TODAY_FEED_URL = ("https://www.nseindia.com/api/integrated-filing-results"
                  "?index=equities&type=Integrated%20Filing-%20Financials")
OUT_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "processed", "financials.parquet")
ROTATION_SLICES = 5


def filed_today(session) -> set:
    response = _get(session, TODAY_FEED_URL)
    if response.status_code != 200:
        return set()
    records = response.json().get("data", [])
    return {r["symbol"] for r in records if r.get("symbol")}


def run():
    session = make_session()
    universe = get_all_nse_eq_symbols()

    todays = filed_today(session) & set(universe)
    slice_index = date.today().toordinal() % ROTATION_SLICES
    backstop = set(universe[slice_index::ROTATION_SLICES])
    candidates = sorted(todays | backstop)
    print(f"financials update: {len(todays)} filed today, "
          f"{len(backstop)} in rotation slice {slice_index} → {len(candidates)} symbols")

    existing = pd.read_parquet(OUT_PATH) if os.path.exists(OUT_PATH) else pd.DataFrame()
    updated_frames, changed = [], []
    for symbol in candidates:
        df = fetch_symbol_financials(session, symbol, refresh_integrated=True)
        if df.empty:
            continue
        old_count = int((existing["symbol"] == symbol).sum()) if not existing.empty else 0
        if len(df) != old_count:
            changed.append(f"{symbol}(+{len(df) - old_count})")
        updated_frames.append(df)

    if not updated_frames:
        print("financials: nothing to update")
        return

    updated = pd.concat(updated_frames, ignore_index=True)
    kept = existing[~existing["symbol"].isin(updated["symbol"])] if not existing.empty else existing
    merged = dedupe_filings(pd.concat([kept, updated], ignore_index=True))
    merged.to_parquet(OUT_PATH, index=False)
    print(f"financials: {len(merged)} rows total"
          + (f", new filings: {', '.join(changed)}" if changed else ", no new filings"))


if __name__ == "__main__":
    run()
