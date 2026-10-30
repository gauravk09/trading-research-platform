"""K1: historical analogs (k-nearest-neighbour) on a small, pre-declared
feature set.

Deliberately small feature set (curse of dimensionality for a distance
metric): ret_20, ret_60, ret_250, rvol_20, dist_ma_250, er_60, dd_high_250.
Standardized on the train fold's own mean/std (never refit at predict time).

k = round(sqrt(n_train_rows)) -- derived from the fold's own clean-feature
row count, not tuned, recomputed every fold since n_train_rows grows fold to
fold (expanding window). One shared k per fold, used identically for every
target, rather than a per-target k -- this keeps "recompute per fold" to one
number instead of eight and is consistent with how the neighbour SEARCH
itself only depends on the feature space, not on any particular target's
NaN pattern.

For each target, P(class) is the Laplace-smoothed (alpha=1) frequency of
that class among the k nearest TRAIN rows' values for that target -- with
any neighbour whose own value is NaN for that specific target simply
excluded from that target's count (not from the neighbour search itself),
so an unlucky target-specific NaN in a neighbour degrades gracefully toward
the uniform Laplace prior instead of biasing or crashing.

Neighbours are found with `sklearn.neighbors.NearestNeighbors` fit ONLY on
the fold's train rows (feature-NaN dropped) -- see fit(). predict() only
ever queries that fitted tree; it is never re-fit or extended with any row
from X passed to predict(), so a test-period query row can be a neighbour
of nothing and can never itself be returned as a neighbour. See
tests/test_k1_knn.py::test_neighbours_are_never_test_rows for the check.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.neighbors import NearestNeighbors

from .base import RegimeModel, HORIZONS

FEATURES = ["ret_20", "ret_60", "ret_250", "rvol_20", "dist_ma_250", "er_60", "dd_high_250"]

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

ALPHA = 1.0


def _laplace_freqs(neighbor_vals: np.ndarray, levels: list) -> np.ndarray:
    """neighbor_vals: (n_query, k) array, may contain NaN for rows where the
    target itself is unknown for that particular neighbour. Returns
    (n_query, len(levels)) Laplace-smoothed frequencies.
    """
    n_levels = len(levels)
    valid = ~np.isnan(neighbor_vals)
    denom = valid.sum(axis=1).astype(float) + ALPHA * n_levels
    out = np.empty((neighbor_vals.shape[0], n_levels))
    for j, lvl in enumerate(levels):
        count = np.nansum(np.where(valid, neighbor_vals == lvl, 0.0), axis=1)
        out[:, j] = (count + ALPHA) / denom
    return out


class K1HistoricalAnalogs(RegimeModel):
    """k-NN historical-analog model on 7 pre-declared price/vol features.

    Knob: k_mult, a multiplier on the derived k = round(sqrt(n_train_rows)),
    the harness's single numeric knob for perturbation. n_fitted_knobs = 1.
    """

    name = "K1_knn_analogs"
    is_stochastic = False

    def __init__(self, knobs: dict | None = None):
        knobs = dict(knobs or {"k_mult": 1.0})
        super().__init__(knobs)
        self.k_mult = float(self.knobs.get("k_mult", 1.0))
        self.mean_: pd.Series | None = None
        self.std_: pd.Series | None = None
        self.nn_: NearestNeighbors | None = None
        self.train_targets_: pd.DataFrame | None = None
        self.k_: int = 1

    @property
    def n_fitted_knobs(self) -> int:
        return 1

    def fit(self, X_train: pd.DataFrame, Y_train: pd.DataFrame) -> "K1HistoricalAnalogs":
        Xc = X_train[FEATURES].dropna()
        self.mean_ = Xc.mean()
        self.std_ = Xc.std().replace(0.0, 1.0)
        Xs = ((Xc - self.mean_) / self.std_).to_numpy()

        n_train = len(Xc)
        self.k_ = max(1, min(n_train, round(np.sqrt(max(n_train, 1)) * self.k_mult)))
        self.nn_ = NearestNeighbors(n_neighbors=self.k_, metric="euclidean").fit(Xs)
        self.train_targets_ = Y_train.loc[Xc.index]
        return self

    def predict(self, X: pd.DataFrame) -> pd.DataFrame:
        out = self._empty_predictions(X.index)
        if self.nn_ is None or len(self.train_targets_) == 0:
            return out

        Xq = X[FEATURES]
        valid_rows = Xq.notna().all(axis=1)
        if not valid_rows.any():
            return out

        idx = X.index[valid_rows]
        Xqs = ((Xq.loc[idx] - self.mean_) / self.std_).to_numpy()
        _, neighbor_pos = self.nn_.kneighbors(Xqs, n_neighbors=self.k_)

        for h in HORIZONS:
            band_vals = self.train_targets_[f"band_{h}"].to_numpy()[neighbor_pos]
            probs = _laplace_freqs(band_vals, TARGET_LEVELS[f"band_{h}"])
            out.loc[idx, f"p_down_{h}"] = probs[:, 0]
            out.loc[idx, f"p_flat_{h}"] = probs[:, 1]
            out.loc[idx, f"p_up_{h}"] = probs[:, 2]

            dd_vals = self.train_targets_[f"dd_{h}"].to_numpy()[neighbor_pos]
            dd_probs = _laplace_freqs(dd_vals, TARGET_LEVELS[f"dd_{h}"])
            out.loc[idx, f"p_dd_{h}"] = dd_probs[:, 1]

        vol_vals = self.train_targets_["vol_tercile_20"].to_numpy()[neighbor_pos]
        vol_probs = _laplace_freqs(vol_vals, TARGET_LEVELS["vol_tercile_20"])
        out.loc[idx, "p_vol_low_20"] = vol_probs[:, 0]
        out.loc[idx, "p_vol_mid_20"] = vol_probs[:, 1]
        out.loc[idx, "p_vol_high_20"] = vol_probs[:, 2]

        regime_vals = self.train_targets_["truth_regime"].to_numpy()[neighbor_pos]
        regime_probs = _laplace_freqs(regime_vals, TARGET_LEVELS["truth_regime"])
        out.loc[idx, "regime_p_down"] = regime_probs[:, 0]
        out.loc[idx, "regime_p_chop"] = regime_probs[:, 1]
        out.loc[idx, "regime_p_up"] = regime_probs[:, 2]

        return out
