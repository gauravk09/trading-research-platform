"""
nse_universe.py — Build the stock universe for scanning

Two ways to build a universe:

  1. INDEX-BASED (curated):
     Use Nifty 500 / Midcap 150 / Smallcap 250 / etc.
     Pros: pre-filtered by market cap, clean list (~500-750 stocks).
     Cons: misses smaller liquid stocks where big momentum moves happen.

  2. ALL-NSE (full market):
     Use Kite instrument dump → filter EQ series → apply liquidity filter.
     Pros: catches all real opportunities (~1000-1500 stocks).
     Cons: needs liquidity filter to exclude dead/illiquid stocks.

Both are supported via build_universe() / build_full_nse_universe().
"""

import os

from data_collection.paths import ROOT_DIR
import io
import requests
import pandas as pd
from datetime import date, timedelta

RAW_DIR = os.path.join(ROOT_DIR, "data", "raw")

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
    "Referer": "https://www.niftyindices.com/"
}

# Index name → NSE Indices CSV filename
INDEX_URLS = {
    "nifty500":       "https://www.niftyindices.com/IndexConstituent/ind_nifty500list.csv",
    "nifty_midcap150":  "https://www.niftyindices.com/IndexConstituent/ind_niftymidcap150list.csv",
    "nifty_smallcap250": "https://www.niftyindices.com/IndexConstituent/ind_niftysmallcap250list.csv",
    "nifty_microcap250": "https://www.niftyindices.com/IndexConstituent/ind_niftymicrocap250list.csv",
    "nifty_total_market": "https://www.niftyindices.com/IndexConstituent/ind_niftytotalmarket_list.csv",
}


def download_index(index_name: str) -> pd.DataFrame:
    """
    Download the constituent list for a single Nifty index.
    Caches the result to data/raw/<index_name>_YYYY-MM-DD.csv

    Args:
        index_name: one of the keys in INDEX_URLS (e.g. "nifty500")

    Returns:
        DataFrame with columns: company_name, industry, symbol, series, isin_code
    """
    if index_name not in INDEX_URLS:
        raise ValueError(f"Unknown index '{index_name}'. Choose from: {list(INDEX_URLS.keys())}")

    today = date.today().isoformat()
    save_path = os.path.join(RAW_DIR, f"{index_name}_{today}.csv")

    if os.path.exists(save_path):
        print(f"  {index_name}: already downloaded ({save_path})")
        return pd.read_csv(save_path)

    url = INDEX_URLS[index_name]
    print(f"  {index_name}: downloading from NSE Indices...")

    response = requests.get(url, headers=HEADERS, timeout=30)
    response.raise_for_status()

    df = pd.read_csv(io.BytesIO(response.content))
    df.columns = [c.strip().lower().replace(" ", "_") for c in df.columns]
    df["index_name"] = index_name

    df.to_csv(save_path, index=False)
    print(f"  {index_name}: saved {len(df)} stocks")
    return df


def build_universe(indices: list = None) -> pd.DataFrame:
    """
    Download multiple index lists and merge them into one deduplicated universe.

    Args:
        indices: list of index names to include. Defaults to Nifty 500 + Midcap 150 + Smallcap 250.

    Returns:
        DataFrame with one row per unique stock symbol, plus a column showing which
        indices it belongs to (comma-separated).
    """
    if indices is None:
        indices = ["nifty500", "nifty_midcap150", "nifty_smallcap250"]

    print(f"Building universe from: {indices}")
    frames = []

    for index_name in indices:
        df = download_index(index_name)
        frames.append(df)

    combined = pd.concat(frames, ignore_index=True)

    # For each symbol, record all indices it appears in
    index_membership = (
        combined.groupby("symbol")["index_name"]
        .apply(lambda x: ",".join(sorted(set(x))))
        .reset_index()
        .rename(columns={"index_name": "indices"})
    )

    # Keep one row per symbol (first occurrence has company_name, industry, etc.)
    unique_stocks = combined.drop_duplicates(subset="symbol").drop(columns=["index_name"])
    universe = unique_stocks.merge(index_membership, on="symbol")

    print(f"\nTotal unique stocks in universe: {len(universe)}")
    return universe.reset_index(drop=True)


def get_universe_symbols(indices: list = None) -> list:
    """Return just the list of trading symbols for the chosen universe."""
    df = build_universe(indices)
    return df["symbol"].dropna().str.strip().tolist()


def get_all_nse_eq_symbols() -> list:
    """
    Return ALL NSE equity-series stocks for the data COLLECTION layer.
    No liquidity filter, no ASM/GSM filter — we want to preserve full history
    even for currently-illiquid stocks (they may have been big movers in the past,
    and we need that data for backtesting).

    Source: official NSE EQUITY_L.csv (all listed equities, SERIES=EQ).
    Falls back to Kite instrument dump (instrument_type=EQ, segment=NSE)
    if NSE download fails.
    """
    today = date.today().isoformat()
    save_path = os.path.join(RAW_DIR, f"all_nse_eq_{today}.csv")

    if os.path.exists(save_path):
        df = pd.read_csv(save_path)
        return df["symbol"].dropna().str.strip().tolist()

    try:
        print("Downloading official NSE equity master list (EQUITY_L.csv)...")
        url = "https://nsearchives.nseindia.com/content/equities/EQUITY_L.csv"
        response = requests.get(url, headers=HEADERS, timeout=30)
        response.raise_for_status()
        df = pd.read_csv(io.BytesIO(response.content))
        df.columns = [c.strip().lower().replace(" ", "_") for c in df.columns]

        # Standard column is 'symbol' or 'symbol\xa0'; series column is 'series'
        if "series" in df.columns:
            df = df[df["series"].str.strip() == "EQ"]

        symbols = df["symbol"].dropna().str.strip().tolist()
        df[["symbol"]].to_csv(save_path, index=False)
        print(f"  {len(symbols)} EQ-series stocks from NSE")
        return symbols

    except Exception as e:
        print(f"  NSE download failed ({e}), falling back to Kite instrument dump.")
        from data_collection.kite.instruments import download_instruments
        df = download_instruments("NSE")
        eq = df[(df["instrument_type"] == "EQ") & (df["segment"] == "NSE")]
        symbols = eq["tradingsymbol"].dropna().str.strip().tolist()
        print(f"  {len(symbols)} stocks from Kite (no SERIES filter available)")
        return symbols


def build_full_nse_universe(min_avg_turnover_cr: float = 1.0, lookback_days: int = 20) -> pd.DataFrame:
    """
    Build the FULL NSE equity universe (all ~2000 listed stocks) with a liquidity filter.

    Steps:
      1. Load Kite instrument dump for NSE
      2. Filter to instrument_type='EQ' and segment='NSE'
      3. Filter by SERIES (only 'EQ' — excludes BE/BZ trade-to-trade)
      4. Apply liquidity filter using already-downloaded daily OHLCV data
         (avg daily turnover in ₹ crore over last N days)

    Args:
        min_avg_turnover_cr: Minimum 20-day average daily turnover in ₹ crore. Default 1 crore.
        lookback_days:       Number of recent trading days to compute average turnover.

    Returns:
        DataFrame with: symbol, name, instrument_token, avg_turnover_cr
    """
    # Import here to avoid circular imports at module load
    from data_collection.kite.instruments import download_instruments

    print("Building full NSE equity universe...")

    # Step 1-2: Kite instruments, filtered
    df = download_instruments("NSE")
    eq = df[(df["instrument_type"] == "EQ") & (df["segment"] == "NSE")].copy()
    print(f"  After EQ + NSE segment filter: {len(eq)} stocks")

    # Step 3: Use bhavcopy to filter by SERIES = 'EQ' (regular delivery)
    # Bhavcopy has a 'series' column. Fall back to no filter if bhavcopy not available.
    series_eq_symbols = _get_series_eq_symbols()
    if series_eq_symbols is not None:
        eq = eq[eq["tradingsymbol"].isin(series_eq_symbols)]
        print(f"  After SERIES=EQ filter (from bhavcopy): {len(eq)} stocks")

    # Step 4: Liquidity filter using historical OHLCV files we already have
    eq = _apply_liquidity_filter(eq, min_avg_turnover_cr, lookback_days)

    return eq.reset_index(drop=True)


def _get_series_eq_symbols():
    """Read the most recent bhavcopy to find symbols with SERIES = 'EQ'. Returns None if unavailable."""
    bhav_dir = os.path.join(RAW_DIR, "bhavcopy")
    if not os.path.isdir(bhav_dir):
        return None

    files = sorted(f for f in os.listdir(bhav_dir) if f.startswith("bhavcopy_"))
    if not files:
        return None

    latest = os.path.join(bhav_dir, files[-1])
    df = pd.read_csv(latest)

    # Bhavcopy column names vary slightly — find the right ones
    series_col = next((c for c in df.columns if "sries" in c.lower() or "series" in c.lower()), None)
    symbol_col = next((c for c in df.columns if c.lower() in ("tckrsymb", "symbol")), None)

    if not series_col or not symbol_col:
        return None

    return set(df[df[series_col] == "EQ"][symbol_col].dropna().str.strip())


def _apply_liquidity_filter(eq_df: pd.DataFrame, min_avg_turnover_cr: float, lookback_days: int):
    """
    Compute average daily turnover for each stock and filter out illiquid ones.
    Uses data/raw/historical/<SYMBOL>.csv files (turnover = close * volume).
    """
    hist_dir = os.path.join(RAW_DIR, "historical")
    if not os.path.isdir(hist_dir):
        print("  WARN: No historical data found, skipping liquidity filter.")
        eq_df["avg_turnover_cr"] = None
        return eq_df

    avg_turnovers = {}
    print(f"  Computing {lookback_days}-day average turnover...")

    for symbol in eq_df["tradingsymbol"]:
        path = os.path.join(hist_dir, f"{symbol}.csv")
        if not os.path.exists(path):
            continue
        try:
            df = pd.read_csv(path, usecols=["date", "close", "volume"])
            recent = df.tail(lookback_days)
            if len(recent) < lookback_days:
                continue
            turnover_cr = (recent["close"] * recent["volume"]).mean() / 1e7
            avg_turnovers[symbol] = turnover_cr
        except Exception:
            continue

    eq_df["avg_turnover_cr"] = eq_df["tradingsymbol"].map(avg_turnovers)
    before = len(eq_df)
    eq_df = eq_df[eq_df["avg_turnover_cr"].fillna(0) >= min_avg_turnover_cr].copy()
    print(f"  After liquidity filter (≥ ₹{min_avg_turnover_cr} cr/day): {len(eq_df)} stocks (dropped {before - len(eq_df)})")

    eq_df = eq_df.rename(columns={"tradingsymbol": "symbol"})
    return eq_df[["symbol", "name", "instrument_token", "avg_turnover_cr"]]


def get_full_nse_symbols(min_avg_turnover_cr: float = 1.0) -> list:
    """Return the list of trading symbols for the full filtered NSE universe."""
    df = build_full_nse_universe(min_avg_turnover_cr)
    return df["symbol"].dropna().str.strip().tolist()


if __name__ == "__main__":
    print("=" * 60)
    print("Option 1: Index-based universe")
    print("=" * 60)
    universe = build_universe()
    print(universe[["symbol", "company_name", "indices"]].head(10))

    print("\n" + "=" * 60)
    print("Option 2: Full NSE universe (with liquidity filter)")
    print("=" * 60)
    full = build_full_nse_universe(min_avg_turnover_cr=1.0)
    print(full.head(10))
    print(f"\nTotal: {len(full)} liquid NSE stocks")
