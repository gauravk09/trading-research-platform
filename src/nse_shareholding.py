"""nse_shareholding.py — quarterly shareholding-pattern (Reg 31) + promoter pledge
changes from NSE corporate-filings, as a rolling per-stock parquet.

The *change* is the factor (docs/ALTERNATIVE_DATA_FACTORS.md §4): rising promoter
pledge and falling FII/MF holding are robust downside/vol risk signals — best used
as short-side or exclusion screens, not long alpha. Low turnover (one filing per
stock per quarter).

Sources (free, no key):
  1. NSE shareholding-pattern master API — the feed behind the website's
     "Corporate Filings → Shareholding Pattern" page. Gives symbol, isin,
     promoter %, public %, the period (as-of) date, the broadcast timestamp, and
     a link to the filing's XBRL:
     https://www.nseindia.com/api/corporate-share-holdings-master?index=equities&from_date=DD-MM-YYYY&to_date=DD-MM-YYYY
  2. Each filing's XBRL (nsearchives) — parsed best-effort for the fields the
     master omits: FII %, DII %, mutual-fund %, and promoter pledge %.
NSE blocks bare requests, so a homepage visit mints the archive cookie
(session pattern from nse_stock_oi.py). There is no free CSV archive of these
XBRL detail fields, so the XBRL is fetched per new filing; because the store is
incremental, a nightly run only fetches the handful of filings it hasn't seen.

LOOK-AHEAD (the single most important correctness property here):
Every row is anchored to `disclosure_date` — NSE's `broadcastDate`, when the
pattern was disseminated to the market. The quarter it describes (`as_of_date`)
ends weeks earlier, so a factor must key off `disclosure_date`, NOT `as_of_date`,
or it reads holdings the market could not yet see and injects look-ahead bias.

Stored long/tidy (one row per filing) at
data/processed/shareholding_pattern.parquet. De-duped on `record_id`.

    python src/nse_shareholding.py            # last ~10 days of filings
    python src/nse_shareholding.py 400        # ~400 days back (user backfill; slow — 1 XBRL/filing)
"""

import os
import re
import sys
import time
from datetime import date, timedelta

import pandas as pd
import requests

PROCESSED = os.path.join(os.path.dirname(__file__), "..", "data", "processed")
STORE = os.path.join(PROCESSED, "shareholding_pattern.parquet")

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/120 Safari/537.36",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept": "*/*",
    "Referer": "https://www.nseindia.com/companies-listing/corporate-filings-shareholding-pattern",
}
MASTER_URL = "https://www.nseindia.com/api/corporate-share-holdings-master?index=equities"

# XBRL holding-% tag, read per shareholder-category context. Values are fractions
# (0.5001 = 50.01%), so ×100 on the way out.
PCT_TAG = "ShareholdingAsAPercentageOfTotalNumberOfShares"
PLEDGE_TAG = "EncumberedShareUnderPledgedAsPercentageOfTotalNumberOfShares"
PROMOTER_CTX = "ShareholdingOfPromoterAndPromoterGroup_ContextI"
CTX = {  # our column -> XBRL contextRef whose holding-% we want
    "fii_pct": "InstitutionsForeign_ContextI",
    "dii_pct": "InstitutionsDomestic_ContextI",
    "mf_pct": "MutualFundsOrUTI_ContextI",
}


def _session() -> requests.Session:
    s = requests.Session()
    s.get("https://www.nseindia.com", headers=HEADERS, timeout=15)
    return s


def _extract_xbrl(text: str) -> dict:
    """Best-effort FII/DII/MF % and promoter pledge % from a filing's XBRL.
    Missing category -> NaN (not 0), so 'not disclosed' never reads as 'zero'."""
    pct = dict(re.findall(
        rf'<[^:>]*:{PCT_TAG} contextRef="([^"]+)"[^>]*>([^<]+)<', text))
    pledge = dict(re.findall(
        rf'<[^:>]*:{PLEDGE_TAG} contextRef="([^"]+)"[^>]*>([^<]+)<', text))

    def num(d, key):
        v = pd.to_numeric(d.get(key), errors="coerce")
        return v * 100 if pd.notna(v) else float("nan")

    out = {col: num(pct, ctx) for col, ctx in CTX.items()}
    # pledged as % of total shares, reported under the promoter context (0 if the
    # promoter holds shares but none are pledged; NaN only if the tag is absent).
    out["pledged_pct"] = num(pledge, PROMOTER_CTX)
    return out


def download_master(from_d: date, to_d: date, session: requests.Session = None) -> pd.DataFrame:
    """Shareholding-pattern filings broadcast between from_d and to_d. Master
    fields only (no XBRL enrichment) — symbol, isin, promoter %, public %, dates."""
    s = session or _session()
    url = f"{MASTER_URL}&from_date={from_d:%d-%m-%Y}&to_date={to_d:%d-%m-%Y}"
    r = s.get(url, headers=HEADERS, timeout=40)
    r.raise_for_status()
    payload = r.json()
    rows = payload if isinstance(payload, list) else payload.get("data", [])
    if not rows:
        return pd.DataFrame()

    raw = pd.DataFrame(rows)
    out = pd.DataFrame({
        "symbol": raw.get("symbol", pd.NA).astype(str).str.strip(),
        "isin": raw.get("isin"),
        "name": raw.get("name"),
        "record_id": raw.get("recordId"),
        "xbrl": raw.get("xbrl"),
        "promoter_pct": pd.to_numeric(raw.get("pr_and_prgrp"), errors="coerce"),
        "public_pct": pd.to_numeric(raw.get("public_val"), errors="coerce"),
    })
    # LOOK-AHEAD ANCHOR: broadcastDate is when the pattern went public.
    out["disclosure_date"] = pd.to_datetime(
        raw.get("broadcastDate"), format="mixed", dayfirst=True, errors="coerce"
    ).dt.tz_localize("Asia/Kolkata")
    # as_of_date = the quarter the pattern describes (weeks before disclosure).
    out["as_of_date"] = pd.to_datetime(
        raw.get("date"), format="mixed", dayfirst=True, errors="coerce"
    ).dt.tz_localize("Asia/Kolkata")
    return out


def _enrich(df: pd.DataFrame, session: requests.Session) -> pd.DataFrame:
    """Add fii_pct/dii_pct/mf_pct/pledged_pct by parsing each filing's XBRL."""
    extra = []
    for url in df["xbrl"]:
        vals = {c: float("nan") for c in list(CTX) + ["pledged_pct"]}
        if isinstance(url, str) and url.endswith(".xml"):
            try:
                vals = _extract_xbrl(session.get(url, headers=HEADERS, timeout=40).text)
            except Exception:                          # noqa: BLE001 — best-effort
                pass
            time.sleep(0.3)                            # be polite to nsearchives
        extra.append(vals)
    return df.join(pd.DataFrame(extra, index=df.index))


def load() -> pd.DataFrame:
    return pd.read_parquet(STORE) if os.path.exists(STORE) else pd.DataFrame()


def update(days: int = 10) -> None:
    """Fetch shareholding filings from the last `days` days and append. Only
    filings not already stored (by record_id) are XBRL-enriched, so nightly runs
    are cheap; idempotent and safe to re-run."""
    to_d = date.today()
    from_d = to_d - timedelta(days=days)
    s = _session()
    try:
        fresh = download_master(from_d, to_d, s)
    except Exception as e:                             # noqa: BLE001 — log & continue
        print(f"  shareholding: fetch failed ({type(e).__name__})")
        return
    if fresh.empty:
        print("  shareholding: nothing returned")
        return

    existing = load()
    if not existing.empty:
        have = set(existing["record_id"].astype(str))
        fresh = fresh[~fresh["record_id"].astype(str).isin(have)]
    if fresh.empty:
        print("  shareholding: up to date")
        return

    fresh = _enrich(fresh, s)
    combined = pd.concat([existing, fresh], ignore_index=True) if not existing.empty else fresh
    combined = combined.drop_duplicates(subset=["record_id"], keep="last") \
                       .sort_values(["disclosure_date", "symbol"]).reset_index(drop=True)
    os.makedirs(PROCESSED, exist_ok=True)
    combined.to_parquet(STORE, compression="snappy")
    print(f"  shareholding_pattern {combined.shape}  "
          f"{combined['disclosure_date'].min().date()} → "
          f"{combined['disclosure_date'].max().date()}  (+{len(fresh)} new)")


if __name__ == "__main__":
    update(int(sys.argv[1]) if len(sys.argv) > 1 else 10)
