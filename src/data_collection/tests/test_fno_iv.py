import unittest

from data_collection.kite.fno_iv import _quote_mid, black76_price, implied_moves, implied_volatility


class FnoIvMathTests(unittest.TestCase):
    def test_black76_round_trip(self):
        expected = 0.32
        price = black76_price(1000, 1000, 30 / 365, 0.10, expected, "CE")
        actual = implied_volatility(price, 1000, 1000, 30 / 365, "CE")
        self.assertAlmostEqual(actual, expected, places=6)

    def test_implied_moves_use_square_root_of_time(self):
        daily, expiry = implied_moves(31.75, 30 / 365)
        self.assertAlmostEqual(daily, 2.0, places=2)
        self.assertAlmostEqual(expiry, 9.1, places=1)

    def test_implied_moves_reject_non_positive_inputs(self):
        self.assertEqual(implied_moves(0, 30 / 365), (None, None))
        self.assertEqual(implied_moves(30, 0), (None, None))

    def test_good_two_sided_quote_uses_mid(self):
        price, quality, spread = _quote_mid({
            "depth": {"buy": [{"price": 98}], "sell": [{"price": 102}]},
            "last_price": 97,
        })
        self.assertEqual(price, 100)
        self.assertEqual(quality, "mid")
        self.assertAlmostEqual(spread, 4)

    def test_wide_quote_falls_back_to_traded_ltp(self):
        price, quality, _ = _quote_mid({
            "depth": {"buy": [{"price": 80}], "sell": [{"price": 120}]},
            "last_price": 99,
            "oi": 10,
        })
        self.assertEqual(price, 99)
        self.assertEqual(quality, "ltp")


if __name__ == "__main__":
    unittest.main()
