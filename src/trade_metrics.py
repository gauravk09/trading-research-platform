"""trade_metrics.py — empirical P(profit) and expectancy for a live candidate.

Every candidate the platform surfaces gets three decision numbers, all read
off HISTORY rather than modelled:

  P(profit)   share of the candidate's historical cohort that closed higher
              than the entry, at the 5- and 20-day horizon
  expected %  median and mean forward return of that cohort
  expected R  mean stop-based outcome of that cohort (5-day clock ruler and
              the trailed / scale-out ruler the validated strategies use)

Method — empirical conditional expectancy, nothing else:
  1. the candidate's scan maps to a TRIGGER FAMILY in the event store
     (data/processed/events.parquet, ~350k events, 2015+)
  2. inside that family the candidate is matched to a cohort by BUCKETING
     (quartiles, never exact match) at most two conditioning features
  3. the cohort's realised outcomes are reported as-is

Basis is the D+1 OPEN, because that is what the Order Pad actually enters
(AMO on the next open) and it is the ruler every certified finding on the
board was graded on.

Conditioning features are NOT chosen freely. Only features that reached PASS
on research/machine/SCOREBOARD.md *and* survived the red-team in
research/factory/LEDGER.md are used:

  burst / anticipation   net4 (h4_burst_net4) x turn_decile (h3_burst_turn_decile)
  four_pct               net4 x bounce_low21 (b2t_fp_nearlow_net4)
  four_pct_down (short)  net4 (tapedir_net4_short — the lone-loser short)
  bounce / ep / pullback UNCONDITIONAL. The ti65 x pct40ma dip-buy family was
                         red-teamed down to "≈ nothing" (LEDGER 2026-08-06) and
                         the EP family never reached PASS, so conditioning them
                         would be inventing evidence.

Era honesty: cells are cut on era B (2023+, the engine's convention — it
excludes COVID entirely). Era A (<2020) and COVID (2020-22) cells are stored
alongside so a cohort whose sign flips across eras is flagged, not hidden.

Build / refresh (also happens lazily when events.parquet is newer than the
table):
    python src/trade_metrics.py
"""

import functools
import json
import os

import numpy as np
import pandas as pd

_ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
EVENTS = os.path.join(_ROOT, "data", "processed", "events.parquet")
FEAT_DIR = os.path.join(_ROOT, "data", "processed", "features")
MM_HIST = os.path.join(_ROOT, "data", "processed", "mm_history.parquet")
SUMMARY = os.path.join(_ROOT, "data", "processed", "universe_summary.parquet")
TABLE = os.path.join(_ROOT, "output", "grader", "cohort_tables.parquet")
EDGES = os.path.join(_ROOT, "output", "grader", "cohort_edges.json")

MIN_COHORT = 100      # below this a cell is not reported — fall back a level
N_BUCKETS = 4         # quartiles; the engine's default bucketing
WINSOR_R = 5.0        # house tail diagnostic (engine.py WINSOR_R)
TAIL_GAP = 0.15       # |mean R - winsorized mean R| above which R is tail-carried

# trigger family -> (conditioning features, side). Order matters: the first
# feature is the one a thin cohort degrades onto.
SPEC = {
    "burst":         (["net4", "turn_decile"], "long"),
    "four_pct":      (["net4", "bounce_low21"], "long"),
    "four_pct_down": (["net4"], "short"),
    "bounce":        ([], "long"),
    "ep":            ([], "long"),
    "pullback":      ([], "long"),
    "qm_flag":       ([], "long"),
}

# Scan / setup name -> trigger family. Keys cover BOTH the daily_state scan
# names and the conviction.rank family names; they do not collide.
# A value of (family, True) means the family is a PROXY: the candidate has not
# triggered yet (anticipation coils) or the trigger is only a cousin of the
# scan (weak_structure vs a 4% breakdown). Proxy cohorts are reported with the
# proxy named, never silently.
FAMILY_OF = {
    # daily_state scan names
    "four_pct": ("four_pct", False),
    "breakout_setup": ("burst", False),
    "anticipation": ("burst", True),
    "episodic_pivot": ("ep", False),
    "ep9m": ("ep", False),
    "dep": ("ep", True),
    "ep_checklist": ("ep", True),
    "reversal_bullish": ("bounce", False),
    "bottom_bounce": ("bounce", False),
    "four_pct_down": ("four_pct_down", False),
    "weak_structure": ("four_pct_down", True),
    # conviction.rank family names
    "breakout": ("burst", False),
    "reversal": ("bounce", False),
    "bounce": ("bounce", False),
    "ep": ("ep", False),
    "short": ("four_pct_down", True),
}

_LABEL = {"net4": "tape (net4)", "turn_decile": "liquidity",
          "bounce_low21": "extension off the 21d low"}


# ── building the cohort tables ────────────────────────────────────────────────

def _naive(idx):
    return idx.tz_localize(None) if getattr(idx, "tz", None) is not None else idx


def _lookup(ev, frame):
    """Value of a date x symbol frame at each event's (date, symbol)."""
    frame = frame.copy()
    frame.index = _naive(pd.DatetimeIndex(frame.index))
    ri = frame.index.get_indexer(ev["date"])
    ci = frame.columns.get_indexer(ev["symbol"])
    ok = (ri >= 0) & (ci >= 0)
    out = np.full(len(ev), np.nan)
    out[ok] = frame.to_numpy()[ri[ok], ci[ok]]
    return out


def _era(dates):
    y = dates.dt.year
    return np.where(y < 2020, "A", np.where(y <= 2022, "COVID", "B"))


def _stats(g, side):
    """Outcome block for one cohort. Long and short read the same columns from
    opposite ends: a short profits when the forward return is negative."""
    sign = 1.0 if side == "long" else -1.0
    r5 = g["stop_r" if side == "long" else "stop_r_short"]
    rt = g["stop_r_trail" if side == "long" else "stop_r_trail_short"]
    # ret_o20 is NaN for events too recent to have a 20-day outcome; dropping
    # them keeps a young cohort's 20-day win rate honest instead of counting
    # "not resolved yet" as a loss.
    f5, f20 = sign * g["ret_o5"], (sign * g["ret_o20"]).dropna()
    return {
        "n": int(len(g)),
        "p5": float((f5 > 0).mean()),
        "med5": float(f5.median()),
        "mean5": float(f5.mean()),
        "p20": float((f20 > 0).mean()) if len(f20) else float("nan"),
        "med20": float(f20.median()) if len(f20) else float("nan"),
        "mean20": float(f20.mean()) if len(f20) else float("nan"),
        "r5": float(r5.mean()),
        "rtrail": float(rt.mean()),
        "rtrail_w5": float(rt.clip(-WINSOR_R, WINSOR_R).mean()),
    }


def _cells(df, feats, side, era):
    """Every reportable cohort for one family/era: the full bucket grid, the
    first-feature marginal, and the unconditional base — so a lookup can walk
    down the ladder without a second pass over the data."""
    rows = []

    def emit(g, b1, b2):
        if len(g):
            rows.append({"era": era, "b1": b1, "b2": b2, **_stats(g, side)})

    emit(df, -1, -1)
    if not feats:
        return rows
    for b1, g1 in df.groupby("b1"):
        emit(g1, int(b1), -1)
        if len(feats) > 1:
            for b2, g2 in g1.groupby("b2"):
                emit(g2, int(b1), int(b2))
    return rows


def build_tables() -> pd.DataFrame:
    """Recompute every family's cohort tables from the event store."""
    ev = pd.read_parquet(EVENTS)
    ev["date"] = _naive(pd.DatetimeIndex(ev["date"]))

    mm = pd.read_parquet(MM_HIST)
    mm.index = _naive(pd.DatetimeIndex(mm.index))
    ev["net4"] = (mm["up4"] - mm["dn4"]).reindex(ev["date"]).to_numpy()
    for name in ("turn_decile", "bounce_low21"):
        ev[name] = _lookup(ev, pd.read_parquet(os.path.join(FEAT_DIR, f"{name}.parquet")))
    ev["era"] = _era(ev["date"])

    frames, edges = [], {}
    for family, (feats, side) in SPEC.items():
        d = ev[ev["trigger"] == family].dropna(subset=feats + ["ret_o5"]).copy()
        if d.empty:
            continue
        # Edges are cut on era B only — the reported cells are era B, so the
        # buckets must be era-B quartiles, not history-wide ones.
        eb = d[d["era"] == "B"]
        edges[family] = {}
        for i, f in enumerate(feats, start=1):
            q = eb[f].quantile([k / N_BUCKETS for k in range(1, N_BUCKETS)])
            edges[family][f] = [float(v) for v in q]
            d[f"b{i}"] = np.searchsorted(edges[family][f], d[f].to_numpy(),
                                         side="right")
        for era, g in d.groupby("era"):
            for row in _cells(g, feats, side, era):
                frames.append({"family": family, **row})

    table = pd.DataFrame(frames)
    os.makedirs(os.path.dirname(TABLE), exist_ok=True)
    table.to_parquet(TABLE, compression="snappy", index=False)
    with open(EDGES, "w") as f:
        json.dump(edges, f, indent=1)
    return table


@functools.lru_cache(maxsize=1)
def _tables(_mtime):
    table = pd.read_parquet(TABLE)
    with open(EDGES) as f:
        edges = json.load(f)
    keyed = {(r["family"], r["era"], r["b1"], r["b2"]): r
             for r in table.to_dict("records")}
    return keyed, edges


def load_tables():
    """Cohort tables, rebuilt if the event store is newer than them."""
    src = os.path.getmtime(EVENTS)
    if not os.path.exists(TABLE) or os.path.getmtime(TABLE) < src:
        build_tables()
    return _tables(os.path.getmtime(TABLE))


# ── looking a candidate up ────────────────────────────────────────────────────

def _bucket(edges, value):
    if value is None or not np.isfinite(value):
        return -1
    return int(np.searchsorted(edges, value, side="right"))


def _qlabel(b):
    return "any" if b < 0 else f"Q{b + 1}"


def metrics_for(scan: str, values: dict) -> dict | None:
    """Decision metrics for one candidate.

    `scan` is a daily_state scan name or a conviction family name; `values`
    holds whatever conditioning features are known (net4, turn_decile,
    bounce_low21). Missing features simply widen the cohort.

    Returns None when the scan has no historical trigger family (e.g. the ti65
    trend screen) — a candidate with no cohort gets no probability, rather than
    a made-up one.
    """
    if scan not in FAMILY_OF:
        return None
    family, proxy = FAMILY_OF[scan]
    keyed, all_edges = load_tables()
    feats, side = SPEC[family]

    buckets = [_bucket(all_edges[family][f], values.get(f)) for f in feats]
    buckets += [-1] * (2 - len(buckets))

    # Walk down the ladder: full cell -> first-feature marginal -> family base.
    notes, cell, used = [], None, (-1, -1)
    for cand in ((buckets[0], buckets[1]), (buckets[0], -1), (-1, -1)):
        cell = keyed.get((family, "B", cand[0], cand[1]))
        if cell and cell["n"] >= MIN_COHORT:
            used = cand
            break
    else:
        return None
    if used != (buckets[0], buckets[1]):
        notes.append(f"cohort thinner than {MIN_COHORT} events — widened to "
                     f"{'the family base rate' if used == (-1, -1) else 'the tape bucket only'}")

    base = keyed[(family, "B", -1, -1)]
    era_a = keyed.get((family, "A", used[0], used[1]))
    if era_a and era_a["n"] >= MIN_COHORT and np.sign(era_a["mean5"]) != np.sign(cell["mean5"]):
        notes.append(f"era A (pre-2020) disagrees in sign (mean {era_a['mean5']:+.2f}%)")
    if abs(cell["rtrail"] - cell["rtrail_w5"]) > TAIL_GAP:
        notes.append("trailed R is tail-carried (raw vs winsorized differ)")
    if proxy:
        notes.append(f"proxy cohort: graded on `{family}` events — the closest "
                     "validated trigger to this scan, not the scan itself")
    if not feats:
        notes.append("unconditional family base rate — no conditioning feature "
                     "on this family survived the red-team")

    cohort = " · ".join(f"{_LABEL[f]} {_qlabel(b)}"
                        for f, b in zip(feats, used) if b >= 0) or "all events"
    low = used == (-1, -1) and bool(feats)

    def num(v, nd):
        # NaN would serialise as bare `NaN`, which is not valid JSON.
        return None if not np.isfinite(v) else round(float(v), nd)

    return {
        "family": family, "side": side, "basis": "D+1 open", "era": "2023+",
        "cohort": cohort, "n": cell["n"],
        "confidence": "low" if low else "high",
        "p_profit_5d": num(cell["p5"], 3),
        "med_ret_5d_pct": num(cell["med5"], 2),
        "mean_ret_5d_pct": num(cell["mean5"], 2),
        "p_profit_20d": num(cell["p20"], 3),
        "med_ret_20d_pct": num(cell["med20"], 2),
        "mean_ret_20d_pct": num(cell["mean20"], 2),
        "exp_r_5d": num(cell["r5"], 3),
        "exp_r_trail": num(cell["rtrail"], 3),
        "exp_r_trail_w5": num(cell["rtrail_w5"], 3),
        "base_p_profit_5d": num(base["p5"], 3),
        "base_exp_r_trail": num(base["rtrail"], 3),
        "notes": notes,
    }


# ── live conditioning values ──────────────────────────────────────────────────

@functools.lru_cache(maxsize=1)
def _turn_ranks(_mtime):
    """Cross-sectional percentile of 20d average turnover, the live twin of the
    `turn_decile` feature matrix (features.py ranks the same quantity)."""
    s = pd.read_parquet(SUMMARY, columns=["symbol", "avg_turnover_cr"])
    return dict(zip(s["symbol"], s["avg_turnover_cr"].rank(pct=True)))


@functools.lru_cache(maxsize=4096)
def _bounce_low21(symbol, _mtime):
    """% above the 21-day low — the live twin of the `bounce_low21` feature.
    `_mtime` is the summary's timestamp: it exists purely to drop the cache
    when the nightly update lands under a long-running dashboard process."""
    from data_collection.storage import read_daily
    df = read_daily(symbol)
    if len(df) < 21:
        return None
    tail = df.tail(21)
    lo = float(tail["low"].min())
    return None if lo <= 0 else (float(tail["close"].iloc[-1]) / lo - 1) * 100


def live_values(symbol: str, market: dict, feats) -> dict:
    """Conditioning features for one live candidate, all knowable at the close
    of the signal day (net4 and turnover are same-session; the 21d low uses
    completed bars only). Only the features the family needs are computed."""
    try:
        stamp = os.path.getmtime(SUMMARY)
    except OSError:
        stamp = None
    out = {}
    if "net4" in feats:
        out["net4"] = (market or {}).get("net4")
    if "turn_decile" in feats:
        out["turn_decile"] = _turn_ranks(stamp).get(symbol) if stamp else None
    if "bounce_low21" in feats:
        out["bounce_low21"] = _bounce_low21(symbol, stamp)
    return out


def for_rows(symbols, scan: str, market: dict) -> list:
    """Metrics for a list of candidate symbols under one scan/family."""
    if scan not in FAMILY_OF:
        return [None] * len(symbols)
    feats = SPEC[FAMILY_OF[scan][0]][0]
    out = []
    for s in symbols:
        try:
            out.append(metrics_for(scan, live_values(s, market, feats)))
        except (OSError, KeyError, ValueError):
            out.append(None)
    return out


if __name__ == "__main__":
    t = build_tables()
    base = t[(t["era"] == "B") & (t["b1"] == -1)]
    print(base[["family", "n", "p5", "med5", "mean5", "r5", "rtrail"]]
          .round(3).to_string(index=False))
    print(f"\nCohort tables ({len(t)} cells) -> {os.path.abspath(TABLE)}")
