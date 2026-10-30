"""
ep9m_trade_bank.py — One annotated page per EP9M trade (winners AND losers).

Each page:
  * daily candles, ~1 year before the EP day and ~1 year after, SMAs 10/20/50/200
  * only the entry is marked (arrow under the EP-day bar); the result of the
    scale-out exit (50% day-3 close, 30% day-4 close, 20% runner) is in the title
  * corporate filings flagged in a strip above the chart (E = results, A = acquisition, ...)
  * a 5-session intraday (5-min) panel centred on the EP day, when the
    intraday store has it (it starts 29 Aug 2024)

Trades come from output/studies/ep9m_catalyst_split_events.csv (the canonical
5,209 EP9M events + causal catalyst tag). Exits are re-simulated here with the
study's scale-out rule; verify_exits() checks the replay matches the saved R.

Usage:
    ~/anaconda3/bin/python src/backtest/studies/ep9m_trade_bank.py            # all years
    ~/anaconda3/bin/python src/backtest/studies/ep9m_trade_bank.py 2024 2025
    ~/anaconda3/bin/python src/backtest/studies/ep9m_trade_bank.py 2025 --limit 10
"""

import argparse
import glob
import os
import sys

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.backends.backend_pdf import PdfPages

sys.path.insert(0, os.path.dirname(__file__))
import common
from chart_bank import SMA_STYLE, UP, DOWN, compact_ohlcv, regime_of, t2108_series

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..")
EVENTS_CSV = os.path.join(common.OUTPUT_DIR, "ep9m_catalyst_split_events.csv")
ANN_GLOB = os.path.join(ROOT, "data", "raw", "announcements", "announcements_*.parquet")
INTRADAY_DIR = os.path.join(ROOT, "data", "parquet", "intraday_5m")
OUT_DIR = os.path.join(common.OUTPUT_DIR, "..", "chart_bank", "ep9m")

BARS_BEFORE = 252     # ~1 trading year before the EP day
BARS_AFTER = 252      # ~1 trading year after
MAX_BARS = 250        # study's simulation cap (global calendar bars)
INTRADAY_DAYS = 5     # 5-min panel: 2 sessions before the EP day -> 2 after

# filing category -> (chart letter, colour). Routine/noisy categories are left out.
FILING_MARKS = {
    "results": ("E", "#1565c0"),
    "acquisition": ("A", "#6a1b9a"),
    "fundraise": ("F", "#ef6c00"),
    "credit_rating": ("CR", "#00838f"),
    "split_bonus": ("S", "#2e7d32"),
    "buyback": ("B", "#2e7d32"),
    "order_win": ("O", "#ad1457"),
    "guidance": ("G", "#5d4037"),
}


# ----------------------------------------------------------------------------
# data
# ----------------------------------------------------------------------------
def load_filings() -> dict:
    """symbol -> DataFrame(when, category, text) of the marked filing categories.
    text = NSE's one-line summary (attchmnttext, from 2025) or else the subject."""
    cols = ["symbol", "category", "an_dt", "subject", "attchmnttext"]
    ann = pd.concat(pd.read_parquet(f).reindex(columns=cols) for f in sorted(glob.glob(ANN_GLOB)))
    ann = ann[ann["category"].isin(FILING_MARKS)].copy()
    ann["text"] = ann["attchmnttext"].fillna(ann["subject"]).fillna("")
    ann["when"] = pd.to_datetime(ann["an_dt"], format="%d-%b-%Y %H:%M:%S", errors="coerce")
    ann = ann.dropna(subset=["when"]).drop_duplicates(["symbol", "category", "when"])
    return {s: g.sort_values("when") for s, g in ann.groupby("symbol")}


def load_intraday(symbol: str, days: pd.DatetimeIndex) -> pd.DataFrame:
    path = os.path.join(INTRADAY_DIR, f"{symbol}.parquet")
    if not os.path.exists(path):
        return pd.DataFrame()
    df = pd.read_parquet(path)
    day = df["date"].dt.tz_convert("Asia/Kolkata").dt.normalize().dt.date
    wanted = {d.date() for d in days}
    return df[day.isin(wanted)].sort_values("date").reset_index(drop=True)


# ----------------------------------------------------------------------------
# scale-out replay (same rule as the deleted ep9m_redefined.simulate_scaleout)
# ----------------------------------------------------------------------------
def scaleout_exits(df: pd.DataFrame, sig: int, entry: float, stop: float,
                   cap_date) -> list:
    """Exit legs as (bar_pos, price, weight, label).

    Half-range stop guards the whole position until the day-4 scale is done;
    then the 20% runner trails at min(entry, lowest low since entry).
    Held bars count the symbol's own traded sessions (suspension-tolerant).
    """
    o, lo, c = df["open"].values, df["low"].values, df["close"].values
    exits, held, weight, min_low, last = [], 0, 1.0, np.inf, sig
    for pos in range(sig + 1, len(df)):
        if df.index[pos] > cap_date:
            break
        level = stop if weight > 0.25 else min(entry, min_low)
        if lo[pos] <= level:
            label = "STOP" if weight > 0.25 else "runner out"
            exits.append((pos, min(o[pos], level), weight, label))
            return exits
        held, last = held + 1, pos
        min_low = min(min_low, lo[pos])
        if held == 3:
            exits.append((pos, c[pos], 0.5, "50% D3"))
            weight -= 0.5
        elif held == 4:
            exits.append((pos, c[pos], 0.3, "30% D4"))
            weight -= 0.3
    exits.append((last, c[last], weight, "still open"))
    return exits


def total_r(exits: list, entry: float, risk: float) -> float:
    return sum(w * (px - entry) / risk for _, px, w, _ in exits)


def cap_date_of(dates: pd.DatetimeIndex, date) -> pd.Timestamp:
    d0 = dates.get_loc(date)
    return dates[min(d0 + MAX_BARS, len(dates)) - 1]


def verify_exits(events: pd.DataFrame, m: dict) -> None:
    """Replay every event and compare with the study's saved r_scale."""
    dates = m["close"].index
    diffs = []
    for sym, g in events.groupby("symbol"):
        df = compact_ohlcv(m, sym)
        for row in g.itertuples():
            ex = scaleout_exits(df, df.index.get_loc(row.date), row.entry, row.stop,
                                cap_date_of(dates, row.date))
            diffs.append(abs(total_r(ex, row.entry, row.risk) - row.r_scale))
    diffs = np.array(diffs)
    print(f"  exit replay vs saved r_scale: max |diff| {diffs.max():.2e}, "
          f"{(diffs > 1e-4).sum()} of {len(diffs)} mismatched")


# ----------------------------------------------------------------------------
# drawing
# ----------------------------------------------------------------------------
def draw_candles(ax, o, h, l, c, width=0.6):
    """Vectorised candles (one vlines + one bar call — fast enough for 5k pages)."""
    x = np.arange(len(c))
    colors = np.where(c >= o, UP, DOWN)
    ax.vlines(x, l, h, colors=colors, linewidths=0.6)
    ax.bar(x, np.maximum(np.abs(c - o), 1e-9), width, np.minimum(o, c),
           color=colors, edgecolor="none")



def draw_filing_strip(ax, win: pd.DataFrame, filings: pd.DataFrame) -> None:
    """Filing flags in their own thin strip above the price chart — nothing drawn over candles."""
    ax.set_yticks([])
    ax.tick_params(axis="x", bottom=False, labelbottom=False)
    for side in ("top", "right", "left"):
        ax.spines[side].set_visible(False)
    ax.set_ylim(0, 1)
    ax.text(-0.005, 0.5, "Filings", transform=ax.transAxes, ha="right", va="center",
            fontsize=7, color="#777")
    if filings is None or filings.empty:
        return
    start, end = win["date"].iloc[0], win["date"].iloc[-1]
    fdates = filings["when"].dt.normalize().dt.tz_localize(start.tz)
    inwin = filings[(fdates >= start) & (fdates <= end)]
    seen = set()
    for when, cat in zip(inwin["when"], inwin["category"]):
        x = win["date"].searchsorted(when.normalize().tz_localize(start.tz))
        letter, color = FILING_MARKS[cat]
        if (x, letter) in seen:
            continue
        seen.add((x, letter))
        ax.text(x, 0.5, letter, ha="center", va="center", fontsize=6.5,
                fontweight="bold", color="white",
                bbox=dict(boxstyle="round,pad=0.2", fc=color, ec="none"))


def near_signal_filings(filings: pd.DataFrame, date) -> str:
    """Filings from 5 calendar days before to 1 day after the EP day, one short phrase."""
    if filings is None or filings.empty:
        return "none"
    d0 = date.tz_localize(None).normalize()
    near = filings[(filings["when"] >= d0 - pd.Timedelta(days=5))
                   & (filings["when"] < d0 + pd.Timedelta(days=2))]
    if near.empty:
        return "none"
    late_cut = d0 + pd.Timedelta(hours=15, minutes=30)
    return ", ".join(f"{cat} {when:%d-%b %H:%M}" + ("" if when <= late_cut else " (after entry)")
                     for when, cat in zip(near["when"], near["category"]))


def mark_entry(ax, x: float, bar_low: float) -> None:
    """Green arrow under the entry bar — never covers the candle itself."""
    ax.annotate("", xy=(x, bar_low), xytext=(0, -30), textcoords="offset points",
                xycoords="data", annotation_clip=False,
                arrowprops=dict(arrowstyle="-|>", color="#0a7d32", lw=2.4, mutation_scale=14,
                                shrinkA=0, shrinkB=3))


def draw_intraday(ax, bars: pd.DataFrame, days: pd.DatetimeIndex,
                  df: pd.DataFrame, sig: int) -> None:
    draw_candles(ax, bars["open"].values, bars["high"].values,
                 bars["low"].values, bars["close"].values, width=0.7)
    bar_day = bars["date"].dt.tz_convert("Asia/Kolkata").dt.date
    ticks, labels = [], []
    for d in days:
        idx = np.flatnonzero((bar_day == d.date()).values)
        if len(idx) == 0:
            continue
        ax.axvline(idx[0] - 0.5, color="#ddd", lw=0.6)
        ticks.append(idx[0] + len(idx) / 2)
        offset = df.index.get_loc(d) - sig
        labels.append(f"{d:%a %d-%b}" + ("  (EP day)" if offset == 0 else f"  (D{offset:+d})"))
        if offset == 0:
            ax.axvspan(idx[0] - 0.5, idx[-1] + 0.5, color="#0a7d32", alpha=0.06, lw=0)
            mark_entry(ax, idx[-1], bars["low"].values[idx[-1]])
    ax.set_xticks(ticks)
    ax.set_xticklabels(labels, fontsize=7.5)
    ax.tick_params(axis="x", length=0)
    ax.yaxis.tick_right()
    ax.set_ylabel("5-min", fontsize=8)
    ax.grid(axis="y", alpha=0.12)
    ax.margins(x=0.005, y=0.12)


def render_trade(pdf: PdfPages, m: dict, df: pd.DataFrame, row: pd.Series,
                 filings: pd.DataFrame) -> None:
    sym, date = row["symbol"], row["date"]
    sig = df.index.get_loc(date)
    entry, stop, risk = row["entry"], row["stop"], row["risk"]
    exits = scaleout_exits(df, sig, entry, stop, cap_date_of(m["close"].index, date))
    r = total_r(exits, entry, risk)

    lo = max(0, sig - BARS_BEFORE)
    hi = min(len(df), sig + 1 + BARS_AFTER)
    win = df.iloc[lo:hi].reset_index()
    p = sig - lo

    days = df.index[max(sig - INTRADAY_DAYS // 2, 0): sig + INTRADAY_DAYS // 2 + 1]
    bars = load_intraday(sym, days)      # empty before 29 Aug 2024 -> daily chart gets the page

    fig = plt.figure(figsize=(11.69, 8.27), layout="constrained")
    heights = [0.18, 3.6, 0.8] + ([2.0] if len(bars) else [])
    gs = fig.add_gridspec(len(heights), 1, height_ratios=heights)
    axf = fig.add_subplot(gs[0])
    axp = fig.add_subplot(gs[1], sharex=axf)
    axv = fig.add_subplot(gs[2], sharex=axf)

    draw_filing_strip(axf, win, filings)

    draw_candles(axp, win["open"].values, win["high"].values,
                 win["low"].values, win["close"].values)
    for col, (color, label) in SMA_STYLE.items():
        axp.plot(win.index, win[col], color=color, lw=0.9, alpha=0.85, label=label)
    for ax in (axp, axv):
        ax.axvspan(p - 0.5, p + 0.5, color="#0a7d32", alpha=0.12, lw=0)
    mark_entry(axp, p, win["low"].iloc[p])
    axp.yaxis.tick_right()
    axp.grid(axis="y", alpha=0.12)
    axp.margins(x=0.01, y=0.06)
    axp.tick_params(axis="x", bottom=False, labelbottom=False)

    vup = win["close"].values >= win["open"].values
    axv.bar(win.index, win["volume"] / 1e6, color=np.where(vup, UP, DOWN), width=0.7)
    axv.plot(win.index, win["vma50"] / 1e6, color="#666", lw=0.8)
    axv.set_ylim(0, 1.3 * win["volume"].iloc[max(p - 5, 0): p + 6].max() / 1e6)  # EP day stays readable
    axv.yaxis.tick_right()
    axv.set_ylabel("Vol (M)", fontsize=8)
    step = max(len(win) // 12, 1)
    ticks = list(range(0, len(win), step))
    axv.set_xticks(ticks)
    axv.set_xticklabels([win["date"].iloc[t].strftime("%b '%y") for t in ticks], fontsize=7.5)

    if len(bars):
        draw_intraday(fig.add_subplot(gs[3]), bars, days, df, sig)

    ctx = row.copy()
    ctx["breadth_score"] = m["score"].get(date, np.nan)
    ctx["rs_rank"] = m["rs"][sym].get(date, np.nan) if sym in m["rs"] else np.nan
    t2108 = m["t2108"].get(date, np.nan)
    vol_m = df["volume"].iloc[sig] / 1e6
    outcome = "WIN" if r > 0 else "LOSS"
    fig.suptitle(f"{sym}    EP {date:%d %b %Y}    +{row['gain_pct']:.1f}% on {vol_m:.0f}M shares"
                 f"    →  {outcome} {r:+.2f}R",
                 fontsize=12, fontweight="bold", color="#0a7d32" if r > 0 else "#c62828")
    rs = f"RS {ctx['rs_rank']:.0f}" if pd.notna(ctx["rs_rank"]) else "RS n/a"
    axf.set_title(
             f"Entry {entry:.2f} (EP-day close)   ·   {rs}   ·   "
             f"{regime_of(ctx)} market (breadth {ctx['breadth_score']:+.0f}/5, T2108 {t2108:.0f}%)"
             f"   ·   Filings near EP: {near_signal_filings(filings, date)}",
             fontsize=8, color="#444", loc="left")
    fig.legend(*axp.get_legend_handles_labels(), loc="outside lower right", ncol=4,
               fontsize=7, frameon=False)

    pdf.savefig(fig)
    plt.close(fig)



# ----------------------------------------------------------------------------
def build_year(year: int, events: pd.DataFrame, m: dict, filings: dict, limit: int) -> None:
    ev = events[events["date"].dt.year == year].sort_values("date")
    if limit:
        ev = ev.head(limit)
    if ev.empty:
        return
    os.makedirs(OUT_DIR, exist_ok=True)
    out = os.path.join(OUT_DIR, f"ep9m_trades_{year}.pdf")
    frames = {}
    with PdfPages(out) as pdf:
        for i, (_, row) in enumerate(ev.iterrows(), 1):
            if i % 50 == 0:
                print(f"  {year}: {i}/{len(ev)}", flush=True)
            sym = row["symbol"]
            if sym not in frames:
                frames[sym] = compact_ohlcv(m, sym)
            render_trade(pdf, m, frames[sym], row, filings.get(sym))
    print(f"  {year}: {len(ev)} trades -> {os.path.relpath(out)}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("years", nargs="*", type=int, help="years to render (default: all)")
    ap.add_argument("--limit", type=int, default=0, help="max trades per year (0 = all)")
    args = ap.parse_args()

    print("Loading study cache, events, filings...")
    m = common.load_cache()
    m["t2108"] = t2108_series(m["close"])
    events = pd.read_csv(EVENTS_CSV, parse_dates=["date"])
    verify_exits(events, m)
    filings = load_filings()

    for year in args.years or sorted(events["date"].dt.year.unique()):
        build_year(year, events, m, filings, args.limit)


if __name__ == "__main__":
    main()
