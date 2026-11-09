"""
nse_announcements.py — Download NSE corporate announcements/filings

NSE publishes a daily stream of all corporate filings for listed companies:
earnings results, dividends, board meetings, order wins, acquisitions,
preferential allotments, regulatory disclosures, etc.

Why this matters:
- Episodic Pivot setup needs a CATALYST. This feed tells us what happened.
- Filtered to our universe (Nifty 500) so we only see relevant filings.
- Each filing is tagged with a simple category for fast scanning.
"""

import re
import requests
import pandas as pd
from datetime import date

import data_collection.nse.announcements_store as store

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.nseindia.com/"
}

ANNOUNCEMENTS_URL = "https://www.nseindia.com/api/corporate-announcements?index=equities"

# Simple keyword-based categorization — subject is matched against these patterns
CATEGORY_PATTERNS = {
    "results":          r"financial\s*result|quarterly\s*result|earnings",
    "guidance":         r"guidance|outlook|forecast",
    "dividend":         r"dividend",
    "board_meeting":    r"board\s*meeting|intimation\s*of\s*board",
    "order_win":        r"order\s*win|contract\s*award|bagged|secured\s*order|loa\b|letter\s*of\s*award",
    "acquisition":      r"acquisition|merger|amalgamation|takeover|scheme\s*of\s*arrangement",
    "fundraise":        r"preferential\s*(issue|allotment)|qip|rights\s*issue|fpo|fund\s*rais",
    "buyback":          r"buyback|buy-?back",
    "split_bonus":      r"stock\s*split|sub-?division|bonus\s*(issue|shares)",
    "insider_trade":    r"insider\s*trading|sast|disclosure\s*under\s*reg",
    "credit_rating":    r"credit\s*rating|ratings\s*action",
    "regulatory":       r"approval|clearance|cdsco|fda|usfda|drug|patent|license",
    "analyst_meet":     r"analyst\s*meet|investor\s*meet|conference\s*call|earnings\s*call",
}


def categorize(subject: str, text: str = None) -> str:
    """Classify an announcement into a category using keyword matching.

    NSE retired the 'Financial Result Updates' subject label during 2025 and
    folded those filings under generic subjects ('General Updates', 'Outcome of
    Board Meeting'), which collapsed results tagging from 9,627 filings in 2024
    to 876 in 2026. `text` is the attachment summary NSE started returning in
    2025 ("X has informed the Exchange about Financial Results"); it is matched
    first and the subject is the fallback, so pre-2025 rows with no text behave
    exactly as before.
    """
    for field in (text, subject):
        if not isinstance(field, str) or not field.strip():
            continue
        s = field.lower()
        for category, pattern in CATEGORY_PATTERNS.items():
            if re.search(pattern, s):
                return category
    return "other"


def download_announcements(for_date: date = None) -> pd.DataFrame:
    """
    Download the FULL day of corporate announcements from NSE.
    Defaults to today.

    NOTE: without from_date/to_date the endpoint returns only its latest ~20
    filings — that starved catalyst tagging for months (every cached file was
    exactly 20 rows). The date-range form returns the whole day.

    Returns:
        DataFrame with: symbol, subject, category, broadcast_date, attachment_url
    """
    if for_date is None:
        for_date = date.today()

    cached = store.load_day(for_date)
    if not cached.empty:
        print(f"Announcements already downloaded for {for_date}")
        return cached

    print(f"Downloading NSE corporate announcements for {for_date}...")

    session = requests.Session()
    session.get("https://www.nseindia.com", headers=HEADERS, timeout=10)

    d = for_date.strftime("%d-%m-%Y")
    response = session.get(f"{ANNOUNCEMENTS_URL}&from_date={d}&to_date={d}",
                           headers=HEADERS, timeout=30)
    response.raise_for_status()

    data = response.json()

    # NSE returns a list of dicts; structure varies slightly across endpoints
    rows = data if isinstance(data, list) else data.get("data", [])
    df = pd.DataFrame(rows)

    if df.empty:
        print("No announcements returned by NSE.")
        return df

    df.columns = [c.strip().lower() for c in df.columns]

    # Standardize the subject column (NSE sometimes uses 'desc' or 'sm_desc' or 'subject')
    subject_col = next((c for c in ["sm_desc", "subject", "desc"] if c in df.columns), None)
    if subject_col:
        df["subject"] = df[subject_col]
        text = df["attchmnttext"] if "attchmnttext" in df.columns else None
        df["category"] = [categorize(s, t) for s, t in
                          zip(df["subject"], text if text is not None
                              else [None] * len(df))]

    store.save_day(df, for_date)
    print(f"Saved {len(df)} announcements for {for_date}")
    return df


def get_announcements_for_universe(symbols: list, for_date: date = None) -> pd.DataFrame:
    """
    Return only announcements for stocks in our universe.

    Args:
        symbols:  list of trading symbols (e.g. from nse_universe.get_universe_symbols())
        for_date: defaults to today
    """
    df = download_announcements(for_date)

    if df.empty or "symbol" not in df.columns:
        return df

    universe = set(s.upper() for s in symbols)
    filtered = df[df["symbol"].str.upper().isin(universe)].copy()
    print(f"Universe filings: {len(filtered)} of {len(df)} total announcements")
    return filtered


def get_announcements_by_category(symbols: list, categories: list, for_date: date = None) -> pd.DataFrame:
    """
    Filter universe announcements by category.
    Example: get_announcements_by_category(symbols, ["results", "guidance", "order_win"])
    """
    df = get_announcements_for_universe(symbols, for_date)
    if df.empty or "category" not in df.columns:
        return df
    return df[df["category"].isin(categories)].copy()


if __name__ == "__main__":
    df = download_announcements()
    if not df.empty:
        print("\nCategory counts:")
        print(df["category"].value_counts())
        print("\nSample rows:")
        print(df[["symbol", "category", "subject"]].head(10))
