"""
chart_bank.py — Build a flip-through deck of annotated "winner" charts per study.

Goal: train the eye. For every study event that went on to gain >= 20% in the
month after entry, render one page showing ~2 years of daily context before the
signal and ~3 months after, with the setup zone shaded, the entry marked, and
the entry criteria spelled out in plain English. Page through the PDF
next / next / next to internalise what a working setup looks like beforehand.

Winners are curated, not dumped: capped per study, spread across calendar years
(so the deck spans bull and bear regimes, not one euphoric run), and limited to
a few events per symbol so no single name dominates.

Usage:
    ~/anaconda3/bin/python src/backtest/studies/chart_bank.py darvas_box
    ~/anaconda3/bin/python src/backtest/studies/chart_bank.py            # all
    ~/anaconda3/bin/python src/backtest/studies/chart_bank.py darvas_box --n 60
"""

import argparse
import os
import sys

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle
from matplotlib.collections import LineCollection
from matplotlib.backends.backend_pdf import PdfPages

sys.path.insert(0, os.path.dirname(__file__))
import common
import annotators

OUT_DIR = os.path.join(common.OUTPUT_DIR, "..", "chart_bank")

BARS_BEFORE = 504      # ~2 trading years of context before the signal
BARS_AFTER = 63        # ~3 trading months after entry
WIN_RET = 20.0         # a "winner" gained >= this % in the month after entry
DEFAULT_N = 40         # charts per study
PER_SYMBOL_CAP = 2     # at most this many events per symbol in a deck

UP, DOWN = "#26a69a", "#ef5350"

# Dashboard SMA palette (tv_chart.py) + 200 SMA. col -> (colour, legend label).
SMA_STYLE = {
    "ma10": ("#f6b93b", "10 SMA"),
    "ma20": ("#4c8dff", "20 SMA"),
    "ma50": ("#c678dd", "50 SMA"),
    "ma200": ("#455a64", "200 SMA"),
}


def t2108_series(close: pd.DataFrame) -> pd.Series:
    """T2108 = % of stocks above their 40-day MA (regime.py pct40ma)."""
    ma40 = close.rolling(40).mean()
    return (close > ma40).sum(axis=1) / close.notna().sum(axis=1) * 100


# ----------------------------------------------------------------------------
# selection
# ----------------------------------------------------------------------------
def select_winners(events: pd.DataFrame, n: int) -> pd.DataFrame:
    """Winners (ret_o20 >= 20%), capped at n, spread across years and symbols.

    Round-robin over calendar years, each round taking the biggest remaining
    winner from each year, capping per symbol — a time-diverse, high-quality
    sample rather than n moonshots from one bull market.
    """
    w = events[events["ret_o20"] >= WIN_RET].copy()
    if w.empty:
        return w
    w["year"] = w["date"].dt.year
    w = w.sort_values("ret_o20", ascending=False)

    picked, per_sym = [], {}
    pools = {y: list(g.index) for y, g in w.groupby("year")}
    years = sorted(pools)
    while len(picked) < n and any(pools.values()):
        for y in years:
            if len(picked) >= n:
                break
            while pools[y]:
                idx = pools[y].pop(0)
                sym = w.at[idx, "symbol"]
                if per_sym.get(sym, 0) >= PER_SYMBOL_CAP:
                    continue
                per_sym[sym] = per_sym.get(sym, 0) + 1
                picked.append(idx)
                break
    return w.loc[picked].sort_values("date")


# ----------------------------------------------------------------------------
# drawing
# ----------------------------------------------------------------------------
def compact_ohlcv(m: dict, symbol: str) -> pd.DataFrame:
    """One symbol's own trading calendar (NaN closes dropped) with MAs."""
    df = pd.DataFrame({k: m[k][symbol] for k in
                       ["open", "high", "low", "close", "volume"]})
    df = df[df["close"].notna()]
    for w in (10, 20, 50, 200):
        df[f"ma{w}"] = df["close"].rolling(w).mean()
    df["vma50"] = df["volume"].rolling(50).mean()
    # TI65 (Bonde trend intensity): 7-day / 65-day close average, per data_loader.py.
    df["ti65"] = df["close"].rolling(7).mean() / df["close"].rolling(65).mean()
    return df


def draw_candles(ax, o, h, l, c):
    x = np.arange(len(c))
    up = c >= o
    ax.add_collection(LineCollection(
        [[(xi, li), (xi, hi)] for xi, li, hi in zip(x, l, h)],
        colors=np.where(up, UP, DOWN), linewidths=0.6))
    for xi, oi, ci, u in zip(x, o, c, up):
        lo, hi = (oi, ci) if u else (ci, oi)
        ax.add_patch(Rectangle((xi - 0.3, lo), 0.6, max(hi - lo, 1e-9),
                               facecolor=UP if u else DOWN, edgecolor="none"))


def regime_of(row: pd.Series) -> str:
    """Regime label, derived from breadth_score if the column is absent
    (washout_reversal writes a slim event log without it)."""
    if "regime" in row and pd.notna(row.get("regime")):
        return row["regime"]
    s = row.get("breadth_score", np.nan)
    if pd.isna(s):
        return "?"
    return "bad" if s <= -2 else ("neutral" if s <= 0 else "good")


def market_context_lines(m: dict, row: pd.Series) -> list:
    """What the market was doing at signal — for the side box."""
    t2108 = m["t2108"].get(row["date"], np.nan)
    score = row.get("breadth_score", np.nan)
    rs = row.get("rs_rank", np.nan)
    return [
        "",
        "-- Market context at signal --",
        f"Stock RS: {rs:.0f} (composite %ile)" if pd.notna(rs)
        else "Stock RS: n/a",
        f"Regime: {regime_of(row)}  (breadth {score:+.0f}/5)" if pd.notna(score)
        else f"Regime: {regime_of(row)}",
        f"T2108: {t2108:.0f}% of mkt > 40 DMA" if pd.notna(t2108)
        else "T2108: n/a",
    ]


def render_event(pdf: PdfPages, m: dict, row: pd.Series, slug: str) -> bool:
    sym = row["symbol"]
    df = compact_ohlcv(m, sym)
    if row["date"] not in df.index:
        return False
    sig = df.index.get_loc(row["date"])            # signal bar (close)
    lo = max(0, sig - BARS_BEFORE)
    hi = min(len(df), sig + 1 + BARS_AFTER)
    win = df.iloc[lo:hi].reset_index()
    p = sig - lo                                   # signal position within window
    entry_x = p + 1                                # entry is D+1 open

    fig, (axp, axv, axb) = plt.subplots(
        3, 1, figsize=(11.69, 8.27), height_ratios=[4, 1, 1.2], sharex=True,
        constrained_layout=True, gridspec_kw={"hspace": 0.03})

    draw_candles(axp, win["open"].values, win["high"].values,
                 win["low"].values, win["close"].values)
    for col, (color, label) in SMA_STYLE.items():
        axp.plot(win.index, win[col], color=color, lw=1.0, label=label)

    entry = row["entry_open"]
    if entry_x < len(win):
        axp.axvline(entry_x, color="#111", lw=1.0, ls="--")
        axp.annotate("ENTRY (D+1 open)", (entry_x, entry),
                     xytext=(6, 14), textcoords="offset points", fontsize=8,
                     fontweight="bold", color="#111",
                     arrowprops=dict(arrowstyle="->", color="#111", lw=1))
    axp.axhline(entry * 1.20, color="#7b1fa2", lw=0.8, ls=":")
    axp.annotate("+20% (1-month target)", (0, entry * 1.20),
                 xytext=(4, 3), textcoords="offset points",
                 fontsize=7, color="#7b1fa2")

    bullets = annotators.annotate(axp, slug, row, win, p, entry_x)
    bullets += market_context_lines(m, row)

    axp.legend(loc="upper left", fontsize=7, framealpha=0.9)
    axp.set_ylabel("Price")
    axp.margins(x=0.01)
    axp.grid(alpha=0.15)

    vup = win["close"].values >= win["open"].values
    axv.bar(win.index, win["volume"], color=np.where(vup, UP, DOWN), width=0.7)
    axv.plot(win.index, win["vma50"], color="#555", lw=0.8)
    if entry_x < len(win):
        axv.axvline(entry_x, color="#111", lw=1.0, ls="--")
    axv.set_ylabel("Vol")
    axv.grid(alpha=0.15)

    axb.plot(win.index, win["ti65"], color="#6d4c41", lw=0.9)
    axb.axhline(1.05, color=UP, lw=0.7, ls=":")
    axb.fill_between(win.index, 1.05, win["ti65"],
                     where=win["ti65"] >= 1.05, color=UP, alpha=0.15)
    if entry_x < len(win):
        axb.axvline(entry_x, color="#111", lw=1.0, ls="--")
    axb.set_ylabel("TI65\n7d/65d")
    axb.grid(alpha=0.15)

    step = max(len(win) // 11, 1)
    ticks = list(range(0, len(win), step))
    axb.set_xticks(ticks)
    axb.set_xticklabels([win["date"].iloc[t].strftime("%b '%y") for t in ticks],
                        fontsize=7, rotation=0)

    ret60 = f"  +{row['ret_o60']:.0f}% at D+60" if "ret_o60" in row and \
        pd.notna(row.get("ret_o60")) else ""
    rs = row.get("rs_rank", np.nan)
    rs_txt = f"   RS {rs:.0f}" if pd.notna(rs) else ""
    axp.set_title(
        f"{sym}   signal {row['date'].date()}   "
        f"+{row['ret_o20']:.0f}% in 1 month{ret60}{rs_txt}   "
        f"{regime_of(row)} market",
        fontsize=11, fontweight="bold")

    axp.text(0.995, 0.02, "\n".join(bullets), transform=axp.transAxes,
             fontsize=7.5, va="bottom", ha="right", family="monospace",
             bbox=dict(boxstyle="round", fc="#fffde7", ec="#cccccc", alpha=0.95))

    pdf.savefig(fig)
    plt.close(fig)
    return True


def build_deck(slug: str, m: dict, n: int) -> None:
    csv = os.path.join(common.OUTPUT_DIR, f"{slug}_events.csv")
    if not os.path.exists(csv):
        print(f"  {slug}: no events csv, skipping")
        return
    events = pd.read_csv(csv, parse_dates=["date"])
    if "ret_o20" not in events.columns:
        print(f"  {slug}: no ret_o20 column, skipping")
        return
    picks = select_winners(events, n)
    if picks.empty:
        print(f"  {slug}: no winners, skipping")
        return

    os.makedirs(OUT_DIR, exist_ok=True)
    out = os.path.join(OUT_DIR, f"{slug}_chart_bank.pdf")
    drawn = 0
    with PdfPages(out) as pdf:
        for _, row in picks.iterrows():
            if render_event(pdf, m, row, slug):
                drawn += 1
    print(f"  {slug}: {drawn} charts -> {os.path.relpath(out)}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("slugs", nargs="*", help="study slugs (default: all)")
    ap.add_argument("--n", type=int, default=DEFAULT_N,
                    help=f"charts per study (default {DEFAULT_N})")
    args = ap.parse_args()

    slugs = args.slugs or sorted(
        f[:-len("_events.csv")] for f in os.listdir(common.OUTPUT_DIR)
        if f.endswith("_events.csv"))

    print("Loading study cache...")
    m = common.load_cache()
    m["t2108"] = t2108_series(m["close"])
    print(f"Building chart banks ({args.n} charts/study)...")
    for slug in slugs:
        build_deck(slug, m, args.n)


if __name__ == "__main__":
    main()
