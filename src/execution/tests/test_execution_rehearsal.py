import json
import os
import tempfile
import unittest
from datetime import date

import pandas as pd

from execution.rehearsal import run_rehearsal, write_rehearsal


def state(data_date="2025-01-02"):
    return {"meta": {"data_date": data_date}, "regime": {"knobs": {
        "risk_per_trade_pct": 1.0, "max_open_positions": 2, "max_gross_exposure_pct": 100}},
        "incubation": {"strategies": {"b5_short_green_tape": {"gates_pass": True,
        "candidates": [{"symbol": "X", "close": 100, "stop_ref": 105}]}}}}


def bar_frame():
    rows = [("2025-01-02", 100, 105, 99, 100), ("2025-01-03", 100, 101, 99, 98),
            ("2025-01-06", 100, 101, 99, 98), ("2025-01-07", 100, 101, 99, 98),
            ("2025-01-08", 100, 101, 99, 98), ("2025-01-09", 100, 101, 99, 98)]
    return pd.DataFrame(rows, columns=["date", "open", "high", "low", "close"])


class ExecutionRehearsalTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.states = os.path.join(self.temp.name, "state")
        self.bars = os.path.join(self.temp.name, "bars")
        os.makedirs(self.states)
        os.makedirs(self.bars)
        with open(os.path.join(self.states, "2025-01-02.json"), "w", encoding="utf-8") as handle:
            json.dump(state(), handle)
        with open(os.path.join(self.states, "latest.json"), "w", encoding="utf-8") as handle:
            json.dump(state(), handle)
        bar_frame().to_parquet(os.path.join(self.bars, "X.parquet"))

    def tearDown(self):
        self.temp.cleanup()

    def test_stale_state_fail_closes_without_historical_flag(self):
        report = run_rehearsal(states_dir=self.states, bars_dir=self.bars, state_choice="latest",
                               today=date(2025, 1, 20))
        self.assertEqual(report["rehearsals"], [])
        self.assertFalse(report["checklist"][-1]["passed"])

    def test_historical_path_simulates_ticket(self):
        report = run_rehearsal(states_dir=self.states, bars_dir=self.bars, state_choice="2025-01-02",
                               historical_state=True, today=date(2025, 1, 20))
        rehearsal = report["rehearsals"][0]
        self.assertTrue(rehearsal["sizing"]["accepted"])
        self.assertIn("PAPER REHEARSAL / DO NOT PUNCH", rehearsal["manual_card"])
        self.assertEqual(rehearsal["fill_stop_exit_evidence"]["entry"]["price"], 100.0)

    def test_invalid_sizing_is_a_checklist_failure(self):
        report = run_rehearsal(states_dir=self.states, bars_dir=self.bars, state_choice="2025-01-02",
                               historical_state=True, equity=0, today=date(2025, 1, 20))
        rehearsal = report["rehearsals"][0]
        self.assertFalse(rehearsal["sizing"]["accepted"])
        self.assertFalse(next(check for check in rehearsal["checklist"] if check["name"] == "sizing")["passed"])

    def test_artifact_is_deterministic_and_idempotent(self):
        report = run_rehearsal(states_dir=self.states, bars_dir=self.bars, state_choice="2025-01-02",
                               historical_state=True, today=date(2025, 1, 20))
        out = os.path.join(self.temp.name, "rehearsals")
        first = write_rehearsal(report, out)
        with open(first, encoding="utf-8") as handle:
            payload = handle.read()
        second = write_rehearsal(report, out)
        self.assertEqual(first, second)
        with open(second, encoding="utf-8") as handle:
            self.assertEqual(payload, handle.read())
        self.assertEqual(len(os.listdir(out)), 1)

    def test_module_never_imports_execution_code(self):
        path = os.path.join(os.path.dirname(__file__), "..", "rehearsal.py")
        with open(path, encoding="utf-8") as handle:
            source = handle.read()
        self.assertNotIn("orders.execute", source)
        self.assertNotIn("place_order", source)


if __name__ == "__main__":
    unittest.main()
