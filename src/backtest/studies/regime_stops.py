"""
regime_stops.py — Stage 2 of regime calibration: judge every regime signal on
STOP-BASED trade outcomes, across two cohorts, and mine per-signal insights.

Stage 1 (regime_calibration.py) used raw D+5 returns and found breadth zones
anti-predictive per-event. But the live process trades with stops — a signal
can fail to move the average yet strongly predict stop-outs or tail losses.
This study measures that, and reports what each signal is actually good FOR.

Cohorts:
  burst  stockbee_4pct_burst events, entry D+1 open, stop = signal-bar low
         (capped 6% under entry), gap-through fills at open, time exit D+5.
         Outcomes in R (risk units). Covers anticipation-style entries by
         construction (events require a tight 5-day base first).
  ep     EP9M volume-spike event log (output/studies/ep_volume_spike_v3_g5_t10.csv)
         with its own stop simulation (stopped_ret / stopped_out / stop_pct),
         converted to R = stopped_ret / stop_pct.

Output: output/studies/regime_stops_study.md (report-template format),
charts/ PNGs, regime_stops_report.pdf (chart + caption per page), events CSV.

Usage:
    ~/anaconda3/bin/python src/backtest/studies/regime_stops.py
"""

import os
import sys

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

sys.path.insert(0, os.path.dirname(__file__))

import common
from regime_calibration import build_panel, SIGNALS
from stockbee_4pct_burst import find_events

EP_CSV = os.path.join(common.OUTPUT_DIR, "ep_volume_spike_v3_g5_t10.csv")
CHART_DIR = os.path.join(common.OUTPUT_DIR, "regime_stops_charts")
ZONE_NAME = {1: "bullish", 0: "neutral", -1: "bearish"}
MIN_N = 200          # per zone x era cell to be judged at all


def simulate_burst(events: pd.DataFrame, m: dict, hold_max: int = 5) -> pd.DataFrame:
    """stockbee_4pct_burst.simulate_exits, re-run locally so each trade keeps
    its date (needed to join the signal panel; the original returns only R)."""
    O, H, L, C = (m[k].values for k in ("open", "high", "low", "close"))
    n_dates = O.shape[0]
    rows = []
    for ev in events.itertuples():
        d0, s = ev.date_idx, ev.sym_idx
        if d0 + 1 >= n_dates:
            continue
        entry = O[d0 + 1, s]
        if np.isnan(entry):
            continue
        stop = max(ev.signal_low, entry * 0.94)
        risk = entry - stop
        if risk <= 0:
            continue
        exit_price, hold, stopped = np.nan, np.nan, False
        for d in range(1, hold_max + 1):
            if d0 + d >= n_dates or np.isnan(C[d0 + d, s]):
                break
            if L[d0 + d, s] <= stop:
                exit_price = min(O[d0 + d, s], stop)   # gap-through fills at open
                hold, stopped = d, True
                break
            if d == hold_max:
                exit_price, hold = C[d0 + d, s], d
        if np.isnan(exit_price):
            continue
        rows.append((ev.date, (exit_price - entry) / risk, hold, stopped))
    return pd.DataFrame(rows, columns=["date", "r", "hold", "stopped"])


def load_ep() -> pd.DataFrame:
    """EP9M event log -> (date, r, stopped). R = stopped_ret / stop_pct."""
    df = pd.read_csv(EP_CSV, parse_dates=["date"])
    df = df.dropna(subset=["stopped_ret", "stop_pct"])
    df = df[df["stop_pct"] > 0]
    out = pd.DataFrame({
        "date": df["date"].dt.tz_localize("Asia/Kolkata"),
        "r": df["stopped_ret"] / df["stop_pct"],
        "stopped": df["stopped_out"].astype(bool),
    })
    return out


def attach_zones(trades: pd.DataFrame, panel: pd.DataFrame) -> pd.DataFrame:
    cols = SIGNALS + ["score5", "era"]
    return trades.merge(panel[cols], left_on="date", right_index=True, how="inner")


def cell_stats(g: pd.DataFrame) -> dict:
    r = g["r"]
    pos, neg = r[r > 0].sum(), r[r < 0].sum()
    return {
        "n": len(g),
        "win": (r > 0).mean() * 100,
        "avg_r": r.mean(),
        "med_r": r.median(),
        "stopout": g["stopped"].mean() * 100,
        "bigwin": (r >= 2).mean() * 100,       # >= +2R
        "bigloss": (r <= -1.2).mean() * 100,   # gap-through beyond -1R
        "pf": pos / -neg if neg < 0 else np.inf,
    }


def zone_table(tr: pd.DataFrame, sig: str) -> pd.DataFrame:
    rows = []
    for era, ge in tr.groupby("era"):
        base = cell_stats(ge)
        rows.append({"era": era, "zone": "ALL", **base})
        for z, gz in ge.groupby(sig):
            if len(gz) >= MIN_N:
                rows.append({"era": era, "zone": ZONE_NAME[int(z)], **cell_stats(gz)})
    return pd.DataFrame(rows)


METRICS = [("win", "win rate", "pts", 3.0), ("avg_r", "expectancy (avg R)", "R", 0.08),
           ("stopout", "stop-out rate", "pts", 4.0),
           ("bigwin", ">= +2R big-win rate", "pts", 2.0),
           ("bigloss", "gap-through big-loss rate", "pts", 1.5)]


def mine_insights(tr: pd.DataFrame, cohort: str) -> list:
    """Emit an insight only when a zone moves a metric the SAME direction in
    BOTH eras by at least the metric's threshold (the user's consistency bar)."""
    out = []
    eras = sorted(tr["era"].unique())
    if len(eras) < 2:
        return out
    for sig in SIGNALS:
        t = zone_table(tr, sig)
        for zone in ("bullish", "bearish"):
            deltas = {}
            for era in eras:
                base = t[(t["era"] == era) & (t["zone"] == "ALL")]
                cell = t[(t["era"] == era) & (t["zone"] == zone)]
                if len(cell) == 0:
                    deltas = None
                    break
                deltas[era] = {k: cell.iloc[0][k] - base.iloc[0][k]
                               for k, *_ in METRICS}
            if not deltas:
                continue
            for key, label, unit, thr in METRICS:
                d1, d2 = deltas[eras[0]][key], deltas[eras[1]][key]
                if abs(d1) >= thr and abs(d2) >= thr and np.sign(d1) == np.sign(d2):
                    direction = "raises" if d1 > 0 else "lowers"
                    out.append(f"[{cohort}] **{sig} {zone}** consistently "
                               f"{direction} {label} ({d1:+.2f} / {d2:+.2f} "
                               f"{unit} vs cohort baseline in {eras[0]} / {eras[1]}).")
    return out


def fmt_table(t: pd.DataFrame) -> str:
    hdr = "| era | zone | n | win % | avg R | med R | stop-out % | >=+2R % | <=-1.2R % | PF |"
    sep = "|---|---|---|---|---|---|---|---|---|---|"
    lines = [hdr, sep]
    for _, r in t.iterrows():
        lines.append(f"| {r['era']} | {r['zone']} | {r['n']:,} | {r['win']:.1f} "
                     f"| {r['avg_r']:+.2f} | {r['med_r']:+.2f} | {r['stopout']:.1f} "
                     f"| {r['bigwin']:.1f} | {r['bigloss']:.1f} | {r['pf']:.2f} |")
    return "\n".join(lines)


def chart_zone_metric(tr, sigs, metric, title, fname, caption):
    fig, axes = plt.subplots(1, len(sigs), figsize=(3.2 * len(sigs), 3.4),
                             sharey=True)
    for ax, sig in zip(np.atleast_1d(axes), sigs):
        t = zone_table(tr, sig)
        piv = t[t["zone"] != "ALL"].pivot(index="zone", columns="era", values=metric)
        piv = piv.reindex(["bullish", "neutral", "bearish"]).dropna(how="all")
        piv.plot.bar(ax=ax, legend=(sig == sigs[0]), color=["#4c8dff", "#e0a030"])
        base = t[t["zone"] == "ALL"].set_index("era")[metric].mean()
        ax.axhline(base, color="grey", lw=1, ls="--")
        ax.set_title(sig, fontsize=10)
        ax.set_xlabel("")
        ax.tick_params(axis="x", rotation=30, labelsize=8)
    fig.suptitle(title, fontsize=12)
    fig.tight_layout()
    path = os.path.join(CHART_DIR, fname)
    fig.savefig(path, dpi=130)
    plt.close(fig)
    return path, caption


def build_pdf(md_path: str, charts: list, pdf_path: str) -> None:
    """Delegates to pdf_human: the PDF is the human artifact (styled headings,
    real ruled tables, inline charts); the markdown stays the machine one."""
    from pdf_human import build_pdf as _human
    _human(md_path, charts, pdf_path)


def main():
    os.makedirs(CHART_DIR, exist_ok=True)
    m = common.load_cache()
    panel = build_panel(m)

    print("Simulating burst cohort with stops...")
    burst_ev = find_events(m)
    burst = attach_zones(simulate_burst(burst_ev, m), panel)
    print(f"  {len(burst)} burst trades")
    print("Loading EP9M cohort...")
    ep = attach_zones(load_ep(), panel)
    print(f"  {len(ep)} EP trades")

    insights = mine_insights(burst, "burst") + mine_insights(ep, "EP")

    charts = []
    key_sigs = ["pct40ma", "idx_trend", "dist_days", "ftd"]
    charts.append(chart_zone_metric(
        burst, key_sigs, "stopout", "Burst cohort — stop-out rate by zone (%)",
        "burst_stopout.png",
        "How often the trade hit its stop, by what each signal said the evening "
        "before. Grey dashed line = cohort baseline. If a signal's bearish zone "
        "bar is clearly above baseline in BOTH eras, that signal predicts "
        "stop-outs even if it can't predict average returns."))
    charts.append(chart_zone_metric(
        burst, key_sigs, "avg_r", "Burst cohort — expectancy (avg R) by zone",
        "burst_avgr.png",
        "Average result in risk units (R): +1R means you made what you risked. "
        "With stop = signal-bar low capped 6%, time exit D+5. Above the grey "
        "baseline = the zone improved risk-adjusted outcomes."))
    charts.append(chart_zone_metric(
        ep, key_sigs, "avg_r", "EP9M cohort — expectancy (avg R) by zone",
        "ep_avgr.png",
        "Same expectancy read for the catalyst-driven EP9M cohort (volume-spike "
        "events with that study's own stop rule). EPs are supposed to be less "
        "regime-dependent — if these bars sit closer to their baseline than the "
        "burst chart's, that folklore is confirmed in your data."))
    charts.append(chart_zone_metric(
        burst, ["ftd"], "bigwin", "Burst cohort — big-win (>= +2R) rate, FTD",
        "ftd_bigwin.png",
        "Share of trades that returned at least twice the risk, on follow-through "
        "days vs normal days. FTD was the only stage-1 pass; this chart shows "
        "whether its edge survives stops and shows up in the right tail."))

    # ---- report ----------------------------------------------------------
    L = []
    a = L.append
    a("# Backtest Report: Regime Signals vs Stop-Based Trade Outcomes (NSE)")
    a("")
    a("**Study ID:** REGIME-STOPS-v1 (stage 2 of regime calibration)")
    a(f"**Report date:** {pd.Timestamp.now(tz='Asia/Kolkata').date()}")
    a("**Engine:** vectorized event study + per-trade stop loop (daily bars)")
    a("**Status:** Research — informs regime design, no live capital decision")
    a("")
    a("---")
    a("")
    a("## 1. Hypothesis and rationale")
    a("")
    a("Stage 1 showed regime zones cannot predict a breakout's raw D+5 return")
    a("(bullish tapes even ran slightly worse — crowding + gap-at-open + 5-day")
    a("mean reversion). But the live process trades with stops. A market filter")
    a("can still earn its keep by predicting the SHAPE of outcomes: how often")
    a("you get stopped, how bad the gap-through losses are, how fat the right")
    a("tail is. This study asks, per signal: what is it actually good for?")
    a("")
    a("## 2. Universe, data and cohorts")
    a("")
    a("| Item | Detail |")
    a("|---|---|")
    a(f"| Universe | full NSE EQ history cache, {m['close'].shape[1]} symbols |")
    a(f"| Period | {m['close'].index.min().date()} to {m['close'].index.max().date()} |")
    a("| Era split | A: 2015-2020, B: 2021-2026 (insights must hold in BOTH) |")
    a(f"| Burst cohort | {len(burst):,} trades (4% burst out of tight 5-day base) |")
    a(f"| EP cohort | {len(ep):,} trades (EP9M volume-spike log, its own stops) |")
    a("| Signals | 9 zones, all computed from data <= signal-day close |")
    a("| Entry timing | burst: D+1 open. Signals known at D0 close (prev-close rule) |")
    a("")
    a("Anticipation entries are covered by the burst cohort by construction")
    a("(every event requires a <=8% 5-day range first). DEP / overnight-news")
    a("cohorts exist in separate studies and are not re-tested here.")
    a("")
    a("## 3. Trade rules (burst cohort)")
    a("")
    a("- Entry: D+1 open after the burst signal.")
    a("- Stop: signal-bar low, capped 6% below entry; a gap through the stop")
    a("  fills at that day's open (honest slippage on gaps).")
    a("- Exit: stop, else D+5 close. Outcomes in R (result / risk).")
    a("")
    a("## 4. Costs")
    a("")
    a("No brokerage/STT/impact modelled — this is a relative study (zone vs")
    a("zone within the same cohort), so per-trade frictions cancel in the")
    a("comparison. Absolute R numbers would be ~0.05-0.1R worse live.")
    a("")
    a("## 5. Headline result")
    a("")
    for name, tr in (("Burst", burst), ("EP9M", ep)):
        base = cell_stats(tr)
        a(f"**{name} cohort, all trades:** n={base['n']:,}, win {base['win']:.1f}%, "
          f"avg {base['avg_r']:+.2f}R, stop-out {base['stopout']:.1f}%, "
          f">=+2R {base['bigwin']:.1f}%, PF {base['pf']:.2f}")
        a("")
    a("## 6. Per-signal tables")
    a("")
    for name, tr in (("Burst", burst), ("EP9M", ep)):
        a(f"### {name} cohort")
        a("")
        for sig in SIGNALS:
            a(f"**{sig}**")
            a("")
            a(fmt_table(zone_table(tr, sig)))
            a("")
    a("## 7. Insights (auto-mined, consistent in BOTH eras only)")
    a("")
    if insights:
        for i in insights:
            a(f"- {i}")
    else:
        a("- No zone moved any metric consistently in both eras.")
    a("")
    a("## 8. Limitations")
    a("")
    a("- Effective sample = regime episodes (dozens), not trades; overlapping")
    a("  windows; no historical ASM/GSM; EP cohort inherits its study's entry")
    a("  convention; costs excluded (relative study).")
    a("- Daily bars: intraday stop touch sequencing approximated (stop wins on")
    a("  ambiguity — conservative).")
    a("")
    a("## 9. Conclusion")
    a("")
    a("See the insights list — each line is a validated, era-stable claim about")
    a("what a signal is good for. Everything else failed the consistency bar.")

    md_path = os.path.join(common.OUTPUT_DIR, "regime_stops_study.md")
    with open(md_path, "w") as f:
        f.write("\n".join(L) + "\n")
    burst.to_csv(os.path.join(common.OUTPUT_DIR, "regime_stops_burst_trades.csv"),
                 index=False)
    pdf_path = os.path.join(common.OUTPUT_DIR, "regime_stops_report.pdf")
    build_pdf(md_path, charts, pdf_path)
    print(f"\nReport -> {md_path}\nPDF    -> {pdf_path}")
    print(f"\n{len(insights)} era-stable insights:")
    for i in insights:
        print(f"  - {i}")


if __name__ == "__main__":
    main()
