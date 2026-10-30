"""nse_stock_oi.py — daily per-stock options/futures Open Interest & PCR from the
NSE F&O bhavcopy (stock-level positioning proxy).

Single-name option OI carries more signal than the index PCR the media quotes: a
stock's put/call OI ratio and the day-on-day change in its futures OI are the
cheapest free read on where derivatives positioning is building in THAT name.

Source (free, no key): NSE's daily derivatives bhavcopy — the same archive
nse_fo_bhavcopy.py already reads for NIFTY futures, but here every EQ underlying
is aggregated, not just the index. Two archive formats:
    2024-07-08 onward : content/fo/BhavCopy_NSE_FO_0_0_0_YYYYMMDD_F_0000.csv.zip  (UDiFF)
    before that       : content/historical/DERIVATIVES/YYYY/MON/foDDMONYYYYbhav.csv.zip

Per underlying per day we store:
    call_oi  — summed OI across all call strikes/expiries
    put_oi   — summed OI across all put strikes/expiries
    pcr      — put_oi / call_oi (NaN when call_oi is 0)
    fut_oi   — summed stock-futures OI (all expiries)

Stored as a long/tidy table (one row per date × symbol) at
data/processed/stock_oi.parquet, mirroring how the other alt-data collectors
write under data/processed. OI change is intentionally NOT stored — it is a
day-on-day diff of fut_oi/pcr the reader derives, so the file stays lean.

No look-ahead: OI is an end-of-session figure published after close and is
aligned to its own trade date, so the value for date D was genuinely knowable at
D's close.

    python src/nse_stock_oi.py            # fetch the last ~10 trading days
    python src/nse_stock_oi.py 120        # backfill ~120 calendar days back
"""

import io
import os
import sys
import time
import zipfile
from datetime import date, timedelta

import pandas as pd
import requests

PROCESSED = os.path.join(os.path.dirname(__file__), "..", "data", "processed")
STOCK_OI = os.path.join(PROCESSED, "stock_oi.parquet")

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/120 Safari/537.36",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept": "text/html,application/xhtml+xml,*/*",
}
UDIFF_FROM = pd.Timestamp("2024-07-08")


def _session() -> requests.Session:
    """NSE hands out the archive cookie only after a homepage visit."""
    s = requests.Session()
    s.get("https://www.nseindia.com", headers=HEADERS, timeout=15)
    return s


def _url(d: date) -> str:
    ts = pd.Timestamp(d)
    if ts >= UDIFF_FROM:
        return ("https://nsearchives.nseindia.com/content/fo/"
                f"BhavCopy_NSE_FO_0_0_0_{ts:%Y%m%d}_F_0000.csv.zip")
    mon = f"{ts:%b}".upper()
    return ("https://nsearchives.nseindia.com/content/historical/DERIVATIVES/"
            f"{ts:%Y}/{mon}/fo{ts:%d}{mon}{ts:%Y}bhav.csv.zip")


def _aggregate(df: pd.DataFrame, ts: date) -> pd.DataFrame:
    """Collapse a full F&O bhavcopy into one row per stock underlying.

    Handles both archive layouts. Index instruments (NIFTY/BANKNIFTY etc.) are
    dropped by keeping only the stock instrument types, so the result is purely
    the single-name universe the scans rank."""
    if "TckrSymb" in df.columns:                                    # UDiFF
        sym, oi, opt = "TckrSymb", "OpnIntrst", "OptnTp"
        opt_tp, fut_tp = {"STO"}, {"STF"}
        tp = df["FinInstrmTp"]
    else:                                                           # legacy
        sym, oi, opt = "SYMBOL", "OPEN_INT", "OPTION_TYP"
        opt_tp, fut_tp = {"OPTSTK"}, {"FUTSTK"}
        tp = df["INSTRUMENT"]

    df = df.copy()
    df[oi] = pd.to_numeric(df[oi], errors="coerce").fillna(0)
    df[sym] = df[sym].astype(str).str.strip()
    opt_type = df[opt].astype(str).str.strip().str.upper()

    opts = df[tp.isin(opt_tp)]
    calls = opts[opt_type.loc[opts.index] == "CE"].groupby(sym)[oi].sum()
    puts = opts[opt_type.loc[opts.index] == "PE"].groupby(sym)[oi].sum()
    futs = df[tp.isin(fut_tp)].groupby(sym)[oi].sum()

    out = pd.DataFrame({"call_oi": calls, "put_oi": puts, "fut_oi": futs}).fillna(0)
    if out.empty:
        return out
    out["pcr"] = out["put_oi"].where(out["call_oi"] > 0) / out["call_oi"]
    out = out.reset_index().rename(columns={sym: "symbol"})
    out.insert(0, "date", pd.Timestamp(ts, tz="Asia/Kolkata"))
    return out[["date", "symbol", "call_oi", "put_oi", "pcr", "fut_oi"]]


def download_oi(for_date: date, session: requests.Session = None) -> pd.DataFrame:
    """Per-stock OI/PCR for one day. Empty frame on weekend/holiday/missing file."""
    if for_date.weekday() >= 5:
        return pd.DataFrame()
    s = session or _session()
    r = s.get(_url(for_date), headers=HEADERS, timeout=30)
    if r.status_code == 404 or len(r.content) < 2000:
        return pd.DataFrame()
    r.raise_for_status()
    z = zipfile.ZipFile(io.BytesIO(r.content))
    df = pd.read_csv(z.open(z.namelist()[0]))
    return _aggregate(df, for_date)


def load() -> pd.DataFrame:
    """The stored long OI table (date × symbol rows). Empty if nothing stored."""
    return pd.read_parquet(STOCK_OI) if os.path.exists(STOCK_OI) else pd.DataFrame()


def update(days: int = 10) -> None:
    """Fetch OI for the last `days` calendar days not already stored and append.
    Idempotent — stored dates are skipped, so it's safe to re-run nightly. One bad
    day is logged and skipped, never aborts the run."""
    existing = load()
    have = set(existing["date"].unique()) if not existing.empty else set()
    s = _session()
    frames = []
    for i in range(days):
        d = date.today() - timedelta(days=i)
        ts = pd.Timestamp(d, tz="Asia/Kolkata")
        if d.weekday() >= 5 or ts in have:
            continue
        try:
            day = download_oi(d, s)
        except Exception as e:                       # noqa: BLE001 — log & continue
            print(f"  {d}: skipped ({type(e).__name__})")
            continue
        if not day.empty:
            frames.append(day)
            print(f"  {d}: {len(day)} underlyings")
        time.sleep(0.4)                              # be polite to NSE
    if not frames:
        print("  stock_oi: up to date")
        return
    combined = pd.concat([existing] + frames, ignore_index=True) if not existing.empty \
        else pd.concat(frames, ignore_index=True)
    combined = combined.drop_duplicates(subset=["date", "symbol"], keep="last") \
                       .sort_values(["date", "symbol"]).reset_index(drop=True)
    os.makedirs(PROCESSED, exist_ok=True)
    combined.to_parquet(STOCK_OI, compression="snappy")
    print(f"  stock_oi {combined.shape}  "
          f"{combined['date'].min().date()} → {combined['date'].max().date()}")


if __name__ == "__main__":
    update(int(sys.argv[1]) if len(sys.argv) > 1 else 10)
