"""
nse_financial_results.py — Official NSE quarterly financial results

Fetches the per-symbol results listing from NSE, downloads each filing
(XBRL for ~2019+, old HTML result tables before that) and parses it into
one row per (symbol, quarter, consolidated/standalone):
    revenue_cr, other_income_cr, pbt_cr, pat_cr, eps_basic, eps_diluted

Raw filings are cached under data/raw/financials/<SYMBOL>/ so a re-parse
never re-downloads.
"""

import io
import json
import os

from data_collection.paths import ROOT_DIR
import re
import time
import urllib.parse
import xml.etree.ElementTree as ET
from datetime import datetime

import pandas as pd
import requests

RAW_DIR = os.path.join(ROOT_DIR, "data", "raw", "financials")
os.makedirs(RAW_DIR, exist_ok=True)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.nseindia.com/",
}

RESULTS_URL = "https://www.nseindia.com/api/corporates-financial-results?index=equities&symbol={symbol}&period=Quarterly"
# Insurance companies (HDFCLIFE, LICI, ICICIGI, ...) file under a separate
# index and never appear in the equities listing.
INSURANCE_RESULTS_URL = "https://www.nseindia.com/api/corporates-financial-results?index=insurance&symbol={symbol}&period=Quarterly"
# SEBI's Integrated Filing framework took over for quarters ending on/after
# 31-Dec-2024: newer results only exist under this endpoint. The XBRL inside
# uses the in-capmkt taxonomy but identical tag localnames and the same
# OneD-quarter convention, so parse_xbrl works unchanged.
INTEGRATED_URL = "https://www.nseindia.com/api/integrated-filing-results?index=equities&period=Quarterly&symbol={symbol}"


def make_session() -> requests.Session:
    session = requests.Session()
    session.headers.update(HEADERS)
    session.get("https://www.nseindia.com", timeout=10)
    return session


def _get(session: requests.Session, url: str, retries: int = 3) -> requests.Response:
    """GET with retry + session refresh on NSE's cookie-expiry 401/403s."""
    for attempt in range(retries):
        try:
            response = session.get(url, timeout=20)
            if response.status_code in (401, 403):
                session.get("https://www.nseindia.com", timeout=10)
                continue
            return response
        except requests.RequestException:
            if attempt == retries - 1:
                raise
            time.sleep(2 * (attempt + 1))
    return response


def _fetch_listing(session: requests.Session, url: str) -> list:
    response = _get(session, url)
    if response.status_code != 200:
        return None
    records = response.json()
    return records if isinstance(records, list) else []


def _normalize_insurance(records: list) -> list:
    """Reshape insurance-index records to the equities-record fields we use.

    Insurance records have periodEnd instead of fromDate/toDate, broadCastDate
    instead of filingDate, and no seqNumber (the XBRL filename stands in as a
    stable cache key).
    """
    for record in records:
        record["toDate"] = record.get("periodEnd")
        record["filingDate"] = record.get("broadCastDate")
        xbrl_name = os.path.basename(record.get("xbrl") or "")
        record["seqNumber"] = os.path.splitext(xbrl_name)[0] or "unknown"
    return records


def list_results(session: requests.Session, symbol: str) -> list:
    """All quarterly filings NSE has for a symbol (cached to disk)."""
    symbol_dir = os.path.join(RAW_DIR, symbol)
    os.makedirs(symbol_dir, exist_ok=True)
    listing_path = os.path.join(symbol_dir, "listing.json")
    if os.path.exists(listing_path):
        with open(listing_path) as f:
            return json.load(f)
    # quote() matters: symbols like ARE&M / M&M would otherwise split the query
    quoted = urllib.parse.quote(symbol, safe="")
    records = _fetch_listing(session, RESULTS_URL.format(symbol=quoted))
    if records is None:
        return []
    if not records:
        insurance = _fetch_listing(session, INSURANCE_RESULTS_URL.format(symbol=quoted))
        if insurance:
            records = _normalize_insurance(insurance)
    with open(listing_path, "w") as f:
        json.dump(records, f)
    return records


def _adapt_integrated(record: dict) -> dict:
    """Reshape an integrated-filing record to the equities-record fields we use."""
    end = datetime.strptime(record["qe_Date"], "%d-%b-%Y")
    start_month = end.month - 2
    start_year = end.year
    if start_month < 1:
        start_month += 12
        start_year -= 1
    return {
        "symbol": record["symbol"],
        "toDate": record["qe_Date"],
        "fromDate": datetime(start_year, start_month, 1).strftime("%d-%b-%Y"),
        "seqNumber": f"IF{record.get('seq_Id', 'unknown')}",
        "xbrl": record.get("xbrl"),
        "consolidated": record.get("consolidated"),
        "filingDate": record.get("broadcast_Date"),
        "audited": record.get("audited"),
        "relatingTo": None,
    }


def list_integrated_results(session: requests.Session, symbol: str,
                            refresh: bool = False) -> list:
    """Integrated-filing financials for a symbol (quarters after Dec-2024).

    Cached separately from the legacy listing; pass refresh=True to re-pull
    (the legacy archive is frozen, but this listing grows every quarter).
    """
    symbol_dir = os.path.join(RAW_DIR, symbol)
    os.makedirs(symbol_dir, exist_ok=True)
    listing_path = os.path.join(symbol_dir, "listing_if.json")
    if os.path.exists(listing_path) and not refresh:
        with open(listing_path) as f:
            return json.load(f)
    quoted = urllib.parse.quote(symbol, safe="")
    response = _get(session, INTEGRATED_URL.format(symbol=quoted))
    if response.status_code != 200:
        return []
    payload = response.json()
    records = [_adapt_integrated(r) for r in payload.get("data", [])
               if r.get("type") == "Integrated Filing- Financials" and r.get("qe_Date")]
    with open(listing_path, "w") as f:
        json.dump(records, f)
    return records


def fetch_filing(session: requests.Session, symbol: str, record: dict) -> tuple:
    """Download a filing, preferring XBRL. Returns (kind, text) or (None, None).

    kind is "xbrl" or "html". Raw body is cached per seqNumber.
    """
    symbol_dir = os.path.join(RAW_DIR, symbol)
    os.makedirs(symbol_dir, exist_ok=True)
    seq = record.get("seqNumber", "unknown")

    for kind, url in (("xbrl", record.get("xbrl")), ("html", record.get("resultDetailedDataLink"))):
        if not url:
            continue
        cache_path = os.path.join(symbol_dir, f"{seq}.{kind}")
        miss_path = cache_path + ".404"
        if os.path.exists(cache_path):
            with open(cache_path, encoding="utf-8", errors="ignore") as f:
                return kind, f.read()
        if os.path.exists(miss_path):
            continue
        response = _get(session, url)
        time.sleep(0.5)
        if response.status_code == 200 and len(response.text) > 500:
            with open(cache_path, "w", encoding="utf-8") as f:
                f.write(response.text)
            return kind, response.text
        open(miss_path, "w").close()
    return None, None


# ---------------------------------------------------------------- XBRL parsing

# XBRL tag localname -> intermediate key (values in rupees; converted to
# crore on output). Non-financial companies and banks file under different
# taxonomies, so several tags can feed one output column — resolved by
# priority in parse_xbrl.
XBRL_TAGS = {
    "RevenueFromOperations": "revenue",
    "InterestEarned": "revenue_bank",
    "OtherIncome": "other_income",
    "ProfitBeforeTax": "pbt",
    "ProfitLossFromOrdinaryActivitiesBeforeTax": "pbt_bank",
    "ProfitLossForPeriod": "pat",
    "ProfitLossForPeriodFromContinuingOperations": "pat_continuing",
    "ProfitLossForThePeriod": "pat_bank",
    "BasicEarningsLossPerShareFromContinuingOperations": "eps_basic",
    "DilutedEarningsLossPerShareFromContinuingOperations": "eps_diluted",
    "BasicEarningsLossPerShareFromContinuingAndDiscontinuedOperations": "eps_basic_total",
    "DilutedEarningsLossPerShareFromContinuingAndDiscontinuedOperations": "eps_diluted_total",
    "BasicEarningsPerShareAfterExtraordinaryItems": "eps_basic_bank",
    "DilutedEarningsPerShareAfterExtraordinaryItems": "eps_diluted_bank",
    # Insurers file IRDAI-format XBRL; life and general insurance are two
    # more taxonomies again. Net premium income stands in for revenue.
    "NetPremiumIncome": "revenue_life",
    "PremiumEarned": "revenue_gi",
    "NetPremiumWritten": "revenue_gi_written",
    "ProfitLossBeforeTax": "pbt_life",
    "ProfitOrLossBeforeTax": "pbt_gi",
    "ProfitLossAfterTaxAndExtraordinaryItems": "pat_life",
    "ProfitLossAfterTax": "pat_gi",
    "BasicAndDilutedEPSAfterExtraordinaryItemsNetOfTaxExpenseForThePeriodNotToBeAnnualized": "eps_insurance",
}


def parse_xbrl(text: str, from_date: str, to_date: str) -> dict:
    """Extract quarter figures from an XBRL instance.

    XBRL files carry several periods (current quarter, YTD, prior year), each
    under a contextRef. We only take facts whose context period matches the
    filing's own fromDate/toDate — grabbing the first match would silently
    return YTD numbers. Insurance-index records carry no fromDate; there the
    context's own duration (≤ 100 days) separates the quarter from YTD.
    """
    try:
        root = ET.fromstring(text)
    except ET.ParseError:
        return {}

    want_start = (datetime.strptime(from_date, "%d-%b-%Y").date().isoformat()
                  if from_date else None)
    want_end = datetime.strptime(to_date, "%d-%b-%Y").date().isoformat()

    quarter_contexts = set()
    for context in root.iter("{http://www.xbrl.org/2003/instance}context"):
        period = context.find("{http://www.xbrl.org/2003/instance}period")
        if period is None:
            continue
        start = period.findtext("{http://www.xbrl.org/2003/instance}startDate", "").strip()
        end = period.findtext("{http://www.xbrl.org/2003/instance}endDate", "").strip()
        if end != want_end or not start:
            continue
        if want_start is not None:
            matches = start == want_start
        else:
            days = (datetime.fromisoformat(end) - datetime.fromisoformat(start)).days
            matches = days <= 100
        if matches:
            quarter_contexts.add(context.get("id"))

    def extract(contexts: set) -> dict:
        found = {}
        for element in root.iter():
            localname = element.tag.rsplit("}", 1)[-1]
            column = XBRL_TAGS.get(localname)
            if column is None or element.get("contextRef") not in contexts:
                continue
            try:
                found[column] = float(element.text)
            except (TypeError, ValueError):
                pass
        return found

    # NSE's filing utility always tags the current quarter as contextRef="OneD"
    # (YTD is "FourD"). The context *definitions* can't be trusted: some files
    # never define OneD, others define FourD with the quarter's dates — so
    # period matching would silently return YTD figures. Convention first,
    # period match only as a fallback for non-standard filers.
    values = extract({"OneD"})
    if not values:
        values = extract(quarter_contexts)

    def first(*keys):
        return next((values[k] for k in keys if k in values), None)

    result = {}
    money = {
        "revenue_cr": first("revenue", "revenue_bank", "revenue_life",
                            "revenue_gi", "revenue_gi_written"),
        "other_income_cr": first("other_income"),
        "pbt_cr": first("pbt", "pbt_bank", "pbt_life", "pbt_gi"),
        "pat_cr": first("pat", "pat_continuing", "pat_bank", "pat_life", "pat_gi"),
    }
    for column, value in money.items():
        if value is not None:
            result[column] = value / 1e7
    result["eps_basic"] = first("eps_basic_total", "eps_basic", "eps_basic_bank",
                                "eps_insurance")
    result["eps_diluted"] = first("eps_diluted_total", "eps_diluted",
                                  "eps_diluted_bank", "eps_insurance")
    return result


# ------------------------------------------------------------ old-HTML parsing

# Per-column priority-ordered label patterns. Labels varied across
# years/companies, and several look-alike rows exist (discontinued
# operations, comprehensive income) that must never win over the real one.
HTML_ROW_EXCLUDE = re.compile(r"discontinu|comprehensive|share\s+of\s+profit|minority")
HTML_COLUMN_PATTERNS = {
    "revenue_cr": [
        r"total\s+income\s+from\s+operations",
        r"revenue\s+from\s+operations",
        r"net\s+sales.*income\s+from\s+operations",
        r"interest\s+earned",  # banks
        r"total\s+revenue",
    ],
    "other_income_cr": [r"^other\s+income"],
    "pbt_cr": [
        r"profit.*ordinary\s+activities\s+before\s+tax",
        r"profit.*before\s+tax",
    ],
    "pat_cr": [
        r"net\s+profit.*for\s+the\s+period",
        r"profit.*ordinary\s+activities\s+after\s+tax",
        r"profit.*for\s+the\s+period\s+from\s+continuing",
        r"net\s+profit.*after\s+tax",
    ],
    "eps_basic": [r"basic.*continuing", r"\bbasic\b"],
    "eps_diluted": [r"diluted.*continuing", r"\bdiluted\b"],
}


def parse_old_html(text: str) -> dict:
    """Extract quarter figures from a pre-2019 archived results page.

    These pages are a two-column Description/Amount table for the quarter
    itself. Amounts are usually "Rs. in lakhs"; the unit is read from the
    header row and everything is normalised to crore.
    """
    try:
        tables = pd.read_html(io.StringIO(text))
    except ValueError:
        return {}
    table = max(tables, key=len)
    if table.shape[1] < 2:
        return {}
    table = table.astype(str)

    header_text = " ".join(table.iloc[0]).lower()
    if "lakh" in header_text:
        to_crore = 1 / 100
    elif "million" in header_text:
        to_crore = 1 / 10
    elif "crore" in header_text:
        to_crore = 1.0
    else:
        to_crore = 1 / 100  # NSE's old format default

    rows = []
    for _, row in table.iterrows():
        label = row.iloc[0].strip().lower()
        if HTML_ROW_EXCLUDE.search(label):
            continue
        try:
            rows.append((label, float(row.iloc[1].replace(",", "").strip())))
        except ValueError:
            continue

    result = {}
    for column, patterns in HTML_COLUMN_PATTERNS.items():
        for pattern in patterns:
            match = next((v for label, v in rows if re.search(pattern, label)), None)
            if match is not None:
                result[column] = match * to_crore if column.endswith("_cr") else match
                break
    return result


# ------------------------------------------------------------------- assembly

def parse_record(session: requests.Session, symbol: str, record: dict) -> dict:
    """One filing -> one output row (or None if the filing is unreachable)."""
    kind, text = fetch_filing(session, symbol, record)
    if kind == "xbrl":
        values = parse_xbrl(text, record.get("fromDate"), record["toDate"])
    elif kind == "html":
        values = parse_old_html(text)
    else:
        return None
    row = {
        "symbol": symbol,
        "quarter_end": datetime.strptime(record["toDate"], "%d-%b-%Y").date(),
        "relating_to": record.get("relatingTo"),
        "consolidated": record.get("consolidated") == "Consolidated",
        "audited": record.get("audited"),
        "filing_date": record.get("filingDate"),
        "source": kind,
    }
    row.update(values)
    return row


def dedupe_filings(df: pd.DataFrame) -> pd.DataFrame:
    """Keep the latest filing per (symbol, quarter, consolidated).

    filing_date must be sorted as a real datetime — as a string,
    '15-Jul-2026' sorts before '22-Apr-2024' and restatements silently lose.
    """
    df = df.assign(_fd=pd.to_datetime(df["filing_date"], dayfirst=True, errors="coerce"))
    return (df.sort_values("_fd")
              .drop_duplicates(subset=["symbol", "quarter_end", "consolidated"], keep="last")
              .drop(columns="_fd")
              .sort_values(["symbol", "quarter_end"])
              .reset_index(drop=True))


def fetch_symbol_financials(session: requests.Session, symbol: str,
                            since_year: int = 2016,
                            refresh_integrated: bool = False) -> pd.DataFrame:
    """All parsed quarterly rows for one symbol from since_year onward.

    Combines the legacy archive (quarters up to Dec-2024) with integrated
    filings (after). Re-filings of a quarter are deduped keeping the latest.
    """
    records = (list_results(session, symbol)
               + list_integrated_results(session, symbol, refresh=refresh_integrated))
    rows = []
    for record in records:
        try:
            quarter_end = datetime.strptime(record["toDate"], "%d-%b-%Y")
        except (KeyError, TypeError, ValueError):
            continue
        if quarter_end.year < since_year:
            continue
        row = parse_record(session, symbol, record)
        if row:
            rows.append(row)
    if not rows:
        return pd.DataFrame()
    return dedupe_filings(pd.DataFrame(rows))
