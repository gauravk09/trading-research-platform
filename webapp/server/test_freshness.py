import unittest
from datetime import date

from webapp.server.freshness import freshness, trading_days_old


class FreshnessTests(unittest.TestCase):
    def test_weekend_counts_only_one_elapsed_session(self):
        self.assertEqual(trading_days_old("2026-09-04", date(2026, 9, 7)), 1)

    def test_more_than_one_session_is_stale(self):
        self.assertTrue(freshness("2026-08-31", date(2026, 9, 2))["stale"])

    def test_recent_session_actionable(self):
        self.assertTrue(freshness("2026-09-01", date(2026, 9, 2))["actionable"])


if __name__ == "__main__":
    unittest.main()
