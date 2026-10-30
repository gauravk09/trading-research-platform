"""
backfill_financials.py — 10-year quarterly financials backfill (Nifty 500)

Loops the Nifty 500, pulls every quarterly filing since 2016 via
nse_financial_results, and writes one long table to
data/processed/financials.parquet.

Resumable: completed symbols are tracked in the state file, and raw
filings are cached, so rerunning after a crash/rate-limit only does the
remaining work. To force a redo of one symbol, delete it from the state
file (its raw cache stays, so the redo is parse-only).
"""

import json
import os
import sys
import time

import pandas as pd

from nse_financial_results import RAW_DIR, fetch_symbol_financials, make_session
from nse_universe import get_all_nse_eq_symbols

STATE_PATH = os.path.join(RAW_DIR, "_backfill_state.json")
OUT_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "processed", "financials.parquet")
SINCE_YEAR = 2016


def load_state() -> dict:
    if os.path.exists(STATE_PATH):
        with open(STATE_PATH) as f:
            return json.load(f)
    return {"done": [], "empty": []}


def save_state(state: dict):
    with open(STATE_PATH, "w") as f:
        json.dump(state, f, indent=1)


def append_output(df: pd.DataFrame):
    if os.path.exists(OUT_PATH):
        existing = pd.read_parquet(OUT_PATH)
        df = pd.concat([existing[~existing["symbol"].isin(df["symbol"])], df],
                       ignore_index=True)
    df.to_parquet(OUT_PATH, index=False)


def main():
    symbols = get_all_nse_eq_symbols()
    state = load_state()
    finished = set(state["done"]) | set(state["empty"])
    todo = [s for s in symbols if s not in finished]
    print(f"universe={len(symbols)}  done={len(finished)}  todo={len(todo)}")

    session = make_session()
    for i, symbol in enumerate(todo, 1):
        try:
            df = fetch_symbol_financials(session, symbol, since_year=SINCE_YEAR)
        except Exception as e:
            print(f"[{i}/{len(todo)}] {symbol} FAILED: {e} — refreshing session")
            # Outlast network outages: keep retrying the session itself,
            # backing off up to 5 minutes, instead of dying mid-run.
            wait = 10
            while True:
                time.sleep(wait)
                try:
                    session = make_session()
                    break
                except Exception:
                    wait = min(wait * 2, 300)
                    print(f"  network still down, retrying in {wait}s")
            continue
        if df.empty:
            state["empty"].append(symbol)
            print(f"[{i}/{len(todo)}] {symbol}: no data")
        else:
            append_output(df)
            state["done"].append(symbol)
            quarters = df["quarter_end"].nunique()
            print(f"[{i}/{len(todo)}] {symbol}: {len(df)} rows, {quarters} quarters "
                  f"({df['quarter_end'].min()} → {df['quarter_end'].max()})")
        save_state(state)
        time.sleep(0.5)

    print(f"\nDone. Output: {os.path.abspath(OUT_PATH)}")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--one":
        session = make_session()
        df = fetch_symbol_financials(session, sys.argv[2], since_year=SINCE_YEAR)
        print(df.to_string())
    else:
        main()
