"""
ryan_52wk_high.py — Does the David Ryan / O'Neil 52-week-high base breakout work in India?

Source: David Ryan (3x US Investing Championship winner 1985-87, +1,379%
cumulative; O'Neil protege) and William O'Neil, "How to Make Money in Stocks".
Buy a stock breaking to new 52-week highs out of a sound base, with top-tier
relative strength, on volume.

Event = (symbol, date) where at that day's close:
  - New high: close > max close of the prior 252 bars (excluding today).
  - Sound base: min close of the prior 35 bars >= 0.75 x base top (base top =
    prior 252-bar max close) — i.e. correction within the base <= 25%.
  - Base lasted: the most recent new-252-day-high close before today is
    >= 35 bars back.
  - Composite RS rank >= 80.
  - Volume >= 1.5 x mean volume of the prior 50 bars.
  - Tradeable per common.tradeable_mask; dedup within 10 bars per symbol.

Reported: forward returns from D+1 open (D+1..60), regime x RS segments,
a no-RS-filter variant, base depth / base length / early-vs-late base /
breakout volume sub-studies, and an O'Neil rule-exit simulation
(7% hard stop, trail below 50 DMA once up 20%, 120-bar time stop).

Usage:
    ~/anaconda3/bin/python src/backtest/studies/ryan_52wk_high.py
"""

import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(__file__))

import common

BASE_BARS = 35
DEDUP_BARS = 10
LONG_HORIZONS = [40, 60]
STOP_PCT = 0.07
TRAIL_ARM = 1.20
MAX_HOLD = 120


def build_signal(m: dict, require_rs: bool = True):
    """Raw (un-deduped) signal mask plus the per-cell feature matrices."""
    close, volume = m["close"], m["volume"]

    base_top = close.rolling(252, min_periods=252).max().shift(1)
    new_high = close > base_top

    base_floor = close.rolling(BASE_BARS).min().shift(1)
    sound_base = base_floor >= 0.75 * base_top

    # bars since the most recent new-252d-high close strictly before today
    ii = np.arange(len(close))
    last_high_pos = pd.DataFrame(
        np.where(new_high.values, ii[:, None], np.nan),
        index=close.index, columns=close.columns).ffill().shift(1)
    base_len = ii[:, None] - last_high_pos.values
    base_lasted = pd.DataFrame(np.isnan(base_len) | (base_len >= BASE_BARS),
                               index=close.index, columns=close.columns)

    vol_ratio = volume / volume.rolling(50).mean().shift(1)

    mask = (new_high & sound_base & base_lasted & (vol_ratio >= 1.5)
            & common.tradeable_mask(close, volume))
    if require_rs:
        mask &= m["rs"] >= 80

    features = {
        "base_depth_pct": (1 - base_floor / base_top) * 100,
        "base_len": pd.DataFrame(base_len, index=close.index, columns=close.columns),
        "vol_ratio": vol_ratio,
    }
    return mask.fillna(False), features


def dedup_mask(mask: pd.DataFrame) -> pd.DataFrame:
    """Keep an event only if the symbol's last KEPT event is > DEDUP_BARS back."""
    vals = mask.values.copy()
    for j in range(vals.shape[1]):
        rows = np.flatnonzero(vals[:, j])
        last_kept = -10**9
        for r in rows:
            if r - last_kept <= DEDUP_BARS:
                vals[r, j] = False
            else:
                last_kept = r
    return pd.DataFrame(vals, index=mask.index, columns=mask.columns)


def build_events(mask: pd.DataFrame, features: dict, m: dict) -> pd.DataFrame:
    events = common.events_from_mask(mask, m)
    dates, syms = np.where(mask.values)          # same row-major order
    events["row"] = dates
    events["col"] = syms
    for name, df in features.items():
        events[name] = df.values[dates, syms]

    close = m["close"]
    for n in LONG_HORIZONS:
        fwd = close.shift(-n).values[dates, syms]
        events[f"ret_o{n}"] = (fwd / events["entry_open"] - 1) * 100

    # prior dedup'd events for the same symbol in the trailing 252 bars
    prior = np.zeros(len(events), dtype=int)
    for _, grp in events.groupby("col"):
        rows = grp["row"].values
        for k, r in enumerate(rows):
            prior[grp.index[k]] = np.sum((rows < r) & (rows >= r - 252))
    events["prior_events_252"] = prior
    return common.add_regime_and_rs_buckets(events)


def simulate_exits(events: pd.DataFrame, m: dict) -> pd.DataFrame:
    """O'Neil rule exit: 7% hard stop, trail below 50 DMA once up 20% on a close."""
    O, H, L, C = (m[k].values for k in ["open", "high", "low", "close"])
    MA = m["close"].rolling(50).mean().values
    n = O.shape[0]
    out = []
    for _, ev in events.iterrows():
        p0, col = int(ev["row"]) + 1, int(ev["col"])
        if p0 >= n:
            continue
        entry = O[p0, col]
        if np.isnan(entry):
            continue
        stop = entry * (1 - STOP_PCT)
        trailing = False
        exit_px = exit_p = None
        last_c = last_p = None
        for p in range(p0, min(p0 + MAX_HOLD, n)):
            c = C[p, col]
            if np.isnan(c):
                continue
            if not trailing:
                o, lo = O[p, col], L[p, col]
                if not np.isnan(o) and o <= stop:      # gap through stop
                    exit_px, exit_p = o, p
                    break
                if not np.isnan(lo) and lo <= stop:    # stop wins on ambiguity
                    exit_px, exit_p = stop, p
                    break
                if c >= entry * TRAIL_ARM:
                    trailing = True
            else:
                ma = MA[p, col]
                if not np.isnan(ma) and c < ma:
                    exit_px, exit_p = c, p
                    break
            last_c, last_p = c, p
        if exit_px is None:
            if last_c is None:
                continue
            exit_px, exit_p = last_c, last_p           # time stop / data end
        out.append({"regime": ev["regime"],
                    "r": (exit_px / entry - 1) / STOP_PCT,
                    "hold": exit_p - p0 + 1})
    return pd.DataFrame(out)


def print_exit_table(trades: pd.DataFrame) -> None:
    def line(label, t):
        if len(t) < 30:
            print(f"  {label:<14} n={len(t)} (too few)")
            return
        r = t["r"]
        gains, losses = r[r > 0].sum(), -r[r < 0].sum()
        pf = gains / losses if losses > 0 else np.inf
        print(f"  {label:<14} n={len(t):<6} win {(r > 0).mean() * 100:4.1f}%  "
              f"avg R {r.mean():+5.2f}  med R {r.median():+5.2f}  "
              f"PF {pf:4.2f}  avg hold {t['hold'].mean():5.1f} bars")
    line("ALL", trades)
    for regime in ["good", "neutral", "bad"]:
        line(regime, trades[trades["regime"] == regime])


def print_report(events: pd.DataFrame, events_norsf: pd.DataFrame,
                 trades: pd.DataFrame) -> None:
    print(f"\n{'=' * 76}")
    print(f"RYAN / O'NEIL 52-WEEK-HIGH BASE BREAKOUT — "
          f"{events['date'].min().date()} → {events['date'].max().date()}")
    print(f"{'=' * 76}")
    print(f"Events: {len(events)} (RS>=80) | no-RS-filter variant: {len(events_norsf)}")
    print("Returns below are from D+1 OPEN entry to D+n close.")

    print("\n[1] Forward returns, all events:")
    for n in common.HORIZONS + LONG_HORIZONS:
        print(f"  D+{n:<3} {common.stat_line(events[f'ret_o{n}'])}")

    common.print_standard_segments(events)
    print("\n[Regime, long horizons]:")
    common.print_table(events, "regime", horizons=[40, 60])

    print("\n[2] No-RS-filter variant — regime and RS quintile "
          "(what does RS>=80 add?):")
    common.print_standard_segments(events_norsf)

    print("\n[3] Base depth (correction inside the base):")
    events["depth_bucket"] = pd.cut(events["base_depth_pct"], [0, 15, 25],
                                    labels=["0-15% deep", "15-25% deep"])
    common.print_table(events, "depth_bucket")

    print("\n[4] Base length (bars since prior 252d-high close):")
    events["len_bucket"] = pd.cut(events["base_len"].fillna(np.inf),
                                  [BASE_BARS - 1, 60, 120, np.inf],
                                  labels=["35-60 bars", "60-120 bars", ">120 bars"])
    common.print_table(events, "len_bucket")

    print("\n[5] Early vs late base (dedup'd events for the symbol, trailing 252 bars):")
    events["stage"] = pd.cut(events["prior_events_252"], [-1, 0, 1, np.inf],
                             labels=["early (0 prior)", "mid (1 prior)",
                                     "late (>=2 prior)"])
    common.print_table(events, "stage")

    print("\n[6] Breakout volume (vs prior 50d mean):")
    events["vol_bucket"] = pd.cut(events["vol_ratio"], [1.5, 2, 3, np.inf],
                                  labels=["1.5-2x", "2-3x", ">3x"])
    common.print_table(events, "vol_bucket")

    print("\n[7] Rule-exit simulation (entry D+1 open, 7% stop, trail 50 DMA "
          "once +20% on a close, 120-bar time stop; R = per-unit-of-stop):")
    print_exit_table(trades)

    print()
    print(common.CAVEATS)


def main():
    m = common.load_cache()
    print(f"Cache: {m['close'].shape[1]} symbols, "
          f"{m['close'].index.min().date()} → {m['close'].index.max().date()}")

    mask, features = build_signal(m, require_rs=True)
    events = build_events(dedup_mask(mask), features, m)
    print(f"Events (RS>=80, dedup'd): {len(events)}")

    mask_norsf, feat_norsf = build_signal(m, require_rs=False)
    events_norsf = build_events(dedup_mask(mask_norsf), feat_norsf, m)

    trades = simulate_exits(events, m)
    print_report(events, events_norsf, trades)

    os.makedirs(common.OUTPUT_DIR, exist_ok=True)
    out_path = os.path.join(common.OUTPUT_DIR, "ryan_52wk_high_events.csv")
    events.drop(columns=["row", "col"]).to_csv(out_path, index=False)
    print(f"\nEvent log → {os.path.abspath(out_path)}")


if __name__ == "__main__":
    main()
