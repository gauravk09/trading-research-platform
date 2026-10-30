"""L1: multinomial logistic regression, fit separately per target.

One `sklearn.linear_model.LogisticRegression` per target column (band_5/20/60,
dd_5/20/60, vol_tercile_20, truth_regime). Features: the full default T1
feature set (`features.build_features` with default config). Rows with any
NaN feature are dropped from the fit; each target's own NaN rows are dropped
independently of the others ("per target, not globally" per the task spec),
since e.g. dd_60/truth_regime need 60 forward rows and drop different rows
near a fold's train-window edge than band_5 does.

Leakage note on the truth_regime classifier (verified against the harness,
not assumed): `runner.run_walkforward` purges/embargoes every fold's train
set with `embargo=EMBARGO=60` (see runner.py line 22: "covers the longest
target window (truth_regime, dd_60) for every fit"), and this is the value
actually used because `run_experiment` never overrides it. `splits.py`'s
docstring confirms the embargo/purge rule: a train row is dropped whenever
`row_position + embargo >= first_test_position`, which is exactly the
condition needed to keep any row whose target window (up to 60 rows forward,
truth_regime's own window) from reaching into the test period. So training a
classifier on truth_regime is safe: every train-fold row's 60-day-forward
label is fully resolved before the test period begins. This is legitimate
hindsight-label supervision (truth_regime is only ever the true state as of
some past date <= end of train), not a leak of test-period information.

Standardization: (x - mean) / std computed from the TRAIN fold only (after
dropping feature-NaN rows), applied unchanged at predict time -- never
refit on test/predict rows.

Missing-class safety: if a fold's train target has fewer than 2 distinct
classes, `LogisticRegression` cannot fit at all; in that case (and for any
individual missing class when >=2 classes are present) `_LevelLogit` falls
back to a Laplace-smoothed (alpha=1) class-frequency vector, exactly as B0
Climatology already does, mixed with the present-class predict_proba output
so probabilities still sum to 1. This never raises.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression

from .base import RegimeModel, HORIZONS

TARGET_LEVELS = {
    "band_5": [0, 1, 2],
    "band_20": [0, 1, 2],
    "band_60": [0, 1, 2],
    "dd_5": [0, 1],
    "dd_20": [0, 1],
    "dd_60": [0, 1],
    "vol_tercile_20": [0, 1, 2],
    "truth_regime": [0, 1, 2],
}


class _LevelLogit:
    """One logistic-regression classifier for one target, safe against a
    fold's train fold missing one or more of the target's possible classes.
    """

    def __init__(self, levels: list, C: float, alpha: float = 1.0):
        self.levels = list(levels)
        self.C = C
        self.alpha = alpha
        self.clf_: LogisticRegression | None = None
        self.classes_ = None
        self.fallback_freq_: dict | None = None
        self.train_n_ = 0

    def fit(self, Xs: np.ndarray, y: np.ndarray) -> "_LevelLogit":
        present = np.unique(y)
        n = len(y)
        self.train_n_ = n
        counts = {lvl: float(np.sum(y == lvl)) for lvl in self.levels}
        if len(present) < 2:
            total = n + self.alpha * len(self.levels)
            self.fallback_freq_ = {lvl: (counts[lvl] + self.alpha) / total for lvl in self.levels}
            self.classes_ = present
            return self
        self.clf_ = LogisticRegression(solver="lbfgs", penalty="l2", C=self.C, max_iter=2000)
        self.clf_.fit(Xs, y)
        self.classes_ = self.clf_.classes_
        return self

    @property
    def n_coefficients(self) -> int:
        if self.clf_ is None:
            return 0
        return int(self.clf_.coef_.size + self.clf_.intercept_.size)

    def predict_proba_full(self, Xs: np.ndarray) -> np.ndarray:
        n_rows = Xs.shape[0]
        if self.clf_ is None:
            row = np.array([self.fallback_freq_[lvl] for lvl in self.levels])
            return np.tile(row, (n_rows, 1))

        raw = self.clf_.predict_proba(Xs)
        present_list = list(self.classes_)
        present_set = set(present_list)
        missing = [lvl for lvl in self.levels if lvl not in present_set]

        full = np.zeros((n_rows, len(self.levels)))
        if not missing:
            col_idx = [present_list.index(lvl) for lvl in self.levels]
            return raw[:, col_idx]

        eps_each = self.alpha / (self.train_n_ + self.alpha * len(self.levels))
        scale = 1.0 - eps_each * len(missing)
        for j, lvl in enumerate(self.levels):
            if lvl in present_set:
                full[:, j] = raw[:, present_list.index(lvl)] * scale
            else:
                full[:, j] = eps_each
        return full


class L1MultinomialLogistic(RegimeModel):
    """Supervised multinomial logistic regression on the full T1 feature set.

    Knob: C (L2 inverse regularization strength), the harness's single
    numeric knob for perturbation. n_fitted_knobs = 1 -- C is shared across
    all 8 per-target classifiers, counted once, matching the spec's
    simplicity tiebreak (Section 4.6): one hyperparameter choice, not eight.
    """

    name = "L1_multinomial_logit"
    is_stochastic = False

    def __init__(self, knobs: dict | None = None):
        knobs = dict(knobs or {"C": 1.0})
        super().__init__(knobs)
        self.C = float(self.knobs.get("C", 1.0))
        self.feature_cols_: list[str] | None = None
        self.mean_: pd.Series | None = None
        self.std_: pd.Series | None = None
        self.classifiers_: dict[str, _LevelLogit] = {}
        self.n_coefficients_ = 0

    @property
    def n_fitted_knobs(self) -> int:
        return 1

    def fit(self, X_train: pd.DataFrame, Y_train: pd.DataFrame) -> "L1MultinomialLogistic":
        Xc = X_train.dropna()
        self.feature_cols_ = list(Xc.columns)
        self.mean_ = Xc.mean()
        self.std_ = Xc.std().replace(0.0, 1.0)
        Xs_full = (Xc - self.mean_) / self.std_

        self.classifiers_ = {}
        self.n_coefficients_ = 0
        for col, levels in TARGET_LEVELS.items():
            y_full = Y_train.loc[Xc.index, col]
            valid = y_full.notna()
            Xs = Xs_full.loc[valid].to_numpy()
            y = y_full.loc[valid].to_numpy()
            clf = _LevelLogit(levels, C=self.C).fit(Xs, y)
            self.classifiers_[col] = clf
            self.n_coefficients_ += clf.n_coefficients
        return self

    def predict(self, X: pd.DataFrame) -> pd.DataFrame:
        out = self._empty_predictions(X.index)
        valid_rows = X[self.feature_cols_].notna().all(axis=1)
        if not valid_rows.any():
            return out

        idx = X.index[valid_rows]
        Xs = ((X.loc[idx, self.feature_cols_] - self.mean_) / self.std_).to_numpy()

        for h in HORIZONS:
            probs = self.classifiers_[f"band_{h}"].predict_proba_full(Xs)
            out.loc[idx, f"p_down_{h}"] = probs[:, 0]
            out.loc[idx, f"p_flat_{h}"] = probs[:, 1]
            out.loc[idx, f"p_up_{h}"] = probs[:, 2]

            dd_probs = self.classifiers_[f"dd_{h}"].predict_proba_full(Xs)
            out.loc[idx, f"p_dd_{h}"] = dd_probs[:, 1]

        vol_probs = self.classifiers_["vol_tercile_20"].predict_proba_full(Xs)
        out.loc[idx, "p_vol_low_20"] = vol_probs[:, 0]
        out.loc[idx, "p_vol_mid_20"] = vol_probs[:, 1]
        out.loc[idx, "p_vol_high_20"] = vol_probs[:, 2]

        regime_probs = self.classifiers_["truth_regime"].predict_proba_full(Xs)
        out.loc[idx, "regime_p_down"] = regime_probs[:, 0]
        out.loc[idx, "regime_p_chop"] = regime_probs[:, 1]
        out.loc[idx, "regime_p_up"] = regime_probs[:, 2]

        return out
