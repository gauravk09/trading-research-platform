"""
high_tight_flag.py — Does the High Tight Flag breakout carry an edge on NSE?

Pattern: William O'Neil's rarest continuation pattern ("How to Make Money in
Stocks"): a ~100% run in <= 8 weeks (the pole), a tight <= 25% flag of 1-4
weeks on contracting volume, then a volume breakout above the flag high.
Dan Zanger traded this pattern to a verified $11k -> $42M run in 1998-2000.

Encoding (per bar t, all reference data as of t-1 — no look-ahead):
  - hi40   = rolling 40-bar max HIGH as of t-1 (the run high)
  - lo40c  = rolling 40-bar min CLOSE as of t-1 (the pole base)
  - Pole:  hi40 / lo40c >= 1.90 (STRICT) or 1.60 (LOOSE), and the bar that
    set hi40 (the run-high bar P) sits 5-20 bars before t.
  - Flag:  min LOW over bars P+1 .. t-1 >= 0.75 * hi40, and the 5-day mean
    volume as of t-1 is below the 5-day mean volume as of bar P (contraction).
  - Event: close(t) > max HIGH over bars P+1 .. t-1 (the flag high, run-high
    bar excluded; breakout above hi40 itself is allowed), with
    volume(t) >= 1.5 * 50-day mean volume as of t-1.
  - Tradeable at t (common.tradeable_mask); one event per symbol per 20 bars.

STRICT (pole >= +90%) is the O'Neil definition; if it yields < 30 events the
LOOSE variant (pole >= +60%) is reported as primary.

Rule-exit simulation (per event, max 60 bars):
  Entry D+1 open. Stop = flag low, capped at entry * 0.90. Partial 1/3 at
  +2R touch, stop to breakeven. Trail: first close below the 10-day MA exits
  the remainder. Gap through stop fills at open; stop wins on ambiguity.
  Force-exit at bar 60 close.

Usage:
    ~/anaconda3/bin/python src/backtest/studies/high_tight_flag.py
"""

import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(__file__))

import common

FLAG_MIN, FLAG_MAX = 5, 20          # run-high bar sits 5-20 bars before t
FLAG_DEPTH = 0.75                    # flag low >= 75% of run high
VOL_MULT = 1.5                       # breakout volume vs 50d mean
DEDUP_BARS = 20
SIM_MAX_BARS = 60


def find_events_mask(m: dict, pole_mult: float):
    """Boolean event mask plus aligned extras (pole %, flag depth/low/high)."""
    high, low, close, volume = m["high"], m["low"], m["close"], m["volume"]

    hi40 = high.rolling(40).max().shift(1)
    lo40c = close.rolling(40).min().shift(1)
    pole_ok = (hi40 / lo40c) >= pole_mult

    # Bars since the last bar that set (or tied) the 40-bar high.
    is_rh = high.eq(high.rolling(40).max()) & high.notna()
    row = np.arange(len(high))[:, None] * np.ones((1, high.shape[1]))
    pos = pd.DataFrame(np.where(is_rh, row, np.nan),
                       index=high.index, columns=high.columns).ffill()
    bs = pd.DataFrame(row - pos.values, index=high.index, columns=high.columns)
    bars_ago = bs.shift(1) + 1
    # bars_ago(t) = t - P, where P = last run-high bar as of t-1.

    vol5 = volume.rolling(5).mean()
    vol50_prev = volume.rolling(50).mean().shift(1)

    # Variable-length flag window (bars P+1 .. t-1 has length bars_ago - 1):
    # select the rolling stat of matching window length per cell.
    flag_low = pd.DataFrame(np.nan, index=high.index, columns=high.columns)
    flag_high = flag_low.copy()
    pole_vol5 = flag_low.copy()
    for k in range(FLAG_MIN, FLAG_MAX + 1):    # k = bars_ago(t)
        sel = bars_ago == k
        w = k - 1                              # flag bars P+1..t-1
        flag_low = flag_low.mask(sel, low.rolling(w).min().shift(1))
        flag_high = flag_high.mask(sel, high.rolling(w).max().shift(1))
        pole_vol5 = pole_vol5.mask(sel, vol5.shift(k))   # 5d mean vol at bar P

    flag_ok = flag_low >= FLAG_DEPTH * hi40
    vol_contract = vol5.shift(1) < pole_vol5
    breakout = (close > flag_high) & (volume >= VOL_MULT * vol50_prev)

    mask = (pole_ok & flag_ok & vol_contract & breakout
            & common.tradeable_mask(close, volume))
    extras = {
        "pole_pct": (hi40 / lo40c - 1) * 100,
        "flag_depth_pct": (1 - flag_low / hi40) * 100,
        "flag_len": bars_ago - 1,
        "flag_low": flag_low,
        "run_high": hi40,
    }
    return mask.fillna(False), extras


def dedupe_mask(mask: pd.DataFrame, gap: int = DEDUP_BARS) -> pd.DataFrame:
    out = mask.copy()
    for col in mask.columns[mask.any().values]:
        idx = np.flatnonzero(mask[col].values)
        last = -gap - 1
        for i in idx:
            if i - last < gap:
                out.iloc[i, out.columns.get_loc(col)] = False
            else:
                last = i
    return out


def build_events(m: dict, pole_mult: float) -> pd.DataFrame:
    mask, extras = find_events_mask(m, pole_mult)
    mask = dedupe_mask(mask)
    events = common.events_from_mask(mask, m)
    di, si = np.where(mask.values)
    for name, frame in extras.items():
        events[name] = frame.values[di, si]
    return common.add_regime_and_rs_buckets(events)


def simulate_exits(events: pd.DataFrame, m: dict) -> pd.DataFrame:
    """Per-event rule-exit loop. Returns one row per simulated trade."""
    close, open_, high, low = m["close"], m["open"], m["high"], m["low"]
    ma10 = close.rolling(10).mean()
    date_pos = {d: i for i, d in enumerate(close.index)}
    n_bars = len(close.index)
    arrays = {c: (open_[c].values, high[c].values, low[c].values,
                  close[c].values, ma10[c].values)
              for c in events["symbol"].unique()}

    rows = []
    for ev in events.itertuples():
        o_a, h_a, l_a, c_a, ma_a = arrays[ev.symbol]
        j0 = date_pos[ev.date] + 1
        if j0 >= n_bars or np.isnan(o_a[j0]):
            continue
        entry = o_a[j0]
        stop = max(ev.flag_low, entry * 0.90)
        if stop >= entry:
            continue
        r_unit = entry - stop
        target = entry + 2 * r_unit
        frac, realized, partial = 1.0, 0.0, False
        j_exit, exit_px = None, None
        for j in range(j0, min(j0 + SIM_MAX_BARS, n_bars)):
            if np.isnan(c_a[j]):
                continue                       # halted day
            if o_a[j] <= stop:                 # gap through stop
                exit_px, j_exit = o_a[j], j
                break
            if l_a[j] <= stop:                 # stop wins on ambiguity
                exit_px, j_exit = stop, j
                break
            if not partial and h_a[j] >= target:
                realized += (1 / 3) * (target - entry) / r_unit
                frac -= 1 / 3
                partial, stop = True, entry
            if c_a[j] < ma_a[j]:               # trail: close below 10d MA
                exit_px, j_exit = c_a[j], j
                break
        if j_exit is None:                     # force-exit at last valid close
            for j in range(min(j0 + SIM_MAX_BARS, n_bars) - 1, j0 - 1, -1):
                if not np.isnan(c_a[j]):
                    exit_px, j_exit = c_a[j], j
                    break
            if j_exit is None:
                continue
        total_r = realized + frac * (exit_px - entry) / r_unit
        rows.append({"symbol": ev.symbol, "date": ev.date, "regime": ev.regime,
                     "total_r": total_r, "hold_days": j_exit - j0 + 1})
    return pd.DataFrame(rows)


def print_sim_report(sim: pd.DataFrame) -> None:
    def line(label, grp):
        if len(grp) == 0:
            print(f"  {label:<22} n=0")
            return
        r = grp["total_r"]
        pos, neg = r[r > 0].sum(), r[r < 0].sum()
        pf = pos / abs(neg) if neg < 0 else np.inf
        print(f"  {label:<22} n={len(grp):<5} win {(r > 0).mean() * 100:4.1f}%  "
              f"avg {r.mean():+5.2f}R  med {r.median():+5.2f}R  "
              f"PF {pf:4.2f}  hold {grp['hold_days'].mean():4.1f}d")

    line("all", sim)
    for regime in ["good", "neutral", "bad"]:
        line(regime, sim[sim["regime"] == regime])


def print_horizon_block(events: pd.DataFrame, label: str) -> None:
    print(f"\n[{label}] Baseline forward returns (D+1 open entry), n={len(events)}:")
    for n in common.HORIZONS:
        print(f"  D+{n:<3} {common.stat_line(events[f'ret_o{n}'])}")


def main():
    print("Loading study cache...")
    m = common.load_cache()

    print("Scanning STRICT High Tight Flags (pole >= +90% in 40 bars)...")
    strict = build_events(m, 1.90)
    print(f"  {len(strict)} strict events")
    print("Scanning LOOSE variant (pole >= +60% in 40 bars)...")
    loose = build_events(m, 1.60)
    # Strict events are a subset of loose; tag them in the loose frame.
    strict_keys = set(zip(strict["symbol"], strict["date"]))
    loose["strict"] = [(s, d) in strict_keys
                       for s, d in zip(loose["symbol"], loose["date"])]
    print(f"  {len(loose)} loose events")

    primary, primary_name = (loose, "LOOSE (pole >= +60%)") \
        if len(strict) < 30 else (strict, "STRICT (pole >= +90%)")

    print(f"\n{'=' * 76}")
    print(f"HIGH TIGHT FLAG STUDY — {primary['date'].min().date()} → "
          f"{primary['date'].max().date()}")
    print(f"{'=' * 76}")
    print(f"STRICT events: {len(strict)} | LOOSE events: {len(loose)} | "
          f"primary variant: {primary_name}")
    print("Returns are from D+1 OPEN entry to D+n close.")

    print_horizon_block(primary, f"1: PRIMARY {primary_name}")
    common.print_standard_segments(primary)

    other, other_name = (strict, "STRICT (pole >= +90%)") \
        if primary is loose else (loose, "LOOSE (pole >= +60%)")
    print(f"\n[2] {other_name} — sensitivity variant, n={len(other)}:")
    for n in common.HORIZONS:
        print(f"  D+{n:<3} {common.stat_line(other[f'ret_o{n}'])}")

    print("\n[3] Pole size (loose set — the only set where it varies):")
    loose["pole_bucket"] = pd.cut(loose["pole_pct"], [0, 90, np.inf],
                                  labels=["pole 60-90%", "pole >90%"])
    common.print_table(loose, "pole_bucket")

    print("\n[4] Flag depth (primary variant):")
    primary["depth_bucket"] = pd.cut(primary["flag_depth_pct"], [0, 15, 25],
                                     labels=["flag <15%", "flag 15-25%"])
    common.print_table(primary, "depth_bucket")

    print("\n[5] Rule-exit simulation (primary variant): entry D+1 open, "
          "stop = flag low")
    print("    (capped -10%), 1/3 off at +2R -> breakeven, trail close < 10d MA, "
          "60-bar cap:")
    sim = simulate_exits(primary, m)
    print_sim_report(sim)

    os.makedirs(common.OUTPUT_DIR, exist_ok=True)
    out_path = os.path.join(common.OUTPUT_DIR, "high_tight_flag_events.csv")
    loose.to_csv(out_path, index=False)
    print(f"\nEvent log (loose variant, strict flagged) → {out_path}")

    print(f"\n{common.CAVEATS}")


if __name__ == "__main__":
    main()
