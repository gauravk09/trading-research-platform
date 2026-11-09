import os
import sys
import unittest

import pandas as pd

from data_collection.paths import ROOT_DIR

ROOT = ROOT_DIR
sys.path.insert(0, os.path.join(ROOT, "strategies"))
from stockbee.breakout_setup import breakout_from_consolidation

SUMMARY = os.path.join(ROOT, "data", "processed", "universe_summary.parquet")


@unittest.skipUnless(os.path.exists(SUMMARY), "universe summary not built")
class EmptyBreakoutScanTests(unittest.TestCase):
    def test_zero_matches_returns_empty_frame_instead_of_crashing(self):
        # 2026-09-28: a day with no breakout setups crashed the daily state file
        # (DataFrame.apply(axis=1) on an empty frame returns a frame, not a column).
        summary = pd.read_parquet(SUMMARY)
        out = breakout_from_consolidation(summary, min_consol_days=10_000, max_consol_days=10_001)
        self.assertTrue(out.empty)
        self.assertIn("reason", out.columns)


if __name__ == "__main__":
    unittest.main()
