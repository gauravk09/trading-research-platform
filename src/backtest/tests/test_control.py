"""control.py: same-date random entries with the matched trade's geometry."""

import types
import unittest

import numpy as np
import pandas as pd

from backtest import control, simulator


def scaled_copies(n_stocks=8, n_dates=40, seed=3):
    """Every stock is the same price path times a constant, so a correctly scaled
    control trade must reproduce the strategy trade's R exactly."""
    rng = np.random.default_rng(seed)
    base = 100 * np.exp(np.cumsum(rng.normal(0, 0.02, n_dates)))
    dates = pd.bdate_range("2021-01-01", periods=n_dates, tz="Asia/Kolkata")
    factors = np.arange(1, n_stocks + 1, dtype=float)
    make = lambda path: pd.DataFrame(np.outer(path, factors), index=dates,
                                     columns=[f"S{i}" for i in range(n_stocks)])
    frames = {"close": make(base), "open": make(base * 0.999),
              "high": make(base * 1.01), "low": make(base * 0.99)}
    return frames.__getitem__


def module_with_signal_on(col, bars):
    signal = col("close") * 0 > 1                            # all False
    for bar in bars:
        signal.iloc[bar, 0] = True                           # strategy trades stock S0 only
    return types.SimpleNamespace(
        DIRECTION="long", DEDUP_BARS=0, COSTS_PCT_PER_SIDE=0.2, MAX_STOP_PCT=None,
        universe_conditions=lambda col: {}, entry_conditions=lambda col: {"s": signal},
        stop_level=lambda col, entry: col("close").shift(1) * 0.95,          # frozen, pivot-like
        exit_rules=lambda col, entry: [
            {"id": "below_level", "kind": "close_exit", "op": "<", "level": col("close").shift(1) * 0.99,
             "fraction": 1.0},
            {"id": "time", "kind": "time", "value": 6, "fraction": 1.0}])


class ControlTests(unittest.TestCase):
    def setUp(self):
        self.col = scaled_copies()
        self.module = module_with_signal_on(self.col, [3, 15, 27])
        self.strategy = simulator.simulate(self.module, self.col, "next_open")

    def test_one_control_trade_per_strategy_trade_on_the_same_dates(self):
        ctrl = control.control_trades(self.module, self.col, "next_open", self.strategy, seed=7)
        self.assertEqual(len(ctrl), len(self.strategy))
        self.assertEqual(sorted(ctrl.signal_date), sorted(self.strategy.signal_date))

    def test_geometry_is_scaled_so_scaled_copies_give_identical_r(self):
        ctrl = control.control_trades(self.module, self.col, "next_open", self.strategy, seed=7)
        self.assertTrue((ctrl.symbol != "S0").any(), "seed should pick other stocks too")
        merged = self.strategy.merge(ctrl, on="signal_date", suffixes=("", "_c"))
        np.testing.assert_allclose(merged.r_c, merged.r, rtol=1e-12)
        self.assertEqual(list(merged.exit_reason_c), list(merged.exit_reason))
        self.assertEqual(list(merged.exit_date_c), list(merged.exit_date))
        factor = merged.symbol_c.str[1:].astype(int) + 1
        np.testing.assert_allclose(merged.entry_px_c, merged.entry_px * factor, rtol=1e-12)

    def test_same_seed_same_control(self):
        a = control.control_trades(self.module, self.col, "next_open", self.strategy, seed=11)
        b = control.control_trades(self.module, self.col, "next_open", self.strategy, seed=11)
        pd.testing.assert_frame_equal(a, b)

    def test_seed_comes_from_the_spec_hash(self):
        self.assertEqual(control.seed_from("00000010abcdef"), 16)

    def test_no_strategy_trades_no_control(self):
        empty = self.strategy.iloc[0:0]
        self.assertTrue(control.control_trades(self.module, self.col, "next_open", empty, seed=1).empty)


if __name__ == "__main__":
    unittest.main()
