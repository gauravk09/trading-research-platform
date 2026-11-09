import csv
import os
import tempfile
import unittest

import pandas as pd

from execution.paper_broker import derive_trades, replay, write_outputs


def bars(rows):
    return pd.DataFrame(rows, columns=["date", "open", "high", "low", "close"])


def state(symbol="X", date="2025-01-02"):
    return {"meta": {"data_date": date}, "incubation": {"strategies": {
        "b5_short_green_tape": {"gates_pass": True,
                                  "candidates": [{"symbol": symbol, "close": 100}]}
    }}}


def standard_rows(first=(100, 101, 99, 98)):
    return [("2025-01-02", 100, 105, 99, 100),
            ("2025-01-03", *first),
            ("2025-01-06", 100, 101, 99, 98),
            ("2025-01-07", 100, 101, 99, 98),
            ("2025-01-08", 100, 101, 99, 98),
            ("2025-01-09", 100, 101, 99, 98)]


class PaperBrokerTests(unittest.TestCase):
    def events(self, rows=standard_rows(), states=None):
        return replay(states or [state()], {"X": bars(rows)})

    def completed_trade(self, rows=standard_rows()):
        return derive_trades(self.events(rows))[0]

    def test_entry_day_intraday_stop_has_no_mtm(self):
        events = self.events(standard_rows((100, 107, 99, 100)))  # stop is 105
        self.assertEqual([event["event"] for event in events],
                         ["signal_intent", "d1_open_fill", "stop_fill"])
        self.assertEqual(events[-1]["price"], 105.0)
        self.assertEqual(events[-1]["reason"], "stop")

    def test_gap_stop_is_filled_at_open(self):
        trade = self.completed_trade(standard_rows((108, 109, 107, 108)))
        self.assertEqual((trade["exit"], trade["reason"]), (108.0, "stop_gap"))

    def test_exact_d5_time_exit_and_five_mtm_events(self):
        events = self.events()
        self.assertEqual(events[-1]["event"], "d5_time_exit")
        self.assertEqual(events[-1]["date"], "2025-01-09")
        self.assertEqual(len([event for event in events if event["event"] == "daily_mtm"]), 5)

    def test_insufficient_horizon_is_unresolved_without_entry(self):
        events = self.events(standard_rows()[:-1])
        self.assertEqual([event["event"] for event in events], ["signal_intent", "unresolved"])
        self.assertIn("fewer", events[-1]["reason"])

    def test_missing_signal_high_and_missing_signal_data(self):
        no_high = standard_rows()
        no_high[0] = ("2025-01-02", 100, None, 99, 100)
        self.assertEqual(self.events(no_high)[-1]["reason"], "missing signal-day high")
        self.assertEqual(self.events(standard_rows()[1:])[-1]["reason"], "missing signal-day data")

    def test_cost_is_applied_only_to_completed_summary(self):
        trade = self.completed_trade()
        self.assertAlmostEqual(trade["gross_return"], 0.02)
        self.assertAlmostEqual(trade["net_return"], 0.019)
        self.assertEqual(trade["cost_bps_per_side"], 5.0)

    def test_duplicate_states_and_candidates_emit_one_journal(self):
        duplicate = state()
        duplicate["incubation"]["strategies"]["b5_short_green_tape"]["candidates"] *= 2
        events = self.events(states=[state(), duplicate])
        self.assertEqual(len(events), len({event["event_id"] for event in events}))
        self.assertEqual(len([event for event in events if event["event"] == "signal_intent"]), 1)

    def test_write_is_idempotent_and_uses_full_journal(self):
        events = self.events()
        with tempfile.TemporaryDirectory() as directory:
            first_journal, first_trades = write_outputs(events + events, directory)
            second_journal, second_trades = write_outputs(events, directory)
            self.assertEqual(len(first_journal), len(events))
            self.assertEqual(len(second_journal), len(events))
            self.assertEqual(first_trades, second_trades)
            with open(os.path.join(directory, "trades.csv"), newline="", encoding="utf-8") as handle:
                self.assertEqual(len(list(csv.DictReader(handle))), 1)


if __name__ == "__main__":
    unittest.main()
