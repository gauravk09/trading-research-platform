"""mf_holdings.py — monthly mutual-fund equity holdings, aggregated per NSE symbol.

Answers one cross-sectional question: which stocks are Indian mutual funds
ACCUMULATING or TRIMMING, month over month? For each equity we sum the value and
quantity held across every disclosed scheme each month; the month-on-month change
in that total is the institutional-demand signal (the reader derives the change —
we only store the monthly level, so the file stays lean, mirroring stock_oi.py).

SOURCE (free, authoritative, no key) — per-AMC monthly portfolio disclosure.
    SEBI mandates every AMC publish FULL scheme portfolios monthly. AMFI itself
    hosts only NAVs (NAVAll.txt), NOT holdings, and there is no clean consolidated
    machine-readable cross-AMC holdings feed (the one free aggregator API, mfdata.in,
    is Cloudflare-walled and its origin was down during build). So we go to the
    source: each AMC's consolidated monthly-portfolio workbook (one .xlsx, one sheet
    per scheme, SEBI-standard columns: Name of the Instrument, ISIN, Industry,
    Quantity, Market value (Rs. in Lakhs), % to AUM).

    This is a top-N AMC registry (AMCS below): SBI, Kotak, ICICI — three of India's
    largest AMCs, each publishing at a URL cleanly predictable from (year, month).
    Each AMC entry is just such a URL builder; download_amc unpacks either shape (a
    single consolidated workbook, or a zip of per-scheme workbooks — ICICI). Together
    they cover ~811 distinct NSE symbols, i.e. the whole liquid universe.

    DELIBERATE STOP AT THREE (decided 2026-08, do not re-litigate without new reason):
    the goal is a cross-sectional RANKING factor. Symbol coverage is already saturated
    at three AMCs — more houses would sharpen the aggregate holding *magnitude*, not
    add *which stocks* are ranked, and the ranking is already stable. Meanwhile every
    additional AMC is a permanent fragility cost: HDFC/Mirae are portal-only (no direct
    file URL), Axis/UTI use per-file doc-id or version-hash URLs, Nippon/ABSL have
    hand-typed inconsistent filename tokens — each needs a bespoke scraper that breaks
    when that AMC redesigns its site. That is rising maintenance against shrinking
    marginal signal. Add a 4th AMC ONLY if a specific fund's holdings must be tracked
    precisely — not to chase "all ~40 AMCs", which is diminishing returns by design.

SYMBOL MAPPING — by ISIN, not name. The workbook names companies ("ICICI Bank
Ltd.") but carries the ISIN, which we inner-join to NSE's EQUITY_L.csv
(ISIN NUMBER -> SYMBOL). ISINs absent from the equity master (debt, G-Secs, TREPS,
foreign, unlisted, BSE-only) are counted and reported as `unmatched`, never
silently dropped — most unmatched rows are the debt legs of hybrid/debt schemes.

LOOK-AHEAD RULE — each month's holdings are keyed to two dates:
    month           = the portfolio AS-OF month-end (what the level describes).
    disclosure_date = month-end + 10 days, the SEBI deadline by which the portfolio
                      is published. The data was NOT knowable until disclosure_date,
                      so any backtest must gate use of a month's row on disclosure_date,
                      not on month. We store both; the reader must respect disclosure_date.

Stored at two grains:
  * data/processed/mf_holdings.parquet — one row per (month, amc, symbol), retained
    for the original cross-AMC demand factor.
  * data/processed/mf_scheme_holdings.parquet — one row per
    (month, amc, scheme, symbol), used for fund-specific style, holding-period, and
    accumulation research.
Both are idempotent: stored (month, amc) pairs are skipped independently.

    PYTHONPATH=src python -m data_collection.other.mf_holdings                 # latest available month, seeded AMCs
    PYTHONPATH=src python -m data_collection.other.mf_holdings 2026 7          # a specific (year, month)
    PYTHONPATH=src python -m data_collection.other.mf_holdings 2026 7 2026 1   # backfill an inclusive month range
"""

import calendar
import io
import os

from data_collection.paths import ROOT_DIR
import re
import sys
import zipfile
from datetime import date, timedelta

import pandas as pd
import requests

PROCESSED = os.path.join(ROOT_DIR, "data", "processed")
RAW = os.path.join(ROOT_DIR, "data", "raw")
MF_HOLDINGS = os.path.join(PROCESSED, "mf_holdings.parquet")
MF_SCHEME_HOLDINGS = os.path.join(PROCESSED, "mf_scheme_holdings.parquet")
ISIN_MAP = os.path.join(RAW, "mf_equity_isin_map.csv")

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/120 Safari/537.36",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept": "text/html,application/xhtml+xml,*/*",
}
ISIN_RE = re.compile(r"^IN[EF][0-9A-Z]{9}$")   # valid ISIN body; equity ISINs are INE...


def _ordinal(day: int) -> str:
    suffix = "th" if 11 <= day <= 13 else {1: "st", 2: "nd", 3: "rd"}.get(day % 10, "th")
    return f"{day}{suffix}"


def _sbi_url(year: int, month: int) -> str:
    """SBI publishes one consolidated all-schemes workbook per month at a URL that
    encodes the month-end date (verified predictable without the version query)."""
    last = calendar.monthrange(year, month)[1]
    mon = calendar.month_name[month].lower()
    return ("https://www.sbimf.com/docs/default-source/scheme-portfolios/"
            f"all-schemes-monthly-portfolio---as-on-{_ordinal(last)}-{mon}-{year}.xlsx")


def _kotak_url(year: int, month: int) -> str:
    """Kotak's consolidated SEBI monthly portfolio (one workbook, one sheet per
    scheme). The folder encodes the month-end date, the filename the month name +
    year (verified predictable for May-2026 onward — Kotak's current URL scheme).
    Header column is 'ISIN Code', matched by _parse_sheet's ISIN-prefix predicate."""
    last = calendar.monthrange(year, month)[1]
    mon = calendar.month_name[month]
    return ("https://vatseelabs-s3.kotakmf.com/FormsDownloads/Portfolios/"
            f"Consolidated-SEBI-Portfolio-as-on-{mon}-{last},-{year}/"
            f"ConsolidatedSEBIPortfolio{mon}{year}.xlsx")


def _icici_url(year: int, month: int) -> str:
    """ICICI Prudential ships a ZIP of per-scheme workbooks (one .xlsx each), NOT a
    single consolidated book — download_amc unpacks it. Month name is spelled in full
    in both the path and filename (verified May-2026 onward). A few older months use
    an abbreviated subdir, e.g. /Apr/; those 404 and are skipped, non-fatal."""
    mon = calendar.month_name[month]
    return ("https://www.icicipruamc.com/blob/downloads/Files/"
            f"Monthly%20Portfolio%20Disclosures/{year}/{mon}/"
            f"Monthly-Portfolio-Disclosure-{mon}-{year}.zip")


# Top-N AMC registry. Each value builds the monthly-workbook URL for (year, month).
# Append more AMCs here to widen coverage; the parser is SEBI-format-generic, and
# download_amc handles both single workbooks (SBI/Kotak) and zip-of-workbooks (ICICI).
AMCS = {"SBI": _sbi_url, "Kotak": _kotak_url, "ICICI": _icici_url}


def _isin_symbol_map() -> pd.Series:
    """ISIN -> NSE trading symbol, from the official NSE EQUITY_L master (cached).
    This is both the equity filter and the name-independent symbol mapping."""
    if not os.path.exists(ISIN_MAP):
        s = requests.Session()
        s.get("https://www.nseindia.com", headers=HEADERS, timeout=15)
        r = s.get("https://nsearchives.nseindia.com/content/equities/EQUITY_L.csv",
                  headers=HEADERS, timeout=30)
        r.raise_for_status()
        df = pd.read_csv(io.BytesIO(r.content))
        df.columns = [c.strip().upper() for c in df.columns]
        os.makedirs(RAW, exist_ok=True)
        df[["ISIN NUMBER", "SYMBOL"]].to_csv(ISIN_MAP, index=False)
    m = pd.read_csv(ISIN_MAP)
    m.columns = [c.strip().upper() for c in m.columns]
    return (m.assign(ISIN=m["ISIN NUMBER"].astype(str).str.strip(),
                     SYMBOL=m["SYMBOL"].astype(str).str.strip())
             .drop_duplicates("ISIN").set_index("ISIN")["SYMBOL"])


def _parse_sheet(df: pd.DataFrame) -> pd.DataFrame:
    """Pull (isin, quantity, market_value_lakh) rows from one SEBI-standard scheme
    sheet. Locates the header row, then keeps every row carrying an ISIN-shaped code
    — equity/debt filtering happens later via the NSE equity ISIN join."""
    header_row = None
    for i in range(min(20, len(df))):
        cells = [str(c).strip().lower() for c in df.iloc[i].tolist()]
        if any(c.startswith("isin") for c in cells) and any("quantity" in c for c in cells):
            header_row = i
            break
    if header_row is None:
        return pd.DataFrame()

    hdr = [str(c).strip().lower() for c in df.iloc[header_row].tolist()]

    def col(pred):
        for j, c in enumerate(hdr):
            if pred(c):
                return j
        return None

    c_isin = col(lambda c: c.startswith("isin"))   # "isin" (SBI) or "isin code" (Kotak)
    c_qty = col(lambda c: "quantity" in c)
    c_val = col(lambda c: "market value" in c)
    if c_isin is None or c_qty is None or c_val is None:
        return pd.DataFrame()

    body = df.iloc[header_row + 1:]
    isin = body.iloc[:, c_isin].astype(str).str.strip()
    keep = body[isin.str.match(ISIN_RE)].copy()
    if keep.empty:
        return pd.DataFrame()
    return pd.DataFrame({
        "isin": keep.iloc[:, c_isin].astype(str).str.strip(),
        "holding_qty": pd.to_numeric(keep.iloc[:, c_qty], errors="coerce"),
        "value_lakh": pd.to_numeric(keep.iloc[:, c_val], errors="coerce"),
    })


def _scheme_name(df: pd.DataFrame, fallback: str) -> str:
    """Find the human-readable scheme name in a workbook's title rows."""
    for i in range(min(15, len(df))):
        row = df.iloc[i].tolist()
        for j, value in enumerate(row):
            text = str(value).strip()
            if not text.lower().startswith("scheme name"):
                continue
            after_colon = text.split(":", 1)[1].strip() if ":" in text else ""
            if after_colon and after_colon.lower() != "nan":
                return after_colon
            for candidate in row[j + 1:]:
                candidate = str(candidate).strip()
                if candidate and candidate.lower() != "nan":
                    return candidate
        for value in row:
            text = str(value).strip()
            match = re.match(r"portfolio\s+of\s+(.+?)\s+as\s+on\b", text,
                             flags=re.IGNORECASE)
            if match:
                return match.group(1).strip()
    return fallback


def _parse_workbook(content: bytes, scheme_label: str = None) -> list:
    """Parse every sheet of one .xlsx workbook into equity-holding frames.
    scheme_label overrides the sheet name — used when the workbook is itself one
    per-scheme file (ICICI) whose filename, not its sheet, names the scheme."""
    book = pd.ExcelFile(io.BytesIO(content))
    frames = []
    for sheet in book.sheet_names:
        raw = book.parse(sheet, header=None)
        rows = _parse_sheet(raw)
        if not rows.empty:
            rows["scheme"] = _scheme_name(raw, scheme_label or sheet)
            frames.append(rows)
    return frames


def download_amc(amc: str, year: int, month: int) -> pd.DataFrame:
    """One AMC's raw equity holdings for a month: one row per (scheme, isin).
    Empty frame if the workbook isn't published yet (403/404).

    Handles two shapes transparently: a single multi-sheet workbook (SBI, Kotak) or
    a ZIP of one-workbook-per-scheme files (ICICI). Both arrive as ZIP bytes — an
    .xlsx is itself a zip — so we open as zip and branch on whether any entry is a
    nested .xlsx: if so it's a container, otherwise the payload is one workbook."""
    r = requests.get(AMCS[amc](year, month), headers=HEADERS, timeout=120)
    if r.status_code in (403, 404) or len(r.content) < 5000:
        return pd.DataFrame()
    r.raise_for_status()

    inner, z = [], None
    try:
        z = zipfile.ZipFile(io.BytesIO(r.content))
        inner = [n for n in z.namelist() if n.lower().endswith((".xlsx", ".xls"))]
    except zipfile.BadZipFile:
        pass  # legacy single .xls — not a zip; parse the raw bytes as one workbook

    frames = []
    if inner:                                    # container zip: one file per scheme
        for n in inner:
            label = os.path.splitext(os.path.basename(n))[0]
            frames += _parse_workbook(z.read(n), label)
    else:                                        # single workbook (multi-sheet)
        frames += _parse_workbook(r.content)
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def _aggregate(raw: pd.DataFrame, amc: str, year: int, month: int) -> dict:
    """Collapse an AMC's (scheme, isin) rows into one row per NSE symbol for the
    month. Returns the tidy frame plus matched/unmatched diagnostics."""
    last = calendar.monthrange(year, month)[1]
    month_end = pd.Timestamp(date(year, month, last), tz="Asia/Kolkata")
    disclosure = pd.Timestamp(date(year, month, last) + timedelta(days=10), tz="Asia/Kolkata")

    isin_to_sym = _isin_symbol_map()
    raw = raw.copy()
    raw["symbol"] = raw["isin"].map(isin_to_sym)

    unmatched = raw[raw["symbol"].isna()]
    matched = raw.dropna(subset=["symbol"])

    if matched.empty:
        agg = pd.DataFrame(columns=["month", "disclosure_date", "amc", "symbol",
                                    "holding_value_cr", "holding_qty", "n_schemes"])
        scheme_agg = pd.DataFrame(columns=["month", "disclosure_date", "amc", "scheme",
                                           "symbol", "holding_value_cr", "holding_qty"])
    else:
        g = matched.groupby("symbol")
        agg = pd.DataFrame({
            "holding_value_cr": g["value_lakh"].sum() / 100.0,   # lakh -> crore (repo convention)
            "holding_qty": g["holding_qty"].sum(),
            "n_schemes": g["scheme"].nunique(),
        }).reset_index()
        agg.insert(0, "amc", amc)
        agg.insert(0, "disclosure_date", disclosure)
        agg.insert(0, "month", month_end)
        agg = agg[["month", "disclosure_date", "amc", "symbol",
                   "holding_value_cr", "holding_qty", "n_schemes"]]

        # Preserve the scheme grain as well as the historical AMC aggregate.  A
        # scheme is the investable decision-making unit needed by investor-style
        # and holding-period research; collapsing it to AMC loses that signal.
        sg = matched.groupby(["scheme", "symbol"])
        scheme_agg = pd.DataFrame({
            "holding_value_cr": sg["value_lakh"].sum() / 100.0,
            "holding_qty": sg["holding_qty"].sum(),
        }).reset_index()
        scheme_agg.insert(0, "amc", amc)
        scheme_agg.insert(0, "disclosure_date", disclosure)
        scheme_agg.insert(0, "month", month_end)
        scheme_agg = scheme_agg[["month", "disclosure_date", "amc", "scheme",
                                 "symbol", "holding_value_cr", "holding_qty"]]

    return {"agg": agg, "scheme_agg": scheme_agg,
            "matched_isins": matched["isin"].nunique(),
            "unmatched_isins": unmatched["isin"].nunique()}


def load() -> pd.DataFrame:
    """The stored long holdings table (month × amc × symbol). Empty if nothing stored."""
    return pd.read_parquet(MF_HOLDINGS) if os.path.exists(MF_HOLDINGS) else pd.DataFrame()


def load_schemes() -> pd.DataFrame:
    """Monthly scheme × symbol holdings (the fund-level research table)."""
    return pd.read_parquet(MF_SCHEME_HOLDINGS) \
        if os.path.exists(MF_SCHEME_HOLDINGS) else pd.DataFrame()


def _stored_pairs(existing: pd.DataFrame) -> set:
    if existing.empty:
        return set()
    return set(zip(existing["month"], existing["amc"]))


def update(months: list = None) -> None:
    """Fetch every (month, amc) not already stored and append. `months` is a list of
    (year, month) tuples; defaults to the two most recently completed months (the
    latest is often not published for the first ~10 days). Idempotent and per-AMC —
    a missing/unpublished workbook is skipped, never aborts the run."""
    if months is None:
        first_of_this = date.today().replace(day=1)
        m1 = first_of_this - timedelta(days=1)              # last completed month
        m0 = m1.replace(day=1) - timedelta(days=1)          # month before that
        months = [(m1.year, m1.month), (m0.year, m0.month)]

    existing = load()
    existing_schemes = load_schemes()
    have = _stored_pairs(existing)
    have_schemes = _stored_pairs(existing_schemes)
    frames, scheme_frames = [], []
    for (year, month) in months:
        month_end = pd.Timestamp(date(year, month, calendar.monthrange(year, month)[1]),
                                 tz="Asia/Kolkata")
        for amc in AMCS:
            need_aggregate = (month_end, amc) not in have
            need_schemes = (month_end, amc) not in have_schemes
            if not need_aggregate and not need_schemes:
                continue
            try:
                raw = download_amc(amc, year, month)
            except Exception as e:                           # noqa: BLE001 — log & continue
                print(f"  {year}-{month:02d} {amc}: skipped ({type(e).__name__})")
                continue
            if raw.empty:
                print(f"  {year}-{month:02d} {amc}: not published yet")
                continue
            res = _aggregate(raw, amc, year, month)
            if need_aggregate:
                frames.append(res["agg"])
            if need_schemes:
                scheme_frames.append(res["scheme_agg"])
            print(f"  {year}-{month:02d} {amc}: {len(res['agg'])} symbols  "
                  f"(matched {res['matched_isins']} isins, unmatched {res['unmatched_isins']})")

    if not frames and not scheme_frames:
        print("  mf_holdings: up to date")
        return

    os.makedirs(PROCESSED, exist_ok=True)
    if frames:
        combined = pd.concat([existing] + frames, ignore_index=True) if not existing.empty \
            else pd.concat(frames, ignore_index=True)
        combined = combined.drop_duplicates(subset=["month", "amc", "symbol"], keep="last") \
                           .sort_values(["month", "amc", "symbol"]).reset_index(drop=True)
        combined.to_parquet(MF_HOLDINGS, compression="snappy")
        print(f"  mf_holdings {combined.shape}  "
              f"{combined['month'].min().date()} → {combined['month'].max().date()}")
    if scheme_frames:
        schemes = pd.concat([existing_schemes] + scheme_frames, ignore_index=True) \
            if not existing_schemes.empty else pd.concat(scheme_frames, ignore_index=True)
        schemes = schemes.drop_duplicates(
            subset=["month", "amc", "scheme", "symbol"], keep="last"
        ).sort_values(["month", "amc", "scheme", "symbol"]).reset_index(drop=True)
        schemes.to_parquet(MF_SCHEME_HOLDINGS, compression="snappy")
        print(f"  mf_scheme_holdings {schemes.shape}  "
              f"{schemes['month'].min().date()} → {schemes['month'].max().date()}")


if __name__ == "__main__":
    args = [int(a) for a in sys.argv[1:]]
    if len(args) == 2:
        update([(args[0], args[1])])
    elif len(args) == 4:
        start = date(args[0], args[1], 1)
        end = date(args[2], args[3], 1)
        step, months = start, []
        while step >= end:
            months.append((step.year, step.month))
            step = (step.replace(day=1) - timedelta(days=1)).replace(day=1)
        update(months)
    else:
        update()
