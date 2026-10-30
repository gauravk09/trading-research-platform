"""The model interface every regime candidate implements, plus the B0
Climatology baseline and the StateToOdds helper used by descriptive
(rule/HMM) models.

CONTRACT: fit(X_train, Y_train) only ever sees the fold's train rows.
predict(X) receives HISTORY, not just the dates being scored: the harness
(runner.run_walkforward) calls it with every row from the start of the
series through the end of the current fold's test year -- including rows
before the fold's own train window -- and only slices the result down to the
test dates afterward. This is so a stateful model (an HMM/jump-model filter,
a running count, anything path-dependent) can carry its state across the
fold boundary instead of restarting cold every January 1st.

Every value the model returns for date t must still depend only on rows of X
with index <= t -- it may use the extra history it's handed, never rows
after t. The harness does not sandbox this at runtime; it is a documented
obligation. The structural defenses are: features.py is itself strictly
causal (see its causality test), splits.py's purge/embargo keeps target
information belonging to the test period out of train, and predict() is
never handed any row past the current fold's test_end (so no later fold's
test data can leak into an earlier fold's predict() call either).
"""
from __future__ import annotations

import numpy as np
import pandas as pd

HORIZONS = (5, 20, 60)

PREDICT_COLUMNS = (
    ["regime_p_up", "regime_p_chop", "regime_p_down"]
    + [f"p_{lab}_{h}" for h in HORIZONS for lab in ("down", "flat", "up")]
    + [f"p_dd_{h}" for h in HORIZONS]
    + ["p_vol_low_20", "p_vol_mid_20", "p_vol_high_20"]
)


class RegimeModel:
    """Base class. Subclasses set `name`, `is_stochastic`, and implement
    fit/predict/n_fitted_knobs.
    """

    name: str = "base"
    is_stochastic: bool = False

    def __init__(self, knobs: dict | None = None):
        self.knobs: dict = dict(knobs or {})

    @property
    def n_fitted_knobs(self) -> int:
        raise NotImplementedError

    def fit(self, X_train: pd.DataFrame, Y_train: pd.DataFrame) -> "RegimeModel":
        raise NotImplementedError

    def predict(self, X: pd.DataFrame) -> pd.DataFrame:
        """Return a DataFrame indexed like X with columns PREDICT_COLUMNS.
        Any column the model doesn't produce (e.g. regime probs for a pure
        odds model) is left as NaN.
        """
        raise NotImplementedError

    @staticmethod
    def _empty_predictions(index) -> pd.DataFrame:
        return pd.DataFrame(np.nan, index=index, columns=list(PREDICT_COLUMNS))


class StateToOdds:
    """Maps a model's state-probability matrix to target odds.

    Fit on the TRAIN window: hard-assign each train row to its argmax state,
    then estimate each state's conditional frequency of every discrete
    target level (Laplace/add-one smoothing). At predict time, a date's odds
    are the state-probability-weighted mix of those per-state frequencies —
    so a model that is never fully certain of its state still gets smoothly
    mixed odds rather than a hard lookup.
    """

    def __init__(self, alpha: float = 1.0):
        self.alpha = alpha
        self.state_cols_: list[str] | None = None
        self.cond_freq_: dict[str, pd.DataFrame] = {}

    def fit(self, state_probs: pd.DataFrame, targets: pd.DataFrame, levels: dict[str, list]):
        self.state_cols_ = list(state_probs.columns)
        state_label = state_probs.idxmax(axis=1)
        for col, lvls in levels.items():
            y = targets[col]
            counts = pd.DataFrame(self.alpha, index=self.state_cols_, columns=lvls, dtype=float)
            valid = y.notna() & state_label.notna()
            for state in self.state_cols_:
                sub = y[valid & (state_label == state)]
                for lvl in lvls:
                    counts.loc[state, lvl] += float((sub == lvl).sum())
            freq = counts.div(counts.sum(axis=1), axis=0)
            self.cond_freq_[col] = freq
        return self

    def predict(self, state_probs: pd.DataFrame, target_col: str) -> pd.DataFrame:
        freq = self.cond_freq_[target_col]
        probs = state_probs[self.state_cols_].to_numpy()
        out = probs @ freq.loc[self.state_cols_].to_numpy()
        return pd.DataFrame(out, index=state_probs.index, columns=freq.columns)


def _freq(series: pd.Series, levels: list) -> dict:
    s = series.dropna()
    if len(s) == 0:
        return {lvl: np.nan for lvl in levels}
    counts = s.value_counts()
    total = len(s)
    return {lvl: counts.get(lvl, 0) / total for lvl in levels}


class Climatology(RegimeModel):
    """B0 baseline: odds = train-window unconditional frequencies. Uses no
    features at all; predicts the identical row for every date. This is the
    floor every other model must beat (spec Section 3.1, B0).
    """

    name = "B0_climatology"
    is_stochastic = False

    def __init__(self):
        super().__init__(knobs={})
        self.freqs_: dict[str, dict] = {}

    @property
    def n_fitted_knobs(self) -> int:
        return 0

    def fit(self, X_train: pd.DataFrame, Y_train: pd.DataFrame) -> "Climatology":
        for h in HORIZONS:
            self.freqs_[f"band_{h}"] = _freq(Y_train[f"band_{h}"], [0, 1, 2])
            self.freqs_[f"dd_{h}"] = _freq(Y_train[f"dd_{h}"], [0, 1])
        self.freqs_["vol_tercile_20"] = _freq(Y_train["vol_tercile_20"], [0, 1, 2])
        self.freqs_["truth_regime"] = _freq(Y_train["truth_regime"], [0, 1, 2])
        return self

    def predict(self, X: pd.DataFrame) -> pd.DataFrame:
        out = self._empty_predictions(X.index)
        for h in HORIZONS:
            f = self.freqs_[f"band_{h}"]
            out[f"p_down_{h}"] = f[0]
            out[f"p_flat_{h}"] = f[1]
            out[f"p_up_{h}"] = f[2]
            out[f"p_dd_{h}"] = self.freqs_[f"dd_{h}"][1]
        vf = self.freqs_["vol_tercile_20"]
        out["p_vol_low_20"] = vf[0]
        out["p_vol_mid_20"] = vf[1]
        out["p_vol_high_20"] = vf[2]
        rf = self.freqs_["truth_regime"]
        out["regime_p_down"] = rf[0]
        out["regime_p_chop"] = rf[1]
        out["regime_p_up"] = rf[2]
        return out
