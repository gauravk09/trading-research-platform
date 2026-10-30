import os
import sys
import unittest
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src"))
import strategy_registry as reg


class RegistrySchemaTests(unittest.TestCase):
    def test_every_strategy_has_machine_lifecycle(self):
        allowed = {"production_candidate", "conditional_research", "incubating", "rejected", "research_only"}
        for strategy in reg.STRATEGIES:
            self.assertIn(strategy["lifecycle"], allowed)
            self.assertIsInstance(strategy["tradeable"], bool)
            self.assertIn("action_policy", strategy)

    def test_current_audit_reconciliation(self):
        by_id = {s["id"]: s for s in reg.STRATEGIES}
        self.assertEqual(by_id["lone_loser_short"]["lifecycle"], "production_candidate")
        self.assertEqual(by_id["darvas_gated"]["lifecycle"], "rejected")
        self.assertEqual(by_id["qullamaggie_gated"]["lifecycle"], "conditional_research")
        self.assertFalse(any(s["tradeable"] for s in reg.STRATEGIES))


if __name__ == "__main__":
    unittest.main()
