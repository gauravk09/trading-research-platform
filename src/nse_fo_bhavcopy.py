"""
nse_fo_bhavcopy.py — NIFTY futures closes from the NSE F&O bhavcopy archive

Kite's instrument dump only carries LIVE contracts, so expired futures are
unreachable through the API. NSE's derivatives bhavcopy is the only free
source with full history. Two formats:
    2024-07 onward : content/fo/BhavCopy_NSE_FO_0_0_0_YYYYMMDD_F_0000.csv.zip
    before that    : content/historical/DERIVATIVES/YYYY/MON/foDDMONYYYYbhav.csv.zip

Only the NIFTY FUT rows are kept (3 contracts per day), so the cache stays tiny.
"""

import io
import os
import sys
import time
import zipfile
import pandas as pd
import requests
from concurrent.futures import ThreadPoolExecutor

RAW = os.path.join(os.path.dirname(__file__), "..", "data", "raw", "fo_bhav")
OUT = os.path.join(os.path.dirname(__file__), "..", "data", "processed", "nifty_futures.parquet")
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/120 Safari/537.36",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept": "text/html,application/xhtml+xml,*/*",
}
UDIFF_FROM = pd.Timestamp("2024-07-08")


def _urls(d: pd.Timestamp):
    if d >= UDIFF_FROM:
        return [f"https://nsearchives.nseindia.com/content/fo/"
                f"BhavCopy_NSE_FO_0_0_0_{d:%Y%m%d}_F_0000.csv.zip"]
    mon = f"{d:%b}".upper()
    return [f"https://nsearchives.nseindia.com/content/historical/DERIVATIVES/"
            f"{d:%Y}/{mon}/fo{d:%d}{mon}{d:%Y}bhav.csv.zip"]


def _parse(raw: bytes, d: pd.Timestamp) -> pd.DataFrame:
    z = zipfile.ZipFile(io.BytesIO(raw))
    df = pd.read_csv(z.open(z.namelist()[0]))
    if "TckrSymb" in df.columns:                       # UDiFF
        f = df[(df["TckrSymb"] == "NIFTY") & (df["FinInstrmTp"].isin(["IDF", "FUTIDX"]))]
        out = pd.DataFrame({"date": d, "expiry": pd.to_datetime(f["XpryDt"]),
                            "close": f["ClsPric"], "oi": f["OpnIntrst"]})
    else:                                              # legacy
        f = df[(df["SYMBOL"] == "NIFTY") & (df["INSTRUMENT"] == "FUTIDX")]
        out = pd.DataFrame({"date": d, "expiry": pd.to_datetime(f["EXPIRY_DT"], format="mixed"),
                            "close": f["CLOSE"], "oi": f["OPEN_INT"]})
    return out.dropna().sort_values("expiry")


def fetch_day(session, d: pd.Timestamp):
    cache = os.path.join(RAW, f"{d:%Y%m%d}.parquet")
    if os.path.exists(cache):
        return pd.read_parquet(cache)
    for url in _urls(d):
        try:
            r = session.get(url, headers=HEADERS, timeout=30)
            if r.status_code == 200 and len(r.content) > 2000:
                out = _parse(r.content, d)
                out.to_parquet(cache)
                return out
        except Exception:
            pass
    return None


def fetch_range(dates, workers=4):
    session = requests.Session()
    session.get("https://www.nseindia.com", headers=HEADERS, timeout=15)
    frames, misses = [], 0
    def job(d):
        time.sleep(0.05)
        return fetch_day(session, d)
    with ThreadPoolExecutor(max_workers=workers) as ex:
        for i, res in enumerate(ex.map(job, dates), start=1):
            if res is None or res.empty:
                misses += 1
            else:
                frames.append(res)
            if i % 100 == 0:
                print(f"  [{i}/{len(dates)}] ok={len(frames)} miss={misses}", flush=True)
    df = pd.concat(frames, ignore_index=True)
    df.to_parquet(OUT)
    print(f"saved {len(df)} contract-days to {OUT}  ({misses} dates missing)")
    return df


if __name__ == "__main__":
    sys.path.insert(0, os.path.dirname(__file__))
    close = pd.read_parquet(os.path.join(os.path.dirname(__file__), "..", "output",
                                         "studies", "cache", "close.parquet"))
    days = pd.to_datetime(close.index).tz_localize(None).normalize()
    start = pd.Timestamp(sys.argv[1]) if len(sys.argv) > 1 else pd.Timestamp("2022-01-01")
    fetch_range([d for d in days if d >= start])
