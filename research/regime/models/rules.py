"""R1 rule grid and R2 (R1 + hysteresis) (design doc Section 3.1).

Both reuse the same hard-label -> StateToOdds pattern as models/baselines.py
(duplicated here rather than imported, since it is a handful of lines and
the two files are meant to stand alone as separate model families).
feature_config must add 200 to the ladder (dist_ma_200, ma_slope_200); er_60
is already in features.DEFAULT_ER_NS.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .base import RegimeModel, StateToOdds
from .base import HORIZONS
from ..targets import TRUTH_DOWN, TRUTH_CHOPPY, TRUTH_UP

REGIME_COL_BY_CODE = {TRUTH_DOWN: "regime_p_down", TRUTH_CHOPPY: "regime_p_chop", TRUTH_UP: "regime_p_up"}

# theta derivation (R1's chop-axis threshold), not tuned on results:
# er_60 (features._efficiency_ratio) is |net move over 60 rows| / sum of 60
# |daily diffs|. Under the null of an iid-Gaussian-step random walk with
# per-step std sigma, the numerator's expectation is E|S_n| = sqrt(2n/pi)*sigma
# (folded-normal mean of a sum of n iid N(0, sigma^2) steps) and the
# denominator's expectation is E[sum|x_i|] = n * sqrt(2/pi)*sigma (n times the
# folded-normal mean of one step). So:
#   E[ER_n] = sqrt(2n/pi)*sigma / (n*sqrt(2/pi)*sigma) = 1/sqrt(n)
# A day is only called "choppy" if its 60-day ER sits well below a pure
# random walk's expected value, so theta = 2 * E[ER_60] = 2/sqrt(60).
THETA_DEFAULT = 2.0 / np.sqrt(60)


def _levels() -> dict:
    levels = {f"band_{h}": [0, 1, 2] for h in HORIZONS}
    levels.update({f"dd_{h}": [0, 1] for h in HORIZONS})
    levels["vol_tercile_20"] = [0, 1, 2]
    return levels


def _onehot(label: pd.Series) -> pd.DataFrame:
    out = pd.DataFrame(0.0, index=label.index, columns=list(REGIME_COL_BY_CODE.values()))
    for code, col in REGIME_COL_BY_CODE.items():
        out.loc[label == code, col] = 1.0
    out.loc[label.isna(), :] = np.nan
    return out


def _raw_trend_chop_label(X: pd.DataFrame, theta: float) -> pd.Series:
    """The R1 rule: trend axis (as B2: price vs rising/falling SMA200) with
    a chop override (60-day efficiency ratio below theta means Choppy no
    matter what the trend axis says). Causal: every input column
    (dist_ma_200, ma_slope_200, er_60) is itself causal at each row.
    """
    dist = X["dist_ma_200"]
    slope = X["ma_slope_200"]
    er = X["er_60"]
    valid = dist.notna() & slope.notna() & er.notna()

    lab = pd.Series(TRUTH_CHOPPY, index=X.index, dtype=float)
    trend_up = (dist > 0) & (slope > 0)
    trend_down = (dist < 0) & (slope < 0)
    lab[valid & trend_up] = TRUTH_UP
    lab[valid & trend_down] = TRUTH_DOWN
    lab[valid & (er < theta)] = TRUTH_CHOPPY  # chop axis overrides the trend axis
    lab[~valid] = np.nan
    return lab


def hysteresis_label(raw_label: pd.Series, k: int) -> pd.Series:
    """Causal hysteresis: the displayed label only switches to a new raw
    value once that raw value has held for `k` consecutive valid rows.
    Depends only on raw_label[<=t] at every row t (a plain forward pass).
    """
    vals = raw_label.to_numpy()
    n = len(vals)
    displayed = np.full(n, np.nan)
    current = np.nan
    candidate = np.nan
    streak = 0
    for i in range(n):
        v = vals[i]
        if np.isnan(v):
            streak = 0
            candidate = np.nan
        elif v == candidate:
            streak += 1
        else:
            candidate = v
            streak = 1
        if streak >= k:
            current = candidate
        displayed[i] = current
    return pd.Series(displayed, index=raw_label.index)


class _RuleStateModel(RegimeModel):
    """Shared fit/predict: subclasses implement `_label(X)`."""

    def __init__(self, knobs: dict | None = None):
        super().__init__(knobs)
        self.s2o = StateToOdds()

    def fit(self, X_train: pd.DataFrame, Y_train: pd.DataFrame) -> "_RuleStateModel":
        state_probs = _onehot(self._label(X_train))
        self.s2o.fit(state_probs, Y_train, _levels())
        return self

    def predict(self, X: pd.DataFrame) -> pd.DataFrame:
        state_probs = _onehot(self._label(X))
        out = self._empty_predictions(X.index)
        for col in REGIME_COL_BY_CODE.values():
            out[col] = state_probs[col]
        for h in HORIZONS:
            odds = self.s2o.predict(state_probs, f"band_{h}")
            out[f"p_down_{h}"] = odds[0]
            out[f"p_flat_{h}"] = odds[1]
            out[f"p_up_{h}"] = odds[2]
            odds_dd = self.s2o.predict(state_probs, f"dd_{h}")
            out[f"p_dd_{h}"] = odds_dd[1]
        odds_vol = self.s2o.predict(state_probs, "vol_tercile_20")
        out["p_vol_low_20"] = odds_vol[0]
        out["p_vol_mid_20"] = odds_vol[1]
        out["p_vol_high_20"] = odds_vol[2]
        return out


class RuleGrid1(_RuleStateModel):
    """R1: trend axis (as B2) x chop axis (60d efficiency ratio < theta).
    1 fitted knob (theta), numeric so the perturbation suite varies it.
    """

    name = "R1_rule_grid"
    is_stochastic = False

    def __init__(self, theta: float = THETA_DEFAULT):
        super().__init__(knobs={"theta": theta})
        self.theta = theta

    @property
    def n_fitted_knobs(self) -> int:
        return 1

    def _label(self, X: pd.DataFrame) -> pd.Series:
        return _raw_trend_chop_label(X, self.theta)


class RuleGrid2(_RuleStateModel):
    """R2 = R1 + hysteresis: the displayed label only flips after the new
    raw R1 label has held for k consecutive days (k=5). 2 fitted knobs
    (theta, k) -- directly targets whipsaw (design doc Section 3.1/4.3).
    """

    name = "R2_rule_grid_hysteresis"
    is_stochastic = False

    def __init__(self, theta: float = THETA_DEFAULT, k: int = 5):
        super().__init__(knobs={"theta": theta, "k": k})
        self.theta = theta
        self.k = int(round(k))

    @property
    def n_fitted_knobs(self) -> int:
        return 2

    def _label(self, X: pd.DataFrame) -> pd.Series:
        raw = _raw_trend_chop_label(X, self.theta)
        return hysteresis_label(raw, self.k)
