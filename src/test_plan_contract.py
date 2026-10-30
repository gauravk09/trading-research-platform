import unittest

from plan_contract import gate_entry


def _state(**over):
    s = {"meta": {"data_date": "2026-09-02"},
         "regime": {"knobs": {"risk_per_trade_pct": 0.5, "max_open_positions": 4,
                              "max_gross_exposure_pct": 75}},
         "participation": {"ratio_20d": 0.94},
         "open_trades": [],
         "scans": {"breakout_setup": {"candidates": [
             {"symbol": "URBANCO", "close": 157.0, "results_due_days": None},
             {"symbol": "ALKYLAMINE", "close": 2040.0, "results_due_days": 3}]}}}
    s.update(over)
    return s


def _reco(**over):
    r = {"symbol": "URBANCO", "scan": "breakout_setup", "entry": 157.4, "stop": 151.0,
         "qty": 1000, "risk_inr": 6400.0}
    r.update(over)
    return r


class PlanContractTests(unittest.TestCase):
    def test_clean_recommendation_passes_every_hard_gate(self):
        out, rows = gate_entry({"date": "2026-09-02", "equity": 1_400_000,
                                "recommendations": [_reco()]}, _state())
        self.assertEqual(rows[0][1], "PASS")
        self.assertEqual(len(out["recommendations"]), 1)
        self.assertEqual(out["rejected"], [])
        self.assertTrue(all(v["ok"] for v in out["recommendations"][0]["gates"].values()))

    def test_stop_above_entry_is_rejected_with_reason(self):
        out, rows = gate_entry({"date": "2026-09-02", "equity": 1_400_000,
                                "recommendations": [_reco(stop=160.0)]}, _state())
        self.assertEqual(rows[0][1], "BLOCK")
        self.assertIn("stop_side", out["rejected"][0]["reject_reason"])
        self.assertEqual(out["recommendations"], [])

    def test_circuit_breaker_and_participation_block_everything(self):
        st = _state(open_trades=[{"status": "stopped"}] * 3, participation={"ratio_20d": 0.6})
        out, _ = gate_entry({"date": "2026-09-02", "equity": 1_400_000,
                             "recommendations": [_reco(), _reco(symbol="ALKYLAMINE", entry=2046.7,
                                                                stop=1915.0, qty=50)]}, st)
        self.assertEqual(len(out["rejected"]), 2)
        for r in out["rejected"]:
            self.assertFalse(r["gates"]["circuit_breaker_ok"]["ok"])
            self.assertFalse(r["gates"]["participation_ok"]["ok"])

    def test_exposure_cap_counts_earlier_recommendations(self):
        # equity 100k, cap 75% = 75k; two 50k notionals: second one must fail
        out, rows = gate_entry({"date": "2026-09-02", "equity": 100_000,
                                "recommendations": [_reco(qty=300, risk_inr=400),
                                                    _reco(symbol="ALKYLAMINE", entry=2040.0,
                                                          stop=2000.0, qty=25, risk_inr=400)]},
                               _state())
        self.assertEqual([r[1] for r in rows], ["PASS", "BLOCK"])
        self.assertIn("exposure_ok", out["rejected"][0]["reject_reason"])

    def test_earnings_is_a_warning_not_a_block(self):
        out, rows = gate_entry({"date": "2026-09-02", "equity": 1_400_000,
                                "recommendations": [_reco(symbol="ALKYLAMINE", entry=2046.7,
                                                          stop=1915.0, qty=50)]}, _state())
        self.assertEqual(rows[0][1], "PASS")
        self.assertEqual(out["recommendations"][0]["gate_warnings"], ["earnings_ok"])

    def test_stale_state_and_unknown_symbol_and_far_entry(self):
        out, _ = gate_entry({"date": "2026-09-01", "equity": 1_400_000,
                             "recommendations": [_reco(symbol="NOPE", entry=300.0, stop=290.0)]},
                            _state())
        reason = out["rejected"][0]["reject_reason"]
        for gate in ("fresh_state", "in_scans", "leakage_checked"):
            self.assertIn(gate, reason)


if __name__ == "__main__":
    unittest.main()
