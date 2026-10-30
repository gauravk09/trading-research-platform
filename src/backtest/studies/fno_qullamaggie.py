"""fno_qullamaggie.py — a FAITHFUL Qullamaggie breakout, with his native exits,
tested on the large-cap/F&O universe vs the mid-cap universe.

Setup (all conditions as-of the signal day's close — causal, no look-ahead):
  - PRIOR BIG MOVE: 3-month return (ret63) >= +30%  (Qullamaggie buys the leaders
    that are already up the most).
  - LEADER / near highs: within 15% of the 252-day high, and above the 50DMA.
  - TIGHT FLAG: 20-day range as-of YESTERDAY <= 25% (it consolidated before the break).
  - BREAKOUT: today's close > the highest HIGH of the prior 10 days (flag high),
    on volume >= its 50-day average.
  - dedupe: one entry per symbol per 15 trading days.

Entry: next day's OPEN. Initial stop: the breakout day's LOW (capped 15% under entry
for the huge-ADR names). NATIVE QULLAMAGGIE EXIT, simulated per trade forward:
  - sell HALF "into strength" at the first day the high touches entry + 1R (else at
    the 5-day close if 1R not reached);
  - TRAIL the other half on the 10- or 20-day SMA: exit at next open after a close
    below the MA; hard initial stop still applies; hard cap at 120 trading days.
Per-trade R = 0.5*(partial exit) + 0.5*(trail exit), in units of initial risk.

Universes (point-in-time mcap rank): F&O large-cap = rank<=150; mid-cap = 150<rank<=500.

Usage: ~/anaconda3/bin/python src/backtest/studies/fno_qullamaggie.py
"""
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "..", "..", "..", "research", "machine"))
import common  # noqa: E402
import batch5_two_sided as TS  # noqa: E402  (per-trade-hold portfolio sim)
import long_lab as LL  # noqa: E402  (era_stats)

CACHE = os.path.join(os.path.dirname(__file__), "..", "..", "..",
                     "output", "studies", "cache")


def detect(m):
    close, high, low, vol = m["close"], m["high"], m["low"], m["volume"]
    ret63 = close / close.shift(63) - 1.0
    hi10_prior = high.rolling(10).max().shift(1)          # prior 10-day high
    range20 = (high.rolling(20).max() - low.rolling(20).min()) / close
    vol50 = vol.rolling(50).mean()
    ma50 = close.rolling(50).mean()
    hh252 = high.rolling(252).max()
    liquid = (close * vol).rolling(20).mean() > 5e7       # >~₹5cr/day turnover

    mask = ((ret63 >= 0.30) &
            (close > hi10_prior) &
            (range20.shift(1) <= 0.25) &
            (vol >= vol50) &
            (close / hh252 - 1 >= -0.15) &
            (close > ma50) &
            liquid)
    # dedupe: one per symbol per 15 bars
    recent = mask.shift(1, fill_value=False).rolling(15, min_periods=1).sum() > 0
    mask = mask & ~recent
    d, s = np.where(mask.fillna(False).to_numpy())
    return pd.DataFrame({"date": close.index[d], "symbol": close.columns[s],
                         "di": d, "si": s})


def sim_exit(ev, m, ma_len):
    """Native Qullamaggie exit, per trade. Returns R and days held (causal)."""
    O, H, L, C = (m["open"].values, m["high"].values,
                  m["low"].values, m["close"].values)
    ma = m["close"].rolling(ma_len).mean().values
    n = len(C)
    R = np.full(len(ev), np.nan)
    held = np.full(len(ev), 0)
    for i, (d0, si) in enumerate(zip(ev["di"].to_numpy(), ev["si"].to_numpy())):
        if d0 + 1 >= n or np.isnan(O[d0 + 1, si]):
            continue
        entry = O[d0 + 1, si]
        stop = max(L[d0, si], entry * 0.85)               # breakout low, cap 15%
        risk = entry - stop
        if risk <= 0 or np.isnan(risk):
            continue
        target = entry + risk                              # +1R "into strength"
        half_done, half_r = False, 0.0
        r_total, k = None, None
        for k in range(1, 121):
            day = d0 + k
            if day >= n or np.isnan(C[day, si]):
                k -= 1
                break
            # hard stop first (gap-through fills at open)
            if L[day, si] <= stop:
                fill = min(O[day, si], stop)
                if half_done:
                    r_total = half_r + 0.5 * (fill - entry) / risk
                else:
                    r_total = (fill - entry) / risk
                break
            # partial: sell half into strength at +1R
            if not half_done and H[day, si] >= target:
                half_r = 0.5 * (target - entry) / risk
                half_done = True
            # trail the remainder on the MA (act on close, fill next open)
            if half_done and not np.isnan(ma[day, si]) and C[day, si] < ma[day, si]:
                exit_px = O[day + 1, si] if day + 1 < n else C[day, si]
                r_total = half_r + 0.5 * (exit_px - entry) / risk
                break
            # not-yet-partialed: also allow MA exit of the full position
            if not half_done and not np.isnan(ma[day, si]) and C[day, si] < ma[day, si]:
                exit_px = O[day + 1, si] if day + 1 < n else C[day, si]
                r_total = (exit_px - entry) / risk
                break
        if r_total is None:                                # hit 120-day cap
            day = min(d0 + 120, n - 1)
            if half_done:
                r_total = half_r + 0.5 * (C[day, si] - entry) / risk
            else:
                r_total = (C[day, si] - entry) / risk
        R[i] = r_total
        held[i] = max(k, 1)
    out = ev.copy()
    out["R"] = R
    out["stop_pct"] = (m["open"].values[np.minimum(ev["di"].to_numpy() + 1, len(C) - 1),
                                        ev["si"].to_numpy()]
                       - np.maximum(L[ev["di"].to_numpy(), ev["si"].to_numpy()],
                                    m["open"].values[np.minimum(ev["di"].to_numpy() + 1, len(C) - 1),
                                                     ev["si"].to_numpy()] * 0.85))
    entry_v = m["open"].values[np.minimum(ev["di"].to_numpy() + 1, len(C) - 1), ev["si"].to_numpy()]
    out["stop_pct"] = out["stop_pct"] / entry_v
    out["hold"] = held
    out["side"] = "long"
    out["date"] = pd.DatetimeIndex(out["date"]).tz_localize(None)
    return out.dropna(subset=["R", "stop_pct"])


def universe_mask(ev, lo, hi):
    rank = pd.read_parquet(os.path.join(CACHE, "mcap_rank.parquet"))
    rv = rank.index.tz_localize(None) if rank.index.tz is not None else rank.index
    ri = rv.get_indexer(pd.DatetimeIndex(ev["date"]).tz_localize(None))
    rc = rank.columns.get_indexer(ev["symbol"])
    rk = np.full(len(ev), np.nan)
    ok = (ri >= 0) & (rc >= 0)
    rk[ok] = rank.to_numpy()[ri[ok], rc[ok]]
    return (rk > lo) & (rk <= hi)


def report():
    m = common.load_cache()
    cal = m["close"].index.tz_localize(None)
    ev = detect(m)
    print(f"raw Qullamaggie breakout events: {len(ev)}")
    for ma_len in (10, 20):
        trades = sim_exit(ev, m, ma_len)
        print(f"\n===== MA{ma_len} trail =====  (raw avg R {trades['R'].mean():+.2f}, "
              f"median hold {int(trades['hold'].median())}d, win {(trades['R']>0).mean()*100:.0f}%)")
        print(f"{'universe':16s} {'risk':>5s} {'trades':>6s} {'/yr':>4s} {'CAGR':>7s} "
              f"{'maxDD':>7s} {'ret/DD':>6s} {'A/COVID/B/24+':>20s}")
        for uname, lo, hi in [("F&O large ≤150", 0, 150), ("mid 150-500", 150, 500)]:
            u = trades[universe_mask(trades, lo, hi)].reset_index(drop=True)
            if len(u) < 60:
                print(f"{uname:16s}  THIN ({len(u)} trades)")
                continue
            for risk in (0.005, 0.0075):
                x = TS.sim(u[["date", "symbol", "R", "stop_pct", "side", "hold"]],
                           cal, risk, lev_cap=2.5, heat_cap=0.08, cost=0.0005)
                if not x:
                    continue
                rdd = x["cagr"] / abs(x["maxdd"]) if x["maxdd"] else 0
                es = LL.era_stats(x["curve"])
                estr = f"{es.get('A15-19')}/{es.get('COVID20-22')}/{es.get('B23-26')}/{es.get('sub24-26')}"
                yrs = (cal[-1] - cal[0]).days / 365.25
                print(f"{uname:16s} {risk*100:4.2f}% {len(u):6d} {len(u)/yrs:4.0f} "
                      f"{x['cagr']*100:6.1f}% {x['maxdd']*100:6.1f}% {rdd:6.2f} {estr:>20s}")


if __name__ == "__main__":
    report()
