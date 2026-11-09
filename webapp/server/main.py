"""
main.py — JSON API for the web dashboard.

Thin read-only layer over the same precomputed files the Streamlit desk uses
(data/processed/*.parquet). No Streamlit imports here — loaders are re-implemented
minimally so this server has zero UI dependencies.

Run:
    cd "<repo root>"
    python -m uvicorn webapp.server.main:app --port 8700 --reload
"""

import os
import sys
from datetime import datetime
from functools import lru_cache

import numpy as np
import pandas as pd
import urllib.error
import urllib.parse
import urllib.request
from zoneinfo import ZoneInfo

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, os.path.join(ROOT, "strategies"))

import json  # noqa: E402
import glob  # noqa: E402

import market_rhythm  # noqa: E402
import risk_regime  # noqa: E402
import magic_formula as magic  # noqa: E402
import order_pad as op  # noqa: E402
import strategy_registry as reg  # noqa: E402
from data_collection.storage import read_daily  # noqa: E402
from data_collection.nse.fo import download_fo_list  # noqa: E402
from indicators.moving_averages import sma_series  # noqa: E402
from stockbee import scans as sb  # noqa: E402
from .freshness import freshness  # noqa: E402
from .trade_bank import router as trade_bank_router  # noqa: E402
from .fund_study import router as fund_study_router  # noqa: E402

PROCESSED = os.path.join(ROOT, "data", "processed")
IST = ZoneInfo("Asia/Kolkata")
LIVE_BASE = "http://127.0.0.1:8602"
DMA_WINDOWS = (10, 20, 50, 200)
FNO_IV_SNAPSHOT = os.path.join(ROOT, "output", "live", "fno_iv_latest.json")


def _project_intraday_dmas(frame: pd.DataFrame, session_days: pd.Series,
                           daily: pd.DataFrame) -> pd.DataFrame:
    """Attach a live projection of each daily SMA to intraday candles.

    A completed daily SMA repeated on every five-minute bar renders as a
    staircase and ignores what today's price is doing. For each intraday bar,
    use that bar's close as the provisional daily close plus the preceding
    window-1 completed sessions. The final bar of a completed session therefore
    lands exactly on that day's ordinary DMA, while the line evolves smoothly
    during the session.
    """
    out = frame.copy()
    days = pd.Series(session_days.to_numpy(), index=out.index)
    history = daily[["date", "close"]].copy().sort_values("date")
    history["_day"] = pd.to_datetime(history["date"]).dt.date
    for day in days.dropna().unique():
        mask = days == day
        prior = history.loc[history["_day"] < day, "close"].dropna()
        for window in DMA_WINDOWS:
            if len(prior) < window - 1:
                out.loc[mask, f"dma{window}"] = np.nan
                continue
            completed_sum = prior.iloc[-(window - 1):].sum()
            out.loc[mask, f"dma{window}"] = ((completed_sum + out.loc[mask, "close"]) / window).round(2)
    return out


def _live_quote(symbol: str) -> dict | None:
    """Today's streaming quote for one symbol from the live scanner, or None
    when it's offline / the symbol isn't streamed. Short timeout so a chart
    never hangs waiting on it."""
    try:
        with urllib.request.urlopen(f"{LIVE_BASE}/quote?symbol={symbol}", timeout=1.5) as r:
            return json.loads(r.read())
    except (urllib.error.URLError, TimeoutError, ValueError, OSError):
        return None


def _live_5m_chart(symbol: str) -> dict | None:
    """Current Kite 5-minute history from the live scanner, when available.

    The scanner already enforces Kite's request limit and caches each symbol
    for 60 seconds. A failure returns immediately to the local Parquet fallback.
    """
    query = urllib.parse.urlencode({"symbol": symbol, "interval": "5minute"})
    try:
        with urllib.request.urlopen(f"{LIVE_BASE}/chart?{query}", timeout=4.0) as response:
            payload = json.loads(response.read())
    except (urllib.error.URLError, TimeoutError, ValueError, OSError):
        return None
    candles = payload.get("candles") or []
    if not candles or payload.get("error"):
        return None

    daily = read_daily(symbol, columns=["date", "close"])
    if daily.empty:
        return None
    daily = daily.sort_values("date")
    frame = pd.DataFrame(candles)
    # The scanner shifts Unix bars so Lightweight Charts renders IST wall
    # time. Its UTC calendar date therefore equals the intended IST date.
    session_days = pd.to_datetime(frame["time"], unit="s", utc=True).dt.date
    frame = _project_intraday_dmas(frame, session_days, daily)
    candles = _clean(frame)
    sessions = set(session_days)
    return {"symbol": symbol, "timeframe": "5m",
            "as_of": datetime.fromtimestamp(candles[-1]["time"] - 19800, IST).isoformat(),
            "sessions": len(sessions), "source": "kite_live",
            "dma_windows": list(DMA_WINDOWS), "candles": candles}

app = FastAPI(title="Trading Desk API")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["GET"],
    allow_headers=["*"],
)
app.include_router(trade_bank_router)
app.include_router(fund_study_router)


def _mtime(path: str) -> float:
    try:
        return os.path.getmtime(path)
    except FileNotFoundError:
        return 0.0


def _clean(df: pd.DataFrame) -> list[dict]:
    """NaN/Inf → None so the JSON is valid and the frontend can null-check."""
    df = df.replace([np.inf, -np.inf], np.nan)
    return df.astype(object).where(pd.notna(df), None).to_dict("records")


@lru_cache(maxsize=4)
def _universe(mtime: float) -> pd.DataFrame:
    path = os.path.join(PROCESSED, "universe_summary.parquet")
    if not os.path.exists(path):
        raise HTTPException(503, "universe_summary.parquet missing — run the EOD update first")
    df = pd.read_parquet(path)
    master_path = os.path.join(PROCESSED, "company_master.parquet")
    if os.path.exists(master_path):
        master = pd.read_parquet(master_path)[["symbol", "name", "sector", "industry"]]
        df = df.merge(master, on="symbol", how="left")
    return df


def universe() -> pd.DataFrame:
    return _universe(_mtime(os.path.join(PROCESSED, "universe_summary.parquet")))


@lru_cache(maxsize=4)
def _mm_history(mtime: float) -> pd.DataFrame:
    path = os.path.join(PROCESSED, "mm_history.parquet")
    if not os.path.exists(path):
        raise HTTPException(503, "mm_history.parquet missing — run the EOD update first")
    df = pd.read_parquet(path)
    df = df.reset_index().rename(columns={df.index.name or "index": "date"})
    df["date"] = pd.to_datetime(df["date"]).dt.strftime("%Y-%m-%d")
    return df


def mm_history() -> pd.DataFrame:
    return _mm_history(_mtime(os.path.join(PROCESSED, "mm_history.parquet")))


def _regime_summary() -> dict:
    """Today's HMM risk regime from the state file (tier + crash-risk dial)."""
    try:
        with open(STATE_PATH) as f:
            r = json.load(f).get("regime", {})
    except (OSError, json.JSONDecodeError):
        return {"regime_tier": None}
    return {"regime_tier": r.get("tier"), "p_drop_20d": r.get("p_drop_20d"),
            "baseline_p_drop_20d": r.get("baseline_p_drop_20d")}


@lru_cache(maxsize=2)
def _risk_history(_mtime_key: float) -> pd.DataFrame:
    return risk_regime.walkforward_history()


@app.get("/api/risk_regime")
def risk_regime_history(n_days: int = 756):
    """HMM crash-risk dial vs its historical average, last n_days sessions."""
    df = _risk_history(_mtime(risk_regime.LIVE_PARQUET)).copy()
    df["sma200"] = sma_series(df["close"], 200).round(2)  # on full history, then windowed
    df = df.tail(n_days)
    df.index.name = "date"
    df = df.reset_index()
    df["date"] = pd.to_datetime(df["date"]).dt.strftime("%Y-%m-%d")
    return _clean(df[["date", "close", "sma200", "p_drop_20d", "baseline_p_drop_20d", "tier", "state"]])


@app.get("/api/meta")
def meta():
    u = universe()
    mm = mm_history()
    last = mm.iloc[-1]
    as_of = str(u["last_date"].max())[:10]
    fresh = freshness(as_of)
    return {
        "as_of": as_of, "freshness": fresh,
        "n_stocks": len(u),
        **_regime_summary(),
        "net4": int(last["up4"] - last["dn4"]),
        "up4": int(last["up4"]),
        "dn4": int(last["dn4"]),
        "pct40ma": round(float(last["pct40ma"]), 1),
        "ti65_nifty500": round(float(last["ti65_nifty500"]), 3)
        if pd.notna(last["ti65_nifty500"]) and np.isfinite(last["ti65_nifty500"]) else None,
    }


UNIVERSE_COLS = [
    "rank", "symbol", "name", "sector", "close", "chg_pct", "gap_pct",
    "r1w_pct", "r1mo_pct", "r3mo_pct", "r6mo_pct", "r12mo_pct",
    "adr_pct", "avg_turnover_cr", "volume_ratio", "rs_rank", "ti65",
    "pct_from_52w_high", "mcap_cr", "is_fo", "consol_days", "trend_quality",
]


@app.get("/api/universe")
def universe_endpoint():
    df = universe()
    cols = [c for c in UNIVERSE_COLS if c in df.columns]
    return _clean(df[cols])


@app.get("/api/magic-formula")
def magic_formula_endpoint():
    """Latest dated Screener fundamentals blended with local technicals."""
    try:
        board, metadata = magic.load_latest_board()
    except (FileNotFoundError, ValueError, OSError) as exc:
        return {
            "ready": False,
            "message": str(exc),
            "setup_command": "python src/magic_formula.py --auto-import",
            "rows": [],
        }

    states = board["technical_state"].value_counts().to_dict()
    sector_source = board[board["is_candidate"]].copy()
    sectors = []
    if not sector_source.empty:
        sectors = (
            sector_source.assign(industry=sector_source["industry"].replace("", "Unclassified"))
            .groupby("industry", dropna=False)
            .agg(candidates=("symbol", "count"), average_score=("blend_score", "mean"))
            .reset_index()
            .sort_values(["candidates", "average_score"], ascending=False)
        )
        sectors["average_score"] = sectors["average_score"].round(1)
        sectors = _clean(sectors)

    columns = [
        "candidate_rank", "symbol", "name", "industry", "market_cap_cr",
        "ev_ebit", "roce", "roce_3y", "value_score", "quality_score",
        "magic_score", "momentum_12_1_pct", "momentum_score", "blend_score",
        "close", "sma50", "sma200", "avg_turnover_cr", "technical_state",
        "is_candidate", "price_as_of",
    ]
    return {
        "ready": True,
        "meta": metadata,
        "summary": {
            "universe": int(len(board)),
            "candidates": int(board["is_candidate"].sum()),
            "confirmed": int(states.get("CONFIRMED", 0)),
            "waiting": int(states.get("WAITING_FOR_TREND", 0)),
            "insufficient": int(states.get("INSUFFICIENT_HISTORY", 0) + states.get("NO_PRICE_DATA", 0)),
            "median_magic_score": round(float(board["magic_score"].median()), 1) if len(board) else None,
            "median_momentum_pct": round(float(board["momentum_12_1_pct"].median()), 1)
            if board["momentum_12_1_pct"].notna().any() else None,
        },
        "sectors": sectors,
        "rows": _clean(board[[column for column in columns if column in board]]),
    }


def _pct_rank(values: pd.Series) -> pd.Series:
    return values.rank(pct=True, method="average").mul(100).round(1)


@lru_cache(maxsize=2)
def _fno_dashboard(summary_mtime: float, close_mtime: float, fo_mtime: float) -> dict:
    """F&O-only view derived from one consistent EOD close matrix.

    The same 1M/3M/6M composite drives every RS column. Only the comparison
    set changes, which makes the ratings comparable and easy to explain.
    """
    close_path = os.path.join(PROCESSED, "close_matrix.parquet")
    close = pd.read_parquet(close_path).sort_index()
    periods = (21, 63, 126)
    component_ranks = []
    for n in periods:
        returns = close.iloc[-1].div(close.iloc[-1 - n]).sub(1)
        component_ranks.append(_pct_rank(returns))
    score = component_ranks[0].mul(.40).add(component_ranks[1].mul(.30), fill_value=np.nan) \
        .add(component_ranks[2].mul(.30), fill_value=np.nan)

    current_month = pd.Timestamp.now(IST).strftime("%Y-%m")
    fo_path = os.path.join(ROOT, "data", "raw", "fo", f"fo_{current_month}.csv")
    # Normally the nightly updater has already refreshed this. This fallback
    # also keeps the dashboard usable after a new month begins.
    fo = download_fo_list(current_month)
    fo["symbol"] = fo["symbol"].astype(str).str.strip().str.upper()

    u = universe().copy()
    f = u[u["symbol"].isin(set(fo["symbol"]))].copy()
    f["lot_size"] = f["symbol"].map(fo.set_index("symbol")["lot_size"])
    f["rs_all"] = f["symbol"].map(_pct_rank(score))
    f["rs_fo"] = f["symbol"].map(_pct_rank(score.reindex(f["symbol"]).dropna()))

    # Nifty 500 is the most useful common benchmark for the stock-futures
    # universe. Use the newest locally captured constituent file.
    index_files = sorted(glob.glob(os.path.join(ROOT, "data", "raw", "nifty500_*.csv")))
    if index_files:
        members = set(pd.read_csv(index_files[-1])["symbol"].astype(str).str.upper())
        index_rank = _pct_rank(score.reindex(list(members)).dropna())
        f["index_name"] = np.where(f["symbol"].isin(members), "NIFTY 500", "ALL NSE")
        f["rs_index"] = f["symbol"].map(index_rank).where(f["symbol"].isin(members), f["rs_all"])
    else:
        f["index_name"] = "ALL NSE"
        f["rs_index"] = f["rs_all"]

    f["rs_sector"] = f.groupby(f["sector"].fillna("Unclassified"))["symbol"] \
        .transform(lambda symbols: symbols.map(_pct_rank(score.reindex(symbols).dropna())))
    close_change = close.pct_change(fill_method=None).mul(100)

    def _prior_burst(row):
        """Move immediately before the current quiet-base run.

        consol_days excludes the current bar and counts backwards to the most
        recent volatility-adjusted burst. In the full close matrix that burst
        therefore sits consol_days + 2 rows from the end.
        """
        days = row.get("consol_days")
        symbol = row["symbol"]
        if pd.isna(days) or symbol not in close_change:
            return np.nan
        offset = int(days) + 2
        series = close_change[symbol]
        if offset > len(series):
            return np.nan
        return series.iloc[-offset]

    f["prior_burst_pct"] = f.apply(_prior_burst, axis=1).round(2)
    for n in (5, 10, 50, 200):
        ret = close.iloc[-1].div(close.iloc[-1 - n]).sub(1).mul(100)
        f[f"r{n}d_pct"] = f["symbol"].map(ret).round(2)

    f = f.sort_values(["rs_fo", "avg_turnover_cr"], ascending=False)
    cols = ["symbol", "name", "sector", "index_name", "lot_size", "close", "chg_pct", "gap_pct",
            "rs_all", "rs_fo", "rs_index", "rs_sector", "adr_pct",
            "r5d_pct", "r10d_pct", "r50d_pct", "r200d_pct", "max_up_7d", "max_down_7d",
            "volume_ratio", "range_pos", "range_pct_5d", "nr7", "inside_days",
            "vol_contraction", "consol_days", "consol_range_pct", "consol_vol_ratio",
            "burst_thr_pct", "prior_burst_pct", "prior_day_quiet", "trend_quality"]
    as_of = pd.to_datetime(close.index[-1]).strftime("%Y-%m-%d")
    source_date = pd.Timestamp(os.path.getmtime(fo_path), unit="s", tz="UTC").tz_convert(IST).strftime("%Y-%m-%d %H:%M") \
        if os.path.exists(fo_path) else None
    return {"as_of": as_of, "fo_month": current_month, "fo_updated_at": source_date,
            "count": len(f), "rows": _clean(f[[c for c in cols if c in f.columns]])}


@app.get("/api/fno")
def fno_dashboard():
    current_month = pd.Timestamp.now(IST).strftime("%Y-%m")
    fo_path = os.path.join(ROOT, "data", "raw", "fo", f"fo_{current_month}.csv")
    # Refresh first so its mtime becomes part of the cache key.
    download_fo_list(current_month)
    return _fno_dashboard(
        _mtime(os.path.join(PROCESSED, "universe_summary.parquet")),
        _mtime(os.path.join(PROCESSED, "close_matrix.parquet")),
        _mtime(fo_path),
    )


@lru_cache(maxsize=2)
def _fno_iv_snapshot(mtime: float) -> dict:
    if not mtime:
        return {"status": "offline", "updated_at": None, "count": 0, "rows": []}
    try:
        with open(FNO_IV_SNAPSHOT) as handle:
            payload = json.load(handle)
    except (OSError, json.JSONDecodeError):
        return {"status": "offline", "updated_at": None, "count": 0, "rows": []}
    try:
        updated = pd.Timestamp(payload.get("updated_at"))
        now = pd.Timestamp.now(tz=IST)
        age = max(0, int((now - updated).total_seconds()))
    except (TypeError, ValueError):
        age = None
    stale_after = int(payload.get("stale_after_seconds", 120))
    payload["age_seconds"] = age
    payload["stale"] = age is None or age > stale_after
    if payload["stale"]:
        payload["status"] = "stale"
        payload["rows"] = []
        payload["count"] = 0
    return payload


@app.get("/api/fno/iv")
def fno_iv_snapshot():
    """Tiny non-blocking live IV snapshot; never reaches Kite from a request."""
    return _fno_iv_snapshot(_mtime(FNO_IV_SNAPSHOT))


@lru_cache(maxsize=256)
def _fno_chart(symbol: str, timeframe: str, days: int,
               price_mtime: float, daily_mtime: float) -> dict:
    """Daily, weekly, or entry-focused 5-minute candles.

    The cache key includes the source mtimes, so an EOD/intraday update
    invalidates only the affected symbol. Moving averages are calculated once
    here rather than on every browser render.
    """
    del price_mtime, daily_mtime  # cache-key inputs only
    daily = read_daily(symbol, columns=["date", "open", "high", "low", "close", "volume"])
    if daily.empty:
        raise HTTPException(404, f"No data for {symbol}")
    daily = daily.sort_values("date")
    for window in DMA_WINDOWS:
        daily[f"dma{window}"] = daily["close"].rolling(window).mean().round(2)

    if timeframe == "5m":
        path = os.path.join(ROOT, "data", "parquet", "intraday_5m", f"{symbol}.parquet")
        if not os.path.exists(path):
            raise HTTPException(404, f"No cached 5-minute data for {symbol}")
        df = pd.read_parquet(path, columns=["date", "open", "high", "low", "close", "volume"]) \
            .sort_values("date")
        sessions = pd.to_datetime(df["date"]).dt.date.drop_duplicates().tail(21)
        df = df[pd.to_datetime(df["date"]).dt.date.isin(set(sessions))].copy()
        df["time"] = pd.to_datetime(df["date"]).map(lambda d: int(d.timestamp()))
        intraday_day = pd.to_datetime(df["date"]).dt.date
        df = _project_intraday_dmas(df, intraday_day, daily)
        source_as_of = df["date"].iloc[-1]
    else:
        df = daily.set_index("date")
        source_as_of = df.index[-1]
        if timeframe == "weekly":
            aggregations = {"open": "first", "high": "max", "low": "min",
                            "close": "last", "volume": "sum"}
            aggregations.update({f"dma{window}": "last" for window in DMA_WINDOWS})
            df = df.resample("W-FRI").agg(aggregations).dropna(subset=["close"])
        df = df.tail(max(20, min(days, 756))).reset_index()
        df["time"] = pd.to_datetime(df["date"]).dt.strftime("%Y-%m-%d")

    candle_cols = ["time", "open", "high", "low", "close", "volume"] \
        + [f"dma{window}" for window in DMA_WINDOWS]
    candles = _clean(df[candle_cols])
    as_of = source_as_of
    return {"symbol": symbol, "timeframe": timeframe, "as_of": str(as_of),
            "sessions": min(21, len(set(pd.to_datetime(df["date"]).dt.date))) if timeframe == "5m" else None,
            "source": "local_intraday_cache" if timeframe == "5m" else "eod",
            "dma_windows": list(DMA_WINDOWS), "candles": candles}


@app.get("/api/fno/chart/{symbol}")
def fno_chart(symbol: str, timeframe: str = "daily", days: int = 126):
    """Cached daily, weekly, or 5-minute chart payload.

    Intraday is deliberately capped at the most recent 21 trading sessions.
    """
    symbol = symbol.upper()
    if timeframe not in ("daily", "weekly", "5m"):
        raise HTTPException(422, "timeframe must be daily, weekly, or 5m")
    if timeframe == "5m":
        live = _live_5m_chart(symbol)
        if live is not None:
            return live
    daily_path = os.path.join(ROOT, "data", "parquet", "daily", f"{symbol}.parquet")
    price_path = daily_path if timeframe != "5m" else \
        os.path.join(ROOT, "data", "parquet", "intraday_5m", f"{symbol}.parquet")
    return _fno_chart(symbol, timeframe, days, _mtime(price_path), _mtime(daily_path))


@app.get("/api/stock/{symbol}")
def stock_detail(symbol: str, n_days: int = 252):
    symbol = symbol.upper()
    df = read_daily(symbol)
    if df.empty:
        raise HTTPException(404, f"No data for {symbol}")

    # Stored history goes only up to the nightly summary's data date — a
    # partial/unreconciled bar in the raw parquet must not leak in. Today's bar
    # is added separately from the live quote below, so the chart's newest day
    # always matches the Live tables instead of showing yesterday's EOD.
    as_of = str(universe()["last_date"].max())[:10]
    df["date"] = df["date"].dt.strftime("%Y-%m-%d")   # stored dates → plain ISO strings
    df = df[df["date"] <= as_of].copy()
    if df.empty:
        raise HTTPException(404, f"No data for {symbol} up to {as_of}")

    # Append today's forming bar from the live scanner when the market is open
    # and this symbol is streaming, but only if it's a day beyond stored EOD
    # (after the nightly update lands today's real bar, stored wins).
    live = _live_quote(symbol)
    live_used = False
    if live and live.get("last") is not None:
        today = pd.Timestamp.now(IST).strftime("%Y-%m-%d")
        if today > df["date"].iloc[-1]:
            last = live["last"]
            df = pd.concat([df, pd.DataFrame([{
                "date": today,
                "open": live.get("open") or last,
                "high": live.get("high") or last,
                "low": live.get("low") or last,
                "close": last,
                "volume": live.get("vol") or 0,
            }])], ignore_index=True)
            live_used = True

    # Indicators are computed on the full series (incl. the live bar) so the
    # last SMA/TI65 point reflects today, then windowed.
    ti65 = df["close"].rolling(7).mean() / df["close"].rolling(65).mean()
    df["ti65"] = ti65.round(3)
    for n in (10, 20, 50, 200):
        df[f"sma{n}"] = sma_series(df["close"], n).round(2)
    df = df.tail(n_days).copy().reset_index(drop=True)

    row = universe()[universe()["symbol"] == symbol]
    profile = _clean(row)[0] if not row.empty else {}
    if live_used:
        # Header price/change track the live quote, matching the Live tables.
        profile["close"] = round(float(live["last"]), 2)
        prev = live.get("prev_close")
        if prev:
            profile["chg_pct"] = round((live["last"] / prev - 1) * 100, 2)

    return {
        "symbol": symbol,
        "live": live_used,
        "profile": profile,
        "candles": _clean(df[["date", "open", "high", "low", "close", "volume",
                              "sma10", "sma20", "sma50", "sma200", "ti65"]]),
    }


def _excluded() -> set:
    """ASM/GSM symbols from the newest cached surveillance CSVs (offline read).

    Read fresh on every call (two small CSVs, ~ms): an lru_cache keyed on the
    calendar day served yesterday's list between the ~22:00 EOD update and
    midnight — exactly the window when tomorrow's tickets are prepared."""
    import glob
    out = set()
    for prefix in ("asm", "gsm"):
        files = sorted(glob.glob(os.path.join(ROOT, "data", "raw", "surveillance", f"{prefix}_*.csv")))
        if not files:
            continue
        try:
            df = pd.read_csv(files[-1])
        except (OSError, pd.errors.EmptyDataError):
            continue
        col = next((c for c in df.columns if "symbol" in c.lower()), None)
        if col:
            out.update(df[col].dropna().astype(str).str.strip().str.upper())
    return out


SCANS = {
    "four_pct": (sb.four_pct, "4% Breakout", "Up ≥4% today on higher volume, strong close"),
    "four_pct_down": (sb.four_pct_down, "4% Breakdown", "Down ≥4% today on higher volume"),
    "four_pct_up_7d": (sb.four_pct_up_7d, "4% Up · 7d", "A ≥4% up day within the last 7 sessions"),
    "four_pct_down_7d": (sb.four_pct_down_7d, "4% Down · 7d", "A ≥4% down day within the last 7 sessions"),
    "ti65": (sb.ti65, "TI65 Trend", "7-DMA ≥ 5% above 65-DMA — established uptrend"),
    "anticipation": (sb.anticipation, "Anticipation", "3M leader coiling in a tight, quiet range"),
    "reversal_bullish": (sb.reversal_bullish, "Bullish Reversal", "Liquid stock reversing up after a 2+ day slide"),
    "bottom_bounce": (sb.bottom_bounce, "Bottom Bounce", "≥4% bounce, still 25%+ below its 52-week high"),
    "weak_structure": (sb.weak_structure_short, "Weak Structure", "Broken trend structure — short candidates"),
    "swing_exhaustion": (sb.swing_exhaustion, "Swing Exhaustion", "Extended swing showing exhaustion signs"),
}

SCAN_COLS = [
    "symbol", "name", "sector", "close", "chg_pct", "max_up_7d", "max_down_7d",
    "volume_ratio", "range_pos", "ti65", "r1mo_pct", "r3mo_pct", "r6mo_pct",
    "adr_pct", "avg_turnover_cr", "rs_rank", "mcap_cr", "is_fo", "trend_quality",
]


@app.get("/api/scans")
def scan_list():
    return [{"key": k, "label": label, "desc": desc} for k, (_, label, desc) in SCANS.items()]


@app.get("/api/scans/{name}")
def run_scan(name: str, min_turnover_cr: float = 1.0, min_price: float = 0.0,
             fo_only: bool = False, excl_surv: bool = True):
    if name not in SCANS:
        raise HTTPException(404, f"Unknown scan {name}")
    fn = SCANS[name][0]
    excluded = _excluded() if excl_surv else None
    res = fn(universe(), min_turnover_cr=min_turnover_cr, min_price=min_price,
             fo_only=fo_only, excluded=excluded)
    return {"count": len(res), "rows": _clean(res[[c for c in SCAN_COLS if c in res.columns]])}


HORIZONS = [("1D", "chg_pct"), ("1W", "r1w_pct"), ("1M", "r1mo_pct"),
            ("3M", "r3mo_pct"), ("6M", "r6mo_pct"), ("1Y", "r12mo_pct")]


def _round_or_none(v, digits=1):
    v = float(v)
    return None if pd.isna(v) else round(v, digits)


@app.get("/api/sectors")
def sectors(level: str = "sector", weighting: str = "cap"):
    """Point-in-time weighted group returns: start-of-window mcap = mcap / (1 + r)."""
    if level not in ("sector", "industry"):
        raise HTTPException(422, "level must be 'sector' or 'industry'")
    df = universe().copy()
    df = df[df["avg_turnover_cr"] >= 1.0]
    df[level] = df[level].fillna("Unclassified")
    rows = []
    for group, g in df.groupby(level):
        row = {"group": group, "stocks": len(g),
               "adv_pct": _round_or_none((g["chg_pct"] > 0).mean() * 100),
               "vs_52wh": _round_or_none(g["pct_from_52w_high"].mean())}
        for label, col in HORIZONS:
            r = g[col].dropna()
            if r.empty:
                row[label] = None
                continue
            if weighting == "cap":
                mcap0 = (g.loc[r.index, "mcap_cr"] / (1 + r / 100)).clip(lower=0)
                mcap0 = mcap0.replace([np.inf, -np.inf], np.nan)
                valid = mcap0.notna() & (mcap0 > 0)
                row[label] = round(float((r[valid] * mcap0[valid]).sum() / mcap0[valid].sum()), 2) \
                    if valid.any() else None
            else:
                row[label] = round(float(r.mean()), 2)
        rows.append(row)
    rows.sort(key=lambda x: x["1D"] if x["1D"] is not None else -999, reverse=True)
    return rows


MEMBER_COLS = ["symbol", "name", "industry", "mcap_cr", "close", "chg_pct",
               "r1w_pct", "r1mo_pct", "r3mo_pct", "r6mo_pct", "r12mo_pct",
               "pct_from_52w_high", "avg_turnover_cr", "rs_rank"]


@app.get("/api/sectors/members")
def sector_members(group: str, level: str = "sector"):
    if level not in ("sector", "industry"):
        raise HTTPException(422, "level must be 'sector' or 'industry'")
    df = universe()
    df = df[df["avg_turnover_cr"] >= 1.0]
    hit = df[df[level].fillna("Unclassified") == group]
    if hit.empty:
        raise HTTPException(404, f"No stocks in {level} {group}")
    hit = hit.sort_values("chg_pct", ascending=False)
    return _clean(hit[[c for c in MEMBER_COLS if c in hit.columns]])


STATE_PATH = os.path.join(ROOT, "output", "state", "latest.json")


@app.get("/api/state")
def state():
    """The nightly daily-state file, as-is — regime, signals, all scan
    candidate lists with entry/stop/flags. The Brief and Setups pages are
    pure renderers over this."""
    try:
        with open(STATE_PATH) as f:
            payload = json.load(f)
            data_date = payload.get("meta", {}).get("data_date")
            fresh = freshness(data_date)
            payload["freshness"] = fresh
            if fresh["stale"]:
                # Preserve provenance while removing anything that could be
                # mistaken for a current trade/setup.
                payload["actionable"] = False
                for scan in (payload.get("scans") or {}).values():
                    if isinstance(scan, dict):
                        scan["candidates"] = []
                        scan["total_matches"] = 0
                if isinstance(payload.get("incubation"), dict):
                    payload["incubation"]["strategies"] = {}
            return payload
    except (OSError, json.JSONDecodeError):
        raise HTTPException(404, "No state file — run the EOD update first.")


@app.get("/api/strategies")
def strategies():
    market = reg.market_snapshot()
    data_date = market.get("date")
    fresh = freshness(data_date)
    cards = []
    for s in reg.STRATEGIES:
        gates = reg.evaluate_gates(s, market)
        gates_ok = all(g["ok"] is True for g in gates) if gates else True
        cards.append({
            "id": s["id"], "name": s["name"], "direction": s["direction"],
            "status": s["status"], "universe": s["universe"], "rule": s["rule"],
            "lifecycle": s.get("lifecycle", "research_only"),
            "tradeable": bool(s.get("tradeable", False)),
            "action_policy": s.get("action_policy", "research_only"),
            "actionable": bool(s.get("tradeable", False) and gates_ok and fresh["actionable"]),
            "stats": s["stats"], "caveats": s.get("caveats", []),
            "doc_url": s.get("doc_url"),
            "gates": gates,
        })
    return {"market": market, "strategies": cards,
            "freshness": fresh, "actionable": fresh["actionable"]}


@app.get("/api/rhythm")
def rhythm(n_days: int = 252):
    path = os.path.join(PROCESSED, "market_rhythm.parquet")
    if not os.path.exists(path):
        raise HTTPException(503, "market_rhythm.parquet missing — run the EOD update first")
    hist = pd.read_parquet(path)
    shares = market_rhythm.rolling_shares(hist, 21)

    def series(df, cols):
        out = df[cols].tail(n_days).reset_index()
        out.columns = ["date"] + cols
        out["date"] = pd.to_datetime(out["date"]).dt.strftime("%Y-%m-%d")
        return _clean(out)

    tail = hist.tail(21)
    return {
        "spread_21d": _round_or_none(tail["leader_spread"].mean(), 2),
        "winners_21d": _round_or_none(tail["n_winners"].mean(), 1),
        "spread": series(hist, ["leader_spread"]),
        "shares": series(shares, ["w_breakout", "w_reversal", "w_bounce", "w_other"]),
        "winners": series(hist.assign(ma21=hist["n_winners"].rolling(21).mean()),
                          ["n_winners", "ma21"]),
    }


@app.get("/api/orderpad")
def orderpad(equity: float = 1_000_000, risk_pct: float = 0.5):
    """Tonight's EOD tickets from the state file. Prepares orders only —
    nothing here places anything."""
    try:
        with open(STATE_PATH) as f:
            s = json.load(f)
    except (OSError, json.JSONDecodeError):
        raise HTTPException(404, "No state file")
    fresh = freshness(s.get("meta", {}).get("data_date"))
    if fresh["stale"]:
        return {"session": op.session_state(), "data_date": s.get("meta", {}).get("data_date"),
                "freshness": fresh, "actionable": False, "regime_risk_pct": None,
                "shorts": [], "shorts_gates_blocked": [], "breakouts": []}

    registry = {item["id"]: item for item in reg.STRATEGIES}

    def pack(t, strategy_id=None):
        # op.size() returns no qty when entry <= 0 or entry == stop; punch_card
        # guards for that but plan_command doesn't — skip it for such tickets
        # instead of 500ing the whole pad.
        approved = bool(strategy_id and registry.get(strategy_id, {}).get("tradeable"))
        if not approved:
            policy = registry.get(strategy_id, {}).get("action_policy", "not_in_live_registry")
            t = {**t, "actionable": False,
                 "note": f"PAPER ONLY ({policy}) — {t['note']}"}
        return {**t, "card": op.punch_card(t),
                "plan_cmd": op.plan_command(t) if t.get("qty") and approved else ""}

    knobs = s.get("regime", {}).get("knobs", {})
    # Account positions are not yet wired into this read-only pad, so zero is
    # explicit rather than implied. The server-side engine still enforces the
    # regime's per-ticket gross/heat/slot limits and reports any rejection.
    portfolio = {"existing_gross_exposure": 0.0, "existing_heat": 0.0,
                 "open_positions": 0,
                 "max_positions": int(knobs.get("max_open_positions", 1)),
                 "max_gross_exposure_pct": float(knobs.get("max_gross_exposure_pct", 100)),
                 "max_heat_pct": float(knobs.get("risk_per_trade_pct", risk_pct)) * max(1, int(knobs.get("max_open_positions", 1))),
                 "leverage": 1.0}
    shorts, gates_blocked = [], []
    block = (s.get("incubation", {}).get("strategies", {}) or {}).get("b5_short_green_tape", {})
    if block.get("gates_pass"):
        shorts = [pack(op.ticket(c["symbol"], "lone_loser_short", c["close"],
                                 c["stop_ref"], equity, risk_pct, **portfolio),
                       "lone_loser_short")
                  for c in block.get("candidates", [])]
    else:
        gates_blocked = [k for k, v in block.get("gates", {}).items() if not v]

    breakouts = [pack(op.ticket(c["symbol"], "breakout", c["entry_price"],
                                c["stop_price"], equity, risk_pct, **portfolio))
                 for c in s.get("scans", {}).get("breakout_setup", {}).get("candidates", [])
                 if not c.get("flags") and c.get("entry_price") and c.get("stop_price")]

    return {
        "session": op.session_state(),
        "data_date": s.get("meta", {}).get("data_date"),
        "freshness": fresh,
        "actionable": any(t["actionable"] for t in shorts + breakouts),
        "regime_risk_pct": knobs.get("risk_per_trade_pct", 0.5),
        "shorts": shorts, "shorts_gates_blocked": gates_blocked,
        "breakouts": breakouts,
    }


@app.get("/api/docs")
def docs():
    path = os.path.join(ROOT, "docs", "SCANS_REFERENCE.md")
    try:
        with open(path) as f:
            return {"markdown": f.read()}
    except OSError:
        raise HTTPException(404, "SCANS_REFERENCE.md not found")


# ── Live scanner proxy ─────────────────────────────────────────────────────────
# The intraday scanner (src/live_anticipation.py, port 8602) keeps the Kite
# websocket + QuoteBook; this app is just its UI. When it isn't running the
# frontend gets {"offline": true} and shows a friendly banner instead of errors.

# "track" is deliberately NOT proxied: it's a GET that writes tracked.csv on
# the live server — a mutation reachable by any webpage via <img src=...>.
# "quote" is used internally by /api/stock, not exposed here.
LIVE_ENDPOINTS = {"data", "fno", "scan", "orderpad"}


@app.get("/api/live/{endpoint}")
def live_proxy(endpoint: str, request: Request):
    if endpoint not in LIVE_ENDPOINTS:
        raise HTTPException(404, f"Unknown live endpoint {endpoint}")
    url = f"{LIVE_BASE}/{endpoint}"
    if request.url.query:
        url += f"?{request.url.query}"
    try:
        with urllib.request.urlopen(url, timeout=3) as r:
            return Response(content=r.read(), media_type="application/json")
    except (urllib.error.URLError, TimeoutError):
        return {"offline": True}


@app.get("/api/breadth")
def breadth(n_days: int = 252):
    df = mm_history().tail(n_days)
    cols = ["date", "up4", "dn4", "net4", "ratio5", "ratio10",
            "up25q", "dn25q", "up25m", "dn25m", "up50m", "dn50m",
            "pct40ma", "pct20ma",
            "ti65_nifty50", "ti65_nifty500"]
    return _clean(df[[c for c in cols if c in df.columns]])
