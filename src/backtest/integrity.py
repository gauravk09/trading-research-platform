"""
integrity.py — Detect and repair split/bonus price breaks in stored history

Kite serves prices adjusted as of the day you fetch them. Our incremental
updater appends new (freshly adjusted) candles onto old stored rows, so a
split or bonus that happens AFTER a symbol's initial download leaves a
permanent fake gap in the stored series (a 1:2 split looks like a -50%
crash). That corrupts returns, ADR, MAs and RS ranks for both live scans
and backtests.

Detection: flag day-over-day close moves beyond a threshold. NSE circuit
limits cap genuine single-day moves at ±20% for most stocks, so anything
beyond ±35% is almost certainly a corporate action or bad data — either
way the fix is the same.

Repair: re-fetch the symbol's FULL history from Kite. Kite returns the
whole series consistently adjusted, so overwriting the file heals the break.

--- Two DIFFERENT corruptions, two DIFFERENT fixes ---

1. Unadjusted split/bonus/demerger  → re-fetch heals it (--scan / --repair).
   Kite re-serves the whole series consistently adjusted.

2. Phantom "stub" rows  → re-fetch does NOT heal it (--scan-stubs / --scrub-stubs).
   For non-trading periods (e.g. before a stock really listed) Kite returns
   fabricated filler bars — a price frozen at a face-value level (0.05, 0.15,
   2.80…) far from where the stock actually trades, sometimes with invented
   volume. A single such row reads as a ~1000x return; a leading run of them
   pins years of fake history before the real listing. Re-fetching just
   re-downloads the same junk, so the only fix is to DROP the rows.

   A stub is a FLAT bar (open==high==low==close) that is either zero-volume
   (no trade happened, so the price is fabricated) OR part of a frozen run
   (identical close to a neighbour) sitting far from the symbol's real price
   regime. Both conditions are required so we never delete a legitimate bar:
   a real 20-bagger's early low prices are not frozen, and a circuit-locked
   day stays within its regime — neither trips the rule.

   Some IPO filler is NON-flat and slips past that rule, so the stub scan also
   cross-checks NSE's DATE OF LISTING: any bar dated before a symbol listed AND
   priced far from its post-listing regime is pre-listing filler and is dropped
   too. The price guard keeps board-migration cases safe — a stock that really
   traded elsewhere before its NSE listing keeps the pre-listing bars that sit
   inside its real price regime. (A symbol whose NSE listing date predates its
   own filler — a suspended-then-relisted name — is NOT caught by the date
   check; those residual rows need manual review.)

Usage:
    python src/backtest/integrity.py --scan
    python src/backtest/integrity.py --repair
    python src/backtest/integrity.py --repair --symbols TATAMOTORS IRFC
    python src/backtest/integrity.py --scan-stubs
    python src/backtest/integrity.py --scrub-stubs --symbols PRIVISCL TIL

Nightly automation: eod_update.py calls repair_recent_breaks() after the
dashboard precompute — a vectorized 22% scan over the last 60 sessions of the
(just-rebuilt) close matrix, auto re-fetch of flagged symbols, and a second
precompute when anything was repaired. Breaks that survive a re-fetch are
genuine moves (F&O stocks have no hard circuit) and are remembered in
data/processed/price_breaks_confirmed.json so they aren't re-fetched nightly.
"""

import json
import os
import sys
import argparse
import pandas as pd
from datetime import date

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from storage import read_daily, write_daily, list_stored_symbols

OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "output")
_PROCESSED = os.path.join(os.path.dirname(__file__), "..", "..", "data", "processed")
CLOSE_MATRIX = os.path.join(_PROCESSED, "close_matrix.parquet")
CONFIRMED_PATH = os.path.join(_PROCESSED, "price_breaks_confirmed.json")

BREAK_THRESHOLD_PCT = 35.0    # full-history CLI scans: pre-2020 F&O crashes are real
RECENT_THRESHOLD_PCT = 22.0   # nightly recent scan: just above the 20% circuit band
RECENT_DAYS = 60

# A frozen flat bar this far from the symbol's real (non-flat) median close is
# fabricated filler, not a trade. Wide bands so genuine re-ratings never trip it.
STUB_LOW_RATIO = 0.2   # <20% of the real regime
STUB_HIGH_RATIO = 5.0  # >5x the real regime

# NSE's official equity master — carries DATE OF LISTING per symbol.
EQUITY_L_URL = "https://nsearchives.nseindia.com/content/equities/EQUITY_L.csv"


def find_price_breaks(symbols: list = None, threshold_pct: float = BREAK_THRESHOLD_PCT) -> pd.DataFrame:
    """
    Scan stored history for day-over-day close moves beyond threshold_pct.

    Returns a DataFrame with one row per break:
        symbol, date, prev_close, close, change_pct, volume_ratio
    volume_ratio (day volume / prior 20-day avg) helps eyeball splits:
    a real split usually shows a volume jump near the split ratio.
    """
    symbols = symbols or list_stored_symbols()
    breaks = []

    for i, symbol in enumerate(symbols, start=1):
        if i % 500 == 0:
            print(f"  Checking [{i}/{len(symbols)}]...")

        df = read_daily(symbol, columns=["date", "close", "volume"])
        if len(df) < 2:
            continue

        change_pct = df["close"].pct_change() * 100
        flagged = change_pct.abs() > threshold_pct
        if not flagged.any():
            continue

        avg_vol = df["volume"].rolling(20).mean().shift(1)
        for idx in df.index[flagged]:
            vol_ratio = df["volume"].iloc[idx] / avg_vol.iloc[idx] if pd.notna(avg_vol.iloc[idx]) and avg_vol.iloc[idx] > 0 else float("nan")
            breaks.append({
                "symbol":       symbol,
                "date":         df["date"].iloc[idx].date(),
                "prev_close":   round(float(df["close"].iloc[idx - 1]), 2),
                "close":        round(float(df["close"].iloc[idx]), 2),
                "change_pct":   round(float(change_pct.iloc[idx]), 1),
                "volume_ratio": round(float(vol_ratio), 1) if pd.notna(vol_ratio) else None,
            })

    if not breaks:
        return pd.DataFrame()
    return pd.DataFrame(breaks).sort_values(["symbol", "date"]).reset_index(drop=True)


def find_recent_breaks(days: int = RECENT_DAYS,
                       threshold_pct: float = RECENT_THRESHOLD_PCT) -> pd.DataFrame:
    """Fast break scan over the processed close matrix (last `days` sessions).

    One vectorized pass instead of 2100 file reads — cheap enough to run
    nightly. Returns [symbol, date, change_pct], empty when clean."""
    if not os.path.exists(CLOSE_MATRIX):
        return pd.DataFrame()
    cm = pd.read_parquet(CLOSE_MATRIX)
    chg = (cm.pct_change(fill_method=None) * 100).tail(days)
    hits = chg.stack()
    hits = hits[hits.abs() > threshold_pct]
    rows = [{"symbol": sym, "date": str(dt)[:10], "change_pct": round(float(v), 1)}
            for (dt, sym), v in hits.items()]
    return pd.DataFrame(rows)


def _load_confirmed() -> set:
    if not os.path.exists(CONFIRMED_PATH):
        return set()
    try:
        with open(CONFIRMED_PATH) as f:
            return set(json.load(f))
    except (json.JSONDecodeError, OSError):
        return set()


def _save_confirmed(confirmed: set) -> None:
    with open(CONFIRMED_PATH, "w") as f:
        json.dump(sorted(confirmed), f, indent=1)


def _break_survives(symbol: str, day: str, threshold_pct: float) -> bool:
    """After a re-fetch, is the flagged day still a >threshold move?
    True means it was a genuine move, not an unadjusted corporate action."""
    df = read_daily(symbol, columns=["date", "close"])
    if df.empty:
        return False
    df = df.set_index(df["date"].astype(str).str[:10])
    chg = df["close"].pct_change() * 100
    return day in chg.index and abs(float(chg.loc[day])) > threshold_pct


def repair_recent_breaks(days: int = RECENT_DAYS,
                         threshold_pct: float = RECENT_THRESHOLD_PCT) -> int:
    """Nightly integrity step: detect recent breaks, re-fetch flagged symbols,
    remember genuine moves so they aren't re-fetched again. Returns the number
    of symbols whose files were rewritten (0 = nothing changed)."""
    breaks = find_recent_breaks(days, threshold_pct)
    if breaks.empty:
        print("  No price breaks detected.")
        return 0

    confirmed = _load_confirmed()
    breaks["key"] = breaks["symbol"] + "|" + breaks["date"]
    todo = breaks[~breaks["key"].isin(confirmed)]
    if todo.empty:
        print(f"  {len(breaks)} break(s) known-genuine — nothing to repair.")
        return 0

    symbols = sorted(todo["symbol"].unique())
    print(f"  {len(todo)} suspicious break(s) in {len(symbols)} symbol(s): {symbols}")
    counts = refetch_full_history(symbols)

    for _, b in todo.iterrows():
        if _break_survives(b["symbol"], b["date"], threshold_pct):
            confirmed.add(b["key"])
            print(f"  {b['symbol']} {b['date']} {b['change_pct']:+.1f}% persists "
                  "after re-fetch — genuine move, remembered.")
    _save_confirmed(confirmed)
    return counts["repaired"]


def refetch_full_history(symbols: list) -> dict:
    """
    Re-download full history (2015 → today) from Kite for the given symbols
    and overwrite their parquet files with consistently adjusted data.
    """
    from auth import get_kite_client
    from updater import _build_token_map, fetch_new_candles, last_completed_session

    kite = get_kite_client()
    kite.profile()  # fail fast if token expired
    token_map = _build_token_map()

    counts = {"repaired": 0, "error": 0}
    today = last_completed_session()

    for i, symbol in enumerate(symbols, start=1):
        token = token_map.get(symbol.upper())
        if token is None:
            print(f"  [{i}/{len(symbols)}] {symbol}: no instrument token (delisted?) — skipped")
            counts["error"] += 1
            continue
        try:
            df = fetch_new_candles(kite, token, symbol, date(2015, 1, 1), today)
            if df.empty:
                print(f"  [{i}/{len(symbols)}] {symbol}: Kite returned no data — skipped")
                counts["error"] += 1
                continue
            write_daily(symbol, df)
            print(f"  [{i}/{len(symbols)}] {symbol}: repaired ({len(df)} rows)")
            counts["repaired"] += 1
        except Exception as e:
            print(f"  [{i}/{len(symbols)}] {symbol}: ERROR {e}")
            counts["error"] += 1

    return counts


def _stub_mask(df: pd.DataFrame) -> pd.Series:
    """Boolean mask of phantom stub rows in a single symbol's OHLCV frame.

    A stub is a FLAT bar (open==high==low==close) that is EITHER zero-volume
    (no trade occurred, so the printed price is fabricated) OR part of a frozen
    run (its close equals a neighbour's) sitting far from the symbol's real
    price regime. Requiring both flatness and one of those tells apart the junk
    (a frozen 0.15 while the stock really trades at 1300, or a zero-volume
    carried price) from a legitimate bar: a real bagger's early low closes move
    day to day (not frozen) and a circuit-locked day stays within its regime
    (not disconnected), so neither is ever flagged.

    The regime anchor is the median of NON-flat closes, so a long stretch of
    flat filler cannot drag the reference toward the junk.
    """
    o, h, l, c = (df[k].astype("float64") for k in ("open", "high", "low", "close"))
    v = df["volume"].astype("int64")
    flat = (o == h) & (h == l) & (l == c)

    real = c[~flat]
    if real.empty:
        return flat & False  # never really traded — nothing to anchor against
    ref = float(real.median())
    if ref <= 0:
        return flat & False

    frozen = (c == c.shift(1)) | (c == c.shift(-1))
    disconnected = (c < STUB_LOW_RATIO * ref) | (c > STUB_HIGH_RATIO * ref)
    return flat & ((v == 0) | (frozen & disconnected))


def _load_listing_dates() -> dict:
    """{symbol: listing_date} from NSE's EQUITY_L master; {} if unreachable.

    Only currently-listed EQ symbols appear, so delisted names simply get no
    listing date and skip the pre-listing check.
    """
    try:
        import io
        import requests
        from nse_announcements import HEADERS
        resp = requests.get(EQUITY_L_URL, headers=HEADERS, timeout=30)
        resp.raise_for_status()
        df = pd.read_csv(io.StringIO(resp.text))
        df.columns = [c.strip() for c in df.columns]
        df["SYMBOL"] = df["SYMBOL"].str.strip()
        listed = pd.to_datetime(df["DATE OF LISTING"], format="%d-%b-%Y", errors="coerce")
        return {s: d.date() for s, d in zip(df["SYMBOL"], listed) if pd.notna(d)}
    except Exception as e:
        print(f"  WARN: could not load NSE listing dates ({e}) — pre-listing check skipped.")
        return {}


def _prelisting_mask(df: pd.DataFrame, listing_date) -> pd.Series:
    """Mask of pre-listing filler: bars dated before the NSE listing date AND
    priced far from the post-listing regime.

    The disconnection guard is what makes this safe for board migrations: a
    stock that really traded on another exchange before its NSE listing keeps
    the pre-listing bars that sit inside its real price regime, and only the
    fabricated filler (a fraction of, or a multiple of, the real price) is
    flagged. A stock whose stored history begins at its listing date (Kite's
    usual behaviour) has no pre-listing bars and is untouched.
    """
    all_false = pd.Series(False, index=df.index)
    if listing_date is None:
        return all_false

    dates = pd.to_datetime(df["date"]).dt.date
    pre = pd.Series([d < listing_date for d in dates], index=df.index)
    if not pre.any():
        return all_false

    c = df["close"].astype("float64")
    post = c[~pre]
    if post.empty:
        return all_false  # nothing after listing to anchor the regime on
    ref = float(post.median())
    if ref <= 0:
        return all_false

    disconnected = (c < STUB_LOW_RATIO * ref) | (c > STUB_HIGH_RATIO * ref)
    return pre & disconnected


def find_stub_rows(symbols: list = None, listing_dates: dict = None,
                   check_listing: bool = True) -> pd.DataFrame:
    """Scan stored history for phantom rows to drop.

    Two independent sources, both fabricated and both un-healable by re-fetch:
      - flat-stub   : frozen/zero-volume flat bars far from the real regime
                      (see _stub_mask)
      - pre-listing : bars dated before the NSE listing date and disconnected
                      from the post-listing regime (see _prelisting_mask)

    Returns one row per hit: symbol, date, close, volume, ref_price, ratio,
    reason. ratio = close / real-median — how far the fabricated price sits
    from where the stock actually trades.
    """
    symbols = symbols or list_stored_symbols()
    if check_listing and listing_dates is None:
        listing_dates = _load_listing_dates()
    listing_dates = listing_dates or {}
    stubs = []

    for i, symbol in enumerate(symbols, start=1):
        if i % 500 == 0:
            print(f"  Checking [{i}/{len(symbols)}]...")

        df = read_daily(symbol, columns=["date", "open", "high", "low", "close", "volume"])
        if len(df) < 2:
            continue

        flat = _stub_mask(df)
        pre = _prelisting_mask(df, listing_dates.get(symbol))
        hit = flat | pre
        if not hit.any():
            continue

        flat_bar = (df["open"] == df["high"]) & (df["high"] == df["low"]) & (df["low"] == df["close"])
        ref = float(df["close"][~flat_bar].median())
        for idx in df.index[hit]:
            close = float(df["close"].iloc[idx])
            stubs.append({
                "symbol":    symbol,
                "date":      df["date"].iloc[idx].date(),
                "close":     round(close, 4),
                "volume":    int(df["volume"].iloc[idx]),
                "ref_price": round(ref, 2) if pd.notna(ref) else None,
                "ratio":     round(close / ref, 4) if ref else None,
                "reason":    "flat-stub" if flat.iloc[idx] else "pre-listing",
            })

    if not stubs:
        return pd.DataFrame()
    return pd.DataFrame(stubs).sort_values(["symbol", "date"]).reset_index(drop=True)


def scrub_stub_rows(symbols: list = None) -> dict:
    """Drop phantom stub rows and rewrite the affected parquet files.

    Unlike a split break, a stub cannot be re-fetched away (Kite re-serves the
    same filler), so the fix is deletion. Dropping a leading run simply starts
    the series at the real listing; dropping an embedded stub closes the fake
    round-trip. Returns {files, rows_dropped}.
    """
    stubs = find_stub_rows(symbols)
    if stubs.empty:
        print("  No stub rows found — stored history looks clean.")
        return {"files": 0, "rows_dropped": 0}

    files = 0
    rows_dropped = 0
    for symbol, grp in stubs.groupby("symbol"):
        df = read_daily(symbol)  # full frame, all columns, for rewrite
        drop_dates = set(grp["date"])
        keep = df[~df["date"].dt.date.isin(drop_dates)]
        n = len(df) - len(keep)
        if n == 0:
            continue
        write_daily(symbol, keep)
        files += 1
        rows_dropped += n
        print(f"  {symbol}: dropped {n} stub row(s)")

    print(f"\nScrubbed {rows_dropped} stub rows across {files} file(s).")
    return {"files": files, "rows_dropped": rows_dropped}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--scan",    action="store_true", help="Detect price breaks, write CSV report")
    parser.add_argument("--repair",  action="store_true", help="Detect + re-fetch flagged symbols from Kite")
    parser.add_argument("--scan-stubs",  action="store_true", help="Detect phantom stub rows, write CSV report")
    parser.add_argument("--scrub-stubs", action="store_true", help="Detect + DROP phantom stub rows from stored files")
    parser.add_argument("--symbols", nargs="+", default=None, help="Limit to specific symbols")
    parser.add_argument("--threshold", type=float, default=BREAK_THRESHOLD_PCT,
                        help=f"Break threshold in %% (default {BREAK_THRESHOLD_PCT})")
    args = parser.parse_args()

    if not (args.scan or args.repair or args.scan_stubs or args.scrub_stubs):
        parser.error("Pass --scan, --repair, --scan-stubs or --scrub-stubs")

    if args.scan_stubs or args.scrub_stubs:
        print("Scanning stored history for phantom stub rows...")
        stubs = find_stub_rows(args.symbols)
        if stubs.empty:
            print("No stub rows found — stored history looks clean.")
            return
        affected = sorted(stubs["symbol"].unique())
        by_reason = stubs["reason"].value_counts().to_dict()
        print(f"\nFound {len(stubs)} stub rows across {len(affected)} symbols "
              f"({by_reason}). Top by count:")
        print(stubs["symbol"].value_counts().head(20).to_string())
        out_path = os.path.join(OUTPUT_DIR, f"stub_rows_{date.today().isoformat()}.csv")
        stubs.to_csv(out_path, index=False)
        print(f"\nReport saved → {out_path}")
        if args.scrub_stubs:
            print(f"\nDropping stub rows from {len(affected)} files...")
            scrub_stub_rows(args.symbols)
        else:
            print("\n(dry run — pass --scrub-stubs to delete these rows)")
        return

    print(f"Scanning stored history for close moves > {args.threshold}%...")
    breaks = find_price_breaks(args.symbols, args.threshold)

    if breaks.empty:
        print("No price breaks found — stored history looks clean.")
        return

    affected = sorted(breaks["symbol"].unique())
    print(f"\nFound {len(breaks)} breaks across {len(affected)} symbols:")
    print(breaks.to_string(index=False))

    out_path = os.path.join(OUTPUT_DIR, f"price_breaks_{date.today().isoformat()}.csv")
    breaks.to_csv(out_path, index=False)
    print(f"\nReport saved → {out_path}")

    if args.repair:
        print(f"\nRe-fetching full history for {len(affected)} symbols...")
        counts = refetch_full_history(affected)
        print(f"\nRepair summary: {counts}")


if __name__ == "__main__":
    main()
