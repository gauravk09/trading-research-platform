"""
updater.py — Daily incremental update job

What it does:
  1. For each symbol, checks the last date stored in Parquet
  2. Fetches only the missing days from Kite (incremental, not full re-download)
  3. Appends new rows to the Parquet file
  4. Downloads today's NSE bhavcopy and cross-checks close prices against Kite data
  5. Flags any discrepancies above a threshold (default 0.5%)

Run daily after market close:
    python src/updater.py

This replaces the historical bulk-fetch in collect_data.py for day-to-day use.
"""

import os
import sys
import time
import pandas as pd
from datetime import date, datetime, time as dtime, timedelta
from zoneinfo import ZoneInfo

sys.path.insert(0, os.path.dirname(__file__))

from storage import write_daily, read_daily, get_last_date, list_stored_symbols
from auth import get_kite_client
from instruments import download_instruments
from nse_bhavcopy import download_bhavcopy
from nse_universe import get_all_nse_eq_symbols

CHUNK = 2000


# NSE main-board series that trade the SAME underlying under a suffixed symbol.
# Kite lists e.g. "MTARTECH-BE" (Trade-to-Trade) while our store keys on "MTARTECH".
# SME series (SM/ST/SZ) are deliberately excluded — different board, not our universe.
EQUITY_SERIES_SUFFIXES = {"BE", "BZ", "BT"}


def _build_token_map() -> dict:
    """
    Load the instruments CSV once and return a {symbol: instrument_token} dict.
    Called once at the start of a run — not per symbol.

    Kite suffixes the trading series onto the symbol (SYMBOL-BE for Trade-to-Trade),
    so a stock moving into T2T would otherwise stop matching our plain symbol and
    silently freeze. We alias the allow-listed series back to the base symbol.
    A plain-EQ tradingsymbol always wins over an alias (setdefault), and only the
    allow-listed suffixes are stripped, so real hyphenated names (BAJAJ-AUTO,
    NAM-INDIA) keep matching on their exact tradingsymbol.
    """
    df = download_instruments("NSE")
    eq = df[(df["instrument_type"] == "EQ") & (df["segment"] == "NSE")]
    pairs = list(zip(eq["tradingsymbol"].str.upper(), eq["instrument_token"].astype(int)))

    token_map = {ts: token for ts, token in pairs}
    for ts, token in pairs:
        base, _, series = ts.partition("-")
        if series in EQUITY_SERIES_SUFFIXES:
            token_map.setdefault(base, token)
    return token_map


def fetch_new_candles(
    kite,
    token: int,
    symbol: str,
    from_date: date,
    to_date: date,
) -> pd.DataFrame:
    """
    Fetch daily OHLCV from Kite for the given date range.
    Chunked to stay within Kite's 2000-day per-request limit.
    kite and token are passed in — created once per run, not per symbol.
    """
    all_candles = []
    chunk_start = from_date

    while chunk_start <= to_date:
        chunk_end = min(chunk_start + timedelta(days=CHUNK - 1), to_date)
        candles = kite.historical_data(
            instrument_token=token,
            from_date=chunk_start.isoformat(),
            to_date=chunk_end.isoformat(),
            interval="day"
        )
        all_candles.extend(candles)
        chunk_start = chunk_end + timedelta(days=1)
        time.sleep(0.12)

    if not all_candles:
        return pd.DataFrame()

    df = pd.DataFrame(all_candles)
    df["symbol"] = symbol
    return df


def last_completed_session(now: datetime = None) -> date:
    """
    Latest day whose daily candle is final: today once the close is in
    (15:45 IST), otherwise the previous weekday. Fetching only up to this date
    keeps a midday run from storing today's half-formed candle, which the
    incremental update would never re-fetch. Holidays need no handling — Kite
    simply returns no candle for them.
    """
    now = now or datetime.now(ZoneInfo("Asia/Kolkata"))
    d = now.date() if now.time() >= dtime(15, 45) else now.date() - timedelta(days=1)
    while d.weekday() >= 5:
        d -= timedelta(days=1)
    return d


def update_symbol(
    symbol: str,
    today: date,
    kite,
    token_map: dict,
) -> str:
    """
    Incrementally update one symbol's Parquet file.
    Only fetches candles after the last stored date.

    Returns:
        "updated"  — new rows added
        "current"  — already up to date, nothing to fetch
        "error"    — fetch failed
        "new"      — no history stored yet, full fetch from 2015
    """
    token = token_map.get(symbol.upper())
    if token is None:
        return "error"

    last_date = get_last_date(symbol)

    if last_date is None:
        from_date = date(2015, 1, 1)
        status = "new"
    else:
        last_date_d = last_date.date() if hasattr(last_date, "date") else last_date
        if last_date_d >= today:
            return "current"
        from_date = last_date_d + timedelta(days=1)
        status = "updated"

    try:
        new_df = fetch_new_candles(kite, token, symbol, from_date, today)
        if new_df.empty:
            return "current"

        existing = read_daily(symbol)

        # Split/bonus guard: Kite serves prices adjusted as of today, so after a
        # corporate action the new candles won't line up with stored history.
        # A >35% jump at the seam means the stored rows are now stale-adjusted —
        # re-fetch the full history instead of appending a fake price break.
        if not existing.empty:
            last_close = float(existing["close"].iloc[-1])
            first_new_close = float(new_df.sort_values("date")["close"].iloc[0])
            if last_close > 0 and abs(first_new_close / last_close - 1) > 0.35:
                print(f"  {symbol}: {last_close} → {first_new_close} at append seam "
                      f"— likely split/bonus, re-fetching full history")
                full_df = fetch_new_candles(kite, token, symbol, date(2015, 1, 1), today)
                if not full_df.empty:
                    write_daily(symbol, full_df)
                    return "refetched"

        combined = pd.concat([existing, new_df], ignore_index=True) if not existing.empty else new_df
        write_daily(symbol, combined)
        return status

    except Exception as e:
        print(f"  ERROR {symbol}: {e}")
        return "error"


def reconcile_with_bhavcopy(bhavcopy_df: pd.DataFrame, threshold_pct: float = 0.5) -> pd.DataFrame:
    """
    Cross-check today's Kite close prices against NSE bhavcopy close prices.

    A price mismatch is only meaningful when both sources are on the SAME day.
    If a stock's stored Kite row hasn't reached the bhavcopy trade date, its last
    close is stale — that is a fetch/coverage problem, not a price disagreement,
    and reporting the stale-vs-fresh gap as a "discrepancy" is misleading. We
    therefore compare only same-day rows and label the rest "stale".

    Args:
        bhavcopy_df:   DataFrame from download_bhavcopy()
        threshold_pct: flag if abs(kite_close - bhav_close) / bhav_close > threshold

    Returns:
        DataFrame with columns: symbol, status, kite_close, bhav_close, diff_pct,
        kite_last_date. status is "discrepancy" (same-day, over threshold) or
        "stale" (Kite not updated to the bhavcopy date). diff_pct is NaN for stale.
    """
    if bhavcopy_df.empty:
        return pd.DataFrame()

    # Kite's daily "close" is the last traded price, so reconcile against the
    # bhavcopy LTP (lastpric) for a like-for-like check. clspric is NSE's session
    # close (last-30-min VWAP); it differs from the last trade on illiquid names and
    # would flag those as false discrepancies while adding nothing to genuine-error
    # detection (a missed split or bad tick still differs from the LTP too). Fall
    # back to the session close only when a stock didn't trade (lastpric = 0).
    df = bhavcopy_df.copy()
    symbol_col = next((c for c in df.columns if c in ("tckrsymb", "symbol")), None)
    last_col   = "lastpric" if "lastpric" in df.columns else None
    cls_col    = next((c for c in df.columns if c == "clspric" or c == "close"), None)

    if not symbol_col or not (last_col or cls_col):
        print("  WARN: Could not find symbol/close columns in bhavcopy.")
        return pd.DataFrame()

    # The day Kite must have reached for a fair comparison.
    trade_date = None
    if "traddt" in df.columns:
        trade_date = pd.to_datetime(df["traddt"], errors="coerce").max()
        trade_date = trade_date.date() if pd.notna(trade_date) else None

    nan = pd.Series(float("nan"), index=df.index)
    ltp  = pd.to_numeric(df[last_col], errors="coerce") if last_col else nan
    sess = pd.to_numeric(df[cls_col],  errors="coerce") if cls_col  else nan
    df = pd.DataFrame({
        "symbol":     df[symbol_col].str.strip().str.upper(),
        "bhav_close": ltp.where(ltp.fillna(0) > 0, sess),
    }).dropna(subset=["bhav_close"])

    rows = []
    for _, row in df.iterrows():
        symbol = row["symbol"]
        bhav_close = row["bhav_close"]

        kite_df = read_daily(symbol, columns=["date", "close"])
        if kite_df.empty:
            continue

        # Compare as plain dates to sidestep any IST/naive tz mismatch on the seam.
        kite_last_date = pd.to_datetime(kite_df.iloc[-1]["date"]).date()
        kite_close = kite_df.iloc[-1]["close"]

        if trade_date is not None and kite_last_date != trade_date:
            rows.append({
                "symbol": symbol, "status": "stale",
                "kite_close": round(kite_close, 2), "bhav_close": round(bhav_close, 2),
                "diff_pct": float("nan"), "kite_last_date": kite_last_date,
            })
            continue

        diff_pct = abs(kite_close - bhav_close) / bhav_close * 100
        if diff_pct > threshold_pct:
            rows.append({
                "symbol": symbol, "status": "discrepancy",
                "kite_close": round(kite_close, 2), "bhav_close": round(bhav_close, 2),
                "diff_pct": round(diff_pct, 2), "kite_last_date": kite_last_date,
            })

    if not rows:
        return pd.DataFrame()
    result = pd.DataFrame(rows).sort_values(
        ["status", "diff_pct"], ascending=[True, False]
    )
    return result


def run(symbols: list = None, delay: float = 0.12) -> None:
    """
    Full daily update run:
      1. Incrementally update Kite daily OHLCV for all symbols
      2. Download today's bhavcopy
      3. Reconcile and print discrepancies

    Args:
        symbols: list of symbols to update. Defaults to all stored symbols.
        delay:   seconds between Kite API calls
    """
    today = last_completed_session()
    symbols = symbols or list_stored_symbols()
    total = len(symbols)

    print("Loading Kite client and instrument token map...")
    kite = get_kite_client()
    try:
        kite.profile()
    except Exception as e:
        raise RuntimeError(
            f"Kite auth failed — token is expired or invalid.\n"
            f"Regenerate it via: python src/auth.py\n"
            f"Error: {e}"
        )
    token_map = _build_token_map()
    print(f"  Token map: {len(token_map)} instruments loaded")

    print(f"\nUpdating {total} symbols (incremental — only fetching new days)...")
    counts = {"updated": 0, "current": 0, "new": 0, "refetched": 0, "error": 0}

    for i, symbol in enumerate(symbols, start=1):
        status = update_symbol(symbol, today, kite, token_map)
        counts[status] += 1
        if i % 200 == 0 or status in ("new", "error"):
            print(f"  [{i}/{total}] {symbol}: {status}")

    print(f"\nUpdate summary: {counts}")

    print("\nDownloading NSE bhavcopy for reconciliation...")
    bhav = download_bhavcopy(today)

    if not bhav.empty:
        print("Reconciling Kite vs Bhavcopy prices...")
        result = reconcile_with_bhavcopy(bhav)
        stale = result[result["status"] == "stale"] if not result.empty else result
        discrepancies = result[result["status"] == "discrepancy"] if not result.empty else result

        if not stale.empty:
            names = ", ".join(stale["symbol"].head(30))
            more = f" …and {len(stale) - 30} more" if len(stale) > 30 else ""
            print(f"\n  ⓘ {len(stale)} symbols not updated to today — stale Kite data, "
                  f"NOT a price mismatch (check series-suffix / delisting):")
            print(f"    {names}{more}")

        if discrepancies.empty:
            print("  All same-day prices match — no true discrepancies.")
        else:
            print(f"\n  ⚠  {len(discrepancies)} true same-day price discrepancies (> 0.5%):")
            print(discrepancies.to_string(index=False))

        if not result.empty:
            out_path = os.path.join(
                os.path.dirname(__file__), "..", "output",
                f"reconcile_{today.isoformat()}.csv"
            )
            result.to_csv(out_path, index=False)
            print(f"\n  Saved full reconcile (both buckets) to {out_path}")


if __name__ == "__main__":
    run()
