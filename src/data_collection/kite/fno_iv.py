"""Live front-month ATM IV and implied-move snapshots for the F&O dashboard.

The worker is intentionally independent of the web API: an expired Kite token
or an NFO feed outage must never block the EOD strength board. It streams only
the nearest useful expiry's future and nearby CE/PE contracts, computes
Black-76 IV from good two-sided quotes, and atomically publishes a small JSON
snapshot for the API to read.

Run from the project root::

    PYTHONPATH=src python -m data_collection.kite.fno_iv
"""

from __future__ import annotations

import json
import math
import os

from data_collection.paths import ROOT_DIR
import tempfile
import threading
import time
from datetime import datetime, time as clock_time, timedelta
from statistics import median
from zoneinfo import ZoneInfo

import pandas as pd
from dotenv import load_dotenv
from kiteconnect import KiteTicker


from data_collection.kite.auth import ENV_FILE, get_kite_client  # noqa: E402
from data_collection.kite.instruments import download_instruments  # noqa: E402
from data_collection.nse.fo import get_fo_symbols  # noqa: E402

ROOT = os.path.abspath(ROOT_DIR)
SNAPSHOT = os.path.join(ROOT, "output", "live", "fno_iv_latest.json")
IST = ZoneInfo("Asia/Kolkata")
RISK_FREE_RATE = 0.10
MIN_DTE = 7
MAX_SPREAD_PCT = 15.0
PUBLISH_SECONDS = 5
STALE_SECONDS = 120


def _normal_cdf(value: float) -> float:
    return 0.5 * (1.0 + math.erf(value / math.sqrt(2.0)))


def black76_price(forward: float, strike: float, years: float, rate: float,
                  sigma: float, option_type: str) -> float:
    if min(forward, strike, years, sigma) <= 0:
        return math.nan
    root_t = math.sqrt(years)
    d1 = (math.log(forward / strike) + 0.5 * sigma * sigma * years) / (sigma * root_t)
    d2 = d1 - sigma * root_t
    discount = math.exp(-rate * years)
    if option_type == "CE":
        return discount * (forward * _normal_cdf(d1) - strike * _normal_cdf(d2))
    return discount * (strike * _normal_cdf(-d2) - forward * _normal_cdf(-d1))


def implied_volatility(price: float, forward: float, strike: float, years: float,
                       option_type: str, rate: float = RISK_FREE_RATE) -> float | None:
    """Black-76 IV by bounded bisection; returns annualized decimal volatility."""
    if min(price, forward, strike, years) <= 0 or option_type not in {"CE", "PE"}:
        return None
    discount = math.exp(-rate * years)
    intrinsic = discount * max(forward - strike, 0) if option_type == "CE" \
        else discount * max(strike - forward, 0)
    if price <= intrinsic or price >= discount * (forward if option_type == "CE" else strike):
        return None
    low, high = 0.0001, 5.0
    if black76_price(forward, strike, years, rate, high, option_type) < price:
        return None
    for _ in range(64):
        mid = (low + high) / 2
        if black76_price(forward, strike, years, rate, mid, option_type) < price:
            low = mid
        else:
            high = mid
    value = (low + high) / 2
    return value if 0.0001 <= value <= 5.0 else None


def implied_moves(iv_pct: float, years: float) -> tuple[float | None, float | None]:
    """One-standard-deviation percentage moves for one day and to expiry.

    ATM IV is annualized. Daily volatility uses 252 trading sessions, while the
    option's expiry horizon uses the same calendar-time convention as Black-76.
    """
    if iv_pct <= 0 or years <= 0:
        return None, None
    return iv_pct / math.sqrt(252), iv_pct * math.sqrt(years)


def _atomic_json(path: str, payload: dict) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".fno_iv_", suffix=".json", dir=os.path.dirname(path))
    try:
        with os.fdopen(fd, "w") as handle:
            json.dump(payload, handle, separators=(",", ":"), allow_nan=False)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def _quote_mid(quote: dict) -> tuple[float | None, str | None, float | None]:
    depth = quote.get("depth") or {}
    buys, sells = depth.get("buy") or [], depth.get("sell") or []
    bid = float(buys[0].get("price") or 0) if buys else 0
    ask = float(sells[0].get("price") or 0) if sells else 0
    if bid > 0 and ask >= bid:
        mid = (bid + ask) / 2
        spread = (ask - bid) / mid * 100 if mid else math.inf
        if spread <= MAX_SPREAD_PCT:
            return mid, "mid", spread
    last = float(quote.get("last_price") or 0)
    if last > 0 and (quote.get("oi") or quote.get("volume") or quote.get("volume_traded")):
        return last, "ltp", None
    return None, None, None


def _chunks(items: list, size: int = 400):
    for start in range(0, len(items), size):
        yield items[start:start + size]


class IvWorker:
    def __init__(self):
        self.kite = get_kite_client()
        self._lock = threading.Lock()
        self.quotes: dict[int, dict] = {}
        self.contracts: dict[str, dict] = {}
        self.token_meta: dict[int, dict] = {}
        self.ticker = None

    def prepare(self) -> None:
        symbols = get_fo_symbols()
        inst = download_instruments("NFO").copy()
        inst["name"] = inst["name"].astype(str).str.upper()
        inst["expiry"] = pd.to_datetime(inst["expiry"], errors="coerce").dt.date
        inst["strike"] = pd.to_numeric(inst["strike"], errors="coerce")
        inst = inst[inst["name"].isin(symbols)]
        cutoff = datetime.now(IST).date() + timedelta(days=MIN_DTE)

        futures = inst[(inst["instrument_type"] == "FUT") & (inst["expiry"] >= cutoff)]
        futures = futures.sort_values(["name", "expiry"]).groupby("name", as_index=False).first()
        future_keys = [f"NFO:{row.tradingsymbol}" for row in futures.itertuples()]
        seed = {}
        for batch in _chunks(future_keys):
            seed.update(self.kite.quote(batch))
            if len(future_keys) > len(batch):
                time.sleep(1.05)

        for future in futures.itertuples():
            future_key = f"NFO:{future.tradingsymbol}"
            forward = float((seed.get(future_key) or {}).get("last_price") or 0)
            if forward <= 0:
                continue
            chain = inst[(inst["name"] == future.name) & (inst["expiry"] == future.expiry)
                         & inst["instrument_type"].isin(["CE", "PE"])]
            strikes = sorted(chain["strike"].dropna().unique(), key=lambda strike: abs(strike - forward))[:3]
            legs = {}
            for strike in strikes:
                for option_type in ("CE", "PE"):
                    match = chain[(chain["strike"] == strike) & (chain["instrument_type"] == option_type)]
                    if match.empty:
                        continue
                    row = match.iloc[0]
                    token = int(row["instrument_token"])
                    legs[(float(strike), option_type)] = token
                    self.token_meta[token] = {"symbol": future.name, "role": option_type,
                                              "strike": float(strike)}
            future_token = int(future.instrument_token)
            self.token_meta[future_token] = {"symbol": future.name, "role": "FUT"}
            self.contracts[future.name] = {"expiry": future.expiry, "future": future_token,
                                           "legs": legs}

        all_keys = []
        by_key = {}
        for row in inst[inst["instrument_token"].astype(int).isin(self.token_meta)].itertuples():
            key = f"NFO:{row.tradingsymbol}"
            all_keys.append(key)
            by_key[key] = int(row.instrument_token)
        for batch in _chunks(all_keys):
            payload = self.kite.quote(batch)
            with self._lock:
                self.quotes.update({by_key[key]: quote for key, quote in payload.items() if key in by_key})
            if len(all_keys) > len(batch):
                time.sleep(1.05)

    def _row(self, symbol: str, contract: dict, now: datetime) -> dict | None:
        with self._lock:
            quotes = dict(self.quotes)
        future_quote = quotes.get(contract["future"], {})
        forward = float(future_quote.get("last_price") or 0)
        if forward <= 0:
            return None
        expiry_at = datetime.combine(contract["expiry"], clock_time(15, 30), IST)
        years = (expiry_at - now).total_seconds() / (365.0 * 86400)
        if years <= 0:
            return None
        strikes = sorted({strike for strike, _ in contract["legs"]}, key=lambda strike: abs(strike - forward))
        for strike in strikes:
            values, qualities, spreads = {}, {}, {}
            for option_type in ("CE", "PE"):
                token = contract["legs"].get((strike, option_type))
                price, quality, spread = _quote_mid(quotes.get(token, {}))
                value = implied_volatility(price, forward, strike, years, option_type) if price else None
                if value is not None:
                    values[option_type], qualities[option_type], spreads[option_type] = value * 100, quality, spread
            if values:
                iv = median(values.values())
                implied_day_pct, implied_expiry_pct = implied_moves(iv, years)
                return {"symbol": symbol, "iv": round(iv, 2),
                        "implied_day_pct": round(implied_day_pct, 2),
                        "implied_expiry_pct": round(implied_expiry_pct, 2),
                        "iv_ce": round(values["CE"], 2) if "CE" in values else None,
                        "iv_pe": round(values["PE"], 2) if "PE" in values else None,
                        "expiry": contract["expiry"].isoformat(),
                        "dte": max(0, (contract["expiry"] - now.date()).days),
                        "strike": strike, "forward": round(forward, 2),
                        "quality": "mid" if qualities and set(qualities.values()) == {"mid"} else "mixed",
                        "max_spread_pct": round(max((x for x in spreads.values() if x is not None), default=0), 2)}
        return None

    def publish(self) -> None:
        now = datetime.now(IST)
        rows = [row for symbol, contract in self.contracts.items()
                if (row := self._row(symbol, contract, now)) is not None]
        _atomic_json(SNAPSHOT, {"status": "live" if rows else "waiting", "updated_at": now.isoformat(),
                                "stale_after_seconds": STALE_SECONDS, "count": len(rows), "rows": rows})

    def run(self) -> None:
        self.prepare()
        load_dotenv(ENV_FILE)
        api_key, access_token = os.getenv("KITE_API_KEY"), os.getenv("KITE_ACCESS_TOKEN")
        self.ticker = KiteTicker(api_key, access_token)

        def on_connect(ws, response):
            del response
            tokens = list(self.token_meta)
            ws.subscribe(tokens)
            ws.set_mode(ws.MODE_FULL, tokens)
            print(f"IV feed connected: {len(self.contracts)} stocks, {len(tokens)} NFO contracts")

        def on_ticks(ws, ticks):
            del ws
            with self._lock:
                self.quotes.update({int(tick["instrument_token"]): tick for tick in ticks})

        self.ticker.on_connect = on_connect
        self.ticker.on_ticks = on_ticks
        self.ticker.connect(threaded=True)
        while True:
            self.publish()
            time.sleep(PUBLISH_SECONDS)


if __name__ == "__main__":
    try:
        IvWorker().run()
    except KeyboardInterrupt:
        pass
    except Exception as exc:  # worker failure must be visible but isolated
        _atomic_json(SNAPSHOT, {"status": "offline", "updated_at": datetime.now(IST).isoformat(),
                                "stale_after_seconds": STALE_SECONDS, "count": 0, "rows": [],
                                "error": type(exc).__name__})
        raise
