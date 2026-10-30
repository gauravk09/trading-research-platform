"""
close_entry_rescore.py — re-score the champion-strategy batch with the
close-day entry that flipped bursts positive (entry_refinements study).

Question: how many of the July-17 scoreboard's "no edge" verdicts were really
verdicts on the D+1-open entry convention? Same event logs, same stop rule
(signal-day low capped 6% under entry, gap-through fills at open), two holds
(D+5 / D+20), three entries:

  open        D+1 open (the original convention — the known bleed)
  close       signal-day close (Bonde's 3:20pm entry)
  close+gate  close entry, only when the signal bar closed in the top quarter
              of its range (close_pos >= 0.75)

Eras: ex-COVID clean split (2015-2019 vs 2023-2026), per the house standard.
Pre-cost, like the original batch. Close fills assume the closing price.

Usage:
    ~/anaconda3/bin/python src/backtest/studies/close_entry_rescore.py
"""

import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(__file__))

import common

COHORTS = ["ryan_52wk_high", "minervini_trend_template", "weinstein_stage2",
           "darvas_box", "donchian_turtle", "high_tight_flag", "pocket_pivot",
           "kell_ema_crossback", "connors_rsi2", "stockbee_4pct_burst"]
_report = []


def say(line=""):
    print(line)
    _report.append(line)


def simulate(d, s, m, entry_at_close: bool, hold: int):
    O, H, L, C = (m[k].values for k in ("open", "high", "low", "close"))
    n_dates = C.shape[0]
    out = np.full(len(d), np.nan)
    for i in range(len(d)):
        d0, si = d[i], s[i]
        if entry_at_close:
            entry = C[d0, si]
        else:
            if d0 + 1 >= n_dates:
                continue
            entry = O[d0 + 1, si]
        if np.isnan(entry):
            continue
        stop = max(L[d0, si], entry * 0.94)
        risk = entry - stop
        if risk <= 0 or np.isnan(risk):
            continue
        # Suspension-tolerant: a NaN bar means the stock didn't trade — you
        # hold and the stop check resumes on the next traded bar. (The old
        # break-on-NaN silently discarded gap-containing trades, which skews
        # beaten-down cohorts badly.) Window capped at hold + 15 extra bars.
        held = 0
        for dd in range(d0 + 1, min(d0 + hold + 16, n_dates)):
            if np.isnan(C[dd, si]):
                continue
            if L[dd, si] <= stop:
                out[i] = (min(O[dd, si], stop) - entry) / risk
                break
            held += 1
            if held >= hold:
                out[i] = (C[dd, si] - entry) / risk
                break
    return out


def stat(r, era_mask):
    r = r[era_mask]
    r = r[~np.isnan(r)]
    if len(r) < 60:
        return f"n={len(r)} (few)"
    pos, neg = r[r > 0].sum(), r[r < 0].sum()
    pf = pos / -neg if neg < 0 else np.inf
    return (f"n={len(r):<6} avg {r.mean():+.2f}R win {(r > 0).mean() * 100:4.1f}% "
            f"PF {pf:4.2f}")


def main():
    m = common.load_cache()
    close, high, low = m["close"], m["high"], m["low"]
    dpos = pd.Series(range(len(close.index)), index=close.index)
    spos = pd.Series(range(len(close.columns)), index=close.columns)

    say("CLOSE-ENTRY RE-SCORE — ex-COVID eras A=2015-2019, B=2023-2026")
    say("stop = signal-day low capped 6%; pre-cost; close fills at closing price")

    for slug in COHORTS:
        path = os.path.join(common.OUTPUT_DIR, f"{slug}_events.csv")
        ev = pd.read_csv(path, usecols=["date", "symbol"], parse_dates=["date"])
        if ev["date"].dt.tz is None:
            ev["date"] = ev["date"].dt.tz_localize("Asia/Kolkata")
        else:
            ev["date"] = ev["date"].dt.tz_convert("Asia/Kolkata")
        y = ev["date"].dt.year
        ev = ev[(y < 2020) | (y > 2022)].reset_index(drop=True)
        d = dpos.reindex(ev["date"]).to_numpy()
        s = spos.reindex(ev["symbol"]).to_numpy()
        keep = ~(np.isnan(d) | np.isnan(s))
        ev = ev[keep].reset_index(drop=True)
        d, s = d[keep].astype(int), s[keep].astype(int)
        era_a = (ev["date"].dt.year <= 2019).to_numpy()

        rng = high.values[d, s] - low.values[d, s]
        cpos = np.divide(close.values[d, s] - low.values[d, s], rng,
                         where=rng > 0, out=np.ones_like(rng))
        strong = cpos >= 0.75

        say(f"\n{slug}  ({len(ev)} ex-COVID events, {strong.mean() * 100:.0f}% strong-close)")
        for hold in (5, 20):
            r_open = simulate(d, s, m, False, hold)
            r_close = simulate(d, s, m, True, hold)
            say(f"  D+{hold}:")
            say(f"    open        A: {stat(r_open, era_a)}   B: {stat(r_open, ~era_a)}")
            say(f"    close       A: {stat(r_close, era_a)}   B: {stat(r_close, ~era_a)}")
            say(f"    close+gate  A: {stat(r_close[strong], era_a[strong])}   "
                f"B: {stat(r_close[strong], ~era_a[strong])}")

    say("\nRead: a pattern 'flips' if close(+gate) turns PF > 1 in BOTH eras where")
    say("the open entry was PF < 1. Weinstein/Minervini ns are structurally small.")
    md = os.path.join(common.OUTPUT_DIR, "close_entry_rescore_study.md")
    with open(md, "w") as f:
        f.write("\n".join(_report) + "\n")
    print(f"\nReport -> {md}")


if __name__ == "__main__":
    main()
