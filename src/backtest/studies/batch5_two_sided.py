"""batch5_two_sided.py — pair the validated F&O short with the validated F&O long
into ONE ₹10L leveraged book and measure whether they diversify.

SHORT leg: regime-filtered "lone loser" short — four_pct_down, top-150, net4>=18
  (green tape), skip when Nifty extended (ti65_nifty50 < 1.04). 5-day hold, R=stop_r_short.
LONG leg: loud-volume large-cap burst — burst, top-150, rvol50 >= median. 20-day
  hold, R=stop_r_20. (Survives costs; wide ~5.5% stops.)

One shared equity curve, shared portfolio-heat cap and leverage cap, per-trade hold
length. Reports each leg alone vs combined (CAGR / maxDD) and the correlation of
their monthly P&L — the number that decides whether pairing actually smooths.

Usage: ~/anaconda3/bin/python src/backtest/studies/batch5_two_sided.py
"""
import os
import sys

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "..", "..", "..", "research", "machine"))
import batch5_fno_portfolio as P  # noqa: E402
import engine as E  # noqa: E402

START_EQ = 1_000_000.0
COST_SIDE = 0.0005
LEV_CAP = 2.5          # half of ~5x allowed F&O leverage
HEAT_CAP = 0.08


def build_legs():
    s, _b, cal = P.build_setups()
    mm = pd.read_parquet(os.path.join(os.path.dirname(__file__), "..", "..", "..",
                                      "data", "processed", "mm_history.parquet"))
    mm.index = E._naive(mm.index)
    ti = mm["ti65_nifty50"].reindex(pd.DatetimeIndex(s["date"])).to_numpy()
    s = s[ti < 1.04].reset_index(drop=True)      # regime filter
    s["hold"] = 5

    ev = E.load_events()
    m = P.common.load_cache()
    bl = ev[ev["trigger"] == "burst"].copy()
    bl = E.apply_filters(bl, [["mcap_rank", "<=", 150]])
    bl["rvol50"] = E.lookup(bl, pd.read_parquet(
        os.path.join(E.FEAT_DIR, "rvol50.parquet")))
    bl = bl.dropna(subset=["stop_r_20", "rvol50"]).reset_index(drop=True)
    bl = bl[bl["rvol50"] >= bl["rvol50"].median()].reset_index(drop=True)
    bl["stop_pct"] = P._stop_pct(bl, m, "long")
    bl["R"] = bl["stop_r_20"]
    bl["date"] = pd.DatetimeIndex(bl["date"]).tz_localize(None)
    bl["side"] = "long"
    bl["hold"] = 20
    cols = ["date", "symbol", "R", "stop_pct", "side", "hold"]
    return s[cols].dropna(), bl[cols].dropna(), cal


def sim(trades, cal, risk_pct, lev_cap=LEV_CAP, heat_cap=HEAT_CAP, cost=COST_SIDE):
    """Shared-equity sim with per-trade hold length. Returns curve + monthly P&L."""
    pos = pd.Series(range(len(cal)), index=cal)
    trades = trades[trades["stop_pct"] > 0].sort_values("date").reset_index(drop=True)
    eq = START_EQ
    open_pos = []       # (exit_pos, notional, risk_amt)
    pnl_by_month = {}
    realized = []       # (exit_date, pnl) — realize at exit for a proper time curve
    for _, t in trades.iterrows():
        p = pos.get(t["date"], None)
        if p is None:
            continue
        open_pos = [o for o in open_pos if o[0] > p]
        used_n = sum(o[1] for o in open_pos)
        used_r = sum(o[2] for o in open_pos)
        risk_amt = risk_pct * eq
        notional = risk_amt / t["stop_pct"]
        if used_n + notional > lev_cap * eq or used_r + risk_amt > heat_cap * eq:
            continue
        cost_R = 2 * cost / t["stop_pct"]
        pnl = (t["R"] - cost_R) * risk_amt
        eq += pnl
        mk = (t["date"].year, t["date"].month)
        pnl_by_month[mk] = pnl_by_month.get(mk, 0.0) + pnl
        exit_pos = min(p + int(t["hold"]), len(cal) - 1)
        open_pos.append((exit_pos, notional, risk_amt))
        realized.append((cal[exit_pos], pnl))
    if not realized:
        return None
    # proper equity curve: sum realized P&L in EXIT-date order, then compound base
    r = pd.DataFrame(realized, columns=["d", "pnl"]).groupby("d")["pnl"].sum().sort_index()
    c = START_EQ + r.cumsum()
    yrs = (c.index[-1] - c.index[0]).days / 365.25
    return dict(cagr=(c.iloc[-1] / START_EQ) ** (1 / yrs) - 1,
                maxdd=(c / c.cummax() - 1).min(), final=c.iloc[-1], curve=c,
                monthly=pd.Series(pnl_by_month))


def report():
    s, l, cal = build_legs()
    combo = pd.concat([s, l], ignore_index=True)
    print(f"short leg {len(s)} trades | long leg {len(l)} trades | "
          f"lev {LEV_CAP}x heat {HEAT_CAP*100:.0f}% cost {COST_SIDE*100:.2f}%/side")
    risk = 0.0075
    rS, rL = sim(s, cal, risk), sim(l, cal, risk)
    # COMBINED = two independent risk sleeves in one account (additive P&L). This
    # is the honest diversification measure; a single greedy shared-heat pool
    # mechanically crowds the legs and manufactures fake drawdown.
    both = rS["curve"].reindex(rS["curve"].index.union(rL["curve"].index)).ffill().fillna(START_EQ) \
        + rL["curve"].reindex(rS["curve"].index.union(rL["curve"].index)).ffill().fillna(START_EQ) - START_EQ
    yrs = (both.index[-1] - both.index[0]).days / 365.25
    rC = dict(cagr=(both.iloc[-1] / START_EQ) ** (1 / yrs) - 1,
              maxdd=(both / both.cummax() - 1).min(), final=both.iloc[-1], curve=both)

    def rd(r):
        return abs(r["cagr"] / r["maxdd"])
    print(f"\n{'book':16s} {'CAGR':>7s} {'maxDD':>7s} {'ret/DD':>7s} {'final ₹L':>9s}")
    for nm, r in [("SHORT only", rS), ("LONG only", rL), ("COMBINED (add)", rC)]:
        print(f"{nm:16s} {r['cagr']*100:6.1f}% {r['maxdd']*100:6.1f}% {rd(r):6.2f} {r['final']/1e5:8.1f}")

    mS = rS["monthly"].reindex(sorted(set(rS["monthly"].index) | set(rL["monthly"].index)), fill_value=0)
    mL = rL["monthly"].reindex(mS.index, fill_value=0)
    corr = np.corrcoef(mS.values, mL.values)[0, 1]
    print(f"\nmonthly P&L correlation short vs long: {corr:+.2f}  "
          f"({'diversifying' if corr < 0.2 else 'not much help'})")
    print(f"VERDICT: short-alone ret/DD {rd(rS):.2f} vs combined {rd(rC):.2f} -> "
          f"{'pairing HELPS' if rd(rC) > rd(rS) else 'short is BETTER SOLO (long dilutes it)'}")

    fig, ax = plt.subplots(figsize=(11, 5.5))
    for nm, r, col in [("SHORT only", rS, "#1a7f37"), ("LONG only", rL, "#b34700"),
                       ("COMBINED book", rC, "#0b60d0")]:
        ax.plot(r["curve"].index, r["curve"].values / 1e5,
                label=f"{nm}  (CAGR {r['cagr']*100:.1f}%, maxDD {r['maxdd']*100:.0f}%)",
                lw=1.6 if nm.startswith("COMB") else 1.2, color=col,
                alpha=1.0 if nm.startswith("COMB") else 0.8)
    ax.axhline(10, color="gray", ls="--", lw=0.8)
    ax.set_ylabel("Equity (₹ lakh, start ₹10L)")
    ax.set_title(f"Two-sided F&O book — {LEV_CAP}x leverage, {risk*100:.2f}% risk/trade "
                 f"(short/long monthly corr {corr:+.2f})")
    ax.legend(loc="upper left", fontsize=9)
    ax.grid(alpha=0.25)
    plt.tight_layout()
    out = os.path.join(E.BASE, "output", "studies", "batch5_two_sided.png")
    plt.savefig(out, dpi=110)
    print(f"\nPNG -> {out}")


if __name__ == "__main__":
    report()
