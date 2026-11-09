import unittest

import numpy as np
import pandas as pd

from backtest.studies.intraday_halfhour_index import daily_observations, daily_portfolio_returns, random_sign_sharpes, strategy_returns


def frame():
    rows = [
        ("2025-01-02 09:40:00+05:30", 99, 100), ("2025-01-02 09:45:00+05:30", 100, 101),
        ("2025-01-02 15:25:00+05:30", 101, 100),
        ("2025-01-03 09:40:00+05:30", 109, 110), ("2025-01-03 09:45:00+05:30", 111, 111),
        ("2025-01-03 15:00:00+05:30", 111.5, 111.7),
        ("2025-01-03 15:25:00+05:30", 112, 112),
    ]
    return pd.DataFrame(rows, columns=["date", "open", "close"])


class IntradayHalfHourTests(unittest.TestCase):
    def test_predictor_ends_before_entry_and_uses_no_exit_data(self):
        observations = daily_observations(frame(), "NIFTY_50")
        row = observations.iloc[0]
        self.assertAlmostEqual(row["predictor"], 0.10)  # 09:40 close 110 / prior 15:25 close 100
        self.assertAlmostEqual(row["raw_return"], 112 / 111 - 1)  # 09:45 OPEN to 15:25 CLOSE
        self.assertNotEqual(row["cutoff_close"], row["entry_open"])

    def test_cost_is_round_trip_ten_bps(self):
        observations = daily_observations(frame(), "NIFTY_50")
        trade = strategy_returns(observations, "momentum", 0.001).iloc[0]
        self.assertAlmostEqual(trade["cost"], 0.001)
        self.assertAlmostEqual(trade["net"], trade["gross"] - 0.001)

    def test_exact_replication_enters_last_halfhour_after_observable_cutoff(self):
        observations = daily_observations(frame(), "NIFTY_50", cutoff_time="09:40", entry_time="15:00", exit_time="15:25")
        row = observations.iloc[0]
        self.assertAlmostEqual(row["predictor"], 0.10)
        self.assertAlmostEqual(row["entry_open"], 111.5)
        self.assertAlmostEqual(row["raw_return"], 112 / 111.5 - 1)

    def test_random_sign_control_is_deterministic(self):
        observations = pd.concat([daily_observations(frame(), "NIFTY_50")] * 8, ignore_index=True)
        first = random_sign_sharpes(observations, paths=20, seed=7)
        second = random_sign_sharpes(observations, paths=20, seed=7)
        np.testing.assert_array_equal(first, second)

    def test_two_index_legs_are_one_equal_weight_daily_observation(self):
        returns = pd.DataFrame({"date": pd.to_datetime(["2025-01-03", "2025-01-03"]),
                                "gross": [0.01, -0.01], "cost": [0.001, 0.001], "net": [0.009, -0.011]})
        daily = daily_portfolio_returns(returns)
        self.assertEqual(len(daily), 1)
        self.assertAlmostEqual(daily.iloc[0]["gross"], 0.0)
        self.assertAlmostEqual(daily.iloc[0]["net"], -0.001)

    def test_missing_required_bar_is_excluded(self):
        broken = frame().drop(index=4)  # missing the second-day 09:45 entry bar
        self.assertTrue(daily_observations(broken, "NIFTY_50").empty)


if __name__ == "__main__":
    unittest.main()
