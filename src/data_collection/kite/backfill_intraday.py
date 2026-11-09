"""
backfill_intraday.py — one-shot backfill of 5-minute OHLCV for the full NSE
universe + key indices, stored as parquet for the intraday miner to read.

Why a separate script (not intraday.py):
  intraday.py is the on-demand tool — pull a handful of gap-up candidates for
  today. This is the bulk historian: ~2100 EQ symbols + indices, ~2 years of
  5-min bars, chunked under Kite's 100-day-per-request window.

Kite facts baked in here:
  - 5-min history is limited to a 100-day WINDOW per request, not a 100-day
    total lookback. We reach 2 years by walking backward in ~8 windows.
  - Historical API rate limit is ~3 requests/sec. We sleep 0.35s between calls.
  - Access token expires daily at 06:00 IST — refresh with `PYTHONPATH=src python -m data_collection.kite.auth`
    before running. If the token dies mid-run we abort cleanly and you re-run;
    finished symbols are skipped.

Storage:  data/parquet/intraday_5m/<SYMBOL>.parquet   (stocks)
          data/parquet/intraday_5m/_indices/<NAME>.parquet   (indices)
Each file: date (IST tz-aware), open, high, low, close, volume, symbol.

Resumability:
  A symbol's file is written only after ALL its chunks succeed, so a file is
  never half-written. Re-running skips symbols whose file already reaches the
  target end date, and tops up the recent tail for the rest.

Run:
  PYTHONPATH=src python -m data_collection.kite.backfill_intraday                # full universe, 2 years
  PYTHONPATH=src python -m data_collection.kite.backfill_intraday --years 1      # 1 year
  PYTHONPATH=src python -m data_collection.kite.backfill_intraday --symbols RELIANCE TCS   # test a few
"""

import os

from data_collection.paths import ROOT_DIR
import sys
import time
import argparse
from datetime import date, timedelta

import pandas as pd
from kiteconnect.exceptions import TokenException

from data_collection.kite.auth import get_kite_client
from data_collection.kite.instruments import download_instruments
from data_collection.nse.universe import get_all_nse_eq_symbols

INTERVAL = "5minute"
WINDOW_DAYS = 100          # Kite's max window for 5-min
REQ_SLEEP = 0.35           # ~3 req/sec, under Kite's historical limit
RETRY_SLEEP = 2.0          # backoff on transient network errors
MAX_RETRIES = 3

OUT_DIR = os.path.join(ROOT_DIR, "data", "parquet", "intraday_5m")
IDX_DIR = os.path.join(OUT_DIR, "_indices")

# Index tradingsymbols as they appear in Kite's NSE instrument master.
# Stored under _indices/ with a filesystem-safe name.
INDICES = {
    "NIFTY_50":        "NIFTY 50",
    "NIFTY_BANK":      "NIFTY BANK",
    "NIFTY_MIDCAP_100": "NIFTY MIDCAP 100",
    "NIFTY_SMLCAP_100": "NIFTY SMLCAP 100",
    "NIFTY_500":       "NIFTY 500",
}


def build_token_map():
    """One pass over the instrument master → {tradingsymbol: instrument_token}.

    Avoids re-reading the CSV per symbol (get_instrument_token does that 2100x).
    """
    df = download_instruments("NSE")
    return dict(zip(df["tradingsymbol"], df["instrument_token"].astype(int)))


def _to_date(d):
    return date.fromisoformat(d) if isinstance(d, str) else d


def fetch_5min(kite, token, from_date, to_date):
    """Fetch 5-min candles for one instrument, chunked under the 100-day window.

    Returns a DataFrame (date, open, high, low, close, volume) or empty. The
    'date' column keeps Kite's IST tz-aware timestamps — intraday needs the
    time-of-day, so we do NOT normalise to a calendar date here.
    """
    start, end = _to_date(from_date), _to_date(to_date)
    candles = []
    chunk_start = start
    while chunk_start <= end:
        chunk_end = min(chunk_start + timedelta(days=WINDOW_DAYS - 1), end)
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                candles.extend(kite.historical_data(
                    instrument_token=token,
                    from_date=chunk_start.isoformat(),
                    to_date=chunk_end.isoformat(),
                    interval=INTERVAL,
                ))
                break
            except TokenException:
                raise  # token dead — let the caller abort the whole run
            except Exception as e:
                if attempt == MAX_RETRIES:
                    raise
                print(f"    retry {attempt} ({chunk_start}..{chunk_end}): {e}")
                time.sleep(RETRY_SLEEP * attempt)
        chunk_start = chunk_end + timedelta(days=1)
        time.sleep(REQ_SLEEP)
    return pd.DataFrame(candles)


def _existing_last_date(path):
    """Latest calendar date already stored, or None. Cheap: reads one column."""
    if not os.path.exists(path):
        return None
    d = pd.read_parquet(path, columns=["date"])["date"]
    if d.empty:
        return None
    return pd.to_datetime(d).max().date()


def backfill_one(kite, name, token, save_path, from_date, to_date):
    """Fetch (or top up) one instrument and write parquet. Returns status str."""
    last = _existing_last_date(save_path)
    if last is not None and last >= to_date - timedelta(days=4):
        return "skip (current)"

    fetch_from = (last + timedelta(days=1)) if last else from_date
    new = fetch_5min(kite, token, fetch_from, to_date)
    if new.empty:
        return "no data" if last is None else "skip (no new)"

    new["symbol"] = name
    if last is not None:
        old = pd.read_parquet(save_path)
        new = pd.concat([old, new], ignore_index=True)
        new = new.drop_duplicates(subset=["date"]).sort_values("date")

    os.makedirs(os.path.dirname(save_path), exist_ok=True)
    new.to_parquet(save_path, index=False)
    return f"{len(new)} bars"


def run(symbols, years, only=None):
    os.makedirs(OUT_DIR, exist_ok=True)
    os.makedirs(IDX_DIR, exist_ok=True)

    to_date = date.today()
    from_date = to_date - timedelta(days=int(round(years * 365)))
    kite = get_kite_client()
    token_map = build_token_map()

    # (display_name, kite_token, output_path) work list — indices first.
    work = []
    if only in (None, "indices"):
        for name, tsym in INDICES.items():
            if tsym in token_map:
                work.append((name, token_map[tsym], os.path.join(IDX_DIR, f"{name}.parquet")))
            else:
                print(f"index not in master, skipping: {tsym}")
    if only in (None, "stocks"):
        for sym in symbols:
            if sym in token_map:
                work.append((sym, token_map[sym], os.path.join(OUT_DIR, f"{sym}.parquet")))

    total = len(work)
    print(f"Backfilling {INTERVAL} for {total} instruments, {from_date} → {to_date}")
    done = failed = 0
    for i, (name, token, path) in enumerate(work, 1):
        try:
            status = backfill_one(kite, name, token, path, from_date, to_date)
            print(f"[{i}/{total}] {name}: {status}")
            done += 1
        except TokenException:
            print(f"\nTOKEN EXPIRED at {name}. Refresh: PYTHONPATH=src python -m data_collection.kite.auth — then re-run "
                  f"(finished symbols are skipped).")
            sys.exit(1)
        except Exception as e:
            print(f"[{i}/{total}] {name}: ERROR {e}")
            failed += 1
    print(f"\nDone. {done} ok, {failed} errored, out of {total}.")


def main():
    ap = argparse.ArgumentParser(description="Backfill 5-min OHLCV for NSE universe + indices.")
    ap.add_argument("--years", type=float, default=2.0, help="History depth in years (default 2).")
    ap.add_argument("--symbols", nargs="*", help="Specific symbols instead of full universe (test mode).")
    ap.add_argument("--only", choices=["stocks", "indices"], help="Restrict to stocks or indices only.")
    args = ap.parse_args()

    symbols = args.symbols if args.symbols else get_all_nse_eq_symbols()
    run(symbols, args.years, only=args.only)


if __name__ == "__main__":
    main()
