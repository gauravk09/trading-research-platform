import unittest

import pandas as pd

from experimentation.studies.fund_behavior import _current_tenure
from webapp.server.fund_study import _safe


class FundBehaviorStudyTests(unittest.TestCase):
    def test_current_tenure_counts_only_consecutive_active_months(self):
        frame = pd.DataFrame({
            "month": pd.date_range("2025-01-31", periods=6, freq="ME"),
            "weight": [0.1, 0.0, 0.2, 0.2, 0.2, 0.2],
        })
        self.assertEqual(_current_tenure(frame), 4)

    def test_current_tenure_is_zero_after_exit(self):
        frame = pd.DataFrame({
            "month": pd.date_range("2025-01-31", periods=3, freq="ME"),
            "weight": [0.1, 0.1, 0.0],
        })
        self.assertEqual(_current_tenure(frame), 0)

    def test_api_cleaner_handles_dates_and_nan(self):
        cleaned = _safe({"date": pd.Timestamp("2026-09-30", tz="Asia/Kolkata"),
                         "value": float("nan")})
        self.assertEqual(cleaned["date"], "2026-09-30T00:00:00+05:30")
        self.assertIsNone(cleaned["value"])


if __name__ == "__main__":
    unittest.main()
