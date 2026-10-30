"""
kell_ema_crossback.py — Oliver Kell's EMA crossback: does buying the reclaim
of the 10 EMA after a pullback into the 10/20 EMA stack have an edge?

Source: Oliver Kell, "Victory in Stock Trading" (2021); 2020 US Investing
Championship winner (+941%). The crossback is his low-risk secondary entry:
after trend confirmation, price pulls into the rising 10/20 EMA area and the
first up close back above the 10 EMA is the entry.

Event = (symbol, date) where ALL hold at that day's close:
  Power-trend context:
    - EMA10 > EMA20 > SMA50 five bars ago (the stack held BEFORE the pullback)
    - 60-bar max close >= 1.25 x close 60 bars ago (a real prior move)
    - close > SMA200 today
  Pullback + crossback:
    - some bar in the last 5 (excluding today) had low <= that bar's EMA20
    - today: close > EMA10 and close > yesterday's close
    - yesterday: close <= EMA10 (today IS the crossback bar)
  Dedup: no event for the same symbol in the prior 5 bars.
EMAs use pandas ewm(span=n, adjust=False).mean().

Reported: forward returns from D+1 open at D+1/2/3/5/10/20; regime and RS
segments; sub-studies by pullback depth, prior-move strength, crossback
volume; and a rule-exit simulation (stop = signal-day low, 1/3 off at +2R
with stop to breakeven, full exit on first close below EMA20, max 60 bars).

Usage:
    ~/anaconda3/bin/python src/backtest/studies/kell_ema_crossback.py
"""

import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(__file__))

import common

MAX_HOLD = 60


def find_events(m: dict) -> pd.DataFrame:
    close, open_, high, low, volume = (m["close"], m["open"], m["high"],
                                       m["low"], m["volume"])
    ema10 = close.ewm(span=10, adjust=False).mean()
    ema20 = close.ewm(span=20, adjust=False).mean()
    sma50 = close.rolling(50).mean()
    sma200 = close.rolling(200).mean()

    stack = (ema10 > ema20) & (ema20 > sma50)
    prior_move = (close.rolling(60).max() / close.shift(60) - 1) * 100

    low_vs_ema20 = (low / ema20 - 1) * 100
    tag_depth = low_vs_ema20.shift(1).rolling(5).min()  # last 5 bars, ex today

    mask = (
        stack.shift(5, fill_value=False)
        & (prior_move >= 25)
        & (close > sma200)
        & (tag_depth <= 0)                      # some bar's low tagged its EMA20
        & (close > ema10)
        & (close > close.shift(1))
        & (close.shift(1) <= ema10.shift(1))    # yesterday still below EMA10
        & common.tradeable_mask(close, volume)
    )
    # Dedup: drop if the same symbol signalled in the prior 5 bars.
    mask &= ~mask.shift(1).rolling(5).max().fillna(0).astype(bool)

    events = common.events_from_mask(mask, m)
    events = common.add_regime_and_rs_buckets(events)

    dates, syms = np.where(mask.reindex_like(close).fillna(False))
    events["pullback_depth"] = tag_depth.values[dates, syms]
    events["prior_move"] = prior_move.values[dates, syms]
    events["vol_ratio"] = (volume / volume.rolling(50).mean()).values[dates, syms]
    events["signal_low"] = low.values[dates, syms]
    events["date_idx"] = dates
    return events


def simulate_exits(events: pd.DataFrame, m: dict) -> pd.DataFrame:
    """Per event: enter D+1 open, stop = signal-day low, 1/3 off at +2R
    (stop to breakeven), full exit on first close below EMA20, max 60 bars."""
    close, open_, high, low = m["close"], m["open"], m["high"], m["low"]
    ema20 = close.ewm(span=20, adjust=False).mean()
    col_idx = {s: i for i, s in enumerate(close.columns)}
    n_dates = len(close.index)
    o, h, l, c, e = (df.values for df in (open_, high, low, close, ema20))

    rows = []
    for ev in events.itertuples():
        j = col_idx[ev.symbol]
        start = ev.date_idx + 1
        if start >= n_dates or np.isnan(o[start, j]):
            continue
        entry, stop = o[start, j], ev.signal_low
        risk = entry - stop
        if risk <= 0:
            continue

        realized = 0.0     # R already banked by the partial
        size = 1.0         # fraction of position still open
        partial_done = False
        exit_r = hold = last_k = None
        for k in range(start, min(start + MAX_HOLD, n_dates)):
            if np.isnan(c[k, j]):
                break
            if o[k, j] <= stop:                       # gap through stop
                exit_r = realized + size * (o[k, j] - entry) / risk
            elif l[k, j] <= stop:                     # stop wins same-bar ambiguity
                exit_r = realized + size * (stop - entry) / risk
            if exit_r is not None:
                hold = k - start + 1
                break
            if not partial_done and h[k, j] >= entry + 2 * risk:
                realized += (1 / 3) * 2.0
                size = 2 / 3
                stop = entry                          # breakeven
                partial_done = True
            if c[k, j] < e[k, j]:                     # first close below EMA20
                exit_r = realized + size * (c[k, j] - entry) / risk
                hold = k - start + 1
                break
            last_k = k
        if exit_r is None:                            # time/data-end exit at close
            if last_k is None:
                continue
            exit_r = realized + size * (c[last_k, j] - entry) / risk
            hold = last_k - start + 1
        rows.append({"regime": ev.regime, "r": exit_r, "hold": hold})
    return pd.DataFrame(rows)


def print_sim_stats(label: str, sim: pd.DataFrame) -> None:
    if len(sim) < 30:
        print(f"  {label:<14} n={len(sim)} (too few)")
        return
    r = sim["r"]
    gains, losses = r[r > 0].sum(), -r[r <= 0].sum()
    pf = gains / losses if losses > 0 else np.inf
    print(f"  {label:<14} n={len(sim):<6} win {(r > 0).mean() * 100:4.1f}%  "
          f"avg {r.mean():+5.2f}R  med {r.median():+5.2f}R  "
          f"PF {pf:4.2f}  avg hold {sim['hold'].mean():4.1f}d")


def print_report(events: pd.DataFrame, sim: pd.DataFrame) -> None:
    print(f"\n{'=' * 76}")
    print(f"OLIVER KELL EMA CROSSBACK STUDY — "
          f"{events['date'].min().date()} → {events['date'].max().date()}")
    print(f"{'=' * 76}")
    print(f"Events: {len(events)} | Returns are from D+1 OPEN entry to D+n close.")

    print("\n[1] Baseline forward returns (all events):")
    for n in common.HORIZONS:
        print(f"  D+{n:<3} {common.stat_line(events[f'ret_o{n}'])}")

    common.print_standard_segments(events)

    good = events[events["regime"] == "good"].copy()
    good["depth_bucket"] = pd.cut(
        good["pullback_depth"], [-np.inf, -3, -1, 0],
        labels=["deeper than -3%", "undercut -1 to -3%", "tag 0 to -1%"])
    print("\n[3] Good market only — by pullback depth (min low of last 5 bars vs EMA20):")
    common.print_table(good, "depth_bucket")

    good["move_bucket"] = pd.cut(good["prior_move"], [25, 40, 70, np.inf],
                                 labels=["25-40%", "40-70%", ">70%"])
    print("\n[4] Good market only — by strength of prior 60-bar move:")
    common.print_table(good, "move_bucket")

    good["vol_bucket"] = pd.cut(good["vol_ratio"], [0, 1, 1.5, np.inf],
                                labels=["<1x 50d avg", "1-1.5x", ">1.5x"])
    print("\n[5] Good market only — by crossback bar volume vs 50d avg:")
    common.print_table(good, "vol_bucket")

    print("\n[6] Rule-exit simulation (entry D+1 open, stop = signal-day low,")
    print("    1/3 off at +2R touch w/ stop to breakeven, exit close < EMA20, max 60 bars):")
    print_sim_stats("all", sim)
    for regime in ["good", "neutral", "bad"]:
        print_sim_stats(regime, sim[sim["regime"] == regime])

    print()
    print(common.CAVEATS)


def main():
    m = common.load_cache()
    print(f"Cache: {m['close'].shape[1]} symbols, "
          f"{m['close'].index.min().date()} → {m['close'].index.max().date()}")

    events = find_events(m)
    print(f"Events found: {len(events)}")

    sim = simulate_exits(events, m)
    print_report(events, sim)

    os.makedirs(common.OUTPUT_DIR, exist_ok=True)
    out_path = os.path.join(common.OUTPUT_DIR, "kell_ema_crossback_events.csv")
    events.drop(columns=["date_idx"]).to_csv(out_path, index=False)
    print(f"\nEvent log → {os.path.abspath(out_path)}")


if __name__ == "__main__":
    main()
