"""ryan_minervini_book.py — factory S5: the Ryan + Minervini book on a ₹10L account.

Spec: research/factory/ryan_minervini/SPEC.md (pre-registered — do not add
variants here without a new spec).

Entry = signal-day close, only if range_pos >= 0.75. Exits exactly as the two
source studies published. Tier gate from the PREVIOUS session's 5-signal
breadth score (house prev-close rule); breakouts allowed only in
AGGRESSIVE/NORMAL. Risk-based sizing at the live regime knobs, position value
capped at gross_cap/max_positions of equity, costs 0.2%/side, no leverage.

Usage:
    ~/anaconda3/bin/python src/backtest/studies/ryan_minervini_book.py
"""

import os
import sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common

# Frozen copy of the retired breadth-tier sizing (removed from src/regime.py
# 2026-09-28) so this S5 backtest still reproduces what it measured.
TIER_KNOBS = {
    "AGGRESSIVE": {"risk_per_trade_pct": 0.50, "max_open_positions": 6,
                   "max_gross_exposure_pct": 100, "leverage_ok": True,
                   "allowed_entries": ["breakout", "episodic_pivot", "anticipation"]},
    "NORMAL":     {"risk_per_trade_pct": 0.35, "max_open_positions": 4,
                   "max_gross_exposure_pct": 75, "leverage_ok": False,
                   "allowed_entries": ["breakout", "episodic_pivot", "anticipation"]},
    "CAUTIOUS":   {"risk_per_trade_pct": 0.25, "max_open_positions": 2,
                   "max_gross_exposure_pct": 40, "leverage_ok": False,
                   "allowed_entries": ["episodic_pivot", "anticipation"]},
    "DEFENSIVE":  {"risk_per_trade_pct": 0.0, "max_open_positions": 0,
                   "max_gross_exposure_pct": 0, "leverage_ok": False,
                   "allowed_entries": []},
}


def tier_for_score(score: int) -> str:
    if score >= 3:
        return "AGGRESSIVE"
    if score >= 1:
        return "NORMAL"
    if score >= -1:
        return "CAUTIOUS"
    return "DEFENSIVE"

OUT = common.OUTPUT_DIR
START_EQ = 1_000_000.0
COST = 0.002
RANGE_POS_MIN = 0.75
NAN_FORCE_EXIT = 20

RYAN = {"stop_pct": 0.07, "trail_arm": 1.20, "ma": 50, "max_hold": 120}
MINER = {"stop_cap": 0.92, "ma": 20, "max_hold": 60}


def load_events(m):
    close = m["close"]
    dates = close.index
    frames = []
    for name, strat in [("ryan_52wk_high_events.csv", "ryan"),
                        ("minervini_trend_template_events.csv", "minervini")]:
        df = pd.read_csv(os.path.join(OUT, name), parse_dates=["date"])
        if df["date"].dt.tz is None:
            df["date"] = df["date"].dt.tz_localize(dates.tz)
        else:
            df["date"] = df["date"].dt.tz_convert(dates.tz)
        frames.append(df[["date", "symbol", "rs_rank"]].assign(strategy=strat))
    ev = pd.concat(frames, ignore_index=True)
    ev["pos"] = dates.get_indexer(ev["date"])
    ev["col"] = close.columns.get_indexer(ev["symbol"])
    ev = ev[(ev["pos"] >= 0) & (ev["col"] >= 0)]
    # same symbol, same day, both strategies -> ryan takes it (spec)
    ev = ev.sort_values("strategy", ascending=False)  # ryan after minervini
    ev = ev.drop_duplicates(["pos", "col"], keep="last")
    ev["rs_rank"] = ev["rs_rank"].fillna(0)
    return {p: g.sort_values("rs_rank", ascending=False)
            for p, g in ev.groupby("pos")}


class Position:
    def __init__(self, strat, si, shares, entry, stop, di):
        self.strat, self.si = strat, si
        self.shares0 = self.shares = shares
        self.entry, self.stop = entry, stop
        self.risk_value = shares * (entry - stop)
        self.buy_cost = shares * entry * (1 + COST)
        self.realized = 0.0
        self.opened, self.bars = di, 0
        self.armed = False       # ryan trail armed
        self.partial = False     # minervini 1/3 taken
        self.last_px = entry
        self.nan_streak = 0


def knobs_for(variant, tier):
    """(allowed, risk_pct, max_pos, gross_pct) per spec's variant table."""
    if variant == "normal_fixed":
        return True, 0.35, 4, 75.0
    allowed = "breakout" in TIER_KNOBS[tier]["allowed_entries"]
    if variant == "risk1":
        return allowed, 1.0, 6, 100.0
    k = TIER_KNOBS[tier]
    return (allowed, k["risk_per_trade_pct"], k["max_open_positions"],
            float(k["max_gross_exposure_pct"]))


def run(variant, m, by_day, tiers, arrays):
    O, H, L, C, MA20, MA50 = arrays
    dates = m["close"].index
    n_bars = len(dates)
    cash, positions = START_EQ, {}
    eq_curve = np.zeros(n_bars)
    inv_curve = np.zeros(n_bars)
    trades = []
    funnel = dict(events=0, range_gate=0, tier=0, dup=0, slots=0,
                  capital=0, bad_stop=0, taken=0, value_capped=0)

    def sell(p, px, frac=1.0):
        sh = p.shares if frac >= 1.0 else p.shares0 * frac
        sh = min(sh, p.shares)
        proceeds = sh * px * (1 - COST)
        p.shares -= sh
        p.realized += proceeds
        return proceeds

    def close_out(p, sym, di, reason):
        pnl = p.realized - p.buy_cost
        trades.append(dict(symbol=sym, strategy=p.strat,
                           entry_date=dates[p.opened], exit_date=dates[di],
                           reason=reason, pnl=pnl, r=pnl / p.risk_value,
                           hold=p.bars))
        del positions[sym]

    for di in range(n_bars):
        # 1) manage existing positions on today's bar
        for sym in list(positions):
            p = positions[sym]
            s = p.si
            c = C[di, s]
            if np.isnan(c):
                p.nan_streak += 1
                if p.nan_streak >= NAN_FORCE_EXIT:
                    cash += sell(p, p.last_px)
                    close_out(p, sym, di, "delisted")
                continue
            p.nan_streak = 0
            p.bars += 1
            o, h, l = O[di, s], H[di, s], L[di, s]
            if p.strat == "ryan":
                if not p.armed:
                    if not np.isnan(o) and o <= p.stop:
                        cash += sell(p, o); close_out(p, sym, di, "stop_gap"); continue
                    if not np.isnan(l) and l <= p.stop:
                        cash += sell(p, p.stop); close_out(p, sym, di, "stop"); continue
                    if c >= p.entry * RYAN["trail_arm"]:
                        p.armed = True
                else:
                    ma = MA50[di, s]
                    if not np.isnan(ma) and c < ma:
                        cash += sell(p, c); close_out(p, sym, di, "trail_ma50"); continue
                if p.bars >= RYAN["max_hold"]:
                    cash += sell(p, c); close_out(p, sym, di, "time"); continue
            else:
                if not np.isnan(o) and o <= p.stop:
                    cash += sell(p, o); close_out(p, sym, di, "stop_gap"); continue
                if not np.isnan(l) and l <= p.stop:
                    cash += sell(p, p.stop); close_out(p, sym, di, "stop"); continue
                if not p.partial and not np.isnan(h) \
                        and h >= p.entry + 2 * (p.entry - p.stop):
                    cash += sell(p, p.entry + 2 * (p.entry - p.stop), frac=1 / 3)
                    p.partial = True
                    p.stop = p.entry
                ma = MA20[di, s]
                if not np.isnan(ma) and c < ma:
                    cash += sell(p, c); close_out(p, sym, di, "trail_ma20"); continue
                if p.bars >= MINER["max_hold"]:
                    cash += sell(p, c); close_out(p, sym, di, "time"); continue
            p.last_px = c

        # 2) new entries at today's close
        mtm = sum(p.shares * p.last_px for p in positions.values())
        equity = cash + mtm
        today = by_day.get(di)
        if today is not None:
            tier = tiers[di]
            allowed, risk_pct, max_pos, gross_pct = knobs_for(variant, tier)
            for ev in today.itertuples():
                funnel["events"] += 1
                if not allowed:
                    funnel["tier"] += 1; continue
                s = ev.col
                c, h, l = C[di, s], H[di, s], L[di, s]
                if np.isnan(c) or np.isnan(h) or np.isnan(l) or h <= l \
                        or (c - l) / (h - l) < RANGE_POS_MIN:
                    funnel["range_gate"] += 1; continue
                if ev.symbol in positions:
                    funnel["dup"] += 1; continue
                if len(positions) >= max_pos:
                    funnel["slots"] += 1; continue
                if ev.strategy == "ryan":
                    stop = c * (1 - RYAN["stop_pct"])
                else:
                    lo5 = np.nanmin(L[max(0, di - 4):di + 1, s])
                    stop = max(lo5, c * MINER["stop_cap"])
                if not np.isfinite(stop) or c <= stop:
                    funnel["bad_stop"] += 1; continue
                shares = equity * risk_pct / 100 / (c - stop)
                cap = equity * gross_pct / 100 / max_pos
                if shares * c > cap:
                    shares = cap / c
                    funnel["value_capped"] += 1
                headroom = equity * gross_pct / 100 - mtm
                outlay = shares * c * (1 + COST)
                if shares * c > headroom or outlay > cash:
                    funnel["capital"] += 1; continue
                cash -= outlay
                positions[ev.symbol] = Position(ev.strategy, s, shares, c, stop, di)
                funnel["taken"] += 1
                mtm += shares * c
        eq_curve[di] = cash + sum(p.shares * p.last_px for p in positions.values())
        inv_curve[di] = sum(p.shares * p.last_px for p in positions.values())

    for sym in list(positions):
        p = positions[sym]
        cash += sell(p, p.last_px)
        close_out(p, sym, n_bars - 1, "open_at_end")

    eq = pd.Series(eq_curve, index=dates)
    tr = pd.DataFrame(trades).sort_values("exit_date")
    report(variant, eq, pd.Series(inv_curve, index=dates), tr, funnel)
    tr.to_csv(os.path.join(OUT, f"ryan_minervini_book_trades_{variant}.csv"),
              index=False)
    chart(variant, eq)
    return eq, tr


def era_line(eq, a, b, label):
    seg = eq.loc[a:b]
    if len(seg) < 2 or seg.iloc[0] <= 0:
        return
    years = (seg.index[-1] - seg.index[0]).days / 365.25
    tot = seg.iloc[-1] / seg.iloc[0] - 1
    cagr = (1 + tot) ** (1 / years) - 1 if years > 0.5 else tot
    dd = (seg / seg.cummax() - 1).min()
    print(f"  {label:<18} {tot * 100:+7.1f}%  ({cagr * 100:+5.1f}%/yr)  "
          f"maxDD {dd * 100:5.1f}%")


def report(variant, eq, inv, tr, funnel):
    years = (eq.index[-1] - eq.index[0]).days / 365.25
    tot = eq.iloc[-1] / eq.iloc[0] - 1
    cagr = (1 + tot) ** (1 / years) - 1
    dd = (eq / eq.cummax() - 1).min()
    daily = eq.pct_change().dropna()
    sharpe = daily.mean() / daily.std() * np.sqrt(252) if daily.std() > 0 else 0
    print(f"\n===== variant: {variant} =====")
    print(f"₹{START_EQ:,.0f} → ₹{eq.iloc[-1]:,.0f}   total {tot * 100:+.1f}%   "
          f"CAGR {cagr * 100:+.2f}%   (₹{(eq.iloc[-1] - eq.iloc[0]) / years:,.0f}/yr avg)")
    print(f"maxDD {dd * 100:.1f}%   Sharpe {sharpe:.2f}   "
          f"avg invested {(inv / eq).mean() * 100:.1f}%   "
          f"days with 0 positions {(inv == 0).mean() * 100:.0f}%")
    f = funnel
    print(f"funnel: events {f['events']}  -range {f['range_gate']}  "
          f"-tier {f['tier']}  -dup {f['dup']}  -slots {f['slots']}  "
          f"-capital {f['capital']}  -badstop {f['bad_stop']}  "
          f"taken {f['taken']}  (value-capped {f['value_capped']})")
    if len(tr):
        r = tr["r"]
        wins, losses = r[r > 0].sum(), -r[r < 0].sum()
        pf = wins / losses if losses > 0 else np.inf
        streak = worst = 0
        for x in r:
            streak = streak + 1 if x < 0 else 0
            worst = max(worst, streak)
        print(f"trades {len(tr)}  win {(r > 0).mean() * 100:.1f}%  "
              f"avg {r.mean():+.2f}R  med {r.median():+.2f}R  PF {pf:.2f}  "
              f"hold {tr['hold'].mean():.0f}d  worst loss-streak {worst}")
        for strat, g in tr.groupby("strategy"):
            print(f"  {strat:<10} n={len(g):<4} win {(g['r'] > 0).mean() * 100:4.1f}%  "
                  f"avg {g['r'].mean():+.2f}R  pnl ₹{g['pnl'].sum():,.0f}")
    print("eras:")
    era_line(eq, None, "2019-12-31", "A 2015-19")
    era_line(eq, "2020-01-01", "2022-12-31", "COVID 2020-22")
    era_line(eq, "2023-01-01", None, "B 2023-26")
    era_line(eq, "2024-01-01", None, "2024-26 sub-era")
    yearly = eq.resample("YE").last().pct_change().dropna() * 100
    print("yearly: " + "  ".join(f"{d.year} {v:+.1f}%" for d, v in yearly.items()))


def chart(variant, eq):
    dd = (eq / eq.cummax() - 1) * 100
    fig, ax = plt.subplots(2, 1, figsize=(10, 6), sharex=True,
                           gridspec_kw={"height_ratios": [3, 1]})
    ax[0].plot(eq.index, eq.values / 1e5, color="#1a3d6e", lw=1.2)
    ax[0].set_title(f"Ryan+Minervini book — {variant} — equity (₹ lakh)",
                    fontsize=10)
    ax[0].grid(alpha=0.3)
    ax[1].fill_between(dd.index, dd.values, 0, color="#a83232", alpha=0.6)
    ax[1].set_title("Drawdown (%)", fontsize=10)
    ax[1].grid(alpha=0.3)
    fig.tight_layout()
    fig.savefig(os.path.join(OUT, f"ryan_minervini_book_equity_{variant}.png"),
                dpi=110)
    plt.close(fig)


def main():
    m = common.load_cache()
    close = m["close"]
    print(f"Cache: {close.shape[1]} symbols, "
          f"{close.index.min().date()} → {close.index.max().date()}")
    arrays = (m["open"].to_numpy(), m["high"].to_numpy(),
              m["low"].to_numpy(), m["close"].to_numpy(),
              close.rolling(20).mean().to_numpy(),
              close.rolling(50).mean().to_numpy())
    by_day = load_events(m)
    n_ev = sum(len(g) for g in by_day.values())
    print(f"Events after collision-dedup: {n_ev}")
    prev_score = m["score"].reindex(close.index).shift(1).fillna(0)
    tiers = [tier_for_score(int(s)) for s in prev_score]
    for variant in ["knobs", "normal_fixed", "risk1"]:
        run(variant, m, by_day, tiers, arrays)


if __name__ == "__main__":
    main()
