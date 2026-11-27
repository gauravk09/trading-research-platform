"""exits.py is the one copy of the stop / exit rules.

1. The event store's four rulers, now built on exits.walk, must give BIT-IDENTICAL
   results to their pre-refactor code (kept verbatim below as the reference).
2. Unit tests of the walker's fill rules.
"""

import unittest

import numpy as np
import pandas as pd

from backtest import event_store as ES
from backtest import exits
from backtest.event_store import TRAIL_CAP, TRAIL_TARGET_R


# ── reference: the four functions exactly as they were on main ────────────────

def ref_stop_r(entry, signal_low, d, s, O, L, C, n_dates, horizon):
    """Verbatim body from main before the exits.py refactor."""
    out = np.full(len(entry), np.nan)
    for i in range(len(entry)):
        d0, si = d[i], s[i]
        if d0 + 1 >= n_dates or np.isnan(entry[i]):
            continue
        stop = max(signal_low[i], entry[i] * 0.94)
        risk = entry[i] - stop
        if risk <= 0 or np.isnan(risk):
            continue
        for k in range(1, horizon + 1):
            if d0 + k >= n_dates or np.isnan(C[d0 + k, si]):
                break
            if L[d0 + k, si] <= stop:
                out[i] = (min(O[d0 + k, si], stop) - entry[i]) / risk
                break
            if k == horizon:
                out[i] = (C[d0 + k, si] - entry[i]) / risk
    return out


def ref_stop_r_short(entry, signal_high, d, s, O, H, C, n_dates, horizon):
    """Verbatim body from main before the exits.py refactor."""
    out = np.full(len(entry), np.nan)
    for i in range(len(entry)):
        d0, si = d[i], s[i]
        if d0 + 1 >= n_dates or np.isnan(entry[i]):
            continue
        stop = min(signal_high[i], entry[i] * 1.06)
        risk = stop - entry[i]
        if risk <= 0 or np.isnan(risk):
            continue
        for k in range(1, horizon + 1):
            if d0 + k >= n_dates or np.isnan(C[d0 + k, si]):
                break
            if H[d0 + k, si] >= stop:
                out[i] = (entry[i] - max(O[d0 + k, si], stop)) / risk
                break
            if k == horizon:
                out[i] = (entry[i] - C[d0 + k, si]) / risk
    return out


def ref_stop_r_trail(entry, signal_low, d, s, O, H, L, C, RL, n_dates, be_at=None):
    """Verbatim body from main before the exits.py refactor."""
    out = np.full(len(entry), np.nan)
    for i in range(len(entry)):
        d0, si = d[i], s[i]
        if d0 + 1 >= n_dates or np.isnan(entry[i]):
            continue
        e = entry[i]
        stop = max(signal_low[i], e * 0.94)
        risk = e - stop
        if risk <= 0 or np.isnan(risk):
            continue
        target = e + TRAIL_TARGET_R * risk
        be_level = e + be_at * risk if be_at is not None else None
        half_r, half_done, trail = 0.0, False, -np.inf
        for k in range(1, TRAIL_CAP + 1):
            day = d0 + k
            if day >= n_dates or np.isnan(C[day, si]):
                break                                   # unresolved -> NaN
            if L[day, si] <= stop:
                fill = min(O[day, si], stop)
                out[i] = half_r + (0.5 if half_done else 1.0) * (fill - e) / risk
                break
            if not half_done and H[day, si] >= target:
                half_r = 0.5 * (max(O[day, si], target) - e) / risk
                half_done = True
            if be_level is not None and stop < e and H[day, si] >= be_level:
                stop = e
            lvl = RL[day, si]
            if lvl > trail:                              # NaN never passes
                trail = lvl
            if C[day, si] < trail:
                nxt = day + 1
                px = O[nxt, si] if nxt < n_dates and not np.isnan(O[nxt, si]) \
                    else C[day, si]
                out[i] = half_r + (0.5 if half_done else 1.0) * (px - e) / risk
                break
            if k == TRAIL_CAP:
                out[i] = half_r + (0.5 if half_done else 1.0) * (C[day, si] - e) / risk
    return out


def ref_stop_r_trail_short(entry, signal_high, d, s, O, H, L, C, RH, n_dates,
                        be_at=None):
    """Verbatim body from main before the exits.py refactor."""
    out = np.full(len(entry), np.nan)
    for i in range(len(entry)):
        d0, si = d[i], s[i]
        if d0 + 1 >= n_dates or np.isnan(entry[i]):
            continue
        e = entry[i]
        stop = min(signal_high[i], e * 1.06)
        risk = stop - e
        if risk <= 0 or np.isnan(risk):
            continue
        target = e - TRAIL_TARGET_R * risk
        be_level = e - be_at * risk if be_at is not None else None
        half_r, half_done, trail = 0.0, False, np.inf
        for k in range(1, TRAIL_CAP + 1):
            day = d0 + k
            if day >= n_dates or np.isnan(C[day, si]):
                break
            if H[day, si] >= stop:
                fill = max(O[day, si], stop)
                out[i] = half_r + (0.5 if half_done else 1.0) * (e - fill) / risk
                break
            if not half_done and L[day, si] <= target:
                half_r = 0.5 * (e - min(O[day, si], target)) / risk
                half_done = True
            if be_level is not None and stop > e and L[day, si] <= be_level:
                stop = e
            lvl = RH[day, si]
            if lvl < trail:
                trail = lvl
            if C[day, si] > trail:
                nxt = day + 1
                px = O[nxt, si] if nxt < n_dates and not np.isnan(O[nxt, si]) \
                    else C[day, si]
                out[i] = half_r + (0.5 if half_done else 1.0) * (e - px) / risk
                break
            if k == TRAIL_CAP:
                out[i] = half_r + (0.5 if half_done else 1.0) * (e - C[day, si]) / risk
    return out


# ── data with gaps, missing bars and events near the end of the data ──────────

def market(n_dates=260, n_syms=25, seed=0):
    rng = np.random.default_rng(seed)
    close = 100 * np.exp(np.cumsum(rng.normal(0.0005, 0.025, (n_dates, n_syms)), axis=0))
    gap = rng.normal(0, 0.02, close.shape) * (rng.random(close.shape) < 0.15)
    open_ = np.vstack([close[:1], close[:-1]]) * (1 + gap)
    high = np.maximum(open_, close) * (1 + np.abs(rng.normal(0, 0.012, close.shape)))
    low = np.minimum(open_, close) * (1 - np.abs(rng.normal(0, 0.012, close.shape)))
    holes = rng.random(close.shape) < 0.01
    for a in (open_, high, low, close):
        a[holes] = np.nan
    d = rng.integers(0, n_dates, 4000)
    s = rng.integers(0, n_syms, 4000)
    return open_, high, low, close, d, s


def same_bits(a, b):
    return a.dtype == b.dtype and a.shape == b.shape and a.tobytes() == b.tobytes()


class EventStoreParityTests(unittest.TestCase):
    """New event-store rulers == the pre-refactor code, bit for bit."""

    def setUp(self):
        self.O, self.H, self.L, self.C, self.d, self.s = market()
        self.n = self.C.shape[0]
        nxt = np.minimum(self.d + 1, self.n - 1)
        self.entries = {"open": np.where(self.d + 1 < self.n, self.O[nxt, self.s], np.nan),
                        "close": self.C[self.d, self.s]}
        closes = pd.DataFrame(self.C)
        self.RL = closes.rolling(ES.TRAIL_WINDOW).min().to_numpy()
        self.RH = closes.rolling(ES.TRAIL_WINDOW).max().to_numpy()

    def test_inputs_exercise_the_edge_cases(self):
        self.assertTrue(np.isnan(self.C).any())
        self.assertTrue((self.d >= self.n - 5).any())        # trades still open at the data end

    def test_stop_r_long_and_short(self):
        lo, hi = self.L[self.d, self.s], self.H[self.d, self.s]
        for ruler, entry in self.entries.items():
            for horizon in (5, 20):
                with self.subTest(ruler=ruler, horizon=horizon):
                    args = (self.d, self.s, self.O)
                    self.assertTrue(same_bits(
                        ES._stop_r(entry, lo, *args, self.L, self.C, self.n, horizon),
                        ref_stop_r(entry, lo, *args, self.L, self.C, self.n, horizon)))
                    self.assertTrue(same_bits(
                        ES._stop_r_short(entry, hi, *args, self.H, self.C, self.n, horizon),
                        ref_stop_r_short(entry, hi, *args, self.H, self.C, self.n, horizon)))

    def test_trail_long_and_short_with_and_without_breakeven(self):
        lo, hi = self.L[self.d, self.s], self.H[self.d, self.s]
        entry = self.entries["open"]
        bars = (self.d, self.s, self.O, self.H, self.L, self.C)
        for be_at in (None, ES.TRAIL_BE_R):
            with self.subTest(be_at=be_at):
                self.assertTrue(same_bits(
                    ES._stop_r_trail(entry, lo, *bars, self.RL, self.n, be_at=be_at),
                    ref_stop_r_trail(entry, lo, *bars, self.RL, self.n, be_at=be_at)))
                self.assertTrue(same_bits(
                    ES._stop_r_trail_short(entry, hi, *bars, self.RH, self.n, be_at=be_at),
                    ref_stop_r_trail_short(entry, hi, *bars, self.RH, self.n, be_at=be_at)))

    def test_results_are_not_trivially_empty(self):
        lo = self.L[self.d, self.s]
        bars = (self.d, self.s, self.O, self.H, self.L, self.C)
        r = ES._stop_r_trail(self.entries["open"], lo, *bars, self.RL, self.n)
        self.assertGreater(np.isfinite(r).sum(), 1000)
        self.assertTrue(np.isnan(r).any())


# ── walker fill rules ────────────────────────────────────────────────────────

def walk(rows, plan, entry=100.0, signal_bar=0):
    a = np.array(rows, dtype=float)
    return exits.walk(a[:, 0], a[:, 1], a[:, 2], a[:, 3], signal_bar, entry, plan)


class WalkTests(unittest.TestCase):
    def test_stop_gap_fills_at_open_else_at_stop(self):
        gap = walk([(100, 101, 99, 100), (90, 92, 88, 91)], exits.ExitPlan("long", stop=95))
        inside = walk([(100, 101, 99, 100), (98, 99, 94, 96)], exits.ExitPlan("long", stop=95))
        self.assertEqual(gap.legs[0][1:3], (90, "stop"))
        self.assertEqual(inside.legs[0][1:3], (95, "stop"))

    def test_partial_then_close_exit_at_next_open(self):
        plan = exits.ExitPlan("long", touches=(exits.Touch("half", 110, 0.5),),
                              close_exits=(exits.CloseExit("below_100", "<", 100.0),))
        rows = [(100, 101, 99, 100), (100, 111, 99, 108), (105, 106, 98, 99), (97, 98, 96, 98)]
        out = walk(rows, plan)
        self.assertEqual([(f, p, r) for f, p, r, _ in out.legs], [(0.5, 110, "half"), (0.5, 97, "below_100")])
        self.assertAlmostEqual(out.r_multiple(100, 5, "long"), 0.5 * 10 / 5 + 0.5 * -3 / 5)

    def test_time_cap_counts_from_the_signal_bar(self):
        rows = [(100, 101, 99, 100 + i) for i in range(6)]
        out = walk(rows, exits.ExitPlan("long", time_cap=3))
        self.assertEqual(out.legs[0][1:], (103, "time", 3))

    def test_missing_bar_or_data_end_is_unresolved(self):
        hole = walk([(100, 101, 99, 100), (np.nan,) * 4, (100, 101, 99, 100)], exits.ExitPlan("long", time_cap=2))
        short_data = walk([(100, 101, 99, 100), (100, 101, 99, 100)], exits.ExitPlan("long", time_cap=5))
        self.assertFalse(hole.resolved)
        self.assertFalse(short_data.resolved)
        self.assertTrue(np.isnan(hole.r_multiple(100, 5, "long")))

    def test_breakeven_takes_effect_next_bar(self):
        plan = exits.ExitPlan("long", stop=95, breakeven_at=105)
        same_bar = walk([(100, 101, 99, 100), (100, 106, 94, 100)], plan)        # +1R touch, then stop: full loss
        next_bar = walk([(100, 101, 99, 100), (100, 106, 99, 104), (101, 102, 99, 100)], plan)
        self.assertEqual(same_bar.legs[0][1], 95)
        self.assertEqual(next_bar.legs[0][1:3], (100, "stop"))

    def test_short_mirror(self):
        plan = exits.ExitPlan("short", stop=105, touches=(exits.Touch("target", 90, 1.0),))
        stopped = walk([(100, 101, 99, 100), (103, 107, 102, 106)], plan)
        target = walk([(100, 101, 99, 100), (95, 96, 89, 90)], plan)
        self.assertEqual(stopped.legs[0][1], 105)
        self.assertEqual(target.legs[0][1:3], (90, "target"))
        self.assertAlmostEqual(target.r_multiple(100, 5, "short"), 2.0)

    def test_signal_exit_and_ratchet(self):
        when = np.array([False, False, True, False])
        sig = walk([(100, 101, 99, 100)] * 4, exits.ExitPlan("long", close_exits=(exits.CloseExit("sig", when=when),)))
        self.assertEqual(sig.legs[0][1:], (100, "sig", 3))
        level = np.array([np.nan, 98, 96, 97, 97])      # ratchet keeps 98 after the level drops
        rows = [(100, 101, 99, 100), (100, 101, 99, 100), (99, 100, 97, 97.5), (97, 98, 96, 97), (96, 97, 95, 96)]
        trail = walk(rows, exits.ExitPlan("long", close_exits=(exits.CloseExit("trail", "<", level, ratchet=True),)))
        self.assertEqual(trail.legs[0][2:], ("trail", 3))          # 97.5 < 98 at bar 2, filled bar 3 open

    def test_capped_stop(self):
        self.assertEqual(exits.capped_stop("long", 100, 90, 0.94), 94.0)
        self.assertEqual(exits.capped_stop("long", 100, 97, 0.94), 97)
        self.assertEqual(exits.capped_stop("short", 100, 110, 1.06), 106.0)
        self.assertTrue(np.isnan(exits.capped_stop("long", 100, np.nan, 0.94)))


if __name__ == "__main__":
    unittest.main()
