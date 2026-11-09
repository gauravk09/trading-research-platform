"""
regime_calibration.py — Which regime signals actually predict whether
breakouts work, and what should their weights be? (ROADMAP item 5, stage 1.)

The live regime tier (src/preprocessing/breadth.py) sums 5 equal-weighted breadth signals.
src/market_signals.py added 4 orthogonal display-only candidates (index trend,
divergence, distribution days, follow-through). This study audits all 9 against
the outcome that matters: forward returns of the actual 4% momentum-burst
cohort (stockbee_4pct_burst.find_events — entry D+1 open, so every signal is
known at the prior close; no look-ahead by construction).

Sub-studies:
  1. Per-signal audit: era x zone -> burst-event D+5 stats + median-stock check
  2. Within-score separation: does each candidate still separate outcomes
     inside days the incumbent 5-signal score already calls good/bad?
  3. Threshold sweeps for the candidates (plateau = real, spike = noise)
  4. Integer-weight grid {0,1,2}^9, walk-forward 2015-2020 <-> 2021-2026

Success bar (user-set, 2026-07-25): a signal earns weight only if it is
individually predictive in BOTH eras AND adds separation within the incumbent
score. Volume-based signals use the full-history Kite volume cache, so they
reach 2015 here even though the live dashboard's volume_matrix starts 2020-10.

Usage:
    ~/anaconda3/bin/python src/backtest/studies/regime_calibration.py
"""

import os
import sys
from itertools import product

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(__file__))

import common
from stockbee_4pct_burst import find_events

NIFTY500 = os.path.join(os.path.dirname(__file__), "..", "..", "..",
                        "data", "parquet", "indices", "nifty500.parquet")
ERA_SPLIT = pd.Timestamp("2021-01-01", tz="Asia/Kolkata")
SIGNALS = ["ratio5", "ratio10", "net25q", "pct40ma", "pct20ma",   # incumbents
           "idx_trend", "diverg", "dist_days", "ftd"]             # candidates
BASELINE_W = (1, 1, 1, 1, 1, 0, 0, 0, 0)                          # today's score

_report: list = []


def say(line: str = "") -> None:
    print(line)
    _report.append(line)


def _zone(series, bull, bear):
    z = pd.Series(np.where(series > bull, 1, np.where(series < bear, -1, 0)),
                  index=series.index)
    return z.where(series.notna(), 0).astype(int)


def build_panel(m: dict) -> pd.DataFrame:
    """Daily zone panel (+1/0/-1 per signal) + raw values for the sweeps.
    Everything is computed from data <= that day's close; entries are D+1."""
    close, volume = m["close"], m["volume"]
    mm = common.compute_market_monitor(close, volume)
    ma20 = close.rolling(20).mean()
    pct20 = (close > ma20).sum(axis=1) / (close.notna() & ma20.notna()).sum(axis=1) * 100

    idx = pd.read_parquet(NIFTY500).set_index("date")["close"].sort_index()
    p = pd.DataFrame(index=close.index)
    p["ratio5"] = _zone(mm["ratio5"], 2, 0.5)
    p["ratio10"] = _zone(mm["ratio10"], 2, 0.5)
    p["net25q"] = _zone(mm["up25q"] - mm["dn25q"], 0, 0)
    p["pct40ma"] = _zone(mm["pct40ma"], 60, 40)
    p["pct20ma"] = _zone(pct20, 60, 40)

    # Index trend (Qullamaggie): fast MA above slow, both rising over 5 bars.
    ma10, ma20i = idx.rolling(10).mean(), idx.rolling(20).mean()
    up = (ma10 > ma20i) & (ma10 > ma10.shift(5)) & (ma20i > ma20i.shift(5))
    dn = (ma10 < ma20i) & (ma10 < ma10.shift(5)) & (ma20i < ma20i.shift(5))
    p["idx_trend"] = (up.astype(int) - dn.astype(int)).reindex(p.index).fillna(0).astype(int)

    # Divergence: index near a 60d extreme while 20d breadth change disagrees.
    b40 = mm["pct40ma"]
    ali = pd.concat([idx.rename("i"), b40.rename("b")], axis=1).dropna()
    ic = ali["i"] / ali["i"].shift(20) - 1
    bd = ali["b"] - ali["b"].shift(20)
    hi60, lo60 = ali["i"].rolling(60).max(), ali["i"].rolling(60).min()
    bear = (ic > 0) & (ali["i"] >= hi60 * 0.98) & (bd < -5)
    bull = (ic < 0) & (ali["i"] <= lo60 * 1.02) & (bd > 5)
    p["diverg"] = (bull.astype(int) - bear.astype(int)).reindex(p.index).fillna(0).astype(int)
    p["diverg_bd"] = bd.reindex(p.index)          # raw, for the sweep
    p["diverg_ic"] = ic.reindex(p.index)
    p["diverg_athi"] = (ali["i"] >= hi60 * 0.98).reindex(p.index).fillna(False)

    # Distribution days / FTD on aggregate rupee turnover (full Kite history).
    t = (close * volume).sum(axis=1, min_count=1)
    ali2 = pd.concat([idx.rename("i"), t.rename("t")], axis=1).dropna()
    dist = (ali2["i"].pct_change() < -0.002) & (ali2["t"] > ali2["t"].shift(1))
    p["dist_count"] = dist.rolling(25).sum().reindex(p.index)
    p["dist_days"] = np.where(p["dist_count"] >= 5, -1, 0)

    at_low = ali2["i"] <= ali2["i"].rolling(25).min() * 1.001
    pos = pd.Series(range(len(ali2)), index=ali2.index, dtype=float)
    since_low = pos - pos.where(at_low).ffill()
    ftd = ((ali2["i"].pct_change() >= 0.015) & (ali2["t"] > ali2["t"].shift(1))
           & since_low.between(4, 13))
    p["ftd"] = (ftd.rolling(5, min_periods=1).sum() > 0).astype(int) \
        .reindex(p.index).fillna(0).astype(int)

    p["score5"] = p[SIGNALS[:5]].sum(axis=1)      # incumbent equal-weight score
    p["era"] = np.where(p.index < ERA_SPLIT, "2015-2020", "2021-2026")
    return p


def median_stock_fwd(m: dict) -> pd.Series:
    """Outcome B: per-day median 5d forward return of the tradeable universe."""
    close = m["close"]
    ok = common.tradeable_mask(close, m["volume"])
    fwd = (close.shift(-5) / close - 1) * 100
    return fwd.where(ok).median(axis=1)


def audit_line(ev: pd.DataFrame, med_b: pd.Series, days: pd.Index, label: str) -> None:
    sub = ev[ev["date"].isin(days)]
    r = sub["ret_o5"].dropna()
    b = med_b.reindex(days).dropna()
    if len(r) < 30:
        say(f"    {label:<10} days={len(days):<5} events={len(r):<6} (too few)")
        return
    say(f"    {label:<10} days={len(days):<5} events={len(r):<6} "
        f"D+5 med {r.median():+5.2f}%  win {(r > 0).mean() * 100:4.1f}%   "
        f"| med-stock 5d {b.median():+5.2f}%")


def per_signal_audit(p: pd.DataFrame, ev: pd.DataFrame, med_b: pd.Series) -> None:
    say("\n[1] Per-signal audit — burst-event D+5 (entry D+1 open) by zone and era")
    say("    (median-stock 5d = outcome B cross-check on the same days)")
    for sig in SIGNALS:
        say(f"\n  {sig}:")
        for era, pe in p.groupby("era"):
            say(f"   {era}:")
            for zone in (1, 0, -1):
                days = pe.index[pe[sig] == zone]
                if len(days) == 0:
                    continue
                audit_line(ev, med_b, days, {1: "bullish", 0: "neutral", -1: "bearish"}[zone])


def within_score(p: pd.DataFrame, ev: pd.DataFrame, med_b: pd.Series) -> None:
    say("\n[2] Within-score separation — candidates inside incumbent-score bands")
    say("    (a candidate must still separate outcomes here to earn weight)")
    for band, cond in (("score5 >= +1 (good)", p["score5"] >= 1),
                       ("score5 <= 0 (weak)", p["score5"] <= 0)):
        say(f"\n  {band}:")
        for sig in SIGNALS[5:]:
            say(f"   {sig}:")
            for zone in (1, 0, -1):
                days = p.index[cond & (p[sig] == zone)]
                if len(days) == 0:
                    continue
                audit_line(ev, med_b, days, {1: "bullish", 0: "neutral", -1: "bearish"}[zone])


def sweeps(p: pd.DataFrame, ev: pd.DataFrame) -> None:
    say("\n[3] Threshold sweeps — plateau = real edge, single-point spike = noise")

    say("\n  distribution-day count >= N (bearish):")
    for n in (3, 4, 5, 6, 7):
        days = p.index[p["dist_count"] >= n]
        rest = p.index[p["dist_count"] < n]
        rb = ev[ev["date"].isin(days)]["ret_o5"].dropna()
        rr = ev[ev["date"].isin(rest)]["ret_o5"].dropna()
        say(f"    N={n}: bear days={len(days):<5} ev={len(rb):<6} "
            f"med {rb.median():+5.2f}% | rest med {rr.median():+5.2f}%")

    say("\n  divergence breadth-drop > D pts (bearish, index near 60d high):")
    for d in (3, 4, 5, 6, 8):
        cond = (p["diverg_ic"] > 0) & p["diverg_athi"] & (p["diverg_bd"] < -d)
        days = p.index[cond.fillna(False)]
        rb = ev[ev["date"].isin(days)]["ret_o5"].dropna()
        say(f"    D={d}: days={len(days):<5} ev={len(rb):<6} med "
            f"{rb.median():+5.2f}%" if len(rb) >= 30 else
            f"    D={d}: days={len(days):<5} ev={len(rb):<6} (too few)")


def weight_grid(p: pd.DataFrame, ev: pd.DataFrame) -> None:
    say("\n[4] Integer-weight grid {0,1,2}^9 — walk-forward, tertile cuts from")
    say("    the TRAIN era only; ranked by the worse of the two validation spreads")

    Z = p[SIGNALS].to_numpy(dtype=float)                     # days x 9
    ev = ev.dropna(subset=["ret_o5"])
    day_pos = pd.Series(range(len(p)), index=p.index)
    epos = day_pos.reindex(ev["date"]).to_numpy()
    keep = ~np.isnan(epos)
    epos = epos[keep].astype(int)
    ret = ev["ret_o5"].to_numpy()[keep]
    era_a = (p["era"] == "2015-2020").to_numpy()
    ev_a = era_a[epos]

    def spread(w, train_mask, ev_train_mask):
        s_days = Z @ w
        lo, hi = np.percentile(s_days[train_mask], [33.34, 66.67])
        if lo == hi:
            return None
        s_ev = s_days[epos]
        vmask = ~ev_train_mask
        top = ret[vmask & (s_ev >= hi)]
        bot = ret[vmask & (s_ev <= lo)]
        if len(top) < 200 or len(bot) < 200:
            return None
        return np.median(top) - np.median(bot)

    rows = []
    for w in product((0, 1, 2), repeat=len(SIGNALS)):
        if sum(w) == 0:
            continue
        wa = np.array(w, dtype=float)
        s1 = spread(wa, era_a, ev_a)          # fit A -> validate B
        s2 = spread(wa, ~era_a, ~ev_a)        # fit B -> validate A
        if s1 is None or s2 is None:
            continue
        rows.append((w, round(s1, 3), round(s2, 3), round(min(s1, s2), 3)))

    res = pd.DataFrame(rows, columns=["weights", "spread_AtoB", "spread_BtoA", "worst"])
    res = res.sort_values("worst", ascending=False)
    base = res[res["weights"] == BASELINE_W]

    say(f"\n  combos evaluated: {len(res)}   signal order: {SIGNALS}")
    say(f"  BASELINE {BASELINE_W}: "
        + (f"A->B {base['spread_AtoB'].iloc[0]:+.2f}  B->A {base['spread_BtoA'].iloc[0]:+.2f}  "
           f"worst {base['worst'].iloc[0]:+.2f}  (rank {base.index[0] + 1} of {len(res)})"
           if len(base) else "not evaluable"))
    say("\n  Top 10 by worst-case validation spread (D+5 median, top vs bottom tertile):")
    for _, r in res.head(10).iterrows():
        say(f"    {r['weights']}  A->B {r['spread_AtoB']:+.2f}  "
            f"B->A {r['spread_BtoA']:+.2f}  worst {r['worst']:+.2f}")


def main():
    m = common.load_cache()
    say(f"Cache: {m['close'].shape[1]} symbols, "
        f"{m['close'].index.min().date()} -> {m['close'].index.max().date()}")

    p = build_panel(m)
    ev = find_events(m)
    ev = ev.drop(columns=["date_idx", "sym_idx"])
    med_b = median_stock_fwd(m)
    say(f"Panel: {len(p)} days | burst events: {len(ev)}")

    per_signal_audit(p, ev, med_b)
    within_score(p, ev, med_b)
    sweeps(p, ev)
    weight_grid(p, ev)
    say(f"\n{common.CAVEATS}")
    say("  - Effective sample = regime EPISODES (dozens), not days; treat small")
    say("    spread differences between weight vectors as ties.")
    say("  - Signals known at D0 close; entries at D+1 open (prev-close rule).")

    os.makedirs(common.OUTPUT_DIR, exist_ok=True)
    ev_out = ev.merge(p[SIGNALS + ["score5", "era"]], left_on="date", right_index=True)
    ev_out.to_csv(os.path.join(common.OUTPUT_DIR, "regime_calibration_events.csv"),
                  index=False)
    with open(os.path.join(common.OUTPUT_DIR, "regime_calibration_study.md"), "w") as f:
        f.write("\n".join(_report) + "\n")
    say(f"\nEvent log + study md -> {os.path.abspath(common.OUTPUT_DIR)}")


if __name__ == "__main__":
    main()
