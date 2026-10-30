"""
gold_cycle_analogs.py — where is gold in its peak → crash → bounce cycle, and
what did every comparable cycle since 1971 do next?

Method (daily XAUUSD spot, 1971+):
  1. Swing pivots = 15% zigzag on closes.
  2. A "major top" = a swing peak that is a 2-year high and later falls >=20%
     before being reclaimed.
  3. Structure per top: first swing low (L1), the relief bounce (B), then the
     ANCHOR = first day the bounce has given back >=50% while L1 still holds.
     That is where gold sits today, so outcomes are measured from the anchor.
  4. Each analog's post-anchor path is replayed onto today's price (scenario fan).

Data: repo spot store; days after its last row are spliced from COMEX GC=F
scaled by the median spot/futures ratio on the overlap.

Run: ~/anaconda3/bin/python src/backtest/studies/gold_cycle_analogs.py
"""

import os
import sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd
import yfinance as yf

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
import commodity_store
from backtest.studies.pdf_human import build_pdf

OUT = os.path.join(os.path.dirname(__file__), "..", "..", "..", "output", "studies", "gold_cycle_analogs")
SWING = 0.15
MIN_DD = 0.20
GIVEBACK = 0.5
BLOWOFF = 0.35                              # 12m run-up into the top that makes it a blow-off


def load_gold() -> pd.Series:
    spot = commodity_store.read("spot", "XAUUSD").set_index("date")["close"]
    fut = yf.download("GC=F", start=spot.index[-1] - pd.Timedelta(days=90),
                      progress=False, auto_adjust=False)["Close"]["GC=F"]
    fut.index = fut.index.tz_localize(None)
    overlap = spot.index.intersection(fut.index)
    ratio = (spot[overlap] / fut[overlap]).median()
    tail = fut[fut.index > spot.index[-1]] * ratio
    return pd.concat([spot, tail]).loc["1971":]


def zigzag(s: pd.Series, th: float) -> list:
    """Alternating swing pivots [('P'|'T', date, price)]; last entry is the open swing."""
    pivots, mode = [], "up"
    ext_d, ext = s.index[0], s.iloc[0]
    for d, v in s.items():
        if mode == "up":
            if v > ext:
                ext_d, ext = d, v
            elif v <= ext * (1 - th):
                pivots.append(("P", ext_d, ext))
                mode, ext_d, ext = "down", d, v
        else:
            if v < ext:
                ext_d, ext = d, v
            elif v >= ext * (1 + th):
                pivots.append(("T", ext_d, ext))
                mode, ext_d, ext = "up", d, v
    pivots.append(("open", ext_d, ext))
    return pivots


def pct_at(s: pd.Series, d, days: int) -> float:
    """Return from d to `days` calendar days later (NaN if not yet observed)."""
    later = s[d + pd.Timedelta(days=days):]
    return later.iloc[0] / s[d] - 1 if len(later) and d + pd.Timedelta(days=days) <= s.index[-1] else float("nan")


def find_cycles(s: pd.Series) -> list:
    pivots = zigzag(s, SWING)
    ma200 = s.rolling(200).mean()
    cycles = []
    for k, (kind, d, peak) in enumerate(pivots):
        if kind != "P" or peak < s[d - pd.Timedelta(days=730):d].max() or k + 2 >= len(pivots):
            continue
        after = s[d:]
        reclaimed = after[after > peak]
        end = reclaimed.index[0] if len(reclaimed) else None
        seg = s[d:end] if end is not None else after
        if seg.min() / peak - 1 > -MIN_DD:
            continue
        _, l1_d, l1 = pivots[k + 1]
        _, b_d, b = pivots[k + 2]
        if b >= peak:                       # bounce made a new high: no failed-bounce structure
            continue
        trigger = b - (b - l1) * GIVEBACK
        post_b = s[b_d:]
        hit = post_b[post_b <= trigger]
        anchor = hit.index[0] if len(hit) else None
        if anchor is not None and s[l1_d:anchor].iloc[1:].min() < l1:
            anchor = None                   # L1 already broken before the giveback: different setup
        cycles.append(dict(
            peak_d=d, peak=peak, run12=peak / s[:d - pd.Timedelta(days=365)].iloc[-1] - 1,
            ext200=peak / ma200[d] - 1,
            l1_d=l1_d, l1=l1, l1_dd=l1 / peak - 1,
            b_d=b_d, b=b, retrace=(b - l1) / (peak - l1),
            anchor=anchor, low_d=seg.idxmin(), low=seg.min(), final_dd=seg.min() / peak - 1,
            reclaim=end,
        ))
    return cycles


def outcomes(s: pd.Series, c: dict) -> dict:
    a = c["anchor"]
    if a is None or a == s.index[-1]:
        return {}
    yr = s[a:a + pd.Timedelta(days=365)]
    return dict(
        r6m=pct_at(s, a, 182), r12m=pct_at(s, a, 365), r24m=pct_at(s, a, 730),
        mdd12=yr.min() / s[a] - 1,
        broke_l1=bool((s[a:c["reclaim"]] < c["l1"]).any()) if c["reclaim"] else bool((s[a:] < c["l1"]).any()),
        yrs_to_reclaim=(c["reclaim"] - a).days / 365 if c["reclaim"] else float("nan"),
    )


def classify(c: dict) -> str:
    extra = c["final_dd"] - c["l1_dd"]
    years_to_reclaim = (c["reclaim"] - c["peak_d"]).days / 365 if c["reclaim"] is not None else 99
    if years_to_reclaim > 4:
        return "C: multi-year bear"
    if extra > -0.05:
        return "A: retest / small undercut, then recovery"
    return "B: deeper leg, then fast V"


def chart_history(s, cycles, path):
    fig, ax = plt.subplots(figsize=(11, 4.5))
    ax.semilogy(s.index, s.values, lw=0.8, color="#444")
    for c in cycles:
        ax.scatter(c["peak_d"], c["peak"], color="#c0392b", zorder=3, s=18)
        ax.annotate(c["peak_d"].strftime("%b %Y"), (c["peak_d"], c["peak"]), fontsize=7,
                    xytext=(0, 6), textcoords="offset points", ha="center")
        ax.scatter(c["low_d"], c["low"], color="#2471a3", zorder=3, s=18)
    ax.set_title("Gold (XAUUSD) 1971–today, log scale — red = major tops, blue = cycle lows")
    ax.grid(alpha=0.3)
    fig.tight_layout(); fig.savefig(path, dpi=130); plt.close(fig)


def chart_overlay(s, cycles, path):
    w = s.resample("W-FRI").last()
    fig, ax = plt.subplots(figsize=(11, 5.5))
    colors = {"A": "#27ae60", "B": "#e67e22", "C": "#c0392b"}
    for c in cycles:
        path_w = w[c["peak_d"]:c["peak_d"] + pd.Timedelta(weeks=260)] / c["peak"] * 100
        weeks = (path_w.index - c["peak_d"]).days / 7
        if c["peak_d"].year == s.index[-1].year:
            ax.plot(weeks, path_w.values, color="black", lw=2.8, label="NOW (Jan-2026 top)")
        else:
            ax.plot(weeks, path_w.values, color=colors[c["type"][0]], lw=1.1, alpha=0.8)
            ax.annotate(c["peak_d"].strftime("%Y"), (weeks[-1], path_w.values[-1]), fontsize=7,
                        color=colors[c["type"][0]])
    for k, lab in [("A", "A: retest then recovery"), ("B", "B: deeper leg, fast V"), ("C", "C: multi-year bear")]:
        ax.plot([], [], color=colors[k], label=lab)
    ax.axhline(100, color="grey", lw=0.6)
    ax.set_xlim(0, 260); ax.set_ylim(25, 190)
    ax.set_xlabel("weeks after the top"); ax.set_ylabel("price, top = 100")
    ax.set_title("Every major gold top since 1971, lined up at the peak (weekly)")
    ax.legend(fontsize=8, loc="upper left"); ax.grid(alpha=0.3)
    fig.tight_layout(); fig.savefig(path, dpi=130); plt.close(fig)


def chart_now(s, cur, path):
    z = s["2024-06":]
    fig, ax = plt.subplots(figsize=(11, 4.5))
    ax.plot(z.index, z.values, color="#444", lw=1)
    ax.plot(z.index, s.rolling(200).mean()[z.index], color="#2471a3", lw=1, label="200-day MA")
    ax.plot(z.index, s.rolling(1000).mean()[z.index], color="#8e44ad", lw=1, label="200-week MA (~1000d)")
    for lvl, lab, col in [(cur["peak"], "top", "#c0392b"), (cur["b"], "bounce high", "#e67e22"),
                          (cur["l1"], "first low (L1)", "#27ae60")]:
        ax.axhline(lvl, color=col, ls="--", lw=0.8)
        ax.annotate(f"{lab} {lvl:,.0f}", (z.index[0], lvl), fontsize=8, color=col, xytext=(2, 3),
                    textcoords="offset points")
    ax.set_title(f"Gold now: {s.iloc[-1]:,.0f} on {s.index[-1]:%d %b %Y}")
    ax.legend(fontsize=8, loc="upper left"); ax.grid(alpha=0.3)
    fig.tight_layout(); fig.savefig(path, dpi=130); plt.close(fig)


def chart_fan(s, cycles, path):
    """Replay each analog's post-anchor path onto today's price."""
    now_d, now = s.index[-1], s.iloc[-1]
    fig, ax = plt.subplots(figsize=(11, 5))
    colors = {"A": "#27ae60", "B": "#e67e22", "C": "#c0392b"}
    hist = s[now_d - pd.Timedelta(days=365):]
    ax.plot(hist.index, hist.values, color="black", lw=1.6)
    for c in cycles:
        if c.get("anchor") is None or c["peak_d"].year == now_d.year:
            continue
        fwd = s[c["anchor"]:c["anchor"] + pd.Timedelta(days=730)] / s[c["anchor"]] * now
        dates = now_d + (fwd.index - c["anchor"])
        ax.plot(dates, fwd.values, color=colors[c["type"][0]], lw=1, alpha=0.85)
        ax.annotate(c["peak_d"].strftime("%Y"), (dates[-1], fwd.values[-1]), fontsize=7,
                    color=colors[c["type"][0]])
    ax.set_title("If gold repeats each past cycle from the same point: 2-year paths from today")
    ax.grid(alpha=0.3)
    fig.tight_layout(); fig.savefig(path, dpi=130); plt.close(fig)


def fmt(x, pct=True):
    if x is None or pd.isna(x):
        return "–"
    return f"{x:+.0%}" if pct else f"{x:,.0f}"


def write_md(s, cycles, cur, md_path):
    hist = [c for c in cycles if c is not cur]
    ma200, ma1000 = s.rolling(200).mean().iloc[-1], s.rolling(1000).mean().iloc[-1]
    now = s.iloc[-1]
    L = [f"# Gold after a blow-off top: what history says ({s.index[-1]:%d %b %Y})", ""]
    L += ["## Where gold is today", "",
          f"- Top: **{cur['peak']:,.0f}** on {cur['peak_d']:%d %b %Y}, after a {cur['run12']:+.0%} run in the prior 12 months "
          f"({cur['ext200']:+.0%} above its 200-day average at the top).",
          f"- First low (L1): **{cur['l1']:,.0f}** on {cur['l1_d']:%d %b %Y} ({cur['l1_dd']:+.0%} from the top).",
          f"- Relief bounce: **{cur['b']:,.0f}** on {cur['b_d']:%d %b %Y} — recovered {cur['retrace']:.0%} of the fall.",
          f"- Now: **{now:,.0f}** — {now / cur['peak'] - 1:+.0%} from the top, {now / cur['l1'] - 1:+.0%} above L1, "
          f"has given back {(cur['b'] - now) / (cur['b'] - cur['l1']):.0%} of the bounce.",
          f"- 200-day average {ma200:,.0f} (price {now / ma200 - 1:+.0%}); 200-week average {ma1000:,.0f} (price {now / ma1000 - 1:+.0%}).",
          "", "![now](now.png)", ""]
    L += ["## Every comparable top since 1971", "",
          "Major top = 2-year high that later fell 20%+. Only tops whose first bounce failed below the peak are kept, "
          "because that is today's structure.", "",
          "| Top | Price | 12m run-up | Above 200d | First low | Bounce retraced | Final low | Low date | Reclaimed top | Blow-off? | Type |",
          "|---|---|---|---|---|---|---|---|---|---|---|"]
    for c in hist:
        L.append(f"| {c['peak_d']:%b %Y} | {c['peak']:,.0f} | {fmt(c['run12'])} | {fmt(c['ext200'])} | {fmt(c['l1_dd'])} | "
                 f"{c['retrace']:.0%} | {fmt(c['final_dd'])} | {c['low_d']:%b %Y} | "
                 f"{c['reclaim']:%b %Y} | {'yes' if c['run12'] >= BLOWOFF else 'no'} | {c['type'][0]} |")
    L += ["", "![overlay](overlay.png)", ""]
    L += ["## What happened from the same point (bounce half given back, L1 still intact)", "",
          "| Top | Anchor date | 6 months | 12 months | 24 months | Worst dip in 12m | Broke L1? | Years to new high |",
          "|---|---|---|---|---|---|---|---|"]
    for c in hist:
        if not c["out"]:
            continue
        o = c["out"]
        L.append(f"| {c['peak_d']:%b %Y} | {c['anchor']:%d %b %Y} | {fmt(o['r6m'])} | {fmt(o['r12m'])} | {fmt(o['r24m'])} | "
                 f"{fmt(o['mdd12'])} | {'yes' if o['broke_l1'] else 'no'} | {o['yrs_to_reclaim']:.1f} |")
    all_types = pd.Series([c["type"][0] for c in hist]).value_counts()
    hist = [c for c in hist if c["run12"] >= BLOWOFF]
    counts = pd.Series([c["type"][0] for c in hist]).value_counts()
    n = len(hist)
    L += ["", "## Scenario base rates (history only, n = %d — treat as rough odds, not a forecast)" % n, "",
          f"Counted on blow-off tops only (12m run-up >= {BLOWOFF:.0%}; today {cur['run12']:+.0%}). "
          f"Including the slow-grind tops too: A {all_types.get('A', 0)}, B {all_types.get('B', 0)}, C {all_types.get('C', 0)}.", ""]
    for k, name in [("A", "Retest / small undercut of the first low, then recovery"),
                    ("B", "Deeper second leg (another 10–15% below L1), then fast V recovery"),
                    ("C", "Multi-year bear market (40%+ from the top, years to recover)")]:
        members = [c["peak_d"].strftime("%Y") for c in hist if c["type"][0] == k]
        dd = [c["final_dd"] for c in hist if c["type"][0] == k]
        lvl = f"{cur['peak'] * (1 + min(dd)):,.0f}–{cur['peak'] * (1 + max(dd)):,.0f}" if dd else "–"
        L.append(f"- **{name}**: {counts.get(k, 0)}/{n} ({counts.get(k, 0) / n:.0%}) — {', '.join(members)}. "
                 f"Same depth from today's top = {lvl}.")
    L += ["", "![fan](fan.png)", ""]
    L += ["## Caveats", "",
          f"- Only {n} past cycles. One cycle moves any percentage by ~{1 / n:.0%}.",
          "- Price-only study: real rates, the dollar and central-bank buying drove the 1980 and 2011 bears and are not modelled.",
          "- Zigzag pivots (15%) and the 20% top filter are choices; nearby thresholds give the same episode list with minor changes.",
          "- Last month of data is COMEX futures scaled to spot (the spot store ends earlier)."]
    open(md_path, "w").write("\n".join(L) + "\n")


def main():
    os.makedirs(OUT, exist_ok=True)
    s = load_gold()
    cycles = find_cycles(s)
    for c in cycles:
        c["type"] = classify(c)
        c["out"] = outcomes(s, c)
    cur = cycles[-1]
    chart_history(s, cycles, os.path.join(OUT, "history.png"))
    chart_overlay(s, cycles, os.path.join(OUT, "overlay.png"))
    chart_now(s, cur, os.path.join(OUT, "now.png"))
    chart_fan(s, cycles, os.path.join(OUT, "fan.png"))
    md = os.path.join(OUT, "gold_cycle_analogs.md")
    write_md(s, cycles, cur, md)
    build_pdf(md, [(os.path.join(OUT, "history.png"), "Full gold history with major tops and cycle lows.")],
              os.path.join(OUT, "gold_cycle_analogs.pdf"))
    print(open(md).read())


if __name__ == "__main__":
    main()
