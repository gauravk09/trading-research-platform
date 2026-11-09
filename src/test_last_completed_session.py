import unittest
from datetime import date, datetime
from zoneinfo import ZoneInfo

from data_collection.kite.updater import last_completed_session

IST = ZoneInfo("Asia/Kolkata")


def at(y, m, d, hh, mm):
    return datetime(y, m, d, hh, mm, tzinfo=IST)


class LastCompletedSessionTests(unittest.TestCase):
    # 2026-10-01 is a Thursday.
    def test_during_market_hours_returns_previous_day(self):
        self.assertEqual(last_completed_session(at(2026, 10, 1, 13, 0)), date(2026, 9, 30))

    def test_after_close_returns_today(self):
        self.assertEqual(last_completed_session(at(2026, 10, 1, 15, 45)), date(2026, 10, 1))

    def test_before_open_returns_previous_day(self):
        self.assertEqual(last_completed_session(at(2026, 10, 1, 8, 0)), date(2026, 9, 30))

    def test_monday_morning_returns_friday(self):
        self.assertEqual(last_completed_session(at(2026, 10, 5, 11, 0)), date(2026, 10, 2))

    def test_weekend_returns_friday(self):
        self.assertEqual(last_completed_session(at(2026, 10, 4, 18, 0)), date(2026, 10, 2))


if __name__ == "__main__":
    unittest.main()
