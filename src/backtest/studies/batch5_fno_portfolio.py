"""batch5_fno_portfolio.py — factory S5 for the two batch-5 F&O survivors.

Both setups reuse the event store's PRE-COMPUTED per-trade R (5-day time exit,
6% stop), so exits are not re-simulated here — this is only the PORTFOLIO layer:
sequence trades, size by risk, cap concurrent notional by leverage, charge costs,
compound a ₹10L book.

Setup S (SHORT the lone loser): four_pct_down, top-150 mcap, on a GREEN tape
  (net4 >= 18, the confirmed bucket-3 cell). R = stop_r_short.
Setup B (near-expiry bounce LONG): bounce, top-150 mcap, <=7 calendar days to
  monthly expiry. R = stop_r (long).

Leverage is REPORTED, not assumed: we size by fixed-fractional risk and record the
peak concurrent notional as a multiple of equity — that is how much leverage the
setup actually needs. Costs = per-trade stop distance -> cost in R (tighter stops
cost proportionally more), 0.10%/side (STT on the sell + brokerage + slippage;
conservative for liquid F&O). 5-day holds rarely cross an expiry, so no rollover.

Usage: ~/anaconda3/bin/python src/backtest/studies/batch5_fno_portfolio.py
"""
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "..", "..", "..", "research", "machine"))
import common  # noqa: E402
import engine as E  # noqa: E402

START_EQ = 1_000_000.0
COST_SIDE = 0.0010        # 0.10% per side (STT/brokerage/slippage)
HOLD_BARS = 5             # matches stop_r / stop_r_short horizon
LEVERAGE_CAP = 5.0        # F&O buying-power ceiling on a ₹10L cash base
RISK_LEVELS = [0.005, 0.0075, 0.01]


def _stop_pct(ev, m, side):
    """Actual stop distance as a fraction of entry, per trade (<= 6%)."""
    close = m["close"]
    idx = close.index.tz_localize(None) if close.index.tz is not None else close.index
    di = idx.get_indexer(pd.DatetimeIndex(ev["date"]).tz_localize(None))
    ci = close.columns.get_indexer(ev["symbol"])
    ok = (di >= 0) & (ci >= 0) & (di + 1 < len(close.index))
    O, L, H = m["open"].values, m["low"].values, m["high"].values
    out = np.full(len(ev), np.nan)
    d1 = np.minimum(di + 1, len(close.index) - 1)
    entry = O[d1, ci]
    if side == "long":
        stop = np.maximum(L[di, ci], entry * 0.94)
        out = (entry - stop) / entry
    else:
        stop = np.minimum(H[di, ci], entry * 1.06)
        out = (stop - entry) / entry
    out[~ok] = np.nan
    return out


def build_setups():
    ev = E.load_events()
    m = common.load_cache()

    # Setup S: four_pct_down, top150, net4 >= 18 (green tape), short
    s = ev[ev["trigger"] == "four_pct_down"].copy()
    s = E.apply_filters(s, [["mcap_rank", "<=", 150], ["market:net4", ">=", 18]])
    s = s.dropna(subset=["stop_r_short"]).reset_index(drop=True)
    s["R"] = s["stop_r_short"]
    s["stop_pct"] = _stop_pct(s, m, "short")
    s["side"] = "short"

    # Setup B: bounce, top150, <=7 days to expiry, long
    b = ev[ev["trigger"] == "bounce"].copy()
    b = E.apply_filters(b, [["mcap_rank", "<=", 150]])
    b["exp"] = E._expiry_dist(pd.DatetimeIndex(b["date"]))
    b = b[b["exp"] <= 7].dropna(subset=["stop_r"]).reset_index(drop=True)
    b["R"] = b["stop_r"]
    b["stop_pct"] = _stop_pct(b, m, "long")
    b["side"] = "long"

    for df in (s, b):
        df["date"] = pd.DatetimeIndex(df["date"]).tz_localize(None)
    return s, b, m["close"].index.tz_localize(None)


def simulate(trades, cal, risk_pct, lev_cap=LEVERAGE_CAP, cost_side=COST_SIDE,
             heat_cap=None):
    """Fixed-fractional risk, leverage-capped notional, optional portfolio-heat
    cap (sum of OPEN risk / equity). heat_cap is the real risk control for a
    leveraged, cluster-prone book; lev_cap only bounds margin usage."""
    trades = trades.dropna(subset=["R", "stop_pct"])
    trades = trades[trades["stop_pct"] > 0].sort_values("date").reset_index(drop=True)
    pos = pd.Series(range(len(cal)), index=cal)
    eq = START_EQ
    open_pos = []               # (exit_pos, notional, risk_amt)
    curve, taken, skipped = [], 0, 0
    peak_lev, peak_heat = 0.0, 0.0
    net_Rs = []
    for _, t in trades.iterrows():
        p = pos.get(t["date"], None)
        if p is None:
            continue
        open_pos = [(xp, n, rk) for xp, n, rk in open_pos if xp > p]
        used = sum(n for _, n, _ in open_pos)
        used_risk = sum(rk for _, _, rk in open_pos)
        risk_amt = risk_pct * eq
        notional = risk_amt / t["stop_pct"]
        if used + notional > lev_cap * eq:                 # margin-constrained
            skipped += 1
            continue
        if heat_cap and used_risk + risk_amt > heat_cap * eq:  # heat-constrained
            skipped += 1
            continue
        cost_R = 2 * cost_side / t["stop_pct"]
        net_R = t["R"] - cost_R
        pnl = net_R * risk_amt
        eq += pnl
        net_Rs.append(net_R)
        exit_pos = min(p + HOLD_BARS, len(cal) - 1)
        open_pos.append((exit_pos, notional, risk_amt))
        peak_lev = max(peak_lev, (used + notional) / eq)
        peak_heat = max(peak_heat, (used_risk + risk_amt) / eq)
        taken += 1
        curve.append((cal[exit_pos], eq))
    if not curve:
        return None
    c = pd.Series(dict(curve)).sort_index()
    yrs = (c.index[-1] - c.index[0]).days / 365.25
    cagr = (c.iloc[-1] / START_EQ) ** (1 / yrs) - 1
    dd = (c / c.cummax() - 1).min()
    return dict(risk=risk_pct, trades=taken, skipped=skipped, per_yr=taken / yrs,
                cagr=cagr, maxdd=dd, avg_net_R=float(np.mean(net_Rs)),
                win=float((np.array(net_Rs) > 0).mean()), peak_lev=peak_lev,
                peak_heat=peak_heat, final=c.iloc[-1], curve=c)


def report():
    s, b, cal = build_setups()
    print(f"Setup S (short green-tape breakdown): {len(s)} trades "
          f"{s['date'].min().date()}..{s['date'].max().date()}  "
          f"raw avg R {s['R'].mean():+.3f}")
    print(f"Setup B (near-expiry bounce long):    {len(b)} trades "
          f"{b['date'].min().date()}..{b['date'].max().date()}  "
          f"raw avg R {b['R'].mean():+.3f}")
    combo = pd.concat([s, b], ignore_index=True)
    cost = 0.0005   # F&O-realistic all-in (futures STT ~0.02% sell + brokerage + slippage)
    print(f"\n############ NO heat cap, cost {cost*100:.2f}%/side ############")
    for name, df in [("SHORT breakdown", s), ("EXPIRY bounce", b)]:
        print(f"\n=== {name} ===")
        print(f"{'risk/tr':>7s} {'/yr':>5s} {'CAGR':>7s} {'maxDD':>7s} "
              f"{'avgR':>6s} {'win%':>5s} {'pkHeat':>6s} {'skip':>5s}")
        for r in RISK_LEVELS:
            x = simulate(df, cal, r, cost_side=cost)
            if x:
                print(f"{r*100:6.2f}% {x['per_yr']:5.0f} {x['cagr']*100:6.1f}% "
                      f"{x['maxdd']*100:6.1f}% {x['avg_net_R']:+5.2f} "
                      f"{x['win']*100:4.0f}% {x['peak_heat']*100:5.0f}% {x['skipped']:5d}")

    print(f"\n############ SHORT breakdown WITH heat cap (cost {cost*100:.2f}%/side) ############")
    print(f"{'risk/tr':>7s} {'heatcap':>7s} {'/yr':>5s} {'CAGR':>7s} {'maxDD':>7s} "
          f"{'avgR':>6s} {'pkHeat':>6s} {'skip':>5s}")
    for r in (0.005, 0.0075):
        for hc in (0.04, 0.06, 0.08):
            x = simulate(s, cal, r, cost_side=cost, heat_cap=hc)
            if x:
                print(f"{r*100:6.2f}% {hc*100:6.0f}% {x['per_yr']:5.0f} "
                      f"{x['cagr']*100:6.1f}% {x['maxdd']*100:6.1f}% "
                      f"{x['avg_net_R']:+5.2f} {x['peak_heat']*100:5.0f}% {x['skipped']:5d}")


if __name__ == "__main__":
    report()
