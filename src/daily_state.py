"""daily_state.py — write the machine-readable Daily State file.

One JSON per trading day: market risk regime (HMM dial) + exposure knobs, breadth trend,
FII/DII flows, each Stockbee scan's top candidates with their full feature
vectors, compact OHLCV windows for the actionable setups, and open tracked
trades. This file is the platform's API — the dashboard renders the same
numbers for humans; the /brief agent (or any script) reasons over this file
without touching Streamlit.

Written to output/state/<data-date>.json plus a latest.json copy.
Runs at the end of run_daily.py, or manually:
    python src/daily_state.py
"""

import glob
import json
import math
import os
import sys
from datetime import datetime
from zoneinfo import ZoneInfo

import pandas as pd

sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "strategies"))

import data_collection.nse.announcements_store as announcements_store
from data_collection.nse.earnings_calendar import results_due_days
from regime import compute_market_monitor
import risk_regime
from incubation import build_incubation
from data_collection.other.news import load_recent_news
from data_collection.storage import read_daily
import trade_metrics
from stockbee import scans
from stockbee.breakout_setup import breakout_from_consolidation
from stockbee.episodic_pivot import episodic_pivot, attach_catalysts
from stockbee.ep_family import ep9m_today, dep_watchlist, ep_checklist
from stockbee.trade_tracker import evaluate_trades

ROOT = os.path.join(os.path.dirname(__file__), "..")
PROCESSED = os.path.join(ROOT, "data", "processed")
RAW = os.path.join(ROOT, "data", "raw")
STATE_DIR = os.path.join(ROOT, "output", "state")

SCHEMA_VERSION = 1
CANDIDATE_CAP = 15   # per scan — enough to act on, small enough for an agent to read whole
OHLCV_BARS = 40      # price window per actionable candidate ("the chart as numbers")

# Feature vector shared by every scan's candidates (intersected with what the
# scan actually returns, so scan-specific columns like `reason` ride along).
FEATURE_COLS = [
    "symbol", "name", "sector", "industry", "mcap_cr", "cap_segment",
    "close", "chg_pct", "gap_pct", "volume", "volume_ratio",
    "avg_turnover_cr", "adr_pct", "rs_rank", "ti65", "r1mo_pct", "r3mo_pct",
    "r6mo_pct", "range_pos", "up_streak", "down_streak", "trend_age_d", "base_count", "consol_days",
    "consol_range_pct", "consol_vol_ratio", "burst_thr_pct", "prior_day_quiet",
    "trend_quality", "range_pct_5d", "vol_contraction",
    "nr7", "pct_from_52w_high", "pct_from_52w_low", "is_fo",
    "entry_price", "stop_price", "risk_pct", "reason", "catalyst", "catalyst_subject",
    # EP family (TraderLion 2026): institutional-footprint + delayed-reaction fields
    "vol_rank", "event_date", "days_since", "event_chg_pct",
    "pullback_pct", "category", "subject", "neglected",
    "results_due_days",   # calendar days to the next known results meeting
    # NSE delivery % settles EOD, so these describe the last completed session —
    # a next-day signal, legitimate here because candidates are picked EOD.
    "deliv_pct", "deliv_x_avg",
]


def _load_excluded() -> set:
    """ASM/GSM symbols from the newest cached surveillance CSVs (disk only)."""
    excluded = set()
    for prefix in ("asm", "gsm"):
        files = sorted(glob.glob(os.path.join(RAW, "surveillance", f"{prefix}_*.csv")))
        if not files:
            continue
        try:
            df = pd.read_csv(files[-1])
        except (OSError, pd.errors.EmptyDataError):
            continue
        col = next((c for c in df.columns if "symbol" in c.lower()), None)
        if col:
            excluded.update(df[col].dropna().astype(str).str.strip().str.upper())
    return excluded


def _load_fii_dii() -> dict:
    files = sorted(glob.glob(os.path.join(RAW, "fii_dii", "fii_dii_*.csv")))
    if not files:
        return {}
    df = pd.read_csv(files[-1])
    out = {}
    for _, r in df.iterrows():
        key = "FII" if "FII" in str(r["category"]).upper() else "DII"
        out[key + "_net_cr"] = float(r["netValue"])
    out["date"] = str(df["date"].iloc[0])
    return out


def _load_catalysts() -> pd.DataFrame:
    """Newest cached NSE announcements as [symbol, category, subject]."""
    empty = pd.DataFrame(columns=["symbol", "category", "subject"])
    try:
        df = announcements_store.load_latest_day()
    except OSError:
        return empty
    if df.empty or "symbol" not in df.columns:
        return empty
    for c in ("category", "subject"):
        if c not in df.columns:
            df[c] = None
    df = df[["symbol", "category", "subject"]].copy()
    df["symbol"] = df["symbol"].astype(str).str.strip().str.upper()
    df["__rank"] = (df["category"] == "other").astype(int)  # real catalysts first
    return (df.sort_values("__rank").drop_duplicates("symbol")
            .drop(columns="__rank").reset_index(drop=True))


def _load_news(limit: int = 12) -> list:
    """Newest archived Pulse headlines as [published, source, headline, url].
    Empty list if the news archive has not been polled yet."""
    df = load_recent_news(limit)
    if df.empty:
        return []
    return df[["published", "source", "headline", "url"]].to_dict("records")


def _participation(cm: pd.DataFrame, vm: pd.DataFrame | None) -> dict:
    """Market-wide participation: today's total traded value vs the prior-20d
    average. This is the 'volume around 0.3' anchor for the situational-
    awareness read — deterministic, computed from completed sessions only."""
    if vm is None:
        return {}
    turnover_cr = (cm * vm).sum(axis=1) / 1e7
    if len(turnover_cr) < 21:
        return {}
    today = float(turnover_cr.iloc[-1])
    base = float(turnover_cr.iloc[-21:-1].mean())
    if base <= 0:
        return {}
    return {"turnover_cr": round(today), "ratio_20d": round(today / base, 2)}


def candidate_flags(r: dict) -> list:
    """Setup-quality warnings — the 'why NOT to take it' shown next to every
    candidate in the brief and the dashboard. A clean candidate has none."""
    flags = []
    risk, adr = r.get("risk_pct"), r.get("adr_pct")
    if risk and adr and risk > 1.5 * adr:
        flags.append(f"stop {risk:.1f}% wide = {risk / adr:.1f}x ADR (cap 1.5x)")
    if (r.get("avg_turnover_cr") or 0) < 5:
        flags.append(f"thin: ₹{r.get('avg_turnover_cr')}cr avg turnover (< ₹5cr)")
    rs = r.get("rs_rank")
    if rs is None:
        flags.append("no RS rank")
    elif rs < 70:
        flags.append(f"RS {rs:.0f} below 70")
    bases = r.get("base_count")
    if bases is not None and bases >= 4:
        flags.append(f"late-stage: base {bases:.0f} (1st-2nd best, 4th+ fails often)")
    off_high = r.get("pct_from_52w_high")
    if off_high is not None and off_high < -25:
        flags.append(f"{-off_high:.0f}% below 52w high")
    due = r.get("results_due_days")
    if due is not None and due <= 5:
        when = "today" if due == 0 else f"in {due:.0f}d"
        flags.append(f"results {when} — binary event risk")
    return flags


def _records(df: pd.DataFrame, cap: int = None, scan: str = None,
             market: dict = None) -> list:
    """DataFrame → JSON-safe records with quality flags: NaN → None.

    Each record also carries `metrics`: the historical cohort's P(profit),
    expected % return and expected R for that scan (trade_metrics.py). None
    when the scan has no validated trigger family to match against."""
    if df.empty:
        return []
    cols = [c for c in FEATURE_COLS if c in df.columns] or list(df.columns)
    recs = df[cols].head(cap).to_dict("records") if cap else df[cols].to_dict("records")
    for r in recs:
        for k, v in r.items():
            if isinstance(v, float) and math.isnan(v):
                r[k] = None
        r["flags"] = candidate_flags(r)
    if scan:
        mets = trade_metrics.for_rows([r["symbol"] for r in recs], scan, market)
        for r, m in zip(recs, mets):
            r["metrics"] = m
    return recs


def _ohlcv_window(symbol: str, bars: int = OHLCV_BARS) -> dict:
    df = read_daily(symbol).tail(bars)
    if df.empty:
        return {}
    return {
        "date": [str(d.date()) for d in df["date"]],
        "open": [round(float(v), 2) for v in df["open"]],
        "high": [round(float(v), 2) for v in df["high"]],
        "low": [round(float(v), 2) for v in df["low"]],
        "close": [round(float(v), 2) for v in df["close"]],
        "volume": [int(v) for v in df["volume"]],
    }


def _sector_breadth(summary: pd.DataFrame) -> list:
    """Per-sector breadth so the brief can say which groups are moving.
    Medians (not means) so one parabolic small cap can't paint a sector hot.
    Same 1 Cr liquidity floor as the scans — illiquid microcaps don't vote."""
    if "sector" not in summary.columns:
        return []

    def _num(v, nd=1):
        return None if pd.isna(v) else round(float(v), nd)

    liquid = summary[summary["avg_turnover_cr"] >= 1.0].dropna(subset=["sector"])
    rows = []
    for sector, g in liquid.groupby("sector"):
        rows.append({
            "sector": sector,
            "n": len(g),
            "pct_up": _num((g["chg_pct"] > 0).mean() * 100),
            "movers_4pct": int((g["chg_pct"] >= 4).sum()),
            "med_chg_pct": _num(g["chg_pct"].median(), 2),
            "med_r1mo_pct": _num(g["r1mo_pct"].median()),
            "med_r3mo_pct": _num(g["r3mo_pct"].median()),
            "med_rs_rank": _num(g["rs_rank"].median()),
        })
    rows.sort(key=lambda r: (r["med_chg_pct"] is None, -(r["med_chg_pct"] or 0)))
    return rows


def build_state() -> dict:
    summary = pd.read_parquet(os.path.join(PROCESSED, "universe_summary.parquet"))
    # Merged before the scans run so every candidate row inherits it.
    due = results_due_days()
    summary["results_due_days"] = summary["symbol"].map(due)
    dm_path = os.path.join(PROCESSED, "delivery_matrix.parquet")
    if os.path.exists(dm_path):
        dm = pd.read_parquet(dm_path)
        latest = dm.iloc[-1]
        summary["deliv_pct"] = summary["symbol"].map(latest)
        if len(dm) >= 20:
            avg20 = dm.tail(20).mean()
            summary["deliv_x_avg"] = summary["symbol"].map(latest / avg20.where(avg20 > 0))
    cm = pd.read_parquet(os.path.join(PROCESSED, "close_matrix.parquet"))
    vm_path = os.path.join(PROCESSED, "volume_matrix.parquet")
    vm = pd.read_parquet(vm_path) if os.path.exists(vm_path) else None
    # high/low matrices (precompute.py) feed the Ryan/Minervini paper signals
    hl = {}
    for name in ("high", "low"):
        path = os.path.join(PROCESSED, f"{name}_matrix.parquet")
        hl[name] = pd.read_parquet(path) if os.path.exists(path) else None

    mm = compute_market_monitor(cm, vm)

    idx_close = None
    if os.path.exists(risk_regime.LIVE_PARQUET):
        idx_close = pd.read_parquet(risk_regime.LIVE_PARQUET).set_index("date")["close"].sort_index()
    regime = risk_regime.evaluate()

    excluded = _load_excluded()
    base = {"min_turnover_cr": 1.0, "excluded": excluded}

    scan_blocks = {}
    # The tape values every cohort lookup conditions on, as of this session.
    market = {"net4": float(mm["up4"].iloc[-1] - mm["dn4"].iloc[-1]),
              "pct40ma": float(mm["pct40ma"].iloc[-1])}

    def add_scan(name, df, params):
        scan_blocks[name] = {
            # Defaults first so a scan's own min_turnover_cr (e.g. EP9M's 10.0)
            # is recorded, not clobbered by the base 1.0.
            "params": {"min_turnover_cr": 1.0, **params, "asm_gsm_excluded": len(excluded)},
            "total_matches": len(df),
            "candidates": _records(df, CANDIDATE_CAP, name, market),
        }

    params = {"min_change": 4.0, "require_vol_up": True,
              "require_close_strong": True, "max_up_streak": 2}
    add_scan("four_pct", scans.four_pct(summary, **params, **base), params)

    params = {"min_adr_pct": 3.0, "min_consol_days": 5, "max_consol_days": 20,
              "max_consol_range_pct": 15.0, "max_consol_vol_ratio": 1.10,
              "require_close_strong": True, "max_up_streak": 2,
              "require_quiet_prior_day": True}
    breakout = breakout_from_consolidation(summary, **params, **base)
    add_scan("breakout_setup", breakout, params)

    params = {"min_gap": 8.0, "min_vol_ratio": 3.0, "exclude_parabolic": True}
    catalysts = _load_catalysts()
    ep = attach_catalysts(episodic_pivot(summary, **params, **base), catalysts)
    add_scan("episodic_pivot", ep, params)

    def drop_excluded(df):
        return df[~df["symbol"].isin(excluded)] if len(df) else df

    params = {"min_shares": 15_000_000, "min_price": 30.0,
              "min_turnover_cr": 10.0}
    e9 = drop_excluded(ep9m_today(cm, vm, summary, catalysts=catalysts, **params))
    add_scan("ep9m", e9, params)

    params = {"window": 25, "max_pullback": 15.0, "inst_turnover_cr": 25.0}
    dep = drop_excluded(dep_watchlist(cm, vm, summary, **params))
    add_scan("dep", dep, params)

    params = {"min_turnover_cr": 1.0}
    checklist = drop_excluded(ep_checklist(summary, catalysts, **params))
    add_scan("ep_checklist", checklist, params)

    params = {"max_range_5d": 12.0, "max_vol_contraction": 0.85, "min_prior_move": 20.0}
    anticip = scans.anticipation(summary, **params, **base)
    add_scan("anticipation", anticip, params)

    params = {"min_ti": 1.05}
    add_scan("ti65", scans.ti65(summary, **params, **base), params)

    params = {"min_cascade": 2, "min_range_pos": 0.60, "inst_turnover_cr": 25.0}
    add_scan("reversal_bullish", scans.reversal_bullish(summary, **params, **base), params)

    # Bottom bounce only trades at a washout (pct40ma < 20) — candidates are
    # suppressed when the context is off so no agent acts on them by mistake.
    pct40 = float(mm["pct40ma"].iloc[-1])
    params = {"min_chg": 4.0, "min_off_high": 25.0,
              "context": "pct40ma < 20", "pct40ma": pct40,
              "context_active": bool(pct40 < 20)}
    bb = scans.bottom_bounce(summary, min_chg=4.0, min_off_high=25.0, **base)
    add_scan("bottom_bounce", bb if pct40 < 20 else bb.head(0), params)

    params = {"min_change": 4.0}
    add_scan("four_pct_down", scans.four_pct_down(summary, **params, **base), params)

    params = {"require_downtrend": True}
    add_scan("weak_structure", scans.weak_structure_short(summary, **params, **base), params)

    # Price windows for the setups you might actually enter tomorrow.
    actionable = pd.concat([breakout.head(10), ep.head(10), anticip.head(10),
                            e9.head(10), dep.head(10)])
    ohlcv = {s: _ohlcv_window(s) for s in actionable["symbol"].unique()}

    trades = evaluate_trades(summary)
    if not trades.empty:
        trades["results_due_days"] = trades["symbol"].map(due)

    mm_tail = mm.tail(5).reset_index(names="date")
    mm_tail["date"] = mm_tail["date"].astype(str).str[:10]

    return {
        "meta": {
            "schema_version": SCHEMA_VERSION,
            "generated_at": datetime.now(ZoneInfo("Asia/Kolkata")).isoformat(timespec="seconds"),
            "data_date": str(summary["last_date"].max()),
            "universe_size": len(summary),
        },
        "regime": regime,
        "market_monitor_tail": [
            {k: (None if isinstance(v, float) and math.isnan(v) else v)
             for k, v in row.items()}
            for row in mm_tail.to_dict("records")
        ],
        "fii_dii": _load_fii_dii(),
        "participation": _participation(cm, vm),
        "news": _load_news(),
        "sector_breadth": _sector_breadth(summary),
        "scans": scan_blocks,
        "incubation": build_incubation(summary, cm, vm, mm, idx_close,
                                       hm=hl["high"], lm=hl["low"], regime=regime),
        "open_trades": [] if trades.empty else [
            {k: (None if isinstance(v, float) and math.isnan(v) else v)
             for k, v in r.items()}
            for r in trades.to_dict("records")],
        "ohlcv": ohlcv,
    }


def _json_default(o):
    if hasattr(o, "item"):          # numpy scalars
        return o.item()
    return str(o)                   # timestamps, anything else


def run() -> str:
    state = build_state()
    os.makedirs(STATE_DIR, exist_ok=True)

    path = os.path.join(STATE_DIR, f"{state['meta']['data_date']}.json")
    payload = json.dumps(state, indent=1, default=_json_default)
    for p in (path, os.path.join(STATE_DIR, "latest.json")):
        with open(p, "w") as f:
            f.write(payload)

    counts = {name: b["total_matches"] for name, b in state["scans"].items()}
    print(f"Daily state → {path}")
    print(f"  regime: {state['regime']['tier']} (P(drop>=5% in 20d) {state['regime']['p_drop_20d']:.1%} "
          f"vs avg {state['regime']['baseline_p_drop_20d']:.1%}) | "
          f"scans: {counts} | open trades: {len(state['open_trades'])}")
    return path


if __name__ == "__main__":
    run()
