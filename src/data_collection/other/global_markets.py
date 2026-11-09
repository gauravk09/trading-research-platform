"""global_markets.py — snapshot of prominent global/other markets, for context.

Fetches last close + day change from Yahoo's public chart endpoint with plain
requests (no API key, no yfinance dependency). Context/color only — never a
regime input; the regime stays deterministic from NSE breadth (src/regime.py).

Used live by the dashboard's Daily Brief tab (cached there) and by the /brief
skill. CLI:
    PYTHONPATH=src python -m data_collection.other.global_markets
"""

from concurrent.futures import ThreadPoolExecutor

import requests

MARKETS = [
    ("^NSEI",    "Nifty 50"),
    ("^NSEBANK", "Bank Nifty"),
    ("^GSPC",    "S&P 500"),
    ("^IXIC",    "Nasdaq"),
    ("^DJI",     "Dow"),
    ("^N225",    "Nikkei 225"),
    ("^HSI",     "Hang Seng"),
    ("INR=X",    "USD/INR"),
    ("BZ=F",     "Brent"),
    ("GC=F",     "Gold"),
]

_CHART_URL = "https://query1.finance.yahoo.com/v8/finance/chart/{}"
_HEADERS = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"}


def _fetch_one(symbol: str, name: str, session: requests.Session) -> dict | None:
    resp = session.get(_CHART_URL.format(symbol),
                       params={"range": "10d", "interval": "1d"},
                       headers=_HEADERS, timeout=10)
    resp.raise_for_status()
    result = resp.json()["chart"]["result"][0]
    closes = [c for c in result["indicators"]["quote"][0]["close"] if c is not None]
    if len(closes) < 2:
        return None
    last, prev = closes[-1], closes[-2]
    meta = result["meta"]
    return {
        "symbol": symbol,
        "name": name,
        "last": round(last, 2),
        "chg_pct": round((last - prev) / prev * 100, 2),
        "market_time": meta.get("regularMarketTime"),
        "currency": meta.get("currency"),
    }


def _fetch_safe(args) -> dict | None:
    symbol, name = args
    try:
        with requests.Session() as session:
            return _fetch_one(symbol, name, session)
    except (requests.RequestException, KeyError, IndexError, ValueError):
        return None


def fetch_global_snapshot() -> list[dict]:
    """One row per market, fetched in parallel (~0.5s instead of ~3s
    sequentially); markets that fail to fetch are simply omitted."""
    with ThreadPoolExecutor(max_workers=len(MARKETS)) as pool:
        rows = pool.map(_fetch_safe, MARKETS)
    return [r for r in rows if r]


if __name__ == "__main__":
    for r in fetch_global_snapshot():
        print(f"{r['name']:<12} {r['last']:>12,.2f}  {r['chg_pct']:+.2f}%")
