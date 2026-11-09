import unittest

import numpy as np
import pandas as pd

from backtest.attribution import FactorModel, attribute, summarize


def _panel(seed=0, T=120, N=150, K=3):
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range("2021-01-01", periods=T)
    cols = [f"S{i}" for i in range(N)]
    X = {f"x{k}": pd.DataFrame(rng.standard_normal((T, N)), index=idx, columns=cols)
         for k in range(K)}
    f0 = rng.standard_normal(T) * 0.01
    lam = rng.standard_normal((T, K)) * 0.005
    # true residuals, made orthogonal to [1, X(t-1)] per date so OLS recovers
    # f0 and lam exactly and the generated components are the ground truth
    eps = rng.standard_normal((T, N)) * 0.02
    Xl = np.stack([X[f"x{k}"].shift(1).to_numpy() for k in range(K)], axis=-1)
    ret = np.full((T, N), np.nan)
    for t in range(1, T):
        A = np.column_stack([np.ones(N), Xl[t]])
        e = eps[t] - A @ np.linalg.lstsq(A, eps[t], rcond=None)[0]
        eps[t] = e
        ret[t] = f0[t] + Xl[t] @ lam[t] + e
    ret = pd.DataFrame(ret, index=idx, columns=cols)
    universe = pd.DataFrame(True, index=idx, columns=cols)
    return ret, X, universe, f0, lam, eps, Xl


class AttributionTests(unittest.TestCase):
    def setUp(self):
        self.ret, self.X, self.universe, self.f0, self.lam, self.eps, self.Xl = _panel()
        self.fm = FactorModel.from_exposures(self.ret, self.X, self.universe)

    def test_recovers_generating_factors(self):
        np.testing.assert_allclose(self.fm.f0.to_numpy()[1:], self.f0[1:], atol=1e-10)
        np.testing.assert_allclose(self.fm.lam.to_numpy()[1:], self.lam[1:], atol=1e-10)

    def test_identity_and_components_per_trade(self):
        trades = pd.DataFrame({"date": [self.ret.index[10], self.ret.index[40]],
                               "symbol": ["S3", "S77"], "side": ["long", "short"]})
        per, _ = attribute(trades, horizon=5, fm=self.fm)
        self.assertEqual(len(per), 2)
        for j, (r, c, sgn) in enumerate([(10, 3, 1), (40, 77, -1)]):
            sl = slice(r + 2, r + 7)
            self.assertAlmostEqual(per["total"][j], sgn * self.ret.iloc[sl, c].sum(), places=10)
            self.assertAlmostEqual(per["common"][j], sgn * self.f0[sl].sum(), places=10)
            self.assertAlmostEqual(per["style"][j], sgn * (self.Xl[sl, c, :] * self.lam[sl]).sum(), places=10)
            self.assertAlmostEqual(per["selection"][j], sgn * self.eps[sl, c].sum(), places=10)
            self.assertAlmostEqual(per["total"][j],
                                   per["common"][j] + per["style"][j] + per["selection"][j], places=10)

    def test_random_picks_have_no_selection_but_cherry_picks_do(self):
        rng = np.random.default_rng(1)
        r = rng.integers(1, 100, size=400)
        c = rng.integers(0, 150, size=400)
        rand = pd.DataFrame({"date": self.ret.index[r], "symbol": [f"S{i}" for i in c]})
        # cherry-pick: for each date, the stock with the largest future residual
        fut = pd.DataFrame(self.eps, index=self.ret.index).rolling(5).sum().shift(-6)
        best = fut.to_numpy().argmax(axis=1)
        cherry = pd.DataFrame({"date": self.ret.index[r], "symbol": [f"S{best[i]}" for i in r]})
        _, s_rand = attribute(rand, 5, self.fm)
        _, s_cherry = attribute(cherry, 5, self.fm)
        self.assertLess(abs(s_rand["selection_t"]), 3.0)            # ~0 (noise 2%/day, n=400)
        self.assertGreater(s_cherry["selection_pct"], 5.0)          # max of 150 draws, 5 bars
        self.assertGreater(s_cherry["selection_t"], 10)

    def test_exposures_are_centred_inside_the_universe(self):
        # a liquidity screen that drops the bottom third: exposures must be
        # mean 0 / sd 1 over the names that remain, not over the whole panel
        from backtest.attribution import style_exposures
        rng = np.random.default_rng(3)
        T, N = 320, 60
        idx = pd.bdate_range("2020-01-01", periods=T)
        cols = [f"S{i}" for i in range(N)]
        close = pd.DataFrame(100 * np.exp(np.cumsum(rng.standard_normal((T, N)) * 0.02, axis=0)),
                             index=idx, columns=cols)
        m = {"close": close, "open": close * (1 + rng.standard_normal((T, N)) * 0.005),
             "high": close * 1.01, "low": close * 0.99,
             "volume": pd.DataFrame(rng.integers(1_000, 1_000_000, (T, N)), index=idx, columns=cols)}
        universe = pd.DataFrame(True, index=idx, columns=cols)
        universe.iloc[:, :20] = False
        X = style_exposures(m, universe)
        last = X["illiq"].iloc[-1]
        self.assertTrue(last.iloc[:20].isna().all())
        self.assertAlmostEqual(last.iloc[20:].mean(), 0.0, places=9)
        self.assertAlmostEqual(last.iloc[20:].std(), 1.0, places=9)

    def test_empty_summary(self):
        self.assertEqual(summarize(pd.DataFrame(columns=["date", "selection"]))["n"], 0)


if __name__ == "__main__":
    unittest.main()
