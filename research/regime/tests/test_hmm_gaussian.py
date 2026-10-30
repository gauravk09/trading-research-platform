import numpy as np
import pandas as pd
import pytest

from research.regime import features, synthetic, targets
from research.regime.models.hmm_gaussian import (
    GaussianHMM3State, OBS_COLS, N_STATES,
    _forward_backward, _forward_backward_numba,
    _filter_causal, _filter_causal_numba,
    _log_emissions, _resets_from_valid,
)


def _synthetic_xy(n_rows=1500, seed=0):
    df = synthetic.generate_synthetic(n_rows=n_rows, seed=seed)
    close = df["close"]
    X = features.build_features(close)
    Y = targets.build_targets(close, open_lockbox=True)  # dev-only synthetic dates, no lockbox risk
    return X, Y, df["state"]


def _fit_on_first_half(seed=0):
    X, Y, true_state = _synthetic_xy(seed=seed)
    valid = X[OBS_COLS].notna().all(axis=1)
    valid_idx = X.index[valid]
    split = valid_idx[len(valid_idx) // 2]
    train_idx = valid_idx[valid_idx <= split]
    model = GaussianHMM3State().fit(X.loc[train_idx], Y.loc[train_idx])
    return model, X, Y, true_state


def test_loglikelihood_non_decreasing_across_em_iterations():
    model, *_ = _fit_on_first_half()
    hist = model.loglik_history_
    assert len(hist) >= 2
    diffs = np.diff(hist)
    # numerical noise only, never a real decrease
    assert (diffs >= -1e-6).all(), f"log-likelihood decreased: {diffs.min()}"


def test_filtered_accuracy_well_above_chance_on_synthetic():
    model, X, Y, true_state = _fit_on_first_half()
    pred = model.predict(X)
    valid = pred[["regime_p_down", "regime_p_chop", "regime_p_up"]].notna().all(axis=1)
    label_col = pred[["regime_p_down", "regime_p_chop", "regime_p_up"]].idxmax(axis=1)
    code_map = {"regime_p_down": 0, "regime_p_chop": 1, "regime_p_up": 2}
    pred_code = label_col.map(code_map)
    true_code = true_state.reindex(pred.index)
    ok = valid & true_code.notna()
    accuracy = float((pred_code[ok] == true_code[ok]).mean())
    # chance on 3 roughly-balanced states is ~1/3; a fitted HMM on a planted
    # 3-state Markov regime should do much better than that.
    assert accuracy > 0.6, f"filtered-state accuracy only {accuracy:.3f}"


def test_filtered_state_is_causal():
    """P(state at t) must be identical whether or not rows after t exist in
    X -- predict() must only ever use x_1..x_t to produce its output at t.
    """
    model, X, Y, _ = _fit_on_first_half()
    full_pred = model.predict(X)

    valid_idx = X[OBS_COLS].dropna().index
    cut = valid_idx[len(valid_idx) * 3 // 4]
    X_truncated = X.loc[:cut]
    truncated_pred = model.predict(X_truncated)

    cols = ["regime_p_down", "regime_p_chop", "regime_p_up"]
    a = full_pred.loc[cut, cols].to_numpy()
    b = truncated_pred.loc[cut, cols].to_numpy()
    np.testing.assert_allclose(a, b, atol=1e-10)


def test_state_mapping_sorted_by_mean_ret20():
    model, *_ = _fit_on_first_half()
    means = model.info["state_mean_ret20"]
    assert means["regime_p_up"] > means["regime_p_chop"] > means["regime_p_down"]


def test_n_fitted_knobs_is_zero():
    assert GaussianHMM3State().n_fitted_knobs == 0


def test_predict_columns_present():
    from research.regime.models.base import PREDICT_COLUMNS
    model, X, *_ = _fit_on_first_half()
    pred = model.predict(X)
    for col in PREDICT_COLUMNS:
        assert col in pred.columns


def _random_hmm_params(seed=0):
    rng = np.random.default_rng(seed)
    means = rng.normal(size=(N_STATES, 2))
    covs = np.array([np.eye(2) * (0.5 + rng.random()) for _ in range(N_STATES)])
    start = rng.dirichlet(np.ones(N_STATES))
    trans = np.array([rng.dirichlet(np.ones(N_STATES) * 5) for _ in range(N_STATES)])
    return means, covs, start, trans


def test_numba_matches_reference_forward_backward():
    """_forward_backward_numba must agree with the pure-python reference
    (_forward_backward) to 1e-9 on log_gamma, log_xi and loglik.
    """
    X, Y, _ = _synthetic_xy(n_rows=600, seed=1)
    x = X[OBS_COLS].dropna().to_numpy()
    x = (x - x.mean(axis=0)) / x.std(axis=0)
    means, covs, start, trans = _random_hmm_params()
    log_emit = _log_emissions(x, means, covs)
    log_start = np.log(start)
    log_trans = np.log(trans)

    gamma_ref, xi_ref, ll_ref = _forward_backward(log_emit, log_start, log_trans)
    gamma_nb, xi_nb, ll_nb = _forward_backward_numba(log_emit, log_start, log_trans)

    np.testing.assert_allclose(gamma_ref, gamma_nb, atol=1e-9)
    np.testing.assert_allclose(xi_ref, xi_nb, atol=1e-9)
    assert abs(ll_ref - ll_nb) < 1e-9


def test_numba_matches_reference_filter_causal():
    X, Y, _ = _synthetic_xy(n_rows=600, seed=2)
    x = X[OBS_COLS].dropna().to_numpy()
    x = (x - x.mean(axis=0)) / x.std(axis=0)
    means, covs, start, trans = _random_hmm_params(seed=3)
    log_emit = _log_emissions(x, means, covs)
    log_start = np.log(start)
    log_trans = np.log(trans)

    # a couple of synthetic gaps, to exercise the resets logic too
    valid = np.ones(len(x) + 5, dtype=bool)
    valid[10:13] = False
    valid[200] = False
    valid_idx, resets = _resets_from_valid(valid)
    log_emit_gapped = log_emit[: len(valid_idx)]

    filt_ref = _filter_causal(log_emit_gapped, log_start, log_trans, resets)
    filt_nb = _filter_causal_numba(log_emit_gapped, log_start, log_trans, resets)
    np.testing.assert_allclose(filt_ref, filt_nb, atol=1e-9)
