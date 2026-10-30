"""engine.py — the research machine's fixed evaluator.

Agents author small experiment specs (JSON); this engine runs them against
the event store (data/processed/events.parquet, ~265k trigger events with
uniform stop-based outcomes) conditioned on stock features, market state, or
derived long-horizon features — and returns era-split effects with a
permutation luck test. The engine is FIXED CODE: agents may only choose
what to condition on, never how it is judged.

Pre-registered judgment bars (do not edit per experiment):
  eras        A = <2020, COVID = 2020-22 (reported, never judged),
              B = >=2023
  effect      mean stop_r of top bucket minus bottom bucket
  PASS        sign(effect_A) == sign(effect_B)
              and min(|effect_A|, |effect_B|) >= 0.08 R
              and extreme buckets have n >= 200 in each era
              and |full-period effect| beats >= 95% of 200 within-date
              permutations (market conditions: date-block permutations)
  WEAK        signs agree AND min |effect| >= 0.04 AND null >= 90% — always
              requires clearing the luck test (a big effect that beats few
              permutations is noise, not a hint; 2026-07-30). Calibrated on
              the placebo battery so pure noise grades FAIL (CONTROLS.md)
  FAIL        signs disagree, or effect in placebo territory
  INSUFFICIENT  extreme-bucket n < 200 in either era

Modern-era track (pre-registered 2026-08-06). The era gate above cannot ever
certify a feature whose data does not reach era A — delivery % starts 2020-10,
EP9M events are too rare pre-2020 — so those families were permanently
INSUFFICIENT no matter how strong the modern effect. For them, and ONLY for
them, era A is declared unjudgeable and era B is split in half instead:
  trigger     the graded sample has NO era-A events at all (the data does not
              reach before 2020) AND min(era-A extreme-bucket n) < MIN_N.
              Era-A THINNESS is not a trigger (2026-08-06 red-team fix): a
              bucket re-cut that leaves era A with 199 events must stay
              INSUFFICIENT on the full track, never reroute onto the
              two-adjacent-window judge.
  eras        era A reported as "N/A (no data)" and never judged;
              era B split B23 = 2023, B24 = 2024+, which must AGREE in sign
  PASS (modern)   sign(eff_B23) == sign(eff_B24)
                  and min(|eff_B23|, |eff_B24|) >= 0.08 R
                  and extreme buckets have n >= 200 in EACH half
                  and |full-period effect| beats >= 95% of the 200 permutations
                  (the same luck test, unchanged — it uses the whole sample)
  WEAK (modern)   signs agree AND min |eff| >= 0.04 AND null >= 90%
  FAIL (modern)   signs disagree, or effect in placebo territory
  INSUFFICIENT (modern)  either half's extreme-bucket n < 200
The " (modern)" suffix and out["track"] == "modern" are mandatory: such a
verdict rests on ~3.5 years and two ADJACENT windows, not on the full-history
two-era test, and must never be read as a full-history PASS. Features that DO
have era-A data are graded exactly as before — this path cannot reach them.

Entry rulers (two, graded side by side; the event store carries both):
  stop_r        entry at the D+1 OPEN — the original convention and still the
                primary grade, so the board stays comparable to its history.
                It gives away the overnight gap (triggers gap +0.2 to +0.6% on
                average, ~+0.11R on a typical 5-6% stop), so absolute long
                expectancies read ~0.1R low.
  stop_r_close  entry at the SIGNAL-DAY CLOSE (the Order Pad's ~15:20 window),
                same stop/gap-fill/time-exit mechanics. Graded in parallel as
                effect_R_close / null_beat_pct_close / verdict_close. Caveat
                (see src/backtest/event_store.py): triggers that use full-day
                volume are slightly optimistic at a 15:20 fill.
                stop_r_20_close exists in the store but is not graded here.
  stop_r_trail  entry at the D+1 OPEN like stop_r, but the exit is TRAILED
                instead of timed: half the position out at +2R, the rest on a
                ratcheting 20-day low of closes, hard cap 60 bars (shorts
                mirrored). Graded in parallel as effect_R_trail /
                null_beat_pct_trail / verdict_trail.
  stop_r_trail_be  the BREAKEVEN variant of the trail ruler: identical in every
                respect except that the stop moves to the entry price once the
                trade has touched +1R intraday (shorts mirrored). Graded in
                parallel as effect_R_trail_be / null_beat_pct_trail_be /
                verdict_trail_be. It answers a different question from the other
                rulers: not "is this factor real?" but "does the most common
                retail risk-management reflex change what the board believes?"

Why a third ruler (pre-registered 2026-08-06). Both existing rulers exit on the
CLOCK. Every strategy this repo has validated end-to-end — the EP9M 80%
scale-out, the Qullamaggie MA trail, the Ryan/Minervini native exits — makes its
money by holding winners past day 20, so a 5-/20-day screen can reject a setup
whose entire edge is the tail. The trail ruler is that missing judge. Its +2R
and 20-day window are lifted from those studies and are NOT tuned here; nothing
about them was chosen by looking at the board. It shares the D+1-open entry, so
it needs no look-ahead guard and no risk floor (its risk denominator is the same
5-6% stop distance as stop_r). It DOES produce a fat-tailed R distribution by
construction — a 60-bar trail can return +15R — so a +/-5R winsorized companion
(effect_R_trail_w5) is reported the way the close ruler has one, and its WEAK bar
is calibrated on its own placebo battery (WEAK_MIN_TRAIL). Coverage note: a trade
still open when the data ends is NaN, so the trail ruler silently drops the last
~60 trading days of events; extreme-bucket n is taken from the stop_r cohort,
the same convention the close ruler uses.

Two guards the close ruler needs and the D+1-open ruler does not (both added
2026-08-06 after the red-team; the open-ruler path is untouched):

  earliest-known timing.  A close entry can only use what exists by ~15:20.
                Every feature carries a timing tag (NEXT_OPEN_FEATURES below):
                delivery % is a full-session settlement aggregate NSE publishes
                in the EVENING, so `deliv_x20` at date t does not exist at t's
                close — grading it on the close ruler reads tomorrow's
                newspaper (proof: lagging it one day kills the effect,
                +0.27 -> -0.02R). Such experiments get
                verdict_close = FLAWED_CLOSE and NO close effect at all, never
                a silent skip. The D+1-open grade stays valid — the file is out
                hours before the 09:15 open.

  minimum risk floor.  Entering at the close puts the stop (the signal-day low)
                a hair away on reversal triggers — median risk is 0.76% of price
                on `bounce`, 1.05% on `four_pct_down`, with two thirds of bounce
                events under 1% — so R becomes a ratio with a near-zero
                denominator (sd 8.7R) and a single event moves a bucket mean by
                an R. Close-ruler R is therefore recomputed with the risk
                denominator floored at RISK_FLOOR_PCT of entry; P&L is untouched
                (R_floored = R_raw * risk / max(risk, floor)). A winsorized
                +/-5R companion, effect_R_close_w5, is reported alongside as a
                tail diagnostic. Both are close-ruler only.

Spec schema (JSON file):
  {
    "id": "h001_burst_freshness",
    "question": "one line, INCLUDING the expected direction, written before running",
    "cohort": {"trigger": "burst",             # burst | four_pct | four_pct_down
                                               # | ep | bounce | pullback | qm_flag
               "filters": [["adr20", ">=", 4],     # optional; feature/derived names,
                           ["market:net4", ">=", 100]]},  # or market:<series>; ops >= <=
    "condition": {"type": "feature",           # feature | market | derived | placebo
                  "name": "days_since_burst",  # see FEATURES/MARKET/DERIVED below
                  "buckets": "quartiles"}      # quartiles | quintiles | [edge,...]
  }

System-check condition types (control experiments only, id prefix x_/c_):
  placebo          random-but-fixed per-symbol trait (salted by name) — must FAIL
  placebo_market   random-but-fixed per-date series (salted by name) — must FAIL
                   under the stricter date-block permutation
  placebo_shuffled a REAL feature's values permuted across events (same
                   distribution, link to outcomes destroyed) — must FAIL
  cheat            the event's own future ret_o5 as the condition — must PASS
                   enormously (plumbing canary, never a research result)

Usage:
  ~/anaconda3/bin/python research/machine/engine.py specs/h001.json [more...]
  ~/anaconda3/bin/python research/machine/engine.py --scoreboard
"""

import functools
import glob
import hashlib
import json
import os
import sys

import numpy as np
import pandas as pd

BASE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..")
EVENTS = os.path.join(BASE, "data", "processed", "events.parquet")
FEAT_DIR = os.path.join(BASE, "data", "processed", "features")
MM_HIST = os.path.join(BASE, "data", "processed", "mm_history.parquet")
CACHE = os.path.join(BASE, "output", "studies", "cache")
HERE = os.path.dirname(os.path.abspath(__file__))
RESULTS = os.path.join(HERE, "results")

MIN_N = 200
EFFECT_FLOOR = 0.08
N_PERM = 200
NULL_PCT = 95.0
WEAK_MIN = 0.04    # calibrated 2026-07-29 from the 12-placebo battery (CONTROLS.md)
WEAK_NULL = 90.0   # ditto — placebos reached null 84-99% with tiny effects
# The close ruler is a different (gap-free, floored-denominator) distribution,
# so its WEAK bar is calibrated on its own placebo battery — see CONTROLS.md
# 2026-08-06b. Close-ruler noise reached |0.064| and |0.059| R at null 94-99.5
# in the 13-control battery (vs ~0.04 on the D+1-open ruler), so the close WEAK
# effect floor sits just above the largest noise effect observed. The PASS bars
# are shared by both rulers; only WEAK needed re-cutting.
WEAK_MIN_CLOSE = 0.07
WEAK_NULL_CLOSE = 90.0
# The trail ruler is a third distribution again: fat-tailed (a 60-bar trail can
# return +15R) and roughly 2.5x the sd of the 5-day ruler, so noise moves bucket
# means further. Calibrated on the same 13-placebo battery re-run on this ruler
# — see CONTROLS.md 2026-08-06c — and set just above the largest noise effect
# that battery produced. PASS bars are shared by all three rulers.
WEAK_MIN_TRAIL = 0.07
WEAK_NULL_TRAIL = 90.0
# ...and the trail ruler is the FIRST ruler whose PASS bar had to move, on the
# MODERN track only. Full-track trail noise behaved (largest sign-agreeing
# placebo effect 0.067R, x_pb4), but the modern judge compares two ADJACENT
# short windows — B23 is a single year — and a 60-bar hold overlaps heavily
# inside one year, so modern-track noise reached min|eff| 0.119R at null 98.5
# (x_mod_pb2) and PASSED the shared 0.08 floor. A placebo at PASS is the one
# thing the battery may never allow, so the modern-track trail bars are lifted
# to 0.13 for BOTH grades — above that leaker, the same "just above the largest
# observed noise effect" rule that set WEAK_MIN_CLOSE. This can only make trail
# verdicts stricter, never manufacture one. It rests on a SINGLE leaker, so a
# trail PASS (modern) is the weakest claim this board can emit: always red-team.
TRAIL_MODERN_MIN = 0.13
# The breakeven-trail ruler is a FOURTH distribution: the +1R stop-to-entry move
# converts most -1R losses into ~0R scratches and cuts a slice of the winners
# short, so bucket means sit closer together and a noise draw needs less to
# separate them. Calibrated on the same 13-placebo battery re-run on this ruler
# (CONTROLS.md 2026-08-06d): uncalibrated it leaked x_pb4 to PASS at min|eff|
# 0.095, null 100 — a placebo at PASS is the one outcome the battery may never
# allow — so BOTH the WEAK and the PASS floor are lifted to 0.10, just above
# that leaker, the same rule that set WEAK_MIN_CLOSE and TRAIL_MODERN_MIN.
# Anything under 0.10 on this ruler is FAIL. The modern-track bar is inherited
# from the trail ruler (0.13): observed modern BE noise is smaller (x_mod_pb2
# min|eff| 0.075) but the structural cause of the trail's modern leak — two
# ADJACENT one-year windows and a 60-bar hold overlapping inside them — is
# identical here, so the stricter bar stands. This is the SECOND ruler whose
# PASS bar had to move; a trail_be PASS is correspondingly weak evidence.
WEAK_MIN_TRAIL_BE = 0.10
WEAK_NULL_TRAIL_BE = 90.0
TRAIL_BE_PASS_MIN = 0.10
TRAIL_BE_MODERN_MIN = 0.13

RISK_FLOOR_PCT = 1.0   # close-ruler minimum risk, % of entry (see docstring)
WINSOR_R = 5.0         # close-ruler tail diagnostic

# Features whose day-t value is PUBLISHED AFTER day t's close, so it is known
# before the D+1 open but not at a 15:20 same-day entry. Audited 2026-08-06
# across the whole feature store: delivery is the only post-close source in it
# (everything else is derived from price/volume; the mcap trio adds annual
# filing-date steps, a one-day granularity error, not a daily look-ahead). No
# feature is derived from FII/DII, bulk deals or announcements today — add them
# here if one ever is.
NEXT_OPEN_FEATURES = {"deliv_x20"}
FLAWED_CLOSE = "N/A (look-ahead)"

FEATURES = sorted(f[:-8] for f in os.listdir(FEAT_DIR)) if os.path.isdir(FEAT_DIR) else []
MARKET = ["score", "pct40ma", "ratio10", "net4", "net25q"]
DERIVED = ["ret_63", "ret_126", "ret_252", "ret_504"]
CALENDAR = ["month", "dow", "dom", "expiry_dist"]  # date-only, no look-ahead


def _expiry_dist(dates):
    """Calendar days from each date to the LAST THURSDAY of its month
    (0 = on it, positive = before). India monthly F&O expiry proxy.
    Caveat: NSE shifted to last-Tuesday from ~Sep-2025; this uses Thursday
    for the whole history (>95% of the sample), a known small tail error."""
    out = np.empty(len(dates))
    cache = {}
    for i, d in enumerate(dates):
        key = (d.year, d.month)
        if key not in cache:
            nxt = (pd.Timestamp(d.year + 1, 1, 1) if d.month == 12
                   else pd.Timestamp(d.year, d.month + 1, 1))
            last = nxt - pd.Timedelta(days=1)
            cache[key] = last - pd.Timedelta(days=(last.dayofweek - 3) % 7)
        out[i] = (cache[key] - pd.Timestamp(d.year, d.month, d.day)).days
    return out


def _naive(idx):
    return idx.tz_localize(None) if getattr(idx, "tz", None) is not None else idx


@functools.lru_cache(maxsize=None)
def cached_matrix(name):
    """A full-history OHLCV matrix from the study cache, read once per process
    (--rerun-all asks for the same three matrices ~300 times)."""
    return pd.read_parquet(os.path.join(CACHE, f"{name}.parquet"))


def load_events():
    ev = pd.read_parquet(EVENTS)
    ev["date"] = pd.DatetimeIndex(_naive(pd.DatetimeIndex(ev["date"])))
    return ev


def lookup(ev, frame):
    """Value of a date x symbol frame at each event's (date, symbol)."""
    frame = frame.copy()
    frame.index = _naive(frame.index)
    ri = frame.index.get_indexer(ev["date"])
    ci = frame.columns.get_indexer(ev["symbol"])
    ok = (ri >= 0) & (ci >= 0)
    out = np.full(len(ev), np.nan)
    out[ok] = frame.to_numpy()[ri[ok], ci[ok]]
    return out


def condition_values(ev, cond):
    kind, name = cond["type"], cond["name"]
    if kind == "feature":
        if name not in FEATURES:
            raise ValueError(f"unknown feature {name}; have {FEATURES}")
        return lookup(ev, pd.read_parquet(os.path.join(FEAT_DIR, f"{name}.parquet"))), "stock"
    if kind == "derived":
        close = pd.read_parquet(os.path.join(CACHE, "close.parquet"))
        n = {"ret_63": 63, "ret_126": 126, "ret_252": 252, "ret_504": 504}[name]
        return lookup(ev, (close / close.shift(n) - 1) * 100), "stock"
    if kind == "placebo":
        salt = cond.get("salt", name)
        vals = np.array([int(hashlib.md5(f"{salt}:{s}".encode()).hexdigest()[:6], 16)
                         % 1000 / 1000 for s in ev["symbol"]])
        return vals, "stock"
    if kind == "placebo_market":
        salt = cond.get("salt", name)
        days = ev["date"].dt.strftime("%Y-%m-%d")
        uniq = {d: int(hashlib.md5(f"{salt}:{d}".encode()).hexdigest()[:6], 16)
                % 1000 / 1000 for d in days.unique()}
        return days.map(uniq).to_numpy(), "market"
    if kind == "placebo_shuffled":
        base, _ = condition_values(ev, {"type": "feature", "name": name})
        rng = np.random.default_rng(
            int(hashlib.md5(f"shuffle:{cond.get('salt', '0')}".encode()).hexdigest()[:8], 16))
        return rng.permutation(base), "stock"
    if kind == "cheat":
        return ev["ret_o5"].to_numpy(), "stock"
    if kind == "calendar":
        d = ev["date"].dt
        if name == "month":
            return d.month.to_numpy().astype(float), "market"
        if name == "dow":
            return d.dayofweek.to_numpy().astype(float), "market"  # 0=Mon..4=Fri
        if name == "dom":
            return d.day.to_numpy().astype(float), "market"
        if name == "expiry_dist":
            return _expiry_dist(ev["date"]), "market"
        raise ValueError(f"unknown calendar name {name}")
    if kind == "market":
        if name == "score":
            s = pd.read_parquet(os.path.join(CACHE, "breadth_score.parquet"))["score"]
        else:
            mm = pd.read_parquet(MM_HIST)
            mm.index = _naive(mm.index)
            if name == "net4":
                s = mm["up4"] - mm["dn4"]
            elif name == "net25q":
                s = mm["up25q"] - mm["dn25q"]
            else:
                s = mm[name]
        s.index = _naive(s.index)
        return s.reindex(ev["date"]).to_numpy(), "market"
    raise ValueError(f"unknown condition type {kind}")


def apply_min_gap(ev, min_gap):
    """Keep events spaced >= min_gap trading bars apart PER SYMBOL (greedy,
    earliest-first). Breaks the within-symbol serial overlap that inflates
    long-horizon effects for persistent factors (RS/momentum). Cross-symbol
    same-date overlap is already handled by the within-date permutation."""
    close = pd.read_parquet(os.path.join(CACHE, "close.parquet"))
    pos = pd.Series(range(len(close.index)), index=_naive(close.index))
    e = ev.copy()
    e["_pos"] = pos.reindex(_naive(pd.DatetimeIndex(e["date"]))).to_numpy()
    e = e.dropna(subset=["_pos"]).sort_values(["symbol", "_pos"])
    keep, last = [], {}
    for idx, sym, p in zip(e.index, e["symbol"], e["_pos"]):
        if sym not in last or p - last[sym] >= min_gap:
            keep.append(idx)
            last[sym] = p
    return ev.loc[keep].reset_index(drop=True)


def apply_filters(ev, filters):
    for name, op, val in filters or []:
        if name.startswith("market:"):
            vals = condition_values(ev, {"type": "market", "name": name[7:]})[0]
        elif name in ("mcap_rank", "mcap_cr"):
            vals = lookup(ev, pd.read_parquet(os.path.join(CACHE, f"{name}.parquet")))
        elif name in FEATURES:
            vals = condition_values(ev, {"type": "feature", "name": name})[0]
        else:
            vals = condition_values(ev, {"type": "derived", "name": name})[0]
        keep = vals >= val if op == ">=" else vals <= val
        ev = ev[np.nan_to_num(keep, nan=False)]
    return ev.reset_index(drop=True)


def close_flaw(ev, spec):
    """Why the close ruler may not grade this spec, or None.

    A feature published after the close cannot be known at a 15:20 entry, so a
    close-ruler verdict conditioned on it is look-ahead. Used as a cohort FILTER
    the same feature is only a defect if the filter actually SELECTS events —
    `deliv_x20 >= 0` is a pure "this date has delivery data" gate and carries no
    same-day information, which is why the modern-era controls stay valid."""
    cond = spec["condition"]
    if cond["type"] == "feature" and cond["name"] in NEXT_OPEN_FEATURES:
        return f"{cond['name']} is published after the close"
    for name, op, val in spec["cohort"].get("filters") or []:
        if name not in NEXT_OPEN_FEATURES:
            continue
        vals = condition_values(ev, {"type": "feature", "name": name})[0]
        selective = (np.nanmin(vals) < val if op == ">=" else np.nanmax(vals) > val)
        if selective:
            return f"cohort selected on {name}, which is published after the close"
    return None


def close_r(ev, col, side):
    """A *_close R column with its risk denominator floored at RISK_FLOOR_PCT.

    Rebuilds the close-entry risk exactly as event_store._stop_r does
    (stop = signal low capped 6% under the close entry; mirrored for shorts),
    then re-expresses R on a risk of at least RISK_FLOOR_PCT of entry. The trade
    is unchanged — same stop, same exit, same rupees — only the denominator is
    floored, so R = R_raw * risk / max(risk, floor). Below ~1% a stop is not a
    distinct risk unit: round-trip cost plus slippage is already ~0.3%, and
    intraday noise on a 4-5% ADR stock is several times a 0.5% stop."""
    entry = lookup(ev, cached_matrix("close"))
    if side == "long":
        risk = entry - np.maximum(lookup(ev, cached_matrix("low")), entry * 0.94)
    else:
        risk = np.minimum(lookup(ev, cached_matrix("high")), entry * 1.06) - entry
    scale = np.where(risk > 0, risk / np.maximum(risk, entry * RISK_FLOOR_PCT / 100),
                     np.nan)
    return ev[col].to_numpy() * scale


def bucketize(vals, spec):
    if spec == "quartiles":
        return pd.qcut(vals, 4, labels=False, duplicates="drop")
    if spec == "quintiles":
        return pd.qcut(vals, 5, labels=False, duplicates="drop")
    return pd.cut(vals, spec, labels=False)


def era_of(dates):
    y = dates.dt.year
    return np.where(y < 2020, "A", np.where(y <= 2022, "COVID", "B"))


def effect_of(df, col="stop_r"):
    """Top-bucket minus bottom-bucket mean outcome (buckets are ordered)."""
    g = df.groupby("bucket")[col].mean()
    if len(g) < 2:
        return np.nan
    return g.loc[g.index.max()] - g.loc[g.index.min()]


def modern_split(df, col):
    """Era B cut in half: B23 = 2023, B24 = 2024+. Buckets are the ones already
    cut on the full cohort, so the halves are directly comparable to each other
    and to the era effects. Used only by the modern-era track."""
    year = df["date"].dt.year
    lo, hi = df["bucket"].min(), df["bucket"].max()
    out = {}
    for key, mask in (("B23", year == 2023), ("B24", year >= 2024)):
        g = df[mask]
        out[key] = {
            "effect": (round(float(effect_of(g, col)), 3) if len(g) else np.nan),
            "n": int(len(g)),
            "n_ext": [int((g["bucket"] == b).sum()) for b in (lo, hi)]}
    return out


def permutation_pct(df, mode, seed=7, col="stop_r"):
    rng = np.random.default_rng(seed)
    obs = abs(effect_of(df, col))
    nulls = []
    if mode == "market":
        per_date = df.groupby("date")["bucket"].first()
        dates = per_date.index.to_numpy()
        for _ in range(N_PERM):
            shuffled = pd.Series(rng.permutation(per_date.to_numpy()), index=dates)
            d2 = df.copy()
            d2["bucket"] = shuffled.reindex(df["date"]).to_numpy()
            nulls.append(abs(effect_of(d2, col)))
    else:
        idx_by_date = df.groupby("date").indices
        b = df["bucket"].to_numpy()
        for _ in range(N_PERM):
            b2 = b.copy()
            for ii in idx_by_date.values():
                b2[ii] = b[rng.permutation(ii)]
            d2 = df.copy()
            d2["bucket"] = b2
            nulls.append(abs(effect_of(d2, col)))
    return float((obs > np.array(nulls)).mean() * 100)


def run_spec(spec, ev_all):
    ev = ev_all[ev_all["trigger"] == spec["cohort"]["trigger"]].copy()
    flaw = close_flaw(ev, spec)
    ev = apply_filters(ev, spec["cohort"].get("filters"))
    if spec["cohort"].get("min_gap"):
        ev = apply_min_gap(ev, spec["cohort"]["min_gap"])

    side = spec["cohort"].get("side", "long")
    c5 = "stop_r" if side == "long" else "stop_r_short"
    c20 = "stop_r_20" if side == "long" else "stop_r_20_short"
    c5c = c5 + "_close"          # same ruler, entry moved to the signal close

    vals, mode = condition_values(ev, spec["condition"])
    ev["cond"] = vals
    ev = ev.dropna(subset=["cond", c5]).reset_index(drop=True)
    ev["bucket"] = bucketize(ev["cond"].to_numpy(), spec["condition"]["buckets"])
    ev = ev.dropna(subset=["bucket"]).reset_index(drop=True)
    ev["bucket"] = ev["bucket"].astype(int)
    ev["era"] = era_of(ev["date"])

    has20 = c20 in ev.columns
    buckets = {}
    for b, g in ev.groupby("bucket"):
        row = {"cond_range": [float(g["cond"].min()), float(g["cond"].max())]}
        for era, ge in g.groupby("era"):
            row[era] = {"n": int(len(ge)),
                        "avg_stop_r": round(float(ge[c5].mean()), 3),
                        "med_ret_o5": round(float(ge["ret_o5"].median()), 2),
                        "win5_pct": round(float((ge["ret_o5"] > 0).mean() * 100), 1)}
            if has20:
                row[era]["avg_stop_r_20"] = round(float(ge[c20].mean()), 3)
        buckets[int(b)] = row

    def effects(col):
        return {era: (round(float(effect_of(g, col)), 3) if len(g) else np.nan)
                for era, g in ev.groupby("era")}

    eff = effects(c5)
    lo, hi = ev["bucket"].min(), ev["bucket"].max()
    n_ext = {era: [int(((ev["era"] == era) & (ev["bucket"] == b)).sum())
                   for b in (lo, hi)] for era in ("A", "B")}
    null_pct = permutation_pct(ev, mode, col=c5)
    ea, eb = eff.get("A", np.nan), eff.get("B", np.nan)
    mod5 = modern_split(ev, c5)
    modern_ok = int((ev["era"] == "A").sum()) == 0
    verdict = verdict_of(ea, eb, n_ext, null_pct, mod5, modern_ok)

    out = {"id": spec["id"], "question": spec["question"],
           "plain": spec.get("plain"), "spec": spec, "side": side,
           "n": int(len(ev)), "buckets": buckets,
           "effect_R": {"A": ea, "COVID": eff.get("COVID"), "B": eb},
           "extreme_bucket_n": n_ext, "null_beat_pct": null_pct,
           "modern_split": mod5, "modern_eligible": modern_ok,
           "verdict": verdict,
           "track": "modern" if verdict.endswith("(modern)") else "full"}
    if out["track"] == "modern":
        out["era_A"] = era_a_status(n_ext)

    if has20:
        eff20 = effects(c20)
        null20 = permutation_pct(ev, mode, col=c20)
        ea20, eb20 = eff20.get("A", np.nan), eff20.get("B", np.nan)
        out["effect_R_20"] = {"A": ea20, "COVID": eff20.get("COVID"), "B": eb20}
        out["null_beat_pct_20"] = null20
        out["verdict_20"] = verdict_of(ea20, eb20, n_ext, null20,
                                       modern_split(ev, c20), modern_ok)

    c5t = "stop_r_trail" if side == "long" else "stop_r_trail_short"
    if c5t in ev.columns:
        ev["_trail_w5"] = ev[c5t].clip(-WINSOR_R, WINSOR_R)
        efft, efftw = effects(c5t), effects("_trail_w5")
        nullt = permutation_pct(ev, mode, col=c5t)
        eat, ebt = efft.get("A", np.nan), efft.get("B", np.nan)
        out["effect_R_trail"] = {"A": eat, "COVID": efft.get("COVID"), "B": ebt}
        out["effect_R_trail_w5"] = {"A": efftw.get("A"), "COVID": efftw.get("COVID"),
                                    "B": efftw.get("B")}
        out["null_beat_pct_trail"] = nullt
        out["verdict_trail"] = verdict_of(
            eat, ebt, n_ext, nullt, modern_split(ev, c5t), modern_ok,
            bars=(WEAK_MIN_TRAIL, WEAK_NULL_TRAIL, EFFECT_FLOOR),
            bars_modern=(TRAIL_MODERN_MIN, WEAK_NULL_TRAIL, TRAIL_MODERN_MIN))

    c5be = "stop_r_trail_be" if side == "long" else "stop_r_trail_be_short"
    if c5be in ev.columns:
        ev["_be_w5"] = ev[c5be].clip(-WINSOR_R, WINSOR_R)
        effb, effbw = effects(c5be), effects("_be_w5")
        nullb = permutation_pct(ev, mode, col=c5be)
        eab, ebb = effb.get("A", np.nan), effb.get("B", np.nan)
        out["effect_R_trail_be"] = {"A": eab, "COVID": effb.get("COVID"), "B": ebb}
        out["effect_R_trail_be_w5"] = {"A": effbw.get("A"),
                                       "COVID": effbw.get("COVID"),
                                       "B": effbw.get("B")}
        out["null_beat_pct_trail_be"] = nullb
        out["verdict_trail_be"] = verdict_of(
            eab, ebb, n_ext, nullb, modern_split(ev, c5be), modern_ok,
            bars=(WEAK_MIN_TRAIL_BE, WEAK_NULL_TRAIL_BE, TRAIL_BE_PASS_MIN),
            bars_modern=(TRAIL_BE_MODERN_MIN, WEAK_NULL_TRAIL_BE,
                         TRAIL_BE_MODERN_MIN))

    if c5c in ev.columns:
        if flaw:
            out["verdict_close"] = FLAWED_CLOSE
            out["close_flaw"] = flaw
        else:
            ev["_close_r"] = close_r(ev, c5c, side)
            ev["_close_w5"] = ev["_close_r"].clip(-WINSOR_R, WINSOR_R)
            effc, effw = effects("_close_r"), effects("_close_w5")
            nullc = permutation_pct(ev, mode, col="_close_r")
            eac, ebc = effc.get("A", np.nan), effc.get("B", np.nan)
            out["effect_R_close"] = {"A": eac, "COVID": effc.get("COVID"), "B": ebc}
            out["effect_R_close_w5"] = {"A": effw.get("A"),
                                        "COVID": effw.get("COVID"),
                                        "B": effw.get("B")}
            out["null_beat_pct_close"] = nullc
            out["verdict_close"] = verdict_of(
                eac, ebc, n_ext, nullc, modern_split(ev, "_close_r"), modern_ok,
                bars=(WEAK_MIN_CLOSE, WEAK_NULL_CLOSE, EFFECT_FLOOR))
    return out


def _grade(e1, e2, n_pairs, null_pct, bars=None):
    """The judgment bars applied to any two windows that must agree.

    `bars` = (min |effect| for WEAK, min null % for WEAK, min |effect| for PASS)
    and lets a ruler carry its own calibration. The default is the D+1-open
    calibration; the close ruler overrides the WEAK pair and the trail ruler's
    MODERN path overrides all three (see the constants above). NULL_PCT — the
    95% luck bar for PASS — is shared by every ruler and has never moved."""
    weak_min, weak_null, pass_floor = bars or (WEAK_MIN, WEAK_NULL, EFFECT_FLOOR)

    def bad(x):
        return x is None or (isinstance(x, float) and np.isnan(x))
    if any(min(p) < MIN_N for p in n_pairs):
        return "INSUFFICIENT"
    if bad(e1) or bad(e2) or e1 * e2 < 0 or e1 == 0:
        return "FAIL"
    lo = min(abs(e1), abs(e2))
    if lo >= pass_floor and null_pct >= NULL_PCT:
        return "PASS"
    # WEAK always requires clearing the luck test — a big effect that beats
    # few permutations is high-variance noise, not a hint (2026-07-30 fix).
    if lo >= weak_min and null_pct >= weak_null:
        return "WEAK"
    return "FAIL"


def verdict_of(ea, eb, n_ext, null_pct, modern=None, modern_ok=True, bars=None,
               bars_modern=None):
    """Single source of the judgment bars (run_spec and --regrade).

    Full-history track: era A vs era B. Modern-era track (see the module
    docstring): when era A is unjudgeable — the DATA does not reach it, i.e.
    the graded sample holds no era-A events at all (`modern_ok`) — grade era B's
    2023 vs 2024+ halves instead, and suffix the verdict so it can never be
    mistaken for a full-history one. A sample that HAS era-A data and merely
    comes out thin there stays INSUFFICIENT on the full track: otherwise a
    bucket re-cut could silently move a full-history finding onto the weaker
    judge (2026-08-06 red-team fix). `modern` is the dict from modern_split();
    passing None keeps the old behaviour verbatim. `bars_modern` lets a ruler
    whose noise ceiling differs BETWEEN the two judges carry a separate
    calibration for the modern path (the trail ruler does; see TRAIL_MODERN_MIN).
    """
    if modern is not None and modern_ok and min(n_ext["A"]) < MIN_N:
        return _grade(modern["B23"]["effect"], modern["B24"]["effect"],
                      [modern["B23"]["n_ext"], modern["B24"]["n_ext"]],
                      null_pct, bars_modern or bars) + " (modern)"
    return _grade(ea, eb, [n_ext["A"], n_ext["B"]], null_pct, bars)


def base_verdict(v):
    """Strip the modern-era suffix for sorting/plain-English lookups."""
    return v.split(" ")[0]


def era_a_status(n_ext):
    """Why era A was waived — 'no data' and 'too thin' are different failures."""
    lo = min(n_ext["A"])
    return "N/A (no data)" if lo == 0 else f"N/A (thin: n={lo} < {MIN_N})"


def rerun_all():
    """Re-run every stored result's spec through run_spec and overwrite it.
    Use after an engine change (e.g. the 20-day horizon, the close-entry
    ruler) to backfill new fields across the whole board. The D+1-open stop_r
    columns are untouched by those changes, so the primary 5-day verdict only
    moves where the new modern-era track applies."""
    ev_all = load_events()
    paths = sorted(glob.glob(os.path.join(RESULTS, "*.json")))
    ok = fail = 0
    for i, path in enumerate(paths, 1):
        with open(path) as f:
            r = json.load(f)
        spec = r.get("spec")
        if not spec:
            print(f"  [skip] {r.get('id')} has no stored spec")
            fail += 1
            continue
        try:
            res = run_spec(spec, ev_all)
            with open(path, "w") as f:
                json.dump(res, f, indent=1, default=float)
            ok += 1
            v20 = res.get("verdict_20", "-")
            vcl = res.get("verdict_close", "-")
            print(f"  [{i}/{len(paths)}] {spec['id']:<34} 5d {res['verdict']:<21} "
                  f"20d {v20:<21} close {vcl}")
        except Exception as e:
            print(f"  [fail] {spec.get('id')}: {e}")
            fail += 1
    print(f"rerun-all: {ok} refreshed, {fail} skipped/failed")


def regrade():
    """Recompute every stored verdict from stored effects/ns/null (no re-run)."""
    changed = 0
    for path in sorted(glob.glob(os.path.join(RESULTS, "*.json"))):
        with open(path) as f:
            r = json.load(f)
        e = r["effect_R"]
        v = verdict_of(e.get("A"), e.get("B"), r["extreme_bucket_n"],
                       r["null_beat_pct"], r.get("modern_split"),
                       r.get("modern_eligible", True))
        if v != r["verdict"]:
            print(f"  {r['id']}: {r['verdict']} -> {v}")
            r["verdict"] = v
            r["track"] = "modern" if v.endswith("(modern)") else "full"
            if r["track"] == "modern":
                r["era_A"] = era_a_status(r["extreme_bucket_n"])
            changed += 1
            with open(path, "w") as f:
                json.dump(r, f, indent=1, default=float)
    print(f"regraded {changed} results")


def plain_tested(rid):
    """One plain-English sentence of what an experiment tested.
    Reads plain.json; falls back to prefix rules for controls/perturbations."""
    path = os.path.join(HERE, "plain.json")
    table = json.load(open(path)) if os.path.exists(path) else {}
    if rid in table:
        return table[rid]
    if rid.startswith("v_"):                       # red-team perturbation
        base = rid[2:].rsplit("_", 1)[0]
        return f"Robustness re-test of {base} (edges/buckets nudged)."
    if rid.startswith(("x_pb", "x_pm", "x_ps", "c002")):
        return "Sanity check: a fake/random trait should show nothing."
    return "(plain description not written yet)"


def plain_result(verdict, ea, eb):
    """Plain-English outcome derived from the verdict and effect direction."""
    base, modern = base_verdict(verdict), verdict.endswith("(modern)")
    if base == "PASS":
        e = eb if eb is not None else ea
        dirn = "more of it = better" if (e or 0) > 0 else "more of it = worse"
        if modern:
            return ("Passed the MODERN-ERA judge only — the data does not reach "
                    f"before 2020, but 2023 and 2024+ agree ({dirn}).")
        return f"Passed the judge — held old & recent years ({dirn})."
    if base == "WEAK":
        return "Weak hint — real-looking but not trustworthy yet."
    if base == "INSUFFICIENT":
        return "Promising but too few events to certify."
    return "Rejected — no reliable effect (looks like noise)."


def scoreboard():
    rows = []
    for path in sorted(glob.glob(os.path.join(RESULTS, "*.json"))):
        with open(path) as f:
            r = json.load(f)
        e = r["effect_R"]
        tested = r.get("plain") or plain_tested(r["id"])
        def cell(eff, verdict):
            if not verdict:
                return ""
            if verdict.startswith("N/A"):
                return "N/A look-ahead"
            if not eff:
                return ""
            b, tag = eff.get("B"), base_verdict(verdict)[:4]
            return f"{tag} {b:+.2f}" if b is not None else tag
        h20 = cell(r.get("effect_R_20"), r.get("verdict_20"))
        htr = cell(r.get("effect_R_trail"), r.get("verdict_trail"))
        hbe = cell(r.get("effect_R_trail_be"), r.get("verdict_trail_be"))
        hcl = cell(r.get("effect_R_close"), r.get("verdict_close"))

        def w5cell(key):
            w = r.get(key) or {}
            return "" if w.get("B") is None else f"{w['B']:+.2f}"
        rows.append((r["verdict"], r["id"], r["n"], e.get("A"), e.get("B"),
                     r["null_beat_pct"], tested, h20, htr,
                     w5cell("effect_R_trail_w5"), hbe, hcl,
                     w5cell("effect_R_close_w5")))
    order = {"PASS": 0, "WEAK": 1, "INSUFFICIENT": 2, "FAIL": 3}
    # full-history verdicts outrank modern-era ones of the same grade
    rows.sort(key=lambda x: (order.get(base_verdict(x[0]), 9),
                             x[0].endswith("(modern)"),
                             -(abs(x[3] or 0) + abs(x[4] or 0))))
    lines = ["# SCOREBOARD — research machine (auto-generated, do not edit)",
             "",
             "`tested` = the question in plain words. `result` = plain outcome.",
             "`eff A/B` = how much better the top group did vs the bottom, in R",
             "(profit per rupee risked), old era / recent era. Bars: engine.py.",
             "",
             "Note: `verdict` is the *judge's* grade (passed its own bar). "
             "Whether a PASS also survived the red-team attack is tracked in "
             "`research/factory/LEDGER.md`, not here.",
             "`5d B` = recent-era effect at the 5-day hold (the primary grade). "
             "`20d` = verdict + recent-era effect at a 20-day hold, where it has "
             "been run (blank = not yet graded at 20d).",
             "`close` = the same 5-day grade with entry at the SIGNAL-DAY CLOSE "
             "instead of the next open (the Order Pad's real entry window). "
             "The D+1-open convention hands back the overnight gap. That gap is "
             "NOT uniform across buckets — many experiments change grade, "
             "and the extension / volume-spike anti-signal family collapses "
             "toward zero, because much of what it measured was the bigger gap "
             "you pay on an extended stock, not a post-entry edge. Where `5d B` "
             "and `close` disagree, `close` is the column that matches how the "
             "Order Pad actually enters. Close-ruler R uses a 1%-of-entry "
             "minimum-risk floor (a stop a hair under a close entry is not a "
             "real risk unit); `w5` is the same effect winsorized at +/-5R, a "
             "tail diagnostic — a `close` figure far from its `w5` twin is "
             "carried by a handful of events.",
             "`close` = **N/A look-ahead** means the experiment conditions on a "
             "feature NSE publishes after the close (delivery %), so it cannot "
             "be graded at a 15:20 entry at all. Its D+1-open grade stands.",
             "",
             "A verdict marked **(modern)** was graded on the modern-era track: "
             "the feature has no usable pre-2020 data (delivery %, EP cohorts), "
             "so era A was waived and 2023 vs 2024+ had to agree instead. It is "
             "a weaker claim than a full-history PASS — never read it as one.",
             "",
             "`trail` = the THIRD ruler: same D+1-open entry, but half the "
             "position is sold at +2R and the rest trails a ratcheting 20-day "
             "low of closes (60-bar cap) — the exit the validated strategies "
             "actually use. Read it when you suspect a setup's edge lives in "
             "the winner tail that a 5- or 20-day clock exit cuts off. `tw5` is "
             "the same effect winsorized at +/-5R; the trail's R distribution "
             "is fat by construction, so a `trail` far from its `tw5` twin is "
             "carried by a few huge runners and is NOT a stable edge.",
             "`tbe` = the trail ruler with a BREAKEVEN move: the stop jumps to "
             "the entry price once the trade touches +1R. Everything else is "
             "the trail ruler. Read it against `trail` to see whether the most "
             "common retail risk reflex changes the verdict — on the board it "
             "almost never does, because it lowers every bucket's mean by a "
             "similar amount rather than re-ordering them.",
             "",
             "| verdict | tested | result | 5d B | 20d | trail | tw5 | tbe | close | w5 | n | id |",
             "|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for v, i, n, a, b, np_, tested, h20, htr, htw5, hbe, hcl, hw5 in rows:
        fb = "" if b is None else f"{b:+.2f}"
        lines.append(f"| {v} | {tested} | {plain_result(v, a, b)} "
                     f"| {fb} | {h20} | {htr} | {htw5} | {hbe} | {hcl} "
                     f"| {hw5} | {n:,} | {i} |")
    out = os.path.join(HERE, "SCOREBOARD.md")
    with open(out, "w") as f:
        f.write("\n".join(lines) + "\n")
    print(f"scoreboard → {out}  ({len(rows)} experiments)")


def main():
    if "--rerun-all" in sys.argv:
        rerun_all()
        scoreboard()
        return
    if "--regrade" in sys.argv:
        regrade()
        return
    if "--scoreboard" in sys.argv:
        scoreboard()
        return
    os.makedirs(RESULTS, exist_ok=True)
    ev_all = load_events()
    for path in sys.argv[1:]:
        with open(path) as f:
            spec = json.load(f)
        res = run_spec(spec, ev_all)
        out = os.path.join(RESULTS, f"{spec['id']}.json")
        with open(out, "w") as f:
            json.dump(res, f, indent=1, default=float)
        e = res["effect_R"]
        line = (f"{res['verdict']:<12} {spec['id']:<34} n={res['n']:<7,} "
                f"5d[effB {e['B'] if e['B'] is not None else float('nan'):+.2f}R "
                f"null {res['null_beat_pct']:.0f}%]")
        if "effect_R_20" in res:
            e20 = res["effect_R_20"]
            line += (f"  20d[{res['verdict_20']:<12} "
                     f"effB {e20['B'] if e20['B'] is not None else float('nan'):+.2f}R "
                     f"null {res['null_beat_pct_20']:.0f}%]")
        if "effect_R_trail" in res:
            et, ew = res["effect_R_trail"], res["effect_R_trail_w5"]
            line += (f"  trail[{res['verdict_trail']:<12} "
                     f"effB {et['B'] if et['B'] is not None else float('nan'):+.2f}R "
                     f"w5 {ew['B'] if ew['B'] is not None else float('nan'):+.2f}R "
                     f"null {res['null_beat_pct_trail']:.0f}%]")
        if "effect_R_trail_be" in res:
            eb_ = res["effect_R_trail_be"]
            line += (f"  trailBE[{res['verdict_trail_be']:<12} "
                     f"effB {eb_['B'] if eb_['B'] is not None else float('nan'):+.2f}R "
                     f"null {res['null_beat_pct_trail_be']:.0f}%]")
        if res.get("close_flaw"):
            line += f"  close[{FLAWED_CLOSE} — {res['close_flaw']}]"
        elif "effect_R_close" in res:
            ec = res["effect_R_close"]
            line += (f"  close[{res['verdict_close']:<12} "
                     f"effB {ec['B'] if ec['B'] is not None else float('nan'):+.2f}R "
                     f"null {res['null_beat_pct_close']:.0f}%]")
        print(line)


if __name__ == "__main__":
    main()
