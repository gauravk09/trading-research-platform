"""
report_full.py — Generate a full house-template backtest report for one
event-study log (per-trade R stats, NOT a portfolio backtest).

Adapts docs/backtest_report_example.md honestly for event studies: no
Sharpe/CAGR/equity drawdown. Instead: per-trade R stats, cumulative-R curve
(sum of per-trade R by signal date — not a portfolio equity curve), monthly/
annual aggregate R grid, and max drawdown measured on the cumulative-R curve.

Entry variants (close-entry studies 2026-07-25): D+1 open, D0 close, and
D0 close gated on range_pos >= 0.75. Holds D+5 and D+20. Stop = signal-day
low capped 6% under entry, gap-through fills at open (close_entry_rescore).

Eras: 2015-2019, 2020-2022 (COVID, shown as its own segment), 2023-2026.
A finding is era-stable only if 2015-19 and 2023-26 agree.

Usage:
    ~/anaconda3/bin/python src/backtest/studies/report_full.py <slug> [<slug> ...]
"""

import os
import sys
import time

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

sys.path.insert(0, os.path.dirname(__file__))

import common
from close_entry_rescore import simulate
from regime_stops import build_pdf

STUDIES = {
    # keys: title, rules_file, csv (default <slug>_events.csv),
    #       variants (default VARIANTS), note (extra conclusion sentence)
    "stockbee_4pct_burst": {
        "title": "Stockbee 4% Momentum Burst",
        "rules_file": "stockbee_4pct_burst.py",
    },
    "ryan_52wk_high": {
        "title": "David Ryan 52-Week-High Base Breakout",
        "rules_file": "ryan_52wk_high.py",
    },
    "minervini_trend_template": {
        "title": "Minervini Trend Template + VCP Breakout",
        "rules_file": "minervini_trend_template.py",
        "note": "Only ~176 events over the full period — far too small a sample "
                "for standalone conclusions; treat every number in this report "
                "as descriptive, not evidence.",
    },
    "weinstein_stage2": {
        "title": "Weinstein Stage 2 Breakout",
        "rules_file": "weinstein_stage2.py",
        "note": "Only 48 events over the full period — far too small a sample "
                "for standalone conclusions; treat every number in this report "
                "as descriptive, not evidence.",
    },
    "darvas_box": {
        "title": "Darvas Box Breakout",
        "rules_file": "darvas_box.py",
    },
    "donchian_turtle": {
        "title": "Turtle 20-Day Donchian Breakout",
        "rules_file": "donchian_turtle.py",
    },
    "pocket_pivot": {
        "title": "Pocket Pivot (Morales/Kacher)",
        "rules_file": "pocket_pivot.py",
    },
    "kell_ema_crossback": {
        "title": "Oliver Kell EMA Crossback",
        "rules_file": "kell_ema_crossback.py",
    },
    "high_tight_flag": {
        "title": "High Tight Flag",
        "rules_file": "high_tight_flag.py",
        "note": "The 961 events here come from this study's find_events, a "
                "looser definition than the 196-event strict variant cited in "
                "older summaries; results describe the looser cohort.",
    },
    "connors_rsi2": {
        "title": "Connors RSI-2 Mean Reversion",
        "rules_file": "connors_rsi2.py",
        "note": "Dip-buy cohort: the D0 close entry is expected to hurt here — "
                "the overnight gap works FOR dip buyers (a better price at the "
                "D+1 open), the opposite of the breakout cohorts "
                "(close_entry_rescore, 2026-07-25).",
    },
    "washout_reversal": {
        "title": "3-Day Washout Reversal (Dip Buy)",
        "rules_file": "washout_reversal.py",
        "variants": ["D+1 open"],
        "headline": ("D+1 open", 5),
        "exit_text":
            "**Exit model for this report:** stop = signal-day low capped 6% under\n"
            "entry, gap-through fills at open, suspension-tolerant (NaN bar = hold);\n"
            "time exit at D+5 or D+20 close. **Entry is D+1 open only.** The D0-close\n"
            "variants used for the breakout cohorts are omitted by design: the signal\n"
            "bar is a 3rd consecutive down close, so it closes at or near its own low.\n"
            "A D0-close entry with stop = signal-day low would have a near-zero risk\n"
            "denominator (absurd R multiples), and the range_pos >= 0.75 gate selects\n"
            "almost nothing on a down bar.",
        "note": "Dip-buy cohort. Prior habitat work (washout_reversal study, house "
                "memory): 3-down-day dip buys show no edge in good markets; the "
                "bounce edge concentrates in bad markets / leader washouts. This "
                "report is the all-events aggregate — read Section 9 with that in "
                "mind.",
    },
    "ep_volume_spike": {
        "title": "EP9M Volume-Spike Episodic Pivot",
        "csv": "ep_volume_spike_v3_g5_t10.csv",
        "r_source": "columns",
        "variants": ["Recorded entry/stop"],
        "holds": ["own"],
        "headline": ("Recorded entry/stop", "own"),
        "engine": "R taken from the event log's own recorded stop simulation "
                  "(stopped_ret / stop_pct); no re-simulation",
        "tradeable": "day-0 gain >= 5%, volume >= 3x average, turnover >= Rs 10 cr "
                     "(observed floors in the event log; filename v3_g5_t10)",
        "rules_text":
            "EP9M volume-spike episodic pivot (Bonde's EP conveyor belt, NSE\n"
            "adaptation): unusual volume is the footprint of institutions. The event\n"
            "log records days where a stock gained >= 5% on >= 3x average volume with\n"
            ">= Rs 10 cr turnover — a volume-spike repricing candidate.\n"
            "\n"
            "PROVENANCE: the producing script (ep_volume_spike.py) is no longer in\n"
            "the repo; the events were written by an earlier study. Rules here are\n"
            "reconstructed from the CSV column semantics plus the EP9M description\n"
            "in strategies/stockbee/ep_family.py (top-2%-of-market volume for a stock\n"
            "not usually there, price/turnover floors, catalyst joined as research).\n"
            "\n"
            "Recorded columns: entry (price), stop_pct (stop distance, % of entry),\n"
            "stopped_ret (% return at stop hit or at exit), stopped_out, exit_day\n"
            "(1..61 sessions), plus ret_5d/20d/60d, day0_gain_pct, vol_ratio,\n"
            "turnover_cr, adr_pct, hv180.",
        "exit_text":
            "**Exit model for this report:** there is only ONE variant — the study's\n"
            "own entry/stop convention as recorded in the event log. R = stopped_ret\n"
            "/ stop_pct (rows with stop_pct <= 0 or no recorded outcome dropped);\n"
            "stopped-out trades land at -1R, survivors exit at the recorded exit_day\n"
            "(up to ~60 sessions). The D+1-open / D0-close variant grid does not\n"
            "apply: the outcomes were simulated by the original study, not by this\n"
            "report's engine.",
    },
    "overnight_news": {
        "title": "Overnight News (After-Close Filing Score)",
        "csv": "overnight_news_events_pos.csv",
        "rules_file": "overnight_news_orb.py",
        "variants": ["Open after filing"],
        "headline": ("Open after filing", 5),
        "shift_back": True,
        "tradeable": "filing score >= 1.5, positive direction, trailing turnover "
                     ">= Rs 10 cr (point-in-time)",
        "exit_text":
            "**Exit model for this report:** the filing score is known only AFTER\n"
            "the close, so a D0-close entry would be look-ahead and is not offered.\n"
            "The event date in the log is the trade day T (the morning after the\n"
            "filing); the simulation anchor is shifted back one trading day so the\n"
            "shared simulator's next-open entry IS T's open — the first tradable\n"
            "print after the news. Stop = prior (pre-news) day's low capped 6% under\n"
            "entry, gap-through fills at open; time exit at D+5 or D+20 close.\n"
            "\n"
            "**Read this first:** the study's real finding was INTRADAY — the score\n"
            "direction predicts the opening gap, but ORB entries on news alone were\n"
            "NEGATIVE edge (house memory). Daily bars cannot test that; this report\n"
            "only measures buy-the-open-and-hold, which buys AFTER the gap has paid.\n"
            "Cohort: positive-direction events only (overnight_news_events_pos.csv);\n"
            "the full log (overnight_news_events.csv) adds 409 negative-direction\n"
            "events that a long-only daily test cannot use.",
        "note": "The gap itself is the edge the scorer found; this daily-bar test "
                "starts at the post-gap open, so a weak result here does not refute "
                "the gap-prediction finding — and a strong one would not validate "
                "ORB trading, which tested negative intraday.",
    },
}

REPORT_DIR = os.path.join(common.OUTPUT_DIR, "reports")
CHART_DIR = os.path.join(REPORT_DIR, "charts")
ERAS = [("2015-2019", 2015, 2019), ("2020-2022 (COVID)", 2020, 2022),
        ("2023-2026", 2023, 2026)]
VARIANTS = ["D+1 open", "D0 close", "D0 close, range_pos>=0.75"]
HOLDS = [5, 20]
HEADLINE = ("D0 close", 5)
MIN_N = 60  # below this, a stats cell prints "n=X (too few)" instead of stats
CLOSE_VARIANTS = {"D0 close", "D0 close, range_pos>=0.75"}

DEFAULT_EXIT = (
    "**Exit model for this report** (close-entry studies 2026-07-25): stop =\n"
    "signal-day low capped 6% under entry, gap-through fills at open,\n"
    "suspension-tolerant (NaN bar = hold); time exit at D+5 or D+20 close.\n"
    "Entries: D+1 open, D0 close, D0 close gated on range_pos >= 0.75\n"
    "(range_pos = (close-low)/(high-low) on the signal bar).")


def hold_label(h):
    return f"D+{h}" if isinstance(h, int) else "recorded exit (stop or ~D+60)"


def module_docstring(path):
    src = open(path).read()
    q = src.find('"""')
    return src[q + 3:src.find('"""', q + 3)].strip()


def trade_stats(r, dates):
    ok = ~np.isnan(r)
    r, dates = r[ok], dates[ok]
    if len(r) == 0:
        return None
    order = np.argsort(dates, kind="stable")
    r_ord = r[order]
    streak = longest = 0
    for x in r_ord:
        streak = streak + 1 if x < 0 else 0
        longest = max(longest, streak)
    pos, neg = r[r > 0].sum(), r[r < 0].sum()
    top_k = max(1, int(np.ceil(len(r) * 0.05)))
    top_share = (np.sort(r)[-top_k:].sum() / r.sum() * 100
                 if r.sum() > 0 else np.nan)
    return {
        "n": len(r), "days": len(np.unique(dates)),
        "win": (r > 0).mean() * 100, "avg": r.mean(), "med": np.median(r),
        "pf": pos / -neg if neg < 0 else np.inf,
        "total": r.sum(), "streak": longest, "top5": top_share,
    }


def stat_row(label, st):
    if st is None:
        return f"| {label} | 0 | — | — | — | — | — | — |"
    if st["n"] < MIN_N:
        return (f"| {label} | n={st['n']} (too few) | — | — | — | — | — "
                f"| {st['days']} |")
    return (f"| {label} | {st['n']} | {st['win']:.1f}% | {st['avg']:+.3f} "
            f"| {st['med']:+.3f} | {st['pf']:.2f} | {st['total']:+.0f} "
            f"| {st['days']} |")


def daily_r(r, dates):
    ok = ~np.isnan(r)
    return pd.Series(r[ok], index=pd.DatetimeIndex(dates[ok])).groupby(level=0).sum()


def main(slug, m=None):
    cfg = STUDIES[slug]
    variants = cfg.get("variants", VARIANTS)
    holds = cfg.get("holds", HOLDS)
    hl_v, hl_h = cfg.get("headline", HEADLINE)
    hlab = hold_label(hl_h)
    from_columns = cfg.get("r_source") == "columns"
    os.makedirs(CHART_DIR, exist_ok=True)
    if m is None:
        t0 = time.time()
        m = common.load_cache()
        print(f"cache load: {time.time() - t0:.1f}s")

    ev = pd.read_csv(os.path.join(common.OUTPUT_DIR,
                                  cfg.get("csv", f"{slug}_events.csv")),
                     parse_dates=["date"])
    if ev["date"].dt.tz is None:
        ev["date"] = ev["date"].dt.tz_localize("Asia/Kolkata")
    else:
        ev["date"] = ev["date"].dt.tz_convert("Asia/Kolkata")
    n_raw = len(ev)
    if not from_columns:
        close, high, low = m["close"], m["high"], m["low"]
        dpos = pd.Series(range(len(close.index)), index=close.index)
        spos = pd.Series(range(len(close.columns)), index=close.columns)
        d = dpos.reindex(ev["date"]).to_numpy()
        s = spos.reindex(ev["symbol"]).to_numpy()
        if cfg.get("shift_back"):  # event date = trade day; enter at ITS open
            d = d - 1
        keep = ~(np.isnan(d) | np.isnan(s)) & (d >= 0)
        ev = ev[keep].reset_index(drop=True)
        d, s = d[keep].astype(int), s[keep].astype(int)
    dates = ev["date"].dt.tz_localize(None).to_numpy()
    years = ev["date"].dt.year.to_numpy()

    t1 = time.time()
    R = {}  # (variant, hold) -> R array aligned to ev
    if from_columns:
        sp = ev["stop_pct"].to_numpy(float)
        r_cols = np.divide(ev["stopped_ret"].to_numpy(float), sp,
                           out=np.full(len(ev), np.nan), where=sp > 0)
        for hold in holds:
            R[(variants[0], hold)] = r_cols
    else:
        if VARIANTS[2] in variants:
            rng = high.values[d, s] - low.values[d, s]
            range_pos = np.divide(close.values[d, s] - low.values[d, s], rng,
                                  where=rng > 0, out=np.ones_like(rng))
            strong = range_pos >= 0.75
        for hold in holds:
            r_open = (simulate(d, s, m, False, hold)
                      if any(v not in CLOSE_VARIANTS for v in variants) else None)
            r_close = (simulate(d, s, m, True, hold)
                       if any(v in CLOSE_VARIANTS for v in variants) else None)
            for v in variants:
                if v == VARIANTS[2]:
                    R[(v, hold)] = np.where(strong, r_close, np.nan)
                elif v == "D0 close":
                    R[(v, hold)] = r_close
                else:
                    R[(v, hold)] = r_open
    print(f"simulation: {time.time() - t1:.1f}s")

    era_masks = [("Full 2015-2026", np.ones(len(ev), bool))]
    era_masks += [(name, (years >= a) & (years <= b)) for name, a, b in ERAS]

    # ---- charts -------------------------------------------------------
    t2 = time.time()
    charts = []
    fig, ax = plt.subplots(figsize=(10, 5))
    for v in variants:
        cum = daily_r(R[(v, hl_h)], dates).cumsum()
        ax.plot(cum.index, cum.values, label=v, lw=1.2)
    ax.axhline(0, color="grey", lw=0.5)
    ax.legend()
    ax.set_ylabel("Cumulative R")
    ax.set_title(f"{cfg['title']} — cumulative R by entry variant (hold {hlab})\n"
                 "NOT a portfolio equity curve: unsized, overlapping per-trade R summed by signal date")
    fig.tight_layout()
    p1 = os.path.join(CHART_DIR, f"{slug}_cum_r.png")
    fig.savefig(p1, dpi=110)
    plt.close(fig)
    charts.append((p1, "Running sum of per-trade R (risk units) by signal date, one line per "
                   f"entry variant, hold {hlab}. This is NOT a portfolio equity curve — trades "
                   "overlap and are unsized; read the slope and its consistency, not the level. "
                   "A line drifting down means the average trade loses; a line that only rises "
                   "in one burst means the edge is episode-concentrated."))

    fig, ax = plt.subplots(figsize=(10, 5))
    yr_idx = None
    for i, v in enumerate(variants):
        dr = daily_r(R[(v, hl_h)], dates)
        yr = dr.groupby(dr.index.year).sum()
        yr_idx = yr.index if yr_idx is None else yr_idx.union(yr.index)
        ax.bar(np.array(yr.index) + (i - 1) * 0.28, yr.values, width=0.26, label=v)
    ax.axhline(0, color="grey", lw=0.5)
    ax.legend()
    ax.set_ylabel("Total R in year")
    ax.set_xticks(list(yr_idx))
    ax.set_title(f"{cfg['title']} — annual aggregate R (hold {hlab})")
    fig.tight_layout()
    p2 = os.path.join(CHART_DIR, f"{slug}_annual_r.png")
    fig.savefig(p2, dpi=110)
    plt.close(fig)
    charts.append((p2, "Total R summed over all trades signalled in each calendar year, per "
                   f"entry variant (hold {hlab}). Bars above zero = the year's trades collectively "
                   "made money in risk units. Compare eras: a variant that is positive only in "
                   "2020-2022 was carried by COVID."))

    fig, ax = plt.subplots(figsize=(10, 5))
    era_names = [n for n, _ in era_masks[1:]]
    for i, v in enumerate(variants):
        pfs = []
        for _, mask in era_masks[1:]:
            st = trade_stats(R[(v, hl_h)][mask], dates[mask])
            pfs.append(min(st["pf"], 3.0) if st else np.nan)
        ax.bar(np.arange(len(era_names)) + (i - 1) * 0.28, pfs, width=0.26, label=v)
    ax.axhline(1.0, color="red", lw=0.8, ls="--", label="PF 1.0 (breakeven)")
    ax.axhline(1.3, color="orange", lw=0.8, ls=":", label="PF 1.3 (cost bar)")
    ax.set_xticks(range(len(era_names)))
    ax.set_xticklabels(era_names)
    ax.set_ylabel("Profit factor (capped at 3)")
    ax.legend(fontsize=8)
    ax.set_title(f"{cfg['title']} — profit factor by era x entry variant (hold {hlab})")
    fig.tight_layout()
    p3 = os.path.join(CHART_DIR, f"{slug}_pf_era.png")
    fig.savefig(p3, dpi=110)
    plt.close(fig)
    charts.append((p3, "Profit factor (gross wins / gross losses, in R) per era and entry "
                   f"variant, hold {hlab}. Red dashed line = 1.0 breakeven; orange dotted = 1.3, "
                   "below which NSE round-trip costs (~0.05-0.1R) presumably kill the edge. "
                   "Era-stable means the 2015-2019 and 2023-2026 bars agree; the COVID bar "
                   "shows what 2020-2022 contributed."))
    print(f"charts: {time.time() - t2:.1f}s")

    # ---- markdown -----------------------------------------------------
    t3 = time.time()
    rules = (cfg["rules_text"] if "rules_text" in cfg else
             module_docstring(os.path.join(os.path.dirname(__file__), cfg["rules_file"])))
    hl = R[(hl_v, hl_h)]
    hl_full = trade_stats(hl, dates)
    dr_hl = daily_r(hl, dates)
    cum = dr_hl.cumsum()
    max_dd = (cum.cummax() - cum).max()
    monthly = dr_hl.groupby([dr_hl.index.year, dr_hl.index.month]).sum().unstack()

    L = []
    A = L.append
    A(f"# Backtest Report: {cfg['title']}")
    A("")
    A(f"**Study slug:** {slug}")
    A(f"**Report date:** {pd.Timestamp.now():%Y-%m-%d}")
    A("**Engine:** " + cfg.get("engine", "per-trade event study "
      "(close_entry_rescore.simulate), daily bars"))
    A("**Status:** Research — NOT a portfolio backtest, NOT approved for live capital")
    A("")
    A("> Event study: one row per signal, no position sizing, overlapping trades.")
    A("> All results in R (risk units). Sharpe/CAGR/equity drawdown are not")
    A("> defined for this design and are deliberately absent.")
    A("")
    A("## 1. Hypothesis and rationale")
    A("")
    hypo = rules.split("\n\n")[0].replace("\n", " ")
    A(hypo.split(" — ", 1)[-1]
      if hypo.startswith(cfg.get("rules_file", "\0")) else hypo)
    A("")
    A("## 2. Universe and data")
    A("")
    A("| Item | Detail |")
    A("|---|---|")
    A("| Instruments | All NSE EQ-series stocks currently stored (~2100), full history |")
    A("| Tradeable filter | " + cfg.get("tradeable", "close >= Rs 30, 20d avg "
      "turnover >= Rs 1 cr, >= 130 bars history") + " |")
    if from_columns:
        n_ok = int((~np.isnan(R[(hl_v, hl_h)])).sum())
        A(f"| Events | {n_raw} rows in the event log; {n_ok} with a valid "
          f"recorded stop/outcome ({n_raw - n_ok} dropped: stop_pct <= 0 or "
          "no recorded outcome) |")
    else:
        A(f"| Events | {n_raw} raw, {len(ev)} mapped to matrices ({n_raw - len(ev)} dropped: symbol/date not in cache) |")
    A(f"| Period | {ev['date'].min():%Y-%m-%d} to {ev['date'].max():%Y-%m-%d} |")
    A("| Data | Kite daily OHLCV reconciled vs NSE bhavcopy; heuristic split repair |")
    A("| Survivorship | Universe is current listings — delisted names absent (bias: optimistic) |")
    A("")
    A("## 3. Rules (verbatim from the study module)")
    A("")
    A("```")
    A(rules)
    A("```")
    A("")
    A(cfg.get("exit_text", DEFAULT_EXIT))
    A("")
    A("## 4. Cost and execution assumptions")
    A("")
    A("All results are **pre-cost**. NSE round-trip friction is ~0.2% of notional,")
    A("which at typical stop widths here is ~0.05-0.1R per trade. Any variant with")
    A("PF below ~1.3 should be presumed dead after costs. Close entries assume a")
    A("fill at the closing price (in practice a ~3:20pm order near the close).")
    A("")
    A("## 5. Headline results (full period, per-trade R)")
    A("")
    hdr = "| Variant | n | Win | Avg R | Med R | PF | Total R | Signal days |"
    sep = "|---|---|---|---|---|---|---|---|"
    for hold in holds:
        A(f"**Hold {hold_label(hold)}**")
        A("")
        A(hdr)
        A(sep)
        for v in variants:
            A(stat_row(v, trade_stats(R[(v, hold)], dates)))
        A("")
    A(f"Read honestly: expectancy (avg R) is per-trade and pre-cost. The headline")
    A(f"variant for the rest of this report is **{hl_v}, hold {hlab}**.")
    A("")
    A("## 6. Trade statistics (headline variant)")
    A("")
    A("| Metric | Value |")
    A("|---|---|")
    A(f"| Total trades | {hl_full['n']} |")
    A(f"| Distinct signal days | {hl_full['days']} |")
    A(f"| Win rate | {hl_full['win']:.1f}% |")
    A(f"| Avg / median R | {hl_full['avg']:+.3f} / {hl_full['med']:+.3f} |")
    A(f"| Profit factor | {hl_full['pf']:.2f} |")
    A(f"| Expectancy (pre-cost) | {hl_full['avg']:+.3f}R per trade |")
    A(f"| Longest losing streak (by signal order) | {hl_full['streak']} trades |")
    top5 = "n/a (total R <= 0)" if np.isnan(hl_full["top5"]) else f"{hl_full['top5']:.0f}%"
    A(f"| % of total R from top 5% of trades | {top5} |")
    A("")
    A("High top-5% concentration means the result is fragile to missing a few")
    A("outlier trades; streaks are sequential by signal date, ignoring overlap.")
    A("")
    A("## 7. Cumulative-R curve and drawdown")
    A("")
    A("See chart pages in the PDF. The curve is the running sum of per-trade R by")
    A("signal date — **not a portfolio equity curve** (no sizing, overlapping")
    A(f"positions). Max drawdown **measured on the cumulative-R curve** of the")
    A(f"headline variant: **-{max_dd:.0f}R** (peak-to-trough of summed R).")
    A("")
    A("## 8. Monthly and annual aggregate R (headline variant)")
    A("")
    A("Total R of trades signalled in each month (not portfolio returns).")
    A("")
    A("| Year | " + " | ".join(f"{mth:02d}" for mth in range(1, 13)) + " | Year |")
    A("|---" * 14 + "|")
    for yr in monthly.index:
        row = [f"{monthly.loc[yr, mth]:+.0f}" if (mth in monthly.columns and
               pd.notna(monthly.loc[yr, mth])) else "" for mth in range(1, 13)]
        A(f"| {yr} | " + " | ".join(row) + f" | **{monthly.loc[yr].sum():+.0f}** |")
    A("")
    A("## 9. Robustness: era stability (the COVID test)")
    A("")
    A("2020-2022 is reported as its own segment, not excluded. A finding is")
    A("**era-stable only if 2015-2019 and 2023-2026 agree**; the COVID row shows")
    A("what that regime contributed.")
    A("")
    for hold in holds:
        A(f"**Hold {hold_label(hold)}**")
        A("")
        A("| Variant / era | n | Win | Avg R | Med R | PF | Total R | Signal days |")
        A(sep)
        for v in variants:
            for name, mask in era_masks[1:]:
                A(stat_row(f"{v} — {name}", trade_stats(R[(v, hold)][mask], dates[mask])))
        A("")
    A("**Episode-concentration guardrail** — distinct signal days per era:")
    A("")
    for name, mask in era_masks[1:]:
        nd = len(np.unique(dates[mask]))
        warn = "  **WARNING: < 30 distinct days — single-episode anecdote, not evidence**" \
            if nd < 30 else ""
        A(f"- {name}: {nd} distinct signal days{warn}")
    A("")
    verdict = []
    for v in variants:
        sa = trade_stats(R[(v, hl_h)][era_masks[1][1]], dates[era_masks[1][1]])
        sb = trade_stats(R[(v, hl_h)][era_masks[3][1]], dates[era_masks[3][1]])
        na, nb = (sa["n"] if sa else 0), (sb["n"] if sb else 0)
        if na < MIN_N or nb < MIN_N:
            verdict.append(f"- {v} ({hlab}): n={na} (2015-19) / n={nb} "
                           f"(2023-26) — too few (< {MIN_N}) for an "
                           "era-stability verdict")
        else:
            ok = sa["pf"] > 1 and sb["pf"] > 1
            verdict.append(f"- {v} ({hlab}): PF {sa['pf']:.2f} (2015-19) vs "
                           f"{sb['pf']:.2f} (2023-26) — "
                           + ("**era-stable positive**" if ok else "not era-stable"))
    L.extend(verdict)
    A("")
    A("## 10. Known limitations")
    A("")
    A("- Pre-cost; PF < ~1.3 presumed dead after NSE round-trip friction.")
    A("- No position sizing or portfolio overlap handling — per-trade R only.")
    A("- Current-listing universe: delisted/suspended names absent (survivorship).")
    A("- Heuristic split repair; no historical ASM/GSM exclusion at signal time.")
    A("- Daily bars: close entries assume the closing print; intraday slippage unmodeled.")
    A("- Stop fills at min(open, stop) on gap-throughs — optimistic vs real fills is unmodeled beyond that.")
    A("")
    A("## 11. Conclusion")
    A("")
    A("Mechanical read of Section 9 (no discretion):")
    A("")
    L.extend(verdict)
    A("")
    few_day_eras = [name for name, mask in era_masks[1:]
                    if len(np.unique(dates[mask])) < 30]
    if few_day_eras:
        A(f"**WARNING:** {', '.join(few_day_eras)} " +
          ("have" if len(few_day_eras) > 1 else "has") +
          " fewer than 30 distinct signal days — single-episode anecdote, not evidence.")
        A("")
    if "note" in cfg:
        A(f"**Study-specific note:** {cfg['note']}")
        A("")
    A("Next steps: cost-adjust the surviving variants, check episode concentration")
    A("against the guardrail above, and only then consider portfolio-level testing.")

    md_path = os.path.join(REPORT_DIR, f"{slug}_report.md")
    with open(md_path, "w") as f:
        f.write("\n".join(L) + "\n")
    pdf_path = os.path.join(REPORT_DIR, f"{slug}_report.pdf")
    build_pdf(md_path, charts, pdf_path)
    print(f"md+pdf: {time.time() - t3:.1f}s")
    print(f"-> {md_path}\n-> {pdf_path}")


if __name__ == "__main__":
    t0 = time.time()
    cache = common.load_cache()
    print(f"cache load: {time.time() - t0:.1f}s")
    for arg in sys.argv[1:]:
        print(f"=== {arg}")
        main(arg, cache)
