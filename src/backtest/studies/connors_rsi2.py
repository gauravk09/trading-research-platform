"""
connors_rsi2.py — Connors RSI-2 mean reversion: does buying extreme
short-term oversold inside a long-term uptrend have an edge on NSE?

Source: Larry Connors & Cesar Alvarez, "Short Term Trading Strategies That
Work" (2008). The published system: buy when RSI(2) is deeply oversold while
the stock holds above its 200d MA, exit on the snap-back (first close above
the 5d MA). The published version uses NO stop loss.

Event = (symbol, date) where ALL hold at that day's close:
  - RSI(2) < 10, Wilder smoothing: up/down legs of close.diff() smoothed
    with ewm(alpha=1/2, adjust=False).mean(); RSI = 100 - 100/(1 + up/down)
  - close > 200d SMA
  - Dedup: no raw signal from the same symbol in the prior 3 bars
  - Variant segments: RSI(2) < 5 (aggressive) and < 2 (extreme)

Cross-check motive: washout_reversal.py found 3-down-day dip buys have NO
edge in good markets here. Does Connors' stricter oversold qualifier change
that verdict?

Reported: forward returns from D+1 open at D+1/2/3/5/10/20; regime and RS
segments; sub-studies by RSI threshold, distance above the 200d MA, and
RS>=80 leaders vs the rest; a rule-exit simulation (entry D+1 open, exit
first close above the 5d MA, force-exit bar 15, no stop, MAE tracked) plus
a stopped variant (7% hard stop).

Usage:
    ~/anaconda3/bin/python src/backtest/studies/connors_rsi2.py
"""

import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(__file__))

import common

MAX_HOLD = 15


def rsi2(close: pd.DataFrame) -> pd.DataFrame:
    """Wilder RSI(2): ewm(alpha=1/2, adjust=False) of up/down close moves."""
    chg = close.diff()
    avg_up = chg.clip(lower=0).ewm(alpha=1 / 2, adjust=False).mean()
    avg_dn = (-chg.clip(upper=0)).ewm(alpha=1 / 2, adjust=False).mean()
    return 100 - 100 / (1 + avg_up / avg_dn)


def find_events(m: dict) -> pd.DataFrame:
    close, volume = m["close"], m["volume"]
    rsi = rsi2(close)
    sma200 = close.rolling(200).mean()
    dist_200 = (close / sma200 - 1) * 100

    mask = (rsi < 10) & (close > sma200) & common.tradeable_mask(close, volume)
    # Dedup: drop if the same symbol signalled in the prior 3 bars.
    mask &= ~mask.shift(1).rolling(3).max().fillna(0).astype(bool)

    events = common.events_from_mask(mask, m)
    events = common.add_regime_and_rs_buckets(events)

    dates, syms = np.where(mask.reindex_like(close).fillna(False))
    events["rsi2"] = rsi.values[dates, syms]
    events["dist_200ma"] = dist_200.values[dates, syms]
    events["date_idx"] = dates
    return events


def simulate_exits(events: pd.DataFrame, m: dict, stop_pct: float = None) -> pd.DataFrame:
    """Per event: enter D+1 open, exit first close above the 5d MA of close,
    force-exit bar 15. No stop by default (Connors' published version);
    stop_pct=0.07 adds a 7% hard stop. MAE = worst low vs entry while held."""
    close, open_, low = m["close"], m["open"], m["low"]
    ma5 = close.rolling(5).mean()
    col_idx = {s: i for i, s in enumerate(close.columns)}
    n_dates = len(close.index)
    o, l, c, ma = (df.values for df in (open_, low, close, ma5))

    rows = []
    for ev in events.itertuples():
        j = col_idx[ev.symbol]
        start = ev.date_idx + 1
        if start >= n_dates or np.isnan(o[start, j]):
            continue
        entry = o[start, j]
        stop = entry * (1 - stop_pct) if stop_pct else None

        exit_px = hold = None
        worst_low = entry
        last_k = None
        for k in range(start, min(start + MAX_HOLD, n_dates)):
            if np.isnan(c[k, j]):
                break
            if not np.isnan(l[k, j]):
                worst_low = min(worst_low, l[k, j])
            if stop is not None and o[k, j] <= stop:      # gap through stop
                exit_px = o[k, j]
            elif stop is not None and l[k, j] <= stop:    # stop wins same-bar ambiguity
                exit_px = stop
            elif not np.isnan(ma[k, j]) and c[k, j] > ma[k, j]:
                exit_px = c[k, j]
            if exit_px is not None:
                hold = k - start + 1
                break
            last_k = k
        if exit_px is None:                               # time/data-end exit at close
            if last_k is None:
                continue
            exit_px = c[last_k, j]
            hold = last_k - start + 1
        rows.append({"regime": ev.regime, "rsi2": ev.rsi2,
                     "ret_pct": (exit_px / entry - 1) * 100,
                     "mae_pct": (worst_low / entry - 1) * 100,
                     "hold": hold})
    return pd.DataFrame(rows)


def print_sim_stats(label: str, sim: pd.DataFrame) -> None:
    if len(sim) < 30:
        print(f"  {label:<18} n={len(sim)} (too few)")
        return
    r = sim["ret_pct"]
    gains, losses = r[r > 0].sum(), -r[r <= 0].sum()
    pf = gains / losses if losses > 0 else np.inf
    print(f"  {label:<18} n={len(sim):<7} win {(r > 0).mean() * 100:4.1f}%  "
          f"avg {r.mean():+5.2f}%  med {r.median():+5.2f}%  "
          f"PF {pf:4.2f}  avg hold {sim['hold'].mean():3.1f}d")


def print_threshold_lines(events: pd.DataFrame, horizons=(1, 5, 20)) -> None:
    for thr in [10, 5, 2]:
        grp = events[events["rsi2"] < thr]
        cells = "  |  ".join(f"D+{n} {common.stat_line(grp[f'ret_o{n}'])}"
                             for n in horizons)
        print(f"  RSI(2) < {thr:<13} n={len(grp):<6} {cells}")


def print_report(events: pd.DataFrame, sim: pd.DataFrame, sim_stop: pd.DataFrame) -> None:
    print(f"\n{'=' * 76}")
    print(f"CONNORS RSI-2 MEAN REVERSION STUDY — "
          f"{events['date'].min().date()} → {events['date'].max().date()}")
    print(f"{'=' * 76}")
    print(f"Events: {len(events)} (RSI(2)<10, close>200d MA) | "
          f"Returns are from D+1 OPEN entry to D+n close.")

    print("\n[1] Baseline forward returns (all events):")
    for n in common.HORIZONS:
        print(f"  D+{n:<3} {common.stat_line(events[f'ret_o{n}'])}")

    common.print_standard_segments(events)

    print("\n[3] By RSI(2) threshold (cumulative) — all events:")
    print_threshold_lines(events)
    good = events[events["regime"] == "good"].copy()
    print("\n    Good market only:")
    print_threshold_lines(good)

    good["dist_bucket"] = pd.cut(good["dist_200ma"], [0, 10, 30, np.inf],
                                 labels=["0-10% above 200MA", "10-30% above",
                                         ">30% above"])
    print("\n[4] Good market only — by distance above the 200d MA:")
    common.print_table(good, "dist_bucket")

    print("\n[5] RS>=80 leaders vs the rest (washout-study tie-in), by regime:")
    events["leader"] = np.where(events["rs_rank"] >= 80, "RS>=80 leader", "RS<80 rest")
    for regime in ["good", "neutral", "bad"]:
        print(f"  -- {regime} market:")
        common.print_table(events[events["regime"] == regime], "leader")

    print("\n[6] Rule-exit simulation (entry D+1 open, exit first close > 5d MA,")
    print("    force-exit bar 15, NO stop — Connors' published rules):")
    print_sim_stats("all", sim)
    for regime in ["good", "neutral", "bad"]:
        print_sim_stats(regime, sim[sim["regime"] == regime])
    for thr in [10, 5, 2]:
        print_sim_stats(f"RSI(2) < {thr}", sim[sim["rsi2"] < thr])
    mae = sim["mae_pct"]
    print(f"  MAE (worst low vs entry while held): med {mae.median():+5.2f}%  "
          f"p90 {mae.quantile(0.10):+5.2f}%  worst {mae.min():+6.2f}%")

    print("\n[7] Stopped variant (same rules + 7% hard stop):")
    print_sim_stats("all", sim_stop)
    for regime in ["good", "neutral", "bad"]:
        print_sim_stats(regime, sim_stop[sim_stop["regime"] == regime])

    print()
    print(common.CAVEATS)


def main():
    m = common.load_cache()
    print(f"Cache: {m['close'].shape[1]} symbols, "
          f"{m['close'].index.min().date()} → {m['close'].index.max().date()}")

    events = find_events(m)
    print(f"Events found: {len(events)}")

    sim = simulate_exits(events, m)
    sim_stop = simulate_exits(events, m, stop_pct=0.07)
    print_report(events, sim, sim_stop)

    os.makedirs(common.OUTPUT_DIR, exist_ok=True)
    out_path = os.path.join(common.OUTPUT_DIR, "connors_rsi2_events.csv")
    events.drop(columns=["date_idx"]).to_csv(out_path, index=False)
    print(f"\nEvent log → {os.path.abspath(out_path)}")


if __name__ == "__main__":
    main()
