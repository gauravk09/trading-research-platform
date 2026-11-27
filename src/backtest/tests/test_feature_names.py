"""The feature store builds exactly FEATURE_NAMES, and every feature is causal."""

import unittest
from unittest.mock import patch

import numpy as np
import pandas as pd

from backtest import features


def synthetic_cache(n_dates=400, n_stocks=6, seed=0):
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range("2018-01-01", periods=n_dates, tz="Asia/Kolkata")
    cols = [f"S{i}" for i in range(n_stocks)]
    close = pd.DataFrame(100 * np.exp(np.cumsum(rng.normal(0.0005, 0.02, (n_dates, n_stocks)), axis=0)),
                         index=dates, columns=cols)
    high = close * (1 + np.abs(rng.normal(0, 0.01, close.shape)))
    low = close * (1 - np.abs(rng.normal(0, 0.01, close.shape)))
    volume = pd.DataFrame(rng.lognormal(12, 0.5, close.shape), index=dates, columns=cols)
    rs = close.rank(axis=1, pct=True) * 100
    return {"close": close, "high": high, "low": low, "volume": volume, "rs": rs}


def compute_without_optional_inputs(m):
    with patch.object(features, "DELIVERY", "/nonexistent"), \
         patch.object(features, "SECTOR_MAP", "/nonexistent"):
        return features.compute_all(m)


class FeatureNamesTests(unittest.TestCase):
    def test_store_builds_exactly_the_listed_names(self):
        out = compute_without_optional_inputs(synthetic_cache())
        self.assertEqual(set(out), set(features.FEATURE_NAMES) - features.OPTIONAL_FEATURES)

    def test_names_are_unique(self):
        self.assertEqual(len(features.FEATURE_NAMES), len(set(features.FEATURE_NAMES)))

    def test_every_feature_is_causal(self):
        m = synthetic_cache()
        full = compute_without_optional_inputs(m)
        cut = 300
        truncated = compute_without_optional_inputs({k: v.iloc[:cut] for k, v in m.items()})
        for name, frame in truncated.items():
            with self.subTest(feature=name):
                pd.testing.assert_frame_equal(frame, full[name].iloc[:cut], check_freq=False)

    def test_days_since_20dh_and_range_pos(self):
        m = synthetic_cache(n_dates=30, n_stocks=1)
        close = pd.Series(np.r_[np.full(25, 100.0), 101.0, 100.0, 100.0, 102.0, 99.0],
                          index=m["close"].index)
        m["close"] = close.to_frame("S0")
        m["high"], m["low"] = m["close"] + 1, m["close"] - 1
        m["high"].iloc[-1, 0] = m["low"].iloc[-1, 0] = 99.0          # flat bar
        m["volume"] = m["volume"].iloc[:, :1]
        m["rs"] = m["rs"].iloc[:, :1]
        out = compute_without_optional_inputs(m)
        days = out["days_since_20dh"]["S0"].to_numpy()
        self.assertEqual(list(days[25:]), [0.0, 1.0, 2.0, 0.0, 1.0])     # breaks at bars 25 and 28
        self.assertTrue(np.isnan(out["range_pos"]["S0"].iloc[-1]))
        self.assertEqual(out["range_pos"]["S0"].iloc[-2], 0.5)


if __name__ == "__main__":
    unittest.main()
