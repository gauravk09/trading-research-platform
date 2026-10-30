"""incubation.py — S7 paper-signal generator for factory strategies.

PAPER ONLY: these signals are never sized, never sent to the brief's
actionable candidate flow, never traded. They exist so the nightly grader
builds a live forward-test record; promotion to real money needs that
record to match the backtest.

Two incubating strategies short a stock's 4%-down day (D+1 open entry,
stop = min(signal-day high, entry * 1.06), time exit D+5 close, F&O only):
  b5_short_green_tape  batch5 + F3b: mcap top-150, net4 >= 18, stand down
                       when Nifty500 is extended (ti65 >= 1.04)
  ga_short_pocket      GA-evolved: ratio10 >= 0.65, net25q >= -135,
                       volc5_50 >= 0.93, turn_decile >= 0.9
One incubating LONG book (added 2026-09-03 after the attribution audit found
it the only sleeve whose return is mostly stock selection, +1.6%/trade,
every era):
  ryan_minervini       the S5-passed book, signals from the SAME functions the
                       backtest used (ryan_52wk_high.build_signal,
                       minervini_trend_template.signal_mask) on the nightly
                       matrices; gate = regime tier allows breakouts; entry
                       filter = close in the top quarter of the day's range.
"""

import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "backtest", "studies"))

from backtest.pointintime import composite_rs_matrix
import minervini_trend_template as miner
import ryan_52wk_high as ryan

MECHANICS = {"side": "short", "entry": "D+1 open",
             "stop": "min(signal-day high, entry * 1.06)",
             "exit": "close of D+5 (time exit)",
             "instrument": "F&O futures only (no cash shorting overnight)"}
RYAN_MECHANICS = {
    "side": "long", "entry": "D+1 open", "instrument": "cash delivery (CNC)",
    "ryan": "stop entry*0.93; once +20% trail on close < 50DMA; max 120 bars",
    "minervini": "stop max(5-bar low, entry*0.92); 1/3 off at +2R then stop to "
                 "entry; trail on close < 20DMA; max 60 bars",
    "sizing": "regime knobs (risk_per_trade_pct, max_open_positions)",
}
RANGE_POS_MIN = 0.75
# Ryan's "new 252-day high" is a 252-bar window shifted one bar: with exactly
# 252 rows per stock the window never fills and the rule is silently never
# true (found 2026-09-03: zero signals for a year). The last bar is computed
# exactly as the backtest did only with 252 + 1 + 35 (base age) + 10 (dedup)
# rows of history. Fail loudly below that.
MIN_MATRIX_ROWS = 298


def _ryan_minervini(summary, cm, vm, hm, lm, regime):
    """Paper signals for the Ryan/Minervini book from tonight's close.
    Same signal code as the backtest; only the last bar is reported."""
    depth = int(cm.notna().sum().max())
    if depth < MIN_MATRIX_ROWS:
        raise ValueError(f"close matrix holds {depth} rows per stock; the Ryan "
                         f"252d-high rule needs >= {MIN_MATRIX_ROWS} "
                         f"(precompute.CLOSE_MATRIX_DAYS)")
    m = {"close": cm, "high": hm, "low": lm, "volume": vm,
         "rs": composite_rs_matrix(cm)}
    r_mask = ryan.dedup_mask(ryan.build_signal(m)[0])
    m_mask = miner.signal_mask(m)
    # same symbol both strategies -> ryan takes it (the book's spec)
    m_mask &= ~r_mask
    tier = regime["tier"]
    allowed = "breakout" in regime["knobs"]["allowed_entries"]
    gates = {f"regime tier {tier} allows breakouts": allowed}
    rows = []
    for strat, mask in (("ryan", r_mask), ("minervini", m_mask)):
        for sym in mask.columns[mask.iloc[-1].to_numpy(bool)]:
            c, h, l = float(cm[sym].iloc[-1]), float(hm[sym].iloc[-1]), float(lm[sym].iloc[-1])
            range_pos = (c - l) / (h - l) if h > l else np.nan
            if not range_pos >= RANGE_POS_MIN:
                continue
            stop = (c * (1 - ryan.STOP_PCT) if strat == "ryan"
                    else max(float(lm[sym].iloc[-5:].min()), c * miner_stop_cap()))
            row = summary.loc[summary["symbol"] == sym]
            rows.append({"symbol": sym, "strategy": strat, "close": round(c, 2),
                         "stop_ref": round(stop, 2), "range_pos": round(range_pos, 2),
                         "rs_rank": None if row.empty else float(row["rs_rank"].iloc[0]),
                         "avg_turnover_cr": None if row.empty
                         else round(float(row["avg_turnover_cr"].iloc[0]), 2)})
    rows.sort(key=lambda d: -(d["rs_rank"] or 0))
    return {
        "label": "Ryan/Minervini breakout book (S5 PASS; S7 paper from 2026-09-03)",
        "status": "PAPER — do not trade (S7 incubation)",
        "rule": ("Ryan: close at a new 252d high out of a >=35-bar base whose floor "
                 "held 75% of the top, volume >= 1.5x 50d, RS >= 80. Minervini: "
                 "trend template + VCP + 20d-high breakout, RS >= 70. Both: close in "
                 "top quarter of the day's range; only when the regime tier allows "
                 "breakouts."),
        "gates": gates, "gates_pass": bool(allowed),
        "market": {"regime_tier": tier, "p_drop_20d": regime.get("p_drop_20d")},
        "mechanics": RYAN_MECHANICS,
        "candidates": rows if allowed else [],
        "suppressed_candidates": 0 if allowed else len(rows),
    }


def miner_stop_cap():
    from ryan_minervini_book import MINER
    return MINER["stop_cap"]


def _candidates(summary, mask, stop_note_cols):
    cols = ["symbol", "close", "chg_pct", "avg_turnover_cr"] + stop_note_cols
    out = []
    for r in summary.loc[mask, cols].sort_values("chg_pct").itertuples(index=False):
        d = r._asdict()
        d["stop_ref"] = round(min(d.pop("high"), d["close"] * 1.06), 2)
        out.append({k: (round(v, 2) if isinstance(v, float) else v)
                    for k, v in d.items()})
    return out


def build_incubation(summary, cm, vm, mm, idx_close, hm=None, lm=None, regime=None):
    last = mm.iloc[-1]
    net4 = int(last["up4"] - last["dn4"])
    net25q = int(last["up25q"] - last["dn25q"])
    ratio10 = float(last["ratio10"])
    ti65_idx = float((idx_close.rolling(7).mean()
                      / idx_close.rolling(65).mean()).iloc[-1]) \
        if idx_close is not None else np.nan

    down4 = summary["chg_pct"] <= -4.0

    s = summary.copy()
    s["mcap_rank"] = s["mcap_cr"].rank(ascending=False)
    vol50 = vm.rolling(50, min_periods=10).mean().iloc[-1]
    vol5 = vm.rolling(5, min_periods=3).mean().iloc[-1]
    s["volc5_50"] = s["symbol"].map(vol5 / vol50)
    turn20 = (cm * vm).rolling(20).mean().iloc[-1]
    s["turn_decile"] = s["symbol"].map(turn20.rank(pct=True))

    b5_gates = {"net4 >= 18": net4 >= 18,
                "nifty_ti65 < 1.04 (stand down when hot)": ti65_idx < 1.04}
    b5_pass = all(b5_gates.values())
    b5_mask = down4 & (s["mcap_rank"] <= 150)

    ga_gates = {"ratio10 >= 0.65": ratio10 >= 0.65,
                "net25q >= -135": net25q >= -135}
    ga_pass = all(ga_gates.values())
    ga_mask = down4 & (s["volc5_50"] >= 0.9309) & (s["turn_decile"] >= 0.9)

    def block(label, rule, gates, gates_pass, mask):
        return {
            "label": label,
            "status": "PAPER — do not trade (S7 incubation)",
            "rule": rule,
            "gates": {k: bool(v) for k, v in gates.items()},
            "gates_pass": bool(gates_pass),
            "market": {"net4": net4, "net25q": net25q, "ratio10": ratio10,
                       "nifty_ti65": None if np.isnan(ti65_idx)
                       else round(ti65_idx, 3)},
            "mechanics": MECHANICS,
            "candidates": _candidates(s, mask, ["high"]) if gates_pass else [],
            "suppressed_candidates": 0 if gates_pass else int(mask.sum()),
        }

    strategies = {
        "b5_short_green_tape": block(
            "Batch5 green-tape breakdown short (refined)",
            "SHORT 4%-down day, mcap top-150, when net4 >= 18 and "
            "Nifty not extended",
            b5_gates, b5_pass, b5_mask),
        "ga_short_pocket": block(
            "GA-evolved short pocket",
            "SHORT 4%-down day, liquid decile, volume not drying, when "
            "tape is healthy (ratio10/net25q)",
            ga_gates, ga_pass, ga_mask),
    }
    if hm is not None and lm is not None and regime is not None:
        strategies["ryan_minervini"] = _ryan_minervini(summary, cm, vm, hm, lm, regime)
    return {
        "_note": ("PAPER SIGNALS ONLY — S7 incubation forward test. These "
                  "are graded nightly (grade_decisions) and compared to the "
                  "backtest before any promotion to real money."),
        "strategies": strategies,
    }
