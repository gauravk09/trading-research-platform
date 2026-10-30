"""
spot_commodities.py — Official cash/spot benchmark series, no roll gaps.

Sources are the primary publishers, not a broker's CFD derived from them:
    XAUUSD / XAGUSD  LBMA daily benchmark auction  (1968 -> today)
    WTIUSD / NGUSD   EIA Cushing WTI & Henry Hub   (1986 / 1997 -> today)
    BRENTUSD         EIA Europe Brent

Both are free and unauthenticated. This is the "continuous, no roll" series a
CFD would give you, minus the broker's spread and markup.

THREE THINGS THAT MAKE SPOT NOT A DROP-IN FOR FUTURES:

1. Close-only. LBMA publishes one auction print per day; EIA one spot quote.
   There is no open/high/low, so no range, gap or intraday-stop rule can be
   researched on these. The store rejects fabricated OHLC on purpose.
2. LBMA gold PM fixes at 15:00 London; EIA WTI is a US-day quote. Neither lands
   at the same instant as an MCX close (23:30 IST). Joining on calendar date
   alone silently mixes information from different points in time.
3. Spot is not what MCX tracks. MCX GOLD is a FUTURES contract; its fair value
   is spot plus cost-of-carry plus Indian import duty. For gold that carry is
   small and smooth, but for CRUDEOIL and NATURALGAS the futures/spot basis is
   large and regime-dependent (contango vs backwardation) — a signal fitted on
   spot crude will not transfer cleanly to an MCX crude futures position.

CLI:
    python src/spot_commodities.py
"""

import io

import pandas as pd
import requests

import commodity_store

_HEADERS = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"}

LBMA = {
    "XAUUSD": "https://prices.lbma.org.uk/json/gold_pm.json",
    "XAGUSD": "https://prices.lbma.org.uk/json/silver.json",
}

EIA = {
    "WTIUSD":   "https://www.eia.gov/dnav/pet/hist_xls/RWTCd.xls",
    "BRENTUSD": "https://www.eia.gov/dnav/pet/hist_xls/RBRTEd.xls",
    "NGUSD":    "https://www.eia.gov/dnav/ng/hist_xls/RNGWHHDd.xls",
}


def fetch_lbma(url: str) -> pd.DataFrame:
    """LBMA rows look like {'d': '2026-08-19', 'v': [USD, GBP, EUR]}."""
    rows = requests.get(url, headers=_HEADERS, timeout=30).json()
    df = pd.DataFrame([{"date": r["d"], "close": r["v"][0]} for r in rows if r.get("v")])
    df["date"] = pd.to_datetime(df["date"])
    # Auction days with no print come back as None/0; both mean "no fix", not zero.
    df = df[df["close"].notna() & (df["close"] > 0)]
    return df.reset_index(drop=True)


def fetch_eia(url: str) -> pd.DataFrame:
    """EIA ships an .xls whose second sheet is the series, two header rows deep."""
    content = requests.get(url, headers=_HEADERS, timeout=60).content
    xl = pd.ExcelFile(io.BytesIO(content))
    df = xl.parse(xl.sheet_names[-1], skiprows=2)
    df.columns = ["date", "close"]
    df["date"] = pd.to_datetime(df["date"])
    df = df[df["close"].notna()]
    return df.reset_index(drop=True)


def update() -> dict:
    out = {}
    for symbol, url in list(LBMA.items()) + list(EIA.items()):
        fetcher = fetch_lbma if symbol in LBMA else fetch_eia
        try:
            df = fetcher(url)
        except Exception as e:
            print(f"{symbol:9} FAILED  {type(e).__name__}: {e}")
            continue
        commodity_store.write("spot", symbol, df)
        print(f"{symbol:9} {len(df):>6} rows  "
              f"{df['date'].min():%Y-%m-%d} -> {df['date'].max():%Y-%m-%d}  "
              f"last {df['close'].iloc[-1]:,.4g}")
        out[symbol] = df
    return out


if __name__ == "__main__":
    update()
