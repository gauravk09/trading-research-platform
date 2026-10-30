"""
minervini_trend_template.py — Does a Minervini Trend Template + VCP breakout have edge on NSE?

Source: Mark Minervini, "Trade Like a Stock Market Wizard" (2013). SEPA method /
Volatility Contraction Pattern. US Investing Championship winner 1997 (+155%)
and 2021 (+334.8%).

Event (all conditions at Day 0 close):
  Trend Template — close > 150/200 DMA, 150 > 200 DMA, 200 DMA rising vs 21
  bars ago, 50 > 150 > 200 DMA with close > 50 DMA, close >= 1.30x 52wk low,
  close >= 0.75x 52wk high, composite RS rank >= 70.
  VCP proxy — 5d range% < 10d range% < 20d range% (contraction), 5d range% <=
  ADR20, 5d avg volume < 50d avg volume (dry-up).
  Trigger — close breaks the prior 20-day closing high.
  Dedup — drop repeat events within 10 bars of a kept event (same symbol).

If the strict signal fires < 100 times, the volume dry-up leg is dropped
(loose VCP) and both counts are reported.

Reported:
  1. Forward returns from D+1 open at D+1/2/3/5/10/20
  2. By breadth regime and RS quintile (the mandatory cuts)
  3. By distance from 52wk high (<5%, 5-15%, 15-25%)
  4. By ADR20 bucket (<3%, 3-5%, >5%)
  5. Rule-exit simulation: entry D+1 open, stop = 5-bar low capped at -8%,
     1/3 partial at +2R (stop to breakeven), trail out on close < 20 DMA,
     max 60 bars. Stats overall and by regime.

Usage:
    ~/anaconda3/bin/python src/backtest/studies/minervini_trend_template.py
"""

import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(__file__))

import common

MAX_HOLD = 60


def signal_mask(m: dict, require_dryup: bool = True) -> pd.DataFrame:
    close, high, low, volume = m["close"], m["high"], m["low"], m["volume"]

    ma50 = close.rolling(50).mean()
    ma150 = close.rolling(150).mean()
    ma200 = close.rolling(200).mean()
    lo52 = low.rolling(252).min()
    hi52 = high.rolling(252).max()

    trend = (
        (close > ma150) & (close > ma200)
        & (ma150 > ma200)
        & (ma200 > ma200.shift(21))
        & (ma50 > ma150) & (close > ma50)
        & (close >= 1.30 * lo52)
        & (close >= 0.75 * hi52)
        & (m["rs"] >= 70)
    )

    def range_pct(n):
        return (high.rolling(n).max() - low.rolling(n).min()) / close * 100

    rp5, rp10, rp20 = range_pct(5), range_pct(10), range_pct(20)
    adr20 = ((high / low - 1) * 100).rolling(20).mean()
    vcp = (rp5 < rp10) & (rp10 < rp20) & (rp5 <= adr20)
    if require_dryup:
        vcp &= volume.rolling(5).mean() < volume.rolling(50).mean()

    breakout = close > close.rolling(20).max().shift(1)

    return trend & vcp & breakout & common.tradeable_mask(close, volume)


def dedup_events(events: pd.DataFrame, close: pd.DataFrame) -> pd.DataFrame:
    """Keep the first event; drop repeats within 10 bars for the same symbol."""
    events = events.sort_values(["symbol", "date"]).copy()
    events["pos"] = close.index.get_indexer(events["date"])
    keep = []
    for _, grp in events.groupby("symbol"):
        last = -np.inf
        for idx, pos in zip(grp.index, grp["pos"]):
            if pos - last > 10:
                keep.append(idx)
                last = pos
    return events.loc[keep].sort_values(["date", "symbol"]).reset_index(drop=True)


def add_substudy_columns(events: pd.DataFrame, m: dict) -> pd.DataFrame:
    close, high, low = m["close"], m["high"], m["low"]
    rows = events["pos"].to_numpy()
    cols = close.columns.get_indexer(events["symbol"])

    dist_high = (1 - close / high.rolling(252).max()) * 100
    adr20 = ((high / low - 1) * 100).rolling(20).mean()
    events["dist_52wk_high"] = dist_high.values[rows, cols]
    events["adr20"] = adr20.values[rows, cols]
    events["dist_bucket"] = pd.cut(events["dist_52wk_high"], [-np.inf, 5, 15, 25],
                                   labels=["<5% off high", "5-15% off high",
                                           "15-25% off high"])
    events["adr_bucket"] = pd.cut(events["adr20"], [0, 3, 5, np.inf],
                                  labels=["ADR <3%", "ADR 3-5%", "ADR >5%"])
    return events


def simulate_rule_exit(events: pd.DataFrame, m: dict) -> pd.DataFrame:
    """Per-event bar loop: -8%-capped 5-bar-low stop, 1/3 off at +2R with stop
    to breakeven, full exit on first close below the 20 DMA, max 60 bars."""
    close = m["close"]
    O, H, L, C = (m[k].to_numpy() for k in ["open", "high", "low", "close"])
    MA20 = close.rolling(20).mean().to_numpy()
    n_bars = len(close.index)
    cols = close.columns.get_indexer(events["symbol"])

    out = []
    for pos, s in zip(events["pos"].to_numpy(), cols):
        e = pos + 1
        if e >= n_bars or np.isnan(O[e, s]):
            continue
        entry = O[e, s]
        stop = max(np.nanmin(L[pos - 4:pos + 1, s]), entry * 0.92)
        if entry <= stop:
            continue
        risk = entry - stop
        target = entry + 2 * risk

        partial = False
        exit_price, exit_bar, last_close = None, None, entry
        for i in range(e, min(e + MAX_HOLD, n_bars)):
            o, h, l, c = O[i, s], H[i, s], L[i, s], C[i, s]
            if np.isnan(c):
                break  # delisted/suspended: exit at last valid close
            if not np.isnan(o) and o <= stop:
                exit_price, exit_bar = o, i
                break
            if not np.isnan(l) and l <= stop:  # stop wins over same-bar target
                exit_price, exit_bar = stop, i
                break
            if not partial and not np.isnan(h) and h >= target:
                partial = True
                stop = entry  # breakeven
            if not np.isnan(MA20[i, s]) and c < MA20[i, s]:
                exit_price, exit_bar = c, i
                break
            last_close = c
        if exit_price is None:  # timed out or data ran out
            exit_price, exit_bar = last_close, i
        r_rest = (exit_price - entry) / risk
        total_r = (2 * (1 / 3) + r_rest * (2 / 3)) if partial else r_rest
        out.append({"pos": pos, "symbol": close.columns[s], "r": total_r,
                    "hold_days": exit_bar - e + 1, "partial": partial})
    return pd.DataFrame(out)


def sim_stat_line(r: pd.Series, hold: pd.Series) -> str:
    if len(r) < 10:
        return f"n={len(r)} (too few)"
    gross_win = r[r > 0].sum()
    gross_loss = -r[r < 0].sum()
    pf = gross_win / gross_loss if gross_loss > 0 else np.inf
    return (f"n={len(r):<5} win {(r > 0).mean() * 100:4.1f}%  "
            f"avg {r.mean():+5.2f}R  med {r.median():+5.2f}R  "
            f"PF {pf:4.2f}  hold {hold.mean():4.1f}d")


def main():
    print("Loading study cache...")
    m = common.load_cache()

    strict_mask = signal_mask(m, require_dryup=True)
    n_strict = int(strict_mask.to_numpy().sum())
    print(f"Strict signal (with volume dry-up): {n_strict} raw events")
    loosened = n_strict < 100
    mask = signal_mask(m, require_dryup=False) if loosened else strict_mask
    if loosened:
        print(f"  < 100 → loosening VCP: dropping the volume dry-up leg "
              f"({int(mask.to_numpy().sum())} raw events)")

    events = common.events_from_mask(mask, m)
    events = dedup_events(events, m["close"])
    events = add_substudy_columns(events, m)
    events = common.add_regime_and_rs_buckets(events)
    print(f"After 10-bar dedup: {len(events)} events, "
          f"{events['date'].min().date()} → {events['date'].max().date()}")

    print(f"\n{'=' * 76}")
    print("MINERVINI TREND TEMPLATE + VCP BREAKOUT — forward returns from D+1 open")
    print(f"{'=' * 76}")
    print("\n[Baseline] All events:")
    cells = "  |  ".join(f"D+{n} {common.stat_line(events[f'ret_o{n}'])}"
                         for n in common.HORIZONS)
    print(f"  {cells}")

    common.print_standard_segments(events)

    print("\n[Sub-study A] By distance from 52wk high at signal:")
    common.print_table(events, "dist_bucket")

    print("\n[Sub-study B] By ADR20 at signal:")
    common.print_table(events, "adr_bucket")

    print("\n[Sub-study C] Rule-exit simulation (entry D+1 open, 5-bar-low stop")
    print("capped -8%, 1/3 partial at +2R then breakeven, exit close < 20 DMA,")
    print("max 60 bars). R = multiple of initial risk:")
    sim = simulate_rule_exit(events, m)
    sim = sim.merge(events[["pos", "symbol", "regime"]], on=["pos", "symbol"])
    print(f"  {'all events':<22} {sim_stat_line(sim['r'], sim['hold_days'])}")
    for label, grp in sim.groupby("regime", observed=True):
        print(f"  {str(label):<22} {sim_stat_line(grp['r'], grp['hold_days'])}")
    print(f"  partial (+2R) reached in {sim['partial'].mean() * 100:.1f}% of trades")

    os.makedirs(common.OUTPUT_DIR, exist_ok=True)
    out_path = os.path.join(common.OUTPUT_DIR, "minervini_trend_template_events.csv")
    events.to_csv(out_path, index=False)
    print(f"\nEvent log → {out_path}")

    print(f"\n{common.CAVEATS}")


if __name__ == "__main__":
    main()
