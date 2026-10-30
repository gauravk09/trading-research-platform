"""
darvas_box.py — Does the Darvas Box breakout have an edge on NSE?

Source: Nicolas Darvas, "How I Made $2,000,000 in the Stock Market" (1960).
Boxes form near 52-week highs; buy the upside breakout of the box on volume.

Box construction (per symbol, daily bars, state machine):
  - Box starts when the stock makes a new 252-day high H (high > prior
    252-bar max high). Any later high above H resets H to that high.
  - Box TOP confirmed after 3 consecutive bars fail to exceed H (highs <= H).
  - Then track the lowest low L; box BOTTOM confirmed after 3 consecutive
    bars hold above L (lows >= L, streak resets on each new low).
  - Box valid only if height (H-L)/H <= 12% and the bottom confirms within
    25 bars of the top confirmation.
Event: first bar whose HIGH exceeds H after a valid box exists, with
breakout-day volume >= 1.5x the 50d mean volume (prior 50 bars, breakout
day excluded). Dedup: no new signal for the same symbol for 10 bars.
Tradeability: common.tradeable_mask at the breakout day.

Entry is modelled at D+1 open (Darvas used buy-stops at H, so this is
conservative). Sensitivity check: fill at max(D+1 open, H) when D+1 high
exceeds H, else no fill — both reported.

Reported:
  1. Forward returns from D+1 open at D+1/2/3/5/10/20 (+ buy-stop fills)
  2. Breadth-regime and RS-quintile segments (the mandatory cuts)
  3. Sub-studies: box height; box duration top->breakout; volume ratio
  4. Rule-exit simulation: entry D+1 open, stop = box bottom L (skip if
     >12% away), trail stop up to the 20-bar rolling min low (simplified
     proxy for "new box above old box"), gap fills at open, stop wins on
     ambiguity, force-exit at 120 bars — by regime

Usage:
    ~/anaconda3/bin/python src/backtest/studies/darvas_box.py
"""

import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import common

TOP_BARS = 3           # bars failing to exceed H to confirm the top
BOTTOM_BARS = 3        # bars holding above L to confirm the bottom
MAX_HEIGHT = 0.12      # (H - L) / H
MAX_BOTTOM_LAG = 25    # bars from top confirmation to bottom confirmation
VOL_MULT = 1.5         # breakout volume vs 50d mean
DEDUP_BARS = 10
MAX_STOP_PCT = 0.12    # skip sim trades whose box bottom is further away
MAX_HOLD = 120

SEEK_HIGH, SEEK_TOP, SEEK_BOTTOM, ARMED = range(4)


def scan_symbol(h: np.ndarray, l: np.ndarray, v: np.ndarray,
                tr: np.ndarray) -> list:
    """Darvas state machine over one symbol's compact (NaN-free) bars.

    Returns event dicts with compact positions and box geometry.
    """
    prior_max = pd.Series(h).shift(1).rolling(252).max().to_numpy()
    vol50 = pd.Series(v).shift(1).rolling(50).mean().to_numpy()

    events = []
    state, H, L, top_idx, streak = SEEK_HIGH, np.nan, np.nan, 0, 0
    last_signal = -10 ** 9

    for i in range(len(h)):
        if np.isnan(h[i]) or np.isnan(l[i]):
            continue
        if state == SEEK_HIGH:
            if not np.isnan(prior_max[i]) and h[i] > prior_max[i]:
                H, streak, state = h[i], 0, SEEK_TOP
        elif state == SEEK_TOP:
            if h[i] > H:
                H, streak = h[i], 0
            else:
                streak += 1
                if streak == TOP_BARS:
                    top_idx, L, streak, state = i, np.inf, 0, SEEK_BOTTOM
        elif state == SEEK_BOTTOM:
            if h[i] > H:
                H, streak, state = h[i], 0, SEEK_TOP
            elif i - top_idx > MAX_BOTTOM_LAG:
                state = SEEK_HIGH
            elif l[i] < L:
                L, streak = l[i], 0
            else:
                streak += 1
                if streak == BOTTOM_BARS:
                    state = ARMED if (H - L) / H <= MAX_HEIGHT else SEEK_HIGH
        elif state == ARMED:
            if h[i] > H:
                vol_ok = not np.isnan(vol50[i]) and v[i] >= VOL_MULT * vol50[i]
                if vol_ok and tr[i] and i - last_signal > DEDUP_BARS:
                    events.append({"pos": i, "box_top": H, "box_bottom": L,
                                   "duration": i - top_idx,
                                   "vol_ratio": v[i] / vol50[i]})
                    last_signal = i
                H, streak, state = h[i], 0, SEEK_TOP
    return events


def find_events(m: dict) -> tuple:
    """Run the box scan per symbol. Returns (mask, extras) aligned on
    (date, symbol) — extras carries box geometry the mask can't."""
    close = m["close"]
    close_v = close.to_numpy()
    high_v, low_v, vol_v = (m[k].to_numpy() for k in ["high", "low", "volume"])
    tr_v = common.tradeable_mask(close, m["volume"]).to_numpy()

    mask_arr = np.zeros(close.shape, dtype=bool)
    extras = []
    for j, sym in enumerate(close.columns):
        valid = np.flatnonzero(~np.isnan(close_v[:, j]))
        if len(valid) < 260:
            continue
        for ev in scan_symbol(high_v[valid, j], low_v[valid, j],
                              vol_v[valid, j], tr_v[valid, j]):
            row = valid[ev["pos"]]
            mask_arr[row, j] = True
            extras.append({
                "date": close.index[row], "symbol": sym,
                "box_top": ev["box_top"], "box_bottom": ev["box_bottom"],
                "height_pct": (ev["box_top"] - ev["box_bottom"])
                              / ev["box_top"] * 100,
                "duration_bars": ev["duration"],
                "vol_ratio": ev["vol_ratio"],
            })
    mask = pd.DataFrame(mask_arr, index=close.index, columns=close.columns)
    return mask, pd.DataFrame(extras)


def add_buystop_returns(events: pd.DataFrame, mask: pd.DataFrame,
                        m: dict) -> pd.DataFrame:
    """Sensitivity: fill at max(D+1 open, box top) if D+1 high > box top,
    else no fill. Uses the same np.where ordering as events_from_mask."""
    close = m["close"]
    dates, syms = np.where(mask.reindex_like(close).fillna(False))
    d1_high = m["high"].shift(-1).values[dates, syms]

    filled = d1_high > events["box_top"]
    fill_price = np.where(filled,
                          np.maximum(events["entry_open"], events["box_top"]),
                          np.nan)
    events["buystop_fill"] = fill_price
    for n in common.HORIZONS:
        fwd_close = close.shift(-n).values[dates, syms]
        events[f"ret_f{n}"] = (fwd_close / fill_price - 1) * 100
    return events


def simulate_rule_exits(events: pd.DataFrame, m: dict) -> pd.DataFrame:
    """Entry D+1 open; initial stop = box bottom (skip if >12% below entry);
    trail: raise stop to the 20-bar rolling min low (through the prior bar)
    whenever that exceeds it; gap through stop fills at open, stop wins on
    ambiguity; force-exit at MAX_HOLD bars at close."""
    close = m["close"]
    O, L, C = (m[k].to_numpy() for k in ["open", "low", "close"])
    rmin20 = m["low"].rolling(20, min_periods=5).min().shift(1).to_numpy()
    date_pos = {d: i for i, d in enumerate(close.index)}
    sym_pos = {s: j for j, s in enumerate(close.columns)}
    n_rows = len(close.index)

    trades = []
    for ev in events.itertuples():
        i, j = date_pos[ev.date], sym_pos[ev.symbol]
        if i + 1 >= n_rows or np.isnan(O[i + 1, j]):
            continue
        entry, stop = O[i + 1, j], ev.box_bottom
        if entry <= stop or (entry - stop) / entry > MAX_STOP_PCT:
            continue
        risk = entry - stop

        exit_price, hold, reason = np.nan, np.nan, "open"
        last_close, last_k = np.nan, i + 1
        for k in range(i + 1, min(i + 1 + MAX_HOLD, n_rows)):
            if np.isnan(C[k, j]):
                continue
            last_close, last_k = C[k, j], k
            if not np.isnan(rmin20[k, j]):
                stop = max(stop, rmin20[k, j])
            if O[k, j] <= stop:
                exit_price, hold, reason = O[k, j], k - i, "stop_gap"
                break
            if L[k, j] <= stop:
                exit_price, hold, reason = stop, k - i, "stop"
                break
        if reason == "open":
            if np.isnan(last_close):
                continue
            exit_price, hold, reason = last_close, last_k - i, "timeout"

        trades.append({"date": ev.date, "symbol": ev.symbol,
                       "regime": ev.regime, "entry": entry, "exit": exit_price,
                       "R": (exit_price - entry) / risk, "hold": hold,
                       "reason": reason})
    return pd.DataFrame(trades)


def print_exit_table(trades: pd.DataFrame) -> None:
    def line(name, grp):
        if len(grp) < 10:
            print(f"  {name:<14} n={len(grp)} (too few)")
            return
        r = grp["R"]
        pos, neg = r[r > 0].sum(), r[r < 0].sum()
        pf = pos / -neg if neg < 0 else np.inf
        print(f"  {name:<14} n={len(grp):<5} win {(r > 0).mean() * 100:4.1f}%  "
              f"avg R {r.mean():+5.2f}  med R {r.median():+5.2f}  "
              f"PF {pf:4.2f}  hold {grp['hold'].mean():4.1f}d")

    line("all", trades)
    for regime in ["good", "neutral", "bad"]:
        line(regime, trades[trades["regime"] == regime])


def print_report(events: pd.DataFrame, trades: pd.DataFrame) -> None:
    print(f"\n{'=' * 76}")
    print(f"DARVAS BOX BREAKOUT STUDY — "
          f"{events['date'].min().date()} → {events['date'].max().date()}")
    print(f"{'=' * 76}")
    filled = events["buystop_fill"].notna()
    print(f"Events: {len(events)} box breakouts (volume >= {VOL_MULT}x 50d mean)"
          f" | buy-stop fill on D+1: {filled.sum()} "
          f"({filled.mean() * 100:.0f}%)")
    print("Returns below are from D+1 OPEN entry to D+n close unless noted.")

    print("\n[1] Baseline forward returns (all events, D+1 open entry):")
    for n in common.HORIZONS:
        print(f"  D+{n:<3} {common.stat_line(events[f'ret_o{n}'])}")

    print(f"\n[1b] Buy-stop sensitivity — fill at max(D+1 open, box top) only")
    print(f"     when D+1 high > box top ({filled.sum()} fills):")
    for n in [1, 5, 20]:
        print(f"  D+{n:<3} {common.stat_line(events[f'ret_f{n}'])}")

    common.print_standard_segments(events)

    print("\n[3a] By box height (H-L)/H:")
    events["height_bucket"] = pd.cut(events["height_pct"], [0, 6, 9, 12],
                                     labels=["<6%", "6-9%", "9-12%"])
    common.print_table(events, "height_bucket", horizons=[1, 5, 20])

    print("\n[3b] By box duration, top confirmation -> breakout (bars):")
    events["dur_bucket"] = pd.cut(events["duration_bars"], [0, 10, 20, np.inf],
                                  labels=["<10", "10-20", ">20"])
    common.print_table(events, "dur_bucket", horizons=[1, 5, 20])

    print("\n[3c] By breakout volume ratio (vs 50d mean):")
    events["vol_bucket"] = pd.cut(events["vol_ratio"], [1.5, 2, 3, np.inf],
                                  labels=["1.5-2x", "2-3x", ">3x"])
    common.print_table(events, "vol_bucket", horizons=[1, 5, 20])

    print("\n[4] Rule-exit simulation (entry D+1 open, stop = box bottom,")
    print("    trail to 20-bar min low, max 120 bars):")
    print_exit_table(trades)
    reasons = trades["reason"].value_counts()
    print("  exits: " + ", ".join(f"{k} {v}" for k, v in reasons.items()))

    print()
    print(common.CAVEATS)


def main():
    print("Loading study cache...")
    m = common.load_cache()

    print("Scanning for Darvas box breakouts...")
    mask, extras = find_events(m)
    events = common.events_from_mask(mask, m)
    events = events.merge(extras, on=["date", "symbol"])
    events = add_buystop_returns(events, mask, m)
    events = common.add_regime_and_rs_buckets(events)
    print(f"  {len(events)} events")

    print("Simulating rule exits...")
    trades = simulate_rule_exits(events, m)

    print_report(events, trades)

    os.makedirs(common.OUTPUT_DIR, exist_ok=True)
    out_path = os.path.join(common.OUTPUT_DIR, "darvas_box_events.csv")
    events.to_csv(out_path, index=False)
    print(f"\nEvent log → {os.path.abspath(out_path)}")


if __name__ == "__main__":
    main()
