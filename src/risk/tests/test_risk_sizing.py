import unittest

from order_pad import ticket
from risk.sizing import size_position


BASE = dict(equity=100_000, risk_pct=1, entry=100, stop=95, side="BUY",
            existing_gross_exposure=0, existing_heat=0, open_positions=0,
            max_positions=4, max_gross_exposure_pct=100, max_heat_pct=4,
            leverage=1)


class RiskSizingTests(unittest.TestCase):
    def test_long_exact_risk_quantity(self):
        result = size_position(**BASE)
        self.assertTrue(result["accepted"])
        self.assertEqual(result["qty"], 200)
        self.assertEqual(result["per_unit_risk"], 5.0)
        self.assertEqual(result["rupee_risk"], 1000.0)
        self.assertEqual(result["notional"], 20_000.0)
        self.assertEqual(result["margin_estimate"], 20_000.0)

    def test_short_uses_correct_stop_geometry(self):
        result = size_position(**{**BASE, "side": "SELL", "stop": 105})
        self.assertTrue(result["accepted"])
        self.assertEqual(result["qty"], 200)
        self.assertEqual(result["side"], "SHORT")

    def test_gross_and_heat_caps_floor_quantity(self):
        result = size_position(**{**BASE, "existing_gross_exposure": 92_000,
                                  "existing_heat": 3_800})
        self.assertTrue(result["accepted"])
        self.assertEqual(result["qty"], 40)  # heat remaining: 200 / ₹5
        self.assertIn("gross_exposure", result["limits_applied"])
        self.assertIn("portfolio_heat", result["limits_applied"])

    def test_position_and_margin_caps_floor_quantity(self):
        position = size_position(**{**BASE, "max_position_pct": 10})
        self.assertEqual(position["qty"], 100)
        self.assertIn("position", position["limits_applied"])
        margin = size_position(**{**BASE, "max_gross_exposure_pct": 500,
                                  "leverage": 1, "existing_gross_exposure": 99_500})
        self.assertEqual(margin["qty"], 5)
        self.assertIn("margin", margin["limits_applied"])

    def test_slots_and_invalid_stop_reject(self):
        slots = size_position(**{**BASE, "open_positions": 4})
        self.assertFalse(slots["accepted"])
        self.assertEqual(slots["rejection_reasons"][0]["code"], "position_slots_exhausted")
        geometry = size_position(**{**BASE, "stop": 101})
        self.assertFalse(geometry["accepted"])
        self.assertEqual(geometry["rejection_reasons"][0]["code"], "invalid_stop_geometry")

    def test_rejected_ticket_is_never_actionable(self):
        result = ticket("X", "breakout", 100, 101, 100_000, 1,
                        now=__import__("datetime").datetime(2026, 9, 2, 15, 25))
        self.assertFalse(result["accepted"])
        self.assertFalse(result["actionable"])


if __name__ == "__main__":
    unittest.main()
