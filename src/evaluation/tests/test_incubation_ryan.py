import unittest

import numpy as np
import pandas as pd

from evaluation.incubation import build_incubation


def _panel(T=320, N=6, seed=0):
    """Flat-ish universe plus one engineered Ryan breakout on the last bar
    (S0): 40-bar base holding 80% of the prior top, close at a new 252d high
    on 2x volume, closing at the top of its range."""
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range("2025-01-01", periods=T, tz="Asia/Kolkata")
    cols = [f"S{i}" for i in range(N)]
    close = pd.DataFrame(100 + rng.standard_normal((T, N)).cumsum(axis=0) * 0.2,
                         index=idx, columns=cols)
    s0 = np.full(T, 100.0)
    s0[:-40] = np.linspace(80, 120, T - 40)          # long uptrend to a top of 120
    s0[-40:-1] = 100                                  # base: floor 100 >= 0.75*120
    s0[-1] = 121                                      # new 252d high on the last bar
    close["S0"] = s0
    high = close * 1.01
    low = close * 0.99
    high.iloc[-1, 0], low.iloc[-1, 0] = 121.5, 118.0  # range_pos = 0.86
    vol = pd.DataFrame(2_000_000.0, index=idx, columns=cols)
    vol.iloc[-1, 0] = 4_000_000.0                     # 2x the 50d average
    # S1: same shape but a weak close (range_pos 0.2) -> filtered out
    close["S1"] = s0
    high.iloc[-1, 1], low.iloc[-1, 1] = 125.0, 120.0
    vol.iloc[-1, 1] = 4_000_000.0
    return close, high, low, vol


class RyanIncubationTests(unittest.TestCase):
    def setUp(self):
        self.close, self.high, self.low, self.vol = _panel()
        self.summary = pd.DataFrame({"symbol": self.close.columns, "chg_pct": 0.0,
                                     "close": self.close.iloc[-1].values,
                                     "avg_turnover_cr": 5.0, "mcap_cr": 5000.0,
                                     "rs_rank": 90.0, "high": self.high.iloc[-1].values})
        self.mm = pd.DataFrame({"up4": [10], "dn4": [5], "up25q": [50], "dn25q": [20],
                                "ratio10": [1.2]})

    def _build(self, tier, allowed_entries=("breakout", "episodic_pivot", "anticipation")):
        regime = {"tier": tier, "knobs": {"allowed_entries": list(allowed_entries)}}
        return build_incubation(self.summary, self.close, self.vol, self.mm, None,
                                hm=self.high, lm=self.low,
                                regime=regime)["strategies"]["ryan_minervini"]

    def test_engineered_breakout_is_the_only_candidate_and_stop_is_seven_pct(self):
        blk = self._build("CALM")
        self.assertTrue(blk["gates_pass"])
        self.assertEqual([c["symbol"] for c in blk["candidates"]], ["S0"])
        c = blk["candidates"][0]
        self.assertEqual(c["strategy"], "ryan")
        self.assertAlmostEqual(c["stop_ref"], round(121 * 0.93, 2))
        self.assertGreaterEqual(c["range_pos"], 0.75)
        self.assertEqual(blk["mechanics"]["side"], "long")

    def test_breakouts_not_allowed_suppresses_but_counts(self):
        blk = self._build("ELEVATED", allowed_entries=("episodic_pivot",))
        self.assertFalse(blk["gates_pass"])
        self.assertEqual(blk["candidates"], [])
        self.assertEqual(blk["suppressed_candidates"], 1)

    def test_252_row_matrix_raises_instead_of_silently_finding_nothing(self):
        close, high, low, vol = _panel(T=252)
        summary = self.summary.assign(close=close.iloc[-1].values, high=high.iloc[-1].values)
        with self.assertRaisesRegex(ValueError, "252 rows"):
            build_incubation(summary, close, vol, self.mm, None, hm=high, lm=low,
                             regime={"tier": "CALM", "knobs": {"allowed_entries": ["breakout"]}})

    def test_block_absent_without_high_low_matrices(self):
        out = build_incubation(self.summary, self.close, self.vol, self.mm, None)
        self.assertNotIn("ryan_minervini", out["strategies"])


if __name__ == "__main__":
    unittest.main()
