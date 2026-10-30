"""
ga_pocket_book.py — the bridge between the research machine's certified
pockets and the harness's portfolio judge (the missing step: no GA champion
had ever faced bookrunner's beta subtraction, seed spread, or cost model).

Takes a machine spec JSON (research/machine/specs/*.json), reproduces its
event cohort with the machine's own evaluator (engine.apply_filters /
condition_values / bucketize — identical cohort math, no re-derivation
drift), then judges the tradeable claim with the post-audit book:

  - run_book / seed_spread over 20 tie-break orders (capital mode: cash
    account, slot sizing; respect banned=True on skip > 20%)
  - same_date_control: k random tradeable symbols per signal bar, exits
    priced with the SAME entry clock / stop rule / hold (beta subtraction
    with regime held constant by construction)
  - costs at the standard 0.15%/side

Pre-registered verdict rule (plan 2026-08-11): the pocket is PROMOTABLE only
if full-period median book CAGR beats the same-date control's after costs
AND seed-spread p10 stays positive AND the point estimate is not banned.
Otherwise the machine PASS stands as a factor finding only.

Caveat (gradient specs): the extreme condition bucket is assigned by qcut
over the full cohort, exactly as certified — a live rule would need a fixed
threshold, so the bucket edge carries mild full-sample look-ahead. Pocket
specs (pure filter stacks, --bucket none) have no such caveat.

Usage:
  ~/anaconda3/bin/python src/backtest/studies/ga_pocket_book.py \
      [--spec research/machine/specs/ga_four_pct_s1_seeded_250d79.json] \
      [--bucket top|bottom|none] [--slots 10] [--k 1]
"""

import argparse
import json
import os
import sys

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, ".."))

import common  # noqa: E402
import bookrunner  # noqa: E402

# the machine's evaluator, by explicit path — "engine" also names the
# harness's own src/backtest/engine.py, so a plain import is ambiguous
import importlib.util  # noqa: E402

MACHINE_DIR = os.path.abspath(os.path.join(HERE, "..", "..", "..",
                                           "research", "machine"))
sys.path.insert(0, MACHINE_DIR)
_spec = importlib.util.spec_from_file_location(
    "machine_engine", os.path.join(MACHINE_DIR, "engine.py"))
machine = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(machine)

DEFAULT_SPEC = os.path.abspath(os.path.join(
    HERE, "..", "..", "..", "research", "machine", "specs",
    "ga_four_pct_s1_seeded_250d79.json"))
HORIZON = 5            # the certified ruler: stop_r = D+1 open, 5-bar cap
CONTROL_DRAWS = 5


def cohort_events(spec, bucket):
    ev = machine.load_events()
    ev = ev[ev["trigger"] == spec["cohort"]["trigger"]].reset_index(drop=True)
    ev = machine.apply_filters(ev, spec["cohort"].get("filters"))
    if bucket != "none" and "condition" in spec:
        vals, _ = machine.condition_values(ev, spec["condition"])
        b = np.asarray(machine.bucketize(vals, spec["condition"]["buckets"]),
                       dtype=float)
        target = np.nanmax(b) if bucket == "top" else np.nanmin(b)
        ev = ev[b == target].reset_index(drop=True)
    return ev, spec["cohort"].get("side", "long")


def trades_from_events(ev, m, side):
    """Standard bookrunner trade schema from machine events: R is the stored
    stop_r ruler; stop_pct is rebuilt from the matrices with the house stop
    (max(signal low, entry*0.94) long, mirrored short)."""
    close = m["close"]
    di = close.index.get_indexer(pd.DatetimeIndex(ev["date"]))
    si = close.columns.get_indexer(ev["symbol"])
    ok = (di >= 0) & (si >= 0) & (di + 1 < len(close.index))
    ev, di, si = ev[ok].reset_index(drop=True), di[ok], si[ok]
    O = m["open"].to_numpy()
    entry = O[di + 1, si]
    if side == "long":
        anchor = m["low"].to_numpy()[di, si]
        stop = np.maximum(anchor, entry * 0.94)
    else:
        anchor = m["high"].to_numpy()[di, si]
        stop = np.minimum(anchor, entry * 1.06)
    out = pd.DataFrame({
        "date": close.index[di], "symbol": ev["symbol"],
        "R": ev["stop_r" if side == "long" else "stop_r_short"].to_numpy(),
        "stop_pct": np.abs(entry - stop) / entry, "side": side,
        "di": di,
        "ret_o5": ev["ret_o5"].to_numpy(), "ret_o20": ev["ret_o20"].to_numpy()})
    return out.dropna(subset=["R", "stop_pct"]).reset_index(drop=True)


def control_trades(m, universe, rows, side, k, seed):
    ctrl = bookrunner.same_date_control(m, universe, rows, k=k, seed=seed)
    O, H, L, C = (m[c].to_numpy() for c in ("open", "high", "low", "close"))
    n_dates = len(m["close"].index)
    r, c = ctrl["di"].to_numpy(), ctrl["si"].to_numpy()
    entry = O[np.minimum(r + 1, n_dates - 1), c]
    anchor = L[r, c] if side == "long" else H[r, c]
    R = bookrunner._stop_r(entry, anchor, r, c, O, H, L, C, n_dates,
                           HORIZON, side)
    stop = (np.maximum(anchor, entry * 0.94) if side == "long"
            else np.minimum(anchor, entry * 1.06))
    out = pd.DataFrame({"date": ctrl["date"], "symbol": ctrl["symbol"],
                        "R": R, "stop_pct": np.abs(entry - stop) / entry,
                        "side": side})
    return out.dropna(subset=["R", "stop_pct"]).reset_index(drop=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--spec", default=DEFAULT_SPEC)
    ap.add_argument("--bucket", default="top", choices=["top", "bottom", "none"])
    ap.add_argument("--slots", type=int, default=10)
    ap.add_argument("--k", type=int, default=1)
    args = ap.parse_args()

    with open(args.spec) as f:
        spec = json.load(f)
    print(f"spec {spec['id']}  bucket={args.bucket}")

    m = common.load_cache()
    for key in ("open", "high", "low", "close", "volume", "rs"):
        if m[key].index.tz is not None:
            m[key].index = m[key].index.tz_localize(None)
    if m["score"].index.tz is not None:
        m["score"].index = m["score"].index.tz_localize(None)

    ev, side = cohort_events(spec, args.bucket)
    trades = trades_from_events(ev, m, side)
    cal = m["close"].index
    universe = common.tradeable_mask(m["close"], m["volume"])
    print(f"cohort events {len(ev):,} → priced trades {len(trades):,} "
          f"({side}, hold {HORIZON} bars)")

    y = pd.DatetimeIndex(trades["date"]).year
    segments = [("full period", np.ones(len(trades), bool)),
                ("era A <2020", y < 2020),
                ("ex-COVID", (y < 2020) | (y > 2022)),
                ("era B 2023+", y >= 2023)]

    kw = dict(mode="capital", slots=args.slots, horizon=HORIZON)
    verdict_bits = {}
    for label, seg in segments:
        t = trades[seg]
        s = bookrunner.seed_spread(t.drop(columns="di"), cal, **kw)
        print(f"\n--- {label} ---")
        print(bookrunner.fmt("pocket", s))
        meds = []
        for d in range(CONTROL_DRAWS):
            ct = control_trades(m, universe, t["di"].to_numpy(), side,
                                args.k, seed=d)
            cs = bookrunner.seed_spread(ct, cal, **kw)
            if cs:
                meds.append(cs["med"])
                if d == 0:
                    print(bookrunner.fmt(f"same-date control (draw 0)", cs))
        if meds:
            print(f"  control CAGR med over {len(meds)} draws: "
                  f"{np.median(meds):+.1f}% "
                  f"[{min(meds):+.1f}, {max(meds):+.1f}]")
        if label == "full period" and s:
            verdict_bits = {"beats_control": bool(meds) and s["med"] > np.median(meds),
                            "p10_pos": s["lo"] > 0, "not_banned": not s["banned"]}

    ev_tag = trades.copy()
    ev_tag["breadth_score"] = m["score"].reindex(
        pd.DatetimeIndex(trades["date"])).to_numpy()
    rs_di = m["rs"].index.get_indexer(pd.DatetimeIndex(trades["date"]))
    rs_si = m["rs"].columns.get_indexer(trades["symbol"])
    ok = (rs_di >= 0) & (rs_si >= 0)
    vals = np.full(len(trades), np.nan)
    vals[ok] = m["rs"].to_numpy()[rs_di[ok], rs_si[ok]]
    ev_tag["rs_rank"] = vals
    common.add_regime_and_rs_buckets(ev_tag)
    common.print_standard_segments(ev_tag, horizons=(5, 20))

    promotable = verdict_bits and all(verdict_bits.values())
    print(f"\nVERDICT: {'PROMOTABLE' if promotable else 'FACTOR-ONLY'}  "
          f"{verdict_bits}")
    print(common.CAVEATS)


if __name__ == "__main__":
    main()
