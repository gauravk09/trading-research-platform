"""Trade Bank API — scroll through every historical trade of a backtested setup.

Setups: one entry per study event log in output/studies. Each says where the
entry is (signal-day price vs next-day open) and which column holds the result
(R for setups with a real exit rule, % return at a fixed horizon otherwise).
Detail: daily candles ~1 year either side of the entry day (dashboard SMAs),
5-min bars from 2 sessions before to 2 after (the intraday store starts
29 Aug 2024), and marked corporate filings in the window.
"""
import os
import sys
from functools import lru_cache

import pandas as pd
from fastapi import APIRouter, HTTPException

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, os.path.join(ROOT, "src", "backtest", "studies"))

from storage import read_daily  # noqa: E402
from indicators.moving_averages import sma_series  # noqa: E402
from ep9m_trade_bank import FILING_MARKS, load_filings, load_intraday  # noqa: E402

router = APIRouter(prefix="/api/tradebank")

STUDIES = os.path.join(ROOT, "output", "studies")
BARS_EACH_SIDE = 252
INTRADAY_EACH_SIDE = 2
IST_OFFSET_S = 19800   # lightweight-charts draws UTC; shift so the axis reads IST

# Where the entry happens — also tells the 5-min chart which bar gets the BUY arrow.
CLOSE = "close"          # signal-day close (price in the log's `entry` column)
TRIGGER = "trigger"      # buy-stop hit during the signal day (price in `entry`)
NEXT_OPEN = "open"       # open of the bar after the signal
PCT20 = ("ret_o20", "%", "% from next-day open to 20 days later")

# slug -> label, csv, entry timing, (result column, unit, what the result means)
SETUPS = {
    "ep9m": ("EP9M", "ep9m_catalyst_split_events.csv", CLOSE,
             ("r_scale", "R", "R, scale-out exit: 50% day-3 close, 30% day-4, 20% runner")),
    "dep_consol_break": ("DEP consolidation break", "dep_consol_break_events.csv", TRIGGER,
                         ("r20", "R", "R after 20 days, stop = base low")),
    "darvas_box": ("Darvas box", "darvas_box_events.csv", NEXT_OPEN, PCT20),
    "high_tight_flag": ("High-tight flag", "high_tight_flag_events.csv", NEXT_OPEN, PCT20),
    "kell_ema_crossback": ("Kell EMA crossback", "kell_ema_crossback_events.csv", NEXT_OPEN, PCT20),
    "minervini_trend_template": ("Minervini trend template", "minervini_trend_template_events.csv", NEXT_OPEN, PCT20),
    "pocket_pivot": ("Pocket pivot", "pocket_pivot_events.csv", NEXT_OPEN, PCT20),
    "ryan_52wk_high": ("Ryan 52-wk high", "ryan_52wk_high_events.csv", NEXT_OPEN, PCT20),
    "stockbee_4pct_burst": ("Stockbee 4% burst", "stockbee_4pct_burst_events.csv", NEXT_OPEN, PCT20),
    "weinstein_stage2": ("Weinstein stage 2", "weinstein_stage2_events.csv", NEXT_OPEN, PCT20),
    "connors_rsi2": ("Connors RSI-2", "connors_rsi2_events.csv", NEXT_OPEN, PCT20),
    "donchian_turtle": ("Donchian turtle", "donchian_turtle_events.csv", NEXT_OPEN, PCT20),
    "washout_reversal": ("Washout reversal", "washout_reversal_events.csv", NEXT_OPEN, PCT20),
}


def _setup(slug: str) -> tuple:
    if slug not in SETUPS:
        raise HTTPException(404, f"unknown setup {slug}")
    return SETUPS[slug]


@lru_cache(maxsize=4)
def _events(slug: str) -> pd.DataFrame:
    _, csv, _, (col, _, _) = _setup(slug)
    ev = pd.read_csv(os.path.join(STUDIES, csv), low_memory=False)
    ev["day"] = ev["date"].str[:10]
    ev["result"] = ev[col]
    ev = ev.dropna(subset=["result"])
    return ev.sort_values(["day", "symbol"]).reset_index(drop=True)


@lru_cache(maxsize=1)
def _filings() -> dict:
    return load_filings()


def _parse_filed(col: pd.Series) -> pd.Series:
    """NSE filing stamps come as '29-Oct-2025 14:08:12' or '25-May-2016 12:31'."""
    full = pd.to_datetime(col, format="%d-%b-%Y %H:%M:%S", errors="coerce")
    return full.fillna(pd.to_datetime(col, format="%d-%b-%Y %H:%M", errors="coerce"))


@lru_cache(maxsize=1)
def _quarterly() -> dict:
    """symbol -> quarterly results (one row per quarter) with YoY growth.

    YoY is computed within one reporting basis (consolidated vs standalone) so a
    basis switch never shows as fake growth; consolidated wins when both exist
    (a holding company's standalone numbers can be a tiny fraction of the group).
    """
    f = pd.read_parquet(os.path.join(ROOT, "data", "processed", "financials.parquet"))
    f["qe"] = pd.to_datetime(f["quarter_end"], errors="coerce")
    f["filed"] = _parse_filed(f["filing_date"])
    f = f.dropna(subset=["qe"]).sort_values("filed").drop_duplicates(["symbol", "consolidated", "qe"], keep="last")
    prior = f[["symbol", "consolidated", "qe", "revenue_cr", "pat_cr"]].copy()
    prior["qe"] = prior["qe"] + pd.DateOffset(years=1)
    f = f.merge(prior, on=["symbol", "consolidated", "qe"], how="left", suffixes=("", "_ly"))
    for col in ("revenue_cr", "pat_cr"):
        base = f[f"{col}_ly"]
        f[f"{col}_yoy"] = ((f[col] - base) / base.abs() * 100).where(base.abs() > 0)
    f = f.sort_values("consolidated").drop_duplicates(["symbol", "qe"], keep="last")
    return {s: g.sort_values("qe") for s, g in f.groupby("symbol")}


def _round(v, digits=2):
    return None if pd.isna(v) else round(float(v), digits)


@router.get("/setups")
def setups():
    return [{"slug": s, "label": label, "unit": unit, "meaning": meaning}
            for s, (label, _, _, (_, unit, meaning)) in SETUPS.items()]


@router.get("/{slug}/trades")
def trade_list(slug: str, year: str | None = None):
    """One year at a time — the biggest logs have 150k events."""
    ev = _events(slug)
    years = sorted(ev["day"].str[:4].unique())
    year = year if year in years else years[-1]
    sel = ev[ev["day"].str.startswith(year)]
    return {"years": years, "year": year,
            "trades": [{"i": int(i), "day": r.day, "symbol": r.symbol, "result": _round(r.result)}
                       for i, r in zip(sel.index, sel.itertuples())]}


@router.get("/{slug}/trades/{i}")
def trade_detail(slug: str, i: int):
    _, _, timing, _ = _setup(slug)
    ev = _events(slug)
    if not 0 <= i < len(ev):
        raise HTTPException(404, "no such trade")
    row = ev.iloc[i]
    df = read_daily(row["symbol"])
    df["day"] = df["date"].dt.strftime("%Y-%m-%d")
    for n in (10, 20, 50, 200):
        df[f"sma{n}"] = sma_series(df["close"], n).round(2)
    hits = df.index[df["day"] == row["day"]]
    if len(hits) == 0:
        raise HTTPException(404, f"{row['symbol']} has no bar on {row['day']}")
    sig = df.index.get_loc(hits[0])
    ent = sig + 1 if timing == NEXT_OPEN else sig
    if ent >= len(df):
        raise HTTPException(404, "entry bar is beyond stored data")
    entry_price = df["open"].iloc[ent] if timing == NEXT_OPEN else row["entry"]

    win = df.iloc[max(ent - BARS_EACH_SIDE, 0): ent + BARS_EACH_SIDE + 1]
    candles = [{"time": r.day, "open": r.open, "high": r.high, "low": r.low, "close": r.close,
                "volume": r.volume, **{f"sma{n}": _round(getattr(r, f"sma{n}")) for n in (10, 20, 50, 200)}}
               for r in win.itertuples()]

    days = pd.DatetimeIndex(df["date"].iloc[max(ent - INTRADAY_EACH_SIDE, 0): ent + INTRADAY_EACH_SIDE + 1])
    bars = load_intraday(row["symbol"], days)
    intraday = [{"time": int(t.timestamp()) + IST_OFFSET_S, "open": o, "high": h, "low": l, "close": c}
                for t, o, h, l, c in zip(bars.get("date", []), bars.get("open", []), bars.get("high", []),
                                         bars.get("low", []), bars.get("close", []))]

    filings = []
    f = _filings().get(row["symbol"])
    if f is not None:
        fday = f["when"].dt.strftime("%Y-%m-%d")
        f = f[(fday >= win["day"].iloc[0]) & (fday <= win["day"].iloc[-1])]
        f = f[f["category"] != "results"]          # results get their own numbers table
        filings = [{"when": w.strftime("%Y-%m-%d %H:%M"), "category": c, "text": txt,
                    "color": FILING_MARKS[c][1]} for w, c, txt in zip(f["when"], f["category"], f["text"])]

    results = []
    q = _quarterly().get(row["symbol"])
    if q is not None:
        q = q[(q["qe"] >= pd.Timestamp(win["day"].iloc[0]) - pd.DateOffset(months=6))
              & (q["qe"] <= pd.Timestamp(win["day"].iloc[-1]))]
        # a missing filing stamp is approximated as quarter end + 45 days (SEBI deadline)
        filed = q["filed"].fillna(q["qe"] + pd.Timedelta(days=45))
        results = [{"quarter": r.qe.strftime("%b-%y"), "filed": fd.strftime("%Y-%m-%d %H:%M"),
                    "consolidated": bool(r.consolidated),
                    "revenue_cr": _round(r.revenue_cr, 0), "revenue_yoy": _round(r.revenue_cr_yoy, 0),
                    "pat_cr": _round(r.pat_cr, 0), "pat_yoy": _round(r.pat_cr_yoy, 0)}
                   for r, fd in zip(q.itertuples(), filed)]

    sig_bar = df.iloc[sig]
    return {"i": i, "symbol": row["symbol"], "signal_day": row["day"], "entry_day": df["day"].iloc[ent],
            "entry_at": timing,
            "entry": _round(entry_price),
            "signal_chg_pct": _round((sig_bar["close"] / df["close"].iloc[sig - 1] - 1) * 100, 1) if sig else None,
            "signal_volume": int(sig_bar["volume"]), "result": _round(row["result"]),
            "cat": row["cat"] if isinstance(row.get("cat"), str) else None,
            "candles": candles, "intraday": intraday, "filings": filings, "results": results}
