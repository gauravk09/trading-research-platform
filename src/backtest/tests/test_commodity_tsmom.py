import unittest

import numpy as np
import pandas as pd

from backtest.studies.commodity_tsmom import portfolio_returns, random_sign_control, weights_from_signals


class CommodityTSMOMTests(unittest.TestCase):
    def test_weights_have_one_full_bar_lag(self):
        index = pd.to_datetime(["2025-01-03", "2025-01-06", "2025-01-07"])
        signals = pd.DataFrame({"GC_F": [1.0, np.nan, np.nan]}, index=index)
        vols = pd.DataFrame({"GC_F": [0.2, np.nan, np.nan]}, index=index)
        weights = weights_from_signals(signals, vols, target_vol=0.1, vol_cap=2.0, scaled=True)
        self.assertEqual(weights.iloc[0, 0], 0.0)
        self.assertEqual(weights.iloc[1, 0], 0.5)

    def test_turnover_cost_is_one_way_five_bps(self):
        index = pd.date_range("2025-01-01", periods=3, freq="B")
        returns = pd.DataFrame({"GC_F": [0.0, 0.0, 0.0]}, index=index)
        weights = pd.DataFrame({"GC_F": [0.0, 1.0, 1.0]}, index=index)
        result = portfolio_returns(returns, weights, 0.0005)
        self.assertEqual(result["turnover"].tolist(), [0.0, 1.0, 0.0])
        self.assertEqual(result["cost"].tolist(), [0.0, 0.0005, 0.0])
        self.assertEqual(result["net"].sum(), -0.0005)

    def test_random_control_is_deterministic(self):
        index = pd.date_range("2025-01-03", periods=4, freq="W-FRI")
        signals = pd.DataFrame(1.0, index=index, columns=["GC_F", "SI_F"])
        vols = pd.DataFrame(0.2, index=index, columns=signals.columns)
        first = random_sign_control(signals, vols, paths=3, seed=99, target_vol=0.1, vol_cap=2.0, scaled=True)
        second = random_sign_control(signals, vols, paths=3, seed=99, target_vol=0.1, vol_cap=2.0, scaled=True)
        for left, right in zip(first, second):
            pd.testing.assert_frame_equal(left, right)

    def test_random_control_can_preserve_neutral_week(self):
        index = pd.date_range("2025-01-03", periods=3, freq="W-FRI")
        signals = pd.DataFrame({"GC_F": [1.0, 0.0, -1.0]}, index=index)
        vols = pd.DataFrame(0.2, index=index, columns=signals.columns)
        weights = random_sign_control(
            signals, vols, paths=1, seed=7, preserve_neutral=True,
            target_vol=0.1, vol_cap=2.0, scaled=True,
        )[0]
        # The explicit zero is applied after the standard one-row execution lag.
        self.assertEqual(weights.iloc[2, 0], 0.0)

    def test_flat_prices_are_safe(self):
        index = pd.date_range("2025-01-03", periods=3, freq="W-FRI")
        signals = pd.DataFrame(0.0, index=index, columns=["GC_F"])
        vols = pd.DataFrame(0.0, index=index, columns=["GC_F"])
        weights = weights_from_signals(signals, vols, scaled=True)
        returns = pd.DataFrame(0.0, index=index, columns=["GC_F"])
        result = portfolio_returns(returns, weights)
        self.assertTrue(np.isfinite(weights.to_numpy()).all())
        self.assertTrue(np.isfinite(result.to_numpy()).all())
        self.assertEqual(float(result["net"].sum()), 0.0)


if __name__ == "__main__":
    unittest.main()
