"""
s7_verdict.py — S7 incubation verdict: read the forward record nightly.

Factory stage S7 (research/FACTORY.md) is where paper signals accrue the one
thing backtests can never produce again: a forward record on live scan code.
The grader (grade_decisions.py, step 8) rebuilds forward_returns.parquet every
night; this module (step 9) turns that parquet into a verdict a human — or the
brief agent — can act on in seconds, instead of waiting for someone to notice.

What it answers (and what it deliberately does not):
  1. Which scans show a realizable edge so far, on the D+1-open basis
     (ret_o*, what a manual executor could actually capture) and the signal
     basis (ret_c*). Market-relative edge subtracts the same-date _MARKET_
     universe-median row — the post-audit house rule: never judge a long
     against zero, judge it against the same-day market.
  2. Is any scan decaying? Split-half chronological check (early vs recent
     median). Two-sided: a scan that was negative and turned positive matters
     as much as the reverse. This is the edge-death tripwire from the ROADMAP,
     parked-by-design until this record had data.
  3. Do the regime tiers separate the tape? The _MARKET_ rows graded per date
     answer "does DEFENSIVE actually coincide with weak forward returns" — the
     first NSE read on the tier map, pending the full regime-conditioned
     backtest (ROADMAP item 5).

It does NOT compare against backtest expectations yet: no machine-readable
expected-R per scan exists until the regime-conditioned scan backtests land.
When they do, this module grows an expected-vs-realized column; the record
accrues either way.

Multiplicity honesty: a dozen scans x two horizons means some flags appear by
chance. Flags here are WATCH state for the human judgment layer, never kills —
a kill stays a factory decision (LEDGER), not a nightly report's.

Run standalone:
    python src/s7_verdict.py
Outputs:
    output/grader/s7_verdict.md    (human)
    output/grader/s7_verdict.json  (machine — the brief agent reads this)
"""

import json
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(__file__))

ROOT = os.path.join(os.path.dirname(__file__), "..")
OUT_DIR = os.path.join(ROOT, "output", "grader")
IN_PATH = os.path.join(OUT_DIR, "forward_returns.parquet")
MD_PATH = os.path.join(OUT_DIR, "s7_verdict.md")
JSON_PATH = os.path.join(OUT_DIR, "s7_verdict.json")

MARKET_SYMBOL = "_MARKET_"
BOOT_N = 2000        # bootstrap resamples for the median CI
BOOT_SEED = 7        # fixed seed — the report must be reproducible byte-wise
MIN_N = 20           # below this: ACCRUING, read nothing into the medians
MIN_N_20D = 30       # the 20d horizon fills in slower; demand a bit more
# Scans whose verdicts matter most for the human's daily read — the six live
# Stockbee scans the state file carries every night.
PRIMARY_SCANS = ["anticipation", "ti65", "four_pct", "reversal_bullish",
                 "four_pct_down", "dep", "ep_checklist", "weak_structure",
                 "breakout_setup", "ep9m", "episodic_pivot", "ga_short_pocket"]


def _boot_median_ci(vals: np.ndarray, n_boot: int = BOOT_N,
                    seed: int = BOOT_SEED) -> tuple:
    """Percentile bootstrap CI on the median. Fixed seed -> deterministic."""
    if len(vals) < 5:
        return (None, None)
    rng = np.random.default_rng(seed)
    meds = np.median(rng.choice(vals, size=(n_boot, len(vals)), replace=True),
                     axis=1)
    return (float(np.percentile(meds, 2.5)), float(np.percentile(meds, 97.5)))


def _verdict_line(n: int, med: float, lo: float, hi: float,
                  early: float, recent: float) -> str:
    """One of four states, gated hard on sample size (the early-median trap
    the ROADMAP warns about — 'read nothing into the early medians')."""
    if n < MIN_N:
        return "ACCRUING"
    if early is not None and early > 0 and recent < 0:
        return "DECAY-WATCH"
    if med < 0 and hi < 0:
        return "NEGATIVE"
    if med > 0 and lo > 0:
        return "POSITIVE"
    return "TRACKING"


def _scan_table(df: pd.DataFrame, market_rel: pd.DataFrame) -> list:
    """Per-(source, scan) realized record on both bases + split-half decay."""
    rows = []
    for (source, scan), grp in df.groupby(["source", "scan"], dropna=False):
        scan_name = scan if isinstance(scan, str) else "-"
        row = {"source": source, "scan": scan_name, "n": int(len(grp)),
               "dates": int(grp["date"].nunique())}

        o5 = grp["ret_o5_pct"].dropna().to_numpy()
        c5 = grp["ret_c5_pct"].dropna().to_numpy()
        c20 = grp["ret_c20_pct"].dropna().to_numpy()
        row["o5"] = _stat_block(o5)
        row["c5"] = _stat_block(c5)
        row["c20"] = _stat_block(c20, min_n=MIN_N_20D)

        # Same-date market-relative edge (close basis): candidate median minus
        # the universe-median row for the same dates. The beta control.
        if not market_rel.empty:
            m = grp.merge(market_rel, on="date", how="inner")
            for n_ in (5, 20):
                col, mcol = f"ret_c{n_}_pct", f"mkt_c{n_}_pct"
                rel = (m[col] - m[mcol]).dropna()
                row[f"rel_c{n_}"] = _stat_block(rel.to_numpy(),
                                                min_n=MIN_N_20D if n_ == 20 else MIN_N)

        # Chronological split-half on the realizable 5d basis: the tripwire.
        oo = grp[["date", "ret_o5_pct"]].dropna().sort_values("date")
        if len(oo) >= MIN_N:
            half = len(oo) // 2
            early_v = oo["ret_o5_pct"].iloc[:half].to_numpy()
            recent_v = oo["ret_o5_pct"].iloc[half:].to_numpy()
            row["o5_early"] = round(float(np.median(early_v)), 2)
            row["o5_recent"] = round(float(np.median(recent_v)), 2)
            row["verdict"] = _verdict_line(row["o5"]["n"], row["o5"]["median"],
                                           row["o5"]["lo"], row["o5"]["hi"],
                                           row["o5_early"], row["o5_recent"])
        else:
            row["verdict"] = "ACCRUING"
        rows.append(row)
    rows.sort(key=lambda r: (r["source"], -(r["o5"]["n"] if r["o5"] else 0)))
    return rows


def _stat_block(vals: np.ndarray, min_n: int = MIN_N) -> dict:
    if len(vals) == 0:
        return {"n": 0}
    lo, hi = _boot_median_ci(vals)
    return {"n": int(len(vals)), "median": round(float(np.median(vals)), 2),
            "mean": round(float(np.mean(vals)), 2),
            "win_pct": round(float((vals > 0).mean() * 100), 1),
            "lo": None if lo is None else round(lo, 2),
            "hi": None if hi is None else round(hi, 2),
            "ci_ok": len(vals) >= min_n}


def _tier_table(market: pd.DataFrame) -> list:
    """_MARKET_ rows by regime tier: does the tier map separate the tape?"""
    out = []
    for tier, grp in market.groupby("regime_tier", dropna=False):
        block = {"tier": tier if isinstance(tier, str) else "(none)",
                 "n_days": int(grp["date"].nunique())}
        for n_ in (5, 20):
            v = grp[f"ret_c{n_}_pct"].dropna().to_numpy()
            if len(v):
                block[f"c{n_}_med"] = round(float(np.median(v)), 2)
                block[f"c{n_}_p20"] = round(float(np.percentile(v, 20)), 2)
        out.append(block)
    # CALM/ELEVATED = HMM risk regime (2026-09-28+); the rest = retired breadth tiers in older rows
    order = {"CALM": 0, "ELEVATED": 1, "AGGRESSIVE": 2, "NORMAL": 3, "CAUTIOUS": 4, "DEFENSIVE": 5}
    out.sort(key=lambda b: order.get(b["tier"], 9))
    return out


def _fmt_stat(b: dict, unit: str = "%") -> str:
    if not b or b.get("n", 0) == 0:
        return "—"
    s = f"{b['median']:+.2f}{unit} (n={b['n']}, win {b['win_pct']:.0f}%)"
    if b.get("ci_ok") and b.get("lo") is not None:
        s += f" CI[{b['lo']:+.2f},{b['hi']:+.2f}]"
    return s


def _markdown(rows: list, tiers: list, note_days: tuple) -> str:
    as_of, n_dates = note_days
    lines = [
        "# S7 verdict — forward record read-out",
        "",
        f"As of `{as_of}` · {n_dates} decision dates · primary basis "
        "**D+1 open → close** (realizable) · market-relative edge is "
        "close-basis vs the same-date universe median.",
        "",
        "Verdicts: POSITIVE/NEGATIVE need the bootstrap CI to exclude zero —",
        "otherwise TRACKING. ACCRUING = n below the floor, read nothing into",
        "the medians. DECAY-WATCH = early half positive, recent half negative.",
        "These are watch states for the human layer, not kills.",
        "",
        "## Scans & incubation candidates (5d realizable basis)",
        "",
        "| source/scan | n | o5 median | o5 early→recent | rel_c5 | c20 | verdict |",
        "|---|---|---|---|---|---|---|",
    ]
    for r in rows:
        label = r["scan"] if r["scan"] != "-" else r["source"]
        early = (f"{r['o5_early']:+.2f}→{r['o5_recent']:+.2f}"
                 if "o5_early" in r else "—")
        lines.append(
            f"| {r['source']}/{label} | {r['n']} "
            f"| {_fmt_stat(r['o5'])} | {early} "
            f"| {_fmt_stat(r.get('rel_c5', {}))} "
            f"| {_fmt_stat(r['c20'])} | **{r['verdict']}** |")
    lines += [
        "",
        "## Regime tiers vs the tape (_MARKET_ rows, close basis)",
        "",
        "| tier | days | fwd-5d med | fwd-20d med | fwd-20d p20 |",
        "|---|---|---|---|---|",
    ]
    for t in tiers:
        lines.append(
            f"| {t['tier']} | {t['n_days']} "
            f"| {t.get('c5_med', '—')} | {t.get('c20_med', '—')} "
            f"| {t.get('c20_p20', '—')} |")
    lines += [
        "",
        "## Known limits of this record",
        "",
        "- Record started 2026-06-01; horizons fill in as days elapse.",
        "- No expected-vs-realized column yet — waits on the "
        "regime-conditioned scan backtests (ROADMAP item 5).",
        "- With ~12 scans x 2 horizons, expect chance flags; kills stay a "
        "LEDGER decision.",
        "",
    ]
    return "\n".join(lines)


def run():
    if not os.path.exists(IN_PATH):
        print("  s7_verdict: no forward_returns.parquet yet — grader runs first.")
        return
    df = pd.read_parquet(IN_PATH)
    df["date"] = pd.to_datetime(df["date"])
    market = df[df["symbol"] == MARKET_SYMBOL]
    graded = df[df["symbol"] != MARKET_SYMBOL]
    if graded.empty:
        print("  s7_verdict: no graded candidates yet.")
        return

    # Universe-median close->close per date, for the market-relative edge.
    market_rel = market[["date"] + [f"ret_c{n}_pct" for n in (5, 20)]].rename(
        columns={f"ret_c{n}_pct": f"mkt_c{n}_pct" for n in (5, 20)})
    market_rel = market_rel.groupby("date", as_index=False).median()

    rows = _scan_table(graded, market_rel)
    tiers = _tier_table(market)
    as_of = str(df["date"].max().date())
    n_dates = int(df["date"].nunique())

    md = _markdown(rows, tiers, (as_of, n_dates))
    with open(MD_PATH, "w") as f:
        f.write(md)
    with open(JSON_PATH, "w") as f:
        json.dump({"as_of": as_of, "n_dates": n_dates, "scans": rows,
                   "tiers": tiers}, f, indent=1, default=str)

    n_watch = sum(1 for r in rows if r["verdict"] in ("DECAY-WATCH", "NEGATIVE"))
    print(f"  s7_verdict: {len(rows)} tracks, {n_watch} watch flags "
          f"-> {os.path.relpath(MD_PATH, ROOT)}")
    for r in rows:
        if r["verdict"] in ("POSITIVE", "NEGATIVE", "DECAY-WATCH"):
            print(f"    {r['verdict']:12s} {r['source']}/{r['scan']} "
                  f"o5 med {r['o5'].get('median', '—')}")


if __name__ == "__main__":
    run()
