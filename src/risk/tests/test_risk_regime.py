import os
import sys
import unittest

import pandas as pd

sys.path.insert(0, os.path.dirname(__file__))
import risk.regime as risk_regime

LOCKBOX_PREDS = os.path.join(risk_regime.ROOT, "research", "output", "regime", "LOCKBOX_H1", "preds.parquet")


class RiskRegimeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.hist = risk_regime.predict_history()

    @unittest.skipUnless(os.path.exists(LOCKBOX_PREDS), "lockbox predictions not on disk")
    def test_production_dial_reproduces_validated_lockbox_predictions(self):
        lock = pd.read_parquet(LOCKBOX_PREDS)
        lock = lock[lock.index.year == 2026]["p_dd_20"]
        common = lock.index.intersection(self.hist.index)
        self.assertGreater(len(common), 150)
        diff = (self.hist.loc[common, "p_drop_20d"] - lock.loc[common]).abs().max()
        self.assertLess(diff, 1e-9)

    def test_walkforward_history_matches_validated_oos_predictions(self):
        import json
        log = os.path.join(risk_regime.ROOT, "research", "regime", "experiments.jsonl")
        rows = [json.loads(l) for l in open(log)]
        h1 = [r for r in rows if r.get("tag") == "stage-b-long-sequential" and r["model"] == "H1_gaussian_hmm"]
        if not h1 or not os.path.exists(h1[-1]["preds_path"]):
            self.skipTest("validated H1 predictions not on disk")
        oos = pd.read_parquet(h1[-1]["preds_path"])["p_dd_20"]
        wf = risk_regime.walkforward_history(start_year=2000)["p_drop_20d"]
        common = oos.index.intersection(wf.index)
        self.assertGreater(len(common), 6000)
        self.assertLess((wf.loc[common] - oos.loc[common]).abs().max(), 1e-9)

    def test_tier_is_dial_versus_baseline(self):
        above = self.hist["p_drop_20d"] > self.hist["baseline_p_drop_20d"]
        self.assertTrue((self.hist.loc[above, "tier"] == "ELEVATED").all())
        self.assertTrue((self.hist.loc[~above, "tier"] == "CALM").all())

    def test_elevated_is_half_of_calm(self):
        calm, elev = risk_regime.TIER_KNOBS["CALM"], risk_regime.TIER_KNOBS["ELEVATED"]
        self.assertAlmostEqual(elev["risk_per_trade_pct"], calm["risk_per_trade_pct"] / 2)
        self.assertEqual(elev["max_open_positions"], calm["max_open_positions"] // 2)

    def test_evaluate_block_shape(self):
        r = risk_regime.evaluate()
        for key in ("tier", "knobs", "p_drop_20d", "baseline_p_drop_20d", "as_of", "trained_through"):
            self.assertIn(key, r)
        self.assertIn(r["tier"], risk_regime.TIER_KNOBS)


if __name__ == "__main__":
    unittest.main()
