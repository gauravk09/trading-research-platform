"""B1 Naive-50 and B2 Naive-200 baselines (design doc Section 3.1).

Both are hard-label rules with 0 fitted knobs: today's state is decided from
price vs a moving average, then StateToOdds turns that hard state into
target odds (fit on the train fold only, same pattern as synthetic.py's
OracleModel). Causal by construction: the label at t only reads
dist_ma_n/ma_slope_n at t, which features.py itself computes causally.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .base import RegimeModel, StateToOdds
from .base import HORIZONS
from ..targets import TRUTH_DOWN, TRUTH_CHOPPY, TRUTH_UP

REGIME_COL_BY_CODE = {TRUTH_DOWN: "regime_p_down", TRUTH_CHOPPY: "regime_p_chop", TRUTH_UP: "regime_p_up"}


def _levels() -> dict:
    levels = {f"band_{h}": [0, 1, 2] for h in HORIZONS}
    levels.update({f"dd_{h}": [0, 1] for h in HORIZONS})
    levels["vol_tercile_20"] = [0, 1, 2]
    return levels


def _onehot(label: pd.Series) -> pd.DataFrame:
    """label: Series of codes in {TRUTH_DOWN, TRUTH_CHOPPY, TRUTH_UP} or NaN.
    Returns a DataFrame over regime_p_down/chop/up, NaN row where label is NaN.
    """
    out = pd.DataFrame(0.0, index=label.index, columns=list(REGIME_COL_BY_CODE.values()))
    for code, col in REGIME_COL_BY_CODE.items():
        out.loc[label == code, col] = 1.0
    out.loc[label.isna(), :] = np.nan
    return out


class _RuleStateModel(RegimeModel):
    """Shared fit/predict for a hard-label rule model: subclasses only
    implement `_label(X) -> Series of TRUTH_DOWN/CHOPPY/UP codes (NaN where
    undefined, e.g. warm-up)`.
    """

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


class Naive50(_RuleStateModel):
    """B1: Up if close > 50-DMA, else Down. No Choppy state -- regime_p_chop
    is always 0. feature_config must add 50 to the ladder (dist_ma_50).
    """

    name = "B1_naive50"
    is_stochastic = False

    def __init__(self):
        super().__init__(knobs={})

    @property
    def n_fitted_knobs(self) -> int:
        return 0

    def _label(self, X: pd.DataFrame) -> pd.Series:
        dist = X["dist_ma_50"]
        lab = pd.Series(np.nan, index=X.index, dtype=float)
        lab[dist > 0] = TRUTH_UP
        lab[dist <= 0] = TRUTH_DOWN
        return lab


class Naive200(_RuleStateModel):
    """B2: Up if close > SMA200 and its 20-row slope > 0; Down if close <
    SMA200 and slope < 0; else Choppy. feature_config must add 200 to the
    ladder (dist_ma_200, ma_slope_200).
    """

    name = "B2_naive200"
    is_stochastic = False

    def __init__(self):
        super().__init__(knobs={})

    @property
    def n_fitted_knobs(self) -> int:
        return 0

    def _label(self, X: pd.DataFrame) -> pd.Series:
        dist = X["dist_ma_200"]
        slope = X["ma_slope_200"]
        valid = dist.notna() & slope.notna()
        lab = pd.Series(TRUTH_CHOPPY, index=X.index, dtype=float)
        lab[valid & (dist > 0) & (slope > 0)] = TRUTH_UP
        lab[valid & (dist < 0) & (slope < 0)] = TRUTH_DOWN
        lab[~valid] = np.nan
        return lab
