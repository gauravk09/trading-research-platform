"""live_anticipation.py — live intraday scanner + watchlist grid.

Streams the liquid NSE universe (avg turnover >= MIN_TURNOVER_CR) over the Kite
websocket in QUOTE mode, which carries today's cumulative volume and OHLC. From
those live quotes plus last night's EOD summary it runs five intraday scans —
4% breakout, 4% breakdown, anticipation + high volume (EP9M-type), bullish
reversal, bearish reversal — so you can act on a setup *before* the close
instead of finding it tonight.

The first tab is a Live Movers list: a ranked table of the watchlist (the
anticipation list plus last night's DEP watchlist, or a CSV) currently moving
beyond MOVE_THRESHOLD_PCT, biggest move first, change measured off the previous
close exactly as Zerodha shows it. Click any row for its daily/5-minute chart.

    python src/live_anticipation.py                     # anticipation watchlist
    python src/live_anticipation.py output/watch.csv    # custom movers watchlist
    # then open http://localhost:8602

Tabs: Live Movers (/data) · User Picks · 4% Breakout · 4% Breakdown ·
Anticipation+Vol · Reversal Up · Reversal Down · 4% Up (7d) · 4% Down (7d)
(ranked tables, /scan?name=...). The scans always run over the full liquid
universe regardless of the movers watchlist.

User Picks is your own watchlist: put a `symbol` column in output/user_picks.csv
(optionally `date` and `reason`) and every pick shows with its live LTP/Chg%/RVOL
alongside the date you added it and your reasoning. The file is re-read on each
poll so edits and removals show up live; a brand-new symbol added mid-session
won't stream until the next restart (the dashboard restarts each morning anyway).

The ⊕ on any row stamps that symbol with its LTP and the time right now
(output/tracked.csv) and routes it into User Picks, where `Since%` tracks the
move from YOUR stamp rather than from yesterday's close — the read on whether
what you pick actually goes anywhere afterwards. ⊕ again to untrack.
"""

import json
import os
import sys
import threading
import time
from datetime import datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse
from zoneinfo import ZoneInfo

import pandas as pd
from kiteconnect import KiteTicker

sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "strategies"))

import live_scanner as ls
import order_pad
import strategy_registry
import tracker
from auth import get_kite_client
from daily_state import _load_excluded
from instruments import download_instruments
from stockbee import scans

ROOT = os.path.join(os.path.dirname(__file__), "..")
SUMMARY_PATH = os.path.join(ROOT, "data", "processed", "universe_summary.parquet")
STATE_LATEST = os.path.join(ROOT, "output", "state", "latest.json")
PICKS_PATH = os.path.join(ROOT, "output", "user_picks.csv")
LIB_JS = os.path.join(ROOT, "dashboard", "assets", "lightweight-charts.js")
PAGE_HTML = os.path.join(os.path.dirname(__file__), "live_anticipation.html")

IST = ZoneInfo("Asia/Kolkata")
PORT = 8602
WATCHLIST_SIZE = 50
MOVE_THRESHOLD_PCT = 2.0
MIN_TURNOVER_CR = 5.0        # liquid universe streamed for the intraday scans

# Columns for the Live Movers table (/data), rendered by the same front-end
# path as the scan tables.
MOVER_COLUMNS = [{"key": "symbol", "label": "Symbol"},
                 {"key": "last", "label": "LTP"},
                 {"key": "chg_pct", "label": "Chg%"},
                 {"key": "rvol", "label": "RVOL"},
                 {"key": "mcap_cr", "label": "Mcap Cr"}]

# Same params daily_state.py uses for the anticipation scan
SCAN_PARAMS = {"max_range_5d": 12.0, "max_vol_contraction": 0.85,
               "min_prior_move": 20.0}


def load_dep_symbols(data_date):
    """DEP watchlist from last night's daily state, empty if absent or stale."""
    try:
        with open(STATE_LATEST) as f:
            state = json.load(f)
    except FileNotFoundError:
        return []
    state_date = state["meta"]["data_date"]
    if state_date != str(data_date):
        print(f"DEP list skipped: state is for {state_date}, data is {data_date}")
        return []
    return [c["symbol"] for c in state["scans"]["dep"]["candidates"]]


def load_picks(path=PICKS_PATH):
    """User's picks from the watchlist CSV as a DataFrame with `symbol` plus the
    optional `date` and `reason` annotation columns. `symbol` is required (or the
    first column if unnamed); date/reason are filled with None when absent.

    Empty frame if the file is missing — the User Picks tab then shows nothing.
    Re-read on every poll so edits show up live."""
    cols = ["symbol", "date", "reason"]
    if not path or not os.path.exists(path):
        return pd.DataFrame(columns=cols)
    try:
        df = pd.read_csv(path)
    except (UnicodeDecodeError, pd.errors.ParserError, pd.errors.EmptyDataError) as e:
        print(f"[picks] {path} is not a readable CSV ({e}); ignoring watchlist")
        return pd.DataFrame(columns=cols)
    df.columns = [str(c).strip().lower() for c in df.columns]
    if "symbol" not in df.columns:
        df = df.rename(columns={df.columns[0]: "symbol"})
    df["symbol"] = df["symbol"].astype(str).str.strip().str.upper()
    df = df[(df["symbol"] != "") & (df["symbol"] != "NAN")].drop_duplicates("symbol")
    for c in ("date", "reason"):
        if c in df.columns:
            s = df[c].astype(str).str.strip()
            df[c] = s.where(~s.str.lower().isin(["", "nan", "none"]), None)
        else:
            df[c] = None
    return df[cols].reset_index(drop=True)


def build_watchlist(csv_path=None):
    """Return (symbols, dep_set) for today's Live Movers list.

    Change % for the movers is taken live from Kite's previous close (Zerodha's
    basis), so we don't need a stored prev_close here — only which symbols to
    watch and which of them are on last night's DEP list."""
    summary = pd.read_parquet(SUMMARY_PATH)
    data_date = pd.Timestamp(summary["last_date"].max()).date()
    dep = set()
    if csv_path:
        df = pd.read_csv(csv_path)
        col = "symbol" if "symbol" in df.columns else df.columns[0]
        wanted = list(df[col].dropna().astype(str).str.strip().str.upper().unique())
        missing = set(wanted) - set(summary["symbol"])
        if missing:
            print(f"Not in summary, skipped: {', '.join(sorted(missing))}")
        # keep the CSV's own ordering — it's the caller's ranking
        hits = (summary.set_index("symbol")
                .loc[[s for s in wanted if s not in missing]]
                .reset_index()
                .head(WATCHLIST_SIZE))
    else:
        hits = scans.anticipation(summary, **SCAN_PARAMS,
                                  min_turnover_cr=1.0,
                                  excluded=_load_excluded()).head(WATCHLIST_SIZE)
        dep = set(load_dep_symbols(data_date))
        extra = dep - set(hits["symbol"])
        if extra:
            hits = pd.concat([hits, summary[summary["symbol"].isin(extra)]],
                             ignore_index=True)
    return list(hits["symbol"]), dep


def build_stream_universe(summary, min_turnover_cr=MIN_TURNOVER_CR):
    """The liquid universe the intraday scans run over, indexed by symbol.

    `drop=False` keeps a `symbol` column too, since the Stockbee scan predicates
    filter on `out["symbol"]`."""
    liquid = summary[summary["avg_turnover_cr"] >= min_turnover_cr]
    hist = liquid.set_index("symbol", drop=False)
    return hist, list(hist["symbol"])


def map_tokens(symbols):
    """Return {instrument_token: symbol} for the given symbols."""
    inst = download_instruments("NSE")
    eq = inst[inst["tradingsymbol"].isin(symbols)]
    eq = eq[eq["instrument_type"] == "EQ"]
    return {int(r.instrument_token): r.tradingsymbol for r in eq.itertuples()}


class QuoteBook:
    """Thread-safe latest-quote-per-symbol, fed by QUOTE-mode ticks, used to
    compute the intraday scans against last night's EOD `hist`."""

    def __init__(self, hist, excluded, full_hist=None, picks_path=None,
                 market=None):
        self._lock = threading.Lock()
        self._hist = hist
        self._full_hist = full_hist        # whole summary, for the User Picks tab
        self._picks_path = picks_path
        self._excluded = excluded
        self._market = market or {}        # tape snapshot for TAKE/SKIP signals
        self._q = {}                       # symbol -> live quote dict
        self._watch = []                   # Live Movers watchlist symbols
        self._dep = set()                  # which of them are on the DEP list
        self._mcap = {}                    # symbol -> market cap in Cr (EOD)
        self._avg_vol = {}                 # symbol -> 7-day avg volume, for RVOL

    @property
    def size(self):
        return len(self._q)

    @property
    def watch_size(self):
        return len(self._watch)

    def set_movers(self, watch, dep, mcap):
        """Configure the Live Movers watchlist (symbols, DEP set, market caps)."""
        self._watch, self._dep, self._mcap = watch, dep, mcap
        avg = self._full_hist["avg_vol_7d"]
        self._avg_vol = {s: float(avg[s]) for s in watch
                         if s in avg.index and pd.notna(avg[s])}

    def movers(self, threshold=MOVE_THRESHOLD_PCT, now=None):
        """Watchlist symbols moving beyond `threshold`, biggest move first.

        Change is `last / prev_close - 1` using Kite's `ohlc.close` (yesterday's
        close) — the exact basis Zerodha shows, not today's open. RVOL uses the
        same session-curve projection as the scan tabs, so the two agree."""
        frac = ls.session_fraction(now)
        with self._lock:
            quotes = {s: self._q[s] for s in self._watch if s in self._q}
        rows = []
        for sym, q in quotes.items():
            last, prev = q.get("last"), q.get("prev_close")
            if last is None or not prev or prev <= 0:
                continue
            chg = (last / prev - 1) * 100
            if abs(chg) < threshold:
                continue
            vol, avg_vol = q.get("vol"), self._avg_vol.get(sym)
            rvol = (vol / frac) / avg_vol if vol and avg_vol else None
            mcap = self._mcap.get(sym)
            rows.append({"symbol": sym, "last": round(last, 2),
                         "chg_pct": round(chg, 2),
                         "rvol": round(rvol, 2) if rvol else None,
                         "mcap_cr": round(mcap) if mcap is not None else None,
                         "dep": sym in self._dep})
        rows.sort(key=lambda r: abs(r["chg_pct"]), reverse=True)
        return rows

    def fno_moves(self):
        """Compact live tape for every streamed F&O stock.

        This is deliberately one batch snapshot: the F&O board must not make a
        REST quote request per row during the live session.
        """
        fo_symbols = set(self._hist.index[self._hist["is_fo"].fillna(False)])
        with self._lock:
            quotes = {symbol: quote for symbol, quote in self._q.items()
                      if symbol in fo_symbols}
        rows = []
        for symbol, quote in quotes.items():
            last = quote.get("last")
            previous = quote.get("prev_close")
            day_low = quote.get("low")
            if last is None or not previous or previous <= 0:
                continue
            rows.append({
                "symbol": symbol,
                "last": round(float(last), 2),
                "day_move_pct": round((float(last) / float(previous) - 1) * 100, 2),
                "from_low_pct": round((float(last) / float(day_low) - 1) * 100, 2)
                if day_low and day_low > 0 else None,
                "day_low": round(float(day_low), 2) if day_low and day_low > 0 else None,
            })
        return rows

    def update(self, symbol, tick):
        ohlc = tick.get("ohlc") or {}
        with self._lock:
            self._q[symbol] = {
                "last": tick.get("last_price"),
                "open": ohlc.get("open"), "high": ohlc.get("high"),
                "low": ohlc.get("low"), "prev_close": ohlc.get("close"),
                "vol": tick.get("volume_traded", tick.get("volume")),
            }

    def quote(self, symbol):
        """Latest streamed quote for one symbol, or None if not streaming.
        Lets the web chart append today's live bar on top of stored EOD."""
        with self._lock:
            q = self._q.get(symbol)
        if not q or q.get("last") is None:
            return None
        return {"symbol": symbol, **q}

    def scan(self, name):
        with self._lock:
            quotes = dict(self._q)         # snapshot so pandas can't race a tick
        return ls.run(name, quotes, self._hist, excluded=self._excluded,
                      market=self._market)

    def tickets(self, equity, risk_pct):
        with self._lock:
            quotes = dict(self._q)
        return ls.order_tickets(quotes, self._hist, excluded=self._excluded,
                                market=self._market, equity=equity,
                                risk_pct=risk_pct)

    def picks(self):
        picks_df = load_picks(self._picks_path)   # re-read each poll so edits show up
        with self._lock:
            quotes = dict(self._q)
        return ls.run_picks(quotes, self._full_hist, picks_df, tracker.load())

    def is_fo(self, symbol):
        """F&O membership from last night's summary — the chart header's badge.
        Unknown symbols read False rather than raising: the chart still opens."""
        hist = self._full_hist
        return bool(hist.at[symbol, "is_fo"]) if symbol in hist.index else False

    def set_tracked(self, symbol, on):
        """Start/stop tracking `symbol`, stamping the LTP the server holds right
        now — not a price the browser sends — so the stamp is the same quote the
        tables are rendered from."""
        if not on:
            tracker.untrack(symbol)
            return {"symbol": symbol, "tracked": False}
        with self._lock:
            quote = self._q.get(symbol)
        last = quote and quote.get("last")
        if not last:
            return {"symbol": symbol, "tracked": False, "error": "no live quote"}
        return {"symbol": symbol, "tracked": True, **tracker.track(symbol, last)}


class ChartCache:
    """On-demand daily/5-minute candles for the click-to-chart popup.

    Kite's historical API is 3 req/sec — fine for occasional clicks, but a
    user re-opening the same chart shouldn't refetch every time, so results
    are cached for CHART_TTL seconds.
    """

    CHART_TTL = 60

    def __init__(self, kite, sym_token):
        self._kite = kite
        self._sym_token = sym_token   # symbol -> instrument_token
        self._lock = threading.Lock()
        self._cache = {}              # (symbol, interval) -> (fetched_at, candles)

    def get(self, symbol, interval):
        token = self._sym_token.get(symbol)
        if not token:
            return None
        key = (symbol, interval)
        now = time.time()
        with self._lock:
            hit = self._cache.get(key)
            if hit and now - hit[0] < self.CHART_TTL:
                return hit[1]

        to = datetime.now(IST).replace(tzinfo=None)
        if interval == "day":
            frm = to - timedelta(days=730)
            kite_interval = "day"
        else:
            frm = to - timedelta(days=25)
            kite_interval = "5minute"
        raw = self._kite.historical_data(token, frm, to, kite_interval)

        if interval == "day":
            candles = [{"time": c["date"].strftime("%Y-%m-%d"),
                       "open": c["open"], "high": c["high"],
                       "low": c["low"], "close": c["close"],
                       "volume": c["volume"]} for c in raw]
        else:
            candles = [{"time": int(c["date"].timestamp()) + 19800,
                       "open": c["open"], "high": c["high"],
                       "low": c["low"], "close": c["close"],
                       "volume": c["volume"]} for c in raw]

        with self._lock:
            self._cache[key] = (now, candles)
        return candles


def start_ticker(api_key, access_token, tokens, qbook):
    ticker = KiteTicker(api_key, access_token)

    def on_connect(ws, response):
        toks = list(tokens)
        ws.subscribe(toks)
        ws.set_mode(ws.MODE_QUOTE, toks)   # QUOTE carries cumulative volume + OHLC
        print(f"Websocket connected, streaming {len(toks)} symbols")

    def on_ticks(ws, ticks):
        for t in ticks:
            symbol = tokens.get(t["instrument_token"])
            if symbol:
                qbook.update(symbol, t)

    ticker.on_connect = on_connect
    ticker.on_ticks = on_ticks
    ticker.connect(threaded=True)
    return ticker


def tracked_symbols():
    """Symbols stamped today — every table ships this so the ⊕ button can show
    which rows are already being tracked."""
    return list(tracker.load()["symbol"])


class Handler(BaseHTTPRequestHandler):
    qbook = None
    charts = None
    kite = None
    _od_cache = {}                 # symbol -> (fetched_at, quote) for on-demand
    _od_lock = threading.Lock()

    def _ondemand_quote(self, symbol):
        """Live quote for a symbol NOT in the streaming book (e.g. a scan/setup
        name below the 5-Cr stream floor) via a one-off Kite REST quote, cached
        30s so occasional chart opens don't hit the rate limit. This is what
        makes every chart live, not just streamed names."""
        now = time.time()
        with Handler._od_lock:
            hit = Handler._od_cache.get(symbol)
            if hit and now - hit[0] < 30:
                return hit[1]
        try:
            key = f"NSE:{symbol}"
            data = (self.kite.quote([key]) or {}).get(key)
        except Exception:
            return None
        if not data or data.get("last_price") is None:
            return None
        o = data.get("ohlc") or {}
        q = {"symbol": symbol, "last": data.get("last_price"),
             "open": o.get("open"), "high": o.get("high"), "low": o.get("low"),
             "prev_close": o.get("close"), "vol": data.get("volume")}
        with Handler._od_lock:
            Handler._od_cache[symbol] = (now, q)
        return q

    def _send(self, body, content_type):
        data = body.encode()
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        route = urlparse(self.path)
        if route.path == "/":
            with open(PAGE_HTML) as f:
                self._send(f.read(), "text/html")
        elif route.path == "/lib.js":
            with open(LIB_JS) as f:
                self._send(f.read(), "application/javascript")
        elif route.path == "/data":
            self._send(json.dumps({
                "generated": datetime.now(IST).strftime("%H:%M:%S"),
                "threshold": MOVE_THRESHOLD_PCT,
                "watchlist": self.qbook.watch_size,
                "columns": MOVER_COLUMNS,
                "tracked": tracked_symbols(),
                "rows": self.qbook.movers(),
            }), "application/json")
        elif route.path == "/fno":
            rows = self.qbook.fno_moves()
            self._send(json.dumps({
                "generated": datetime.now(IST).strftime("%H:%M:%S"),
                "status": "live" if rows else "waiting",
                "count": len(rows),
                "rows": rows,
            }), "application/json")
        elif route.path == "/track":
            q = parse_qs(route.query)
            symbol = q.get("symbol", [""])[0].upper()
            on = q.get("on", ["1"])[0] != "0"
            if not symbol:
                self.send_error(404)
                return
            self._send(json.dumps(self.qbook.set_tracked(symbol, on)),
                       "application/json")
        elif route.path == "/quote":
            symbol = parse_qs(route.query).get("symbol", [""])[0].upper()
            q = self.qbook.quote(symbol) if symbol else None
            if not q and symbol:          # not streamed → one-off Kite quote
                q = self._ondemand_quote(symbol)
            if not q:
                self.send_error(404)
                return
            self._send(json.dumps(q), "application/json")
        elif route.path == "/scan":
            name = parse_qs(route.query).get("name", ["four_pct"])[0]
            if name == "user_picks":
                res = self.qbook.picks()
            elif name in ls.SCANS:
                res = self.qbook.scan(name)
            else:
                self.send_error(404)
                return
            self._send(json.dumps({
                "generated": datetime.now(IST).strftime("%H:%M:%S"),
                "streamed": self.qbook.size,
                "count": len(res["rows"]),
                "tracked": tracked_symbols(),
                **res,
            }), "application/json")
        elif route.path == "/orderpad":
            q = parse_qs(route.query)
            try:
                equity = float(q.get("equity", ["1000000"])[0])
                risk = float(q.get("risk", ["0.5"])[0])
            except ValueError:
                self.send_error(400)
                return
            now = datetime.now(IST)
            close = now.replace(hour=15, minute=30, second=0, microsecond=0)
            self._send(json.dumps({
                "generated": now.strftime("%H:%M:%S"),
                "session": order_pad.session_state(now),
                "minutes_to_close": max(0, int((close - now).total_seconds() // 60)),
                "equity": equity, "risk_pct": risk,
                "tickets": self.qbook.tickets(equity, risk),
            }), "application/json")
        elif route.path == "/chart":
            q = parse_qs(route.query)
            symbol = q.get("symbol", [""])[0].upper()
            interval = q.get("interval", ["day"])[0]
            if interval not in ("day", "5minute") or not symbol:
                self.send_error(404)
                return
            try:
                candles = self.charts.get(symbol, interval)
            except Exception as e:
                self._send(json.dumps({"error": str(e)}), "application/json")
                return
            if candles is None:
                self.send_error(404)
                return
            self._send(json.dumps({"symbol": symbol, "interval": interval,
                                   "is_fo": self.qbook.is_fo(symbol),
                                   "candles": candles}), "application/json")
        else:
            self.send_error(404)

    def log_message(self, *args):
        pass


def main():
    csv_path = sys.argv[1] if len(sys.argv) > 1 else None
    kite = get_kite_client()   # also loads .env

    summary = pd.read_parquet(SUMMARY_PATH)
    hist, stream_syms = build_stream_universe(summary)
    full_hist = summary.set_index("symbol", drop=False)   # User Picks may be illiquid
    picks = list(load_picks()["symbol"])
    missing = [s for s in picks if s not in full_hist.index]
    if missing:
        print(f"User picks not in summary, skipped: {', '.join(missing)}")
    market = strategy_registry.market_snapshot()
    if "mcap_cr" in summary.columns:
        top = summary["mcap_cr"].nlargest(150)
        if len(top) == 150:
            market["mcap150_cr"] = float(top.iloc[-1])
    print(f"Tape snapshot: {market or 'unavailable (mm_history missing)'}")
    qbook = QuoteBook(hist, _load_excluded(), full_hist=full_hist,
                      picks_path=PICKS_PATH, market=market)
    print(f"Intraday scan universe: {len(stream_syms)} liquid names "
          f"(turnover >= {MIN_TURNOVER_CR} Cr) · {len(picks)} user picks")

    watch_syms, dep_syms = build_watchlist(csv_path)
    source = csv_path or "anticipation scan"
    print(f"Movers watchlist from {source}: {len(watch_syms)} symbols "
          f"({len(dep_syms)} DEP)")

    # One websocket for all: scans need the whole liquid universe, the movers
    # list needs the watchlist, and User Picks may add illiquid names below the
    # turnover floor — every one must be subscribed to get a live quote.
    all_syms = sorted(set(stream_syms) | set(watch_syms) | set(picks))
    tokens = map_tokens(all_syms)
    # NaN would serialize as invalid JSON in /data — keep only real values
    mcap = ({s: v for s, v in zip(summary["symbol"], summary["mcap_cr"])
             if pd.notna(v)} if "mcap_cr" in summary.columns else {})
    qbook.set_movers(watch_syms, dep_syms, mcap)
    Handler.qbook = qbook
    Handler.charts = ChartCache(kite, {sym: tok for tok, sym in tokens.items()})
    Handler.kite = kite            # for on-demand quotes of non-streamed symbols

    server = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    print(f"Live scanner: http://localhost:{PORT}")

    start_ticker(os.getenv("KITE_API_KEY"), os.getenv("KITE_ACCESS_TOKEN"),
                 tokens, qbook)
    while True:
        time.sleep(60)


if __name__ == "__main__":
    main()
