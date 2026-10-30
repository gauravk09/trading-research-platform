import numpy as np
import pandas as pd
import pytest

from research.regime import features, stability, synthetic, targets
from research.regime.models.jump_model import (
    JumpModel3State, OBS_COLS, _sq_cost,
    _dp_assign_core, _dp_assign_numba,
    _online_assign_core, _online_assign_numba,
)
from research.regime.models.hmm_gaussian import _kmeans_pp_init, _resets_from_valid


def _synthetic_xy(n_rows=1500, seed=0):
    df = synthetic.generate_synthetic(n_rows=n_rows, seed=seed)
    close = df["close"]
    X = features.build_features(close)
    Y = targets.build_targets(close, open_lockbox=True)
    return X, Y


def _fit_on_first_half(lam=50.0, seed=0):
    X, Y = _synthetic_xy(seed=seed)
    valid = X[OBS_COLS].notna().all(axis=1)
    valid_idx = X.index[valid]
    split = valid_idx[len(valid_idx) // 2]
    train_idx = valid_idx[valid_idx <= split]
    model = JumpModel3State(knobs={"lambda_penalty": lam}).fit(X.loc[train_idx], Y.loc[train_idx])
    return model, X, Y


def test_dp_objective_non_increasing_across_iterations():
    model, *_ = _fit_on_first_half()
    diffs = np.diff(model.obj_history_)
    assert (diffs <= 1e-8).all(), f"DP objective increased: {diffs.max()}"


def test_penalized_flips_less_than_unpenalized():
    model_lam, X, Y = _fit_on_first_half(lam=50.0)
    model_zero, _, _ = _fit_on_first_half(lam=0.0)

    pred_lam = model_lam.predict(X)
    pred_zero = model_zero.predict(X)

    labels_lam = stability.labels_from_probs(pred_lam)
    labels_zero = stability.labels_from_probs(pred_zero)

    flips_lam = stability.flips_per_year(labels_lam)
    flips_zero = stability.flips_per_year(labels_zero)

    assert flips_lam < flips_zero, f"lambda=50 flipped {flips_lam}/yr vs lambda=0's {flips_zero}/yr"


def test_predict_state_is_causal():
    model, X, Y = _fit_on_first_half()
    full_pred = model.predict(X)

    valid_idx = X[OBS_COLS].dropna().index
    cut = valid_idx[len(valid_idx) * 3 // 4]
    X_truncated = X.loc[:cut]
    truncated_pred = model.predict(X_truncated)

    cols = ["regime_p_down", "regime_p_chop", "regime_p_up"]
    a = full_pred.loc[cut, cols].to_numpy()
    b = truncated_pred.loc[cut, cols].to_numpy()
    np.testing.assert_allclose(a, b, atol=1e-12)


def test_state_mapping_sorted_by_mean_ret20():
    model, *_ = _fit_on_first_half()
    means = model.info["state_mean_ret20"]
    assert means["regime_p_up"] > means["regime_p_chop"] > means["regime_p_down"]


def test_n_fitted_knobs_is_one():
    assert JumpModel3State().n_fitted_knobs == 1


def test_predict_columns_present():
    from research.regime.models.base import PREDICT_COLUMNS
    model, X, _ = _fit_on_first_half()
    pred = model.predict(X)
    for col in PREDICT_COLUMNS:
        assert col in pred.columns


def test_numba_matches_reference_dp_assign():
    """_dp_assign_numba must agree with the pure-python reference
    (_dp_assign_core) on both the state path and the objective.
    """
    X, Y = _synthetic_xy(n_rows=600, seed=4)
    x = X[OBS_COLS].dropna().to_numpy()
    x = (x - x.mean(axis=0)) / x.std(axis=0)
    rng = np.random.default_rng(5)
    centroids = _kmeans_pp_init(x, 3, rng)
    sq_cost = _sq_cost(x, centroids)

    states_ref, obj_ref = _dp_assign_core(sq_cost, lam=50.0)
    states_nb, obj_nb = _dp_assign_numba(sq_cost, 50.0)

    np.testing.assert_array_equal(states_ref, states_nb)
    assert abs(obj_ref - obj_nb) < 1e-9


def test_numba_matches_reference_online_assign():
    X, Y = _synthetic_xy(n_rows=600, seed=6)
    x = X[OBS_COLS].dropna().to_numpy()
    x = (x - x.mean(axis=0)) / x.std(axis=0)
    rng = np.random.default_rng(7)
    centroids = _kmeans_pp_init(x, 3, rng)

    valid = np.ones(len(x) + 4, dtype=bool)
    valid[15:17] = False
    valid[100] = False
    valid_idx, resets = _resets_from_valid(valid)
    sq = _sq_cost(x[: len(valid_idx)], centroids)

    states_ref = _online_assign_core(sq, 50.0, resets)
    states_nb = _online_assign_numba(sq, 50.0, resets)
    np.testing.assert_array_equal(states_ref, states_nb)


def test_dp_assign_backtrace_consistent_with_objective():
    """Regression test for a latent bug: when the fixed-centroid DP switches
    into state k that happens to be the PREVIOUS row's global-argmin state,
    the source of that switch must be the second-best state, not k itself
    (a self-switch is a contradiction -- the objective already added the
    jump penalty for it). Verified by recomputing the path's own cost from
    scratch and checking it matches the DP's reported objective.
    """
    X, Y = _synthetic_xy(n_rows=800, seed=8)
    x = X[OBS_COLS].dropna().to_numpy()
    x = (x - x.mean(axis=0)) / x.std(axis=0)
    rng = np.random.default_rng(9)
    centroids = _kmeans_pp_init(x, 3, rng)
    sq_cost = _sq_cost(x, centroids)
    lam = 50.0

    states, obj = _dp_assign_numba(sq_cost, lam)
    recomputed = sum(sq_cost[t, states[t]] for t in range(len(states)))
    recomputed += lam * sum(states[t] != states[t - 1] for t in range(1, len(states)))
    assert abs(recomputed - obj) < 1e-6
