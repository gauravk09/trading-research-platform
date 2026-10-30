"""Equivalence tests for the vectorized batch IRLS fit added for
performance (cox_calibration_test's bootstrap used to call the scalar
_fit_logistic_calibration once per rep -- 15,015 scalar IRLS fits per
score_predictions call, ~15.6s of a 21s call on 2,971 OOS rows, and 843s on
the "long" window's 6,217 rows).

These tests hold the OLD scalar-loop cox_calibration_test (copied here
verbatim as `_cox_calibration_test_reference`) as ground truth and check the
new vectorized path reproduces it bit-for-bit within 1e-8, plus a real-data
fixture captured before the fix landed.
"""
import json
from pathlib import Path

import numpy as np
import pytest

from research.regime import data, features, runner, scoring, targets
from research.regime.models.base import Climatology

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "b0_default_prefix_metrics.json"


# ---------------------------------------------------------------------------
# Reference (pre-fix) scalar-loop implementation, kept only for these tests.
# ---------------------------------------------------------------------------

def _cox_calibration_test_reference(p, y_binary, block=20, n_reps=1000, seed=0, ci=0.95):
    """Verbatim copy of cox_calibration_test as it was before the batch-IRLS
    fix: one scalar _fit_logistic_calibration call per bootstrap rep.
    """
    p = np.asarray(p, dtype=float)
    y_binary = np.asarray(y_binary, dtype=float)
    valid = ~np.isnan(p) & ~np.isnan(y_binary)
    p, y_binary = p[valid], y_binary[valid]
    n = len(p)
    empty = {
        "n": 0, "slope_defined": False,
        "a": np.nan, "a_lo": np.nan, "a_hi": np.nan,
        "b": np.nan, "b_lo": np.nan, "b_hi": np.nan,
        "citl": np.nan, "citl_lo": np.nan, "citl_hi": np.nan,
    }
    if n == 0:
        return empty

    p_clipped = np.clip(p, 0.01, 0.99)
    logit_p = scoring._logit(p_clipped)
    fit = scoring._fit_logistic_calibration(logit_p, y_binary)
    slope_defined = fit is not None
    citl_point = float(np.mean(y_binary) - np.mean(p_clipped))

    alpha = (1 - ci) / 2 * 100
    a_boot, b_boot, citl_boot = [], [], []
    for idx in scoring._block_bootstrap_index_reps(n, block, n_reps, seed):
        pb, yb = p_clipped[idx], y_binary[idx]
        citl_boot.append(float(np.mean(yb) - np.mean(pb)))
        if slope_defined:
            fit_b = scoring._fit_logistic_calibration(scoring._logit(pb), yb)
            if fit_b is not None:
                a_boot.append(fit_b[0])
                b_boot.append(fit_b[1])

    citl_lo, citl_hi = np.percentile(citl_boot, [alpha, 100 - alpha])
    result = dict(empty)
    result.update({
        "n": int(n), "slope_defined": slope_defined,
        "citl": citl_point, "citl_lo": float(citl_lo), "citl_hi": float(citl_hi),
    })
    if slope_defined and len(a_boot) > 0:
        a_lo, a_hi = np.percentile(a_boot, [alpha, 100 - alpha])
        b_lo, b_hi = np.percentile(b_boot, [alpha, 100 - alpha])
        result.update({
            "a": fit[0], "a_lo": float(a_lo), "a_hi": float(a_hi),
            "b": fit[1], "b_lo": float(b_lo), "b_hi": float(b_hi),
        })
    return result


# ---------------------------------------------------------------------------
# Helpers to build the three "realistic forecaster" fixtures asked for.
# ---------------------------------------------------------------------------

def _constant_p_rows(rng, n):
    """Climatology-like: fold-constant probability -> zero variance in
    logit_p -> the scalar fit returns None for every rep (slope undefined).
    """
    p = np.full(n, 0.37)
    y = (rng.random(n) < 0.37).astype(float)
    return p, y


def _near_separated_rows(rng, n):
    """Overconfident forecaster whose clipped probabilities pile up near
    0.01/0.99 -- exercises the ridge/clip/non-convergence paths.
    """
    true_p = rng.uniform(0.05, 0.95, size=n)
    y = (rng.random(n) < true_p).astype(float)
    true_logit = scoring._logit(true_p)
    reported_p = scoring._sigmoid(3.5 * true_logit)  # aggressive stretch
    return reported_p, y


def _well_calibrated_rows(rng, n):
    p = rng.uniform(0.05, 0.95, size=n)
    y = (rng.random(n) < p).astype(float)
    return p, y


def _random_rows(rng, n):
    p = rng.uniform(0.01, 0.99, size=n)
    y = rng.integers(0, 2, size=n).astype(float)
    return p, y


FORECASTERS = {
    "random": _random_rows,
    "constant_p": _constant_p_rows,
    "near_separated": _near_separated_rows,
    "well_calibrated": _well_calibrated_rows,
}

FORECASTER_SEEDS = {"random": 101, "constant_p": 102, "near_separated": 103, "well_calibrated": 104}


# ---------------------------------------------------------------------------
# 1. Batch fit vs scalar fit, per rep.
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("name", list(FORECASTERS.keys()))
def test_batch_fit_matches_scalar_per_rep(name):
    n = 300
    R = 40
    build = FORECASTERS[name]
    base_seed = FORECASTER_SEEDS[name]

    logit_p_rows = []
    y_rows = []
    for r in range(R):
        p, y = build(np.random.default_rng(base_seed * 1000 + r), n)
        logit_p_rows.append(scoring._logit(np.clip(p, 0.01, 0.99)))
        y_rows.append(y)
    logit_p_matrix = np.array(logit_p_rows)
    y_matrix = np.array(y_rows)

    a_arr, b_arr, ok = scoring._fit_logistic_calibration_batch(logit_p_matrix, y_matrix)

    for r in range(R):
        scalar_fit = scoring._fit_logistic_calibration(logit_p_matrix[r], y_matrix[r])
        if scalar_fit is None:
            assert not ok[r], f"row {r}: scalar returned None but batch says ok"
        else:
            assert ok[r], f"row {r}: scalar fit but batch says not ok"
            assert a_arr[r] == pytest.approx(scalar_fit[0], abs=1e-8)
            assert b_arr[r] == pytest.approx(scalar_fit[1], abs=1e-8)


# ---------------------------------------------------------------------------
# 2. cox_calibration_test: new vectorized path vs the old scalar-loop
#    reference kept above, same inputs/seed.
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("name", list(FORECASTERS.keys()))
def test_cox_calibration_test_matches_reference(name):
    rng = np.random.default_rng(42)
    n = 400
    build = FORECASTERS[name]
    p, y = build(rng, n)

    new = scoring.cox_calibration_test(p, y, block=20, n_reps=300, seed=7)
    old = _cox_calibration_test_reference(p, y, block=20, n_reps=300, seed=7)

    assert new["n"] == old["n"]
    assert new["slope_defined"] == old["slope_defined"]
    for key in ("a", "a_lo", "a_hi", "b", "b_lo", "b_hi", "citl", "citl_lo", "citl_hi"):
        if np.isnan(old[key]):
            assert np.isnan(new[key]), key
        else:
            assert new[key] == pytest.approx(old[key], abs=1e-8), key


# ---------------------------------------------------------------------------
# 3. Real-data end-to-end: B0 Climatology, default window config, full
#    score_predictions metrics dict vs the pre-fix fixture.
# ---------------------------------------------------------------------------

def _clean_for_compare(obj):
    if isinstance(obj, dict):
        return {k: _clean_for_compare(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_clean_for_compare(v) for v in obj]
    if isinstance(obj, (np.floating,)):
        return float(obj)
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, (np.bool_,)):
        return bool(obj)
    return obj


def _assert_metrics_equal(actual, expected, path=""):
    assert set(actual.keys()) == set(expected.keys()), f"key mismatch at {path}"
    for k, exp_v in expected.items():
        act_v = actual[k]
        p = f"{path}.{k}"
        if isinstance(exp_v, dict):
            _assert_metrics_equal(act_v, exp_v, p)
        elif isinstance(exp_v, bool):
            assert act_v is exp_v or bool(act_v) == exp_v, p
        elif isinstance(exp_v, (int, float)):
            if isinstance(exp_v, float) and np.isnan(exp_v):
                assert isinstance(act_v, float) and np.isnan(act_v), p
            else:
                assert act_v == pytest.approx(exp_v, abs=1e-8), p
        else:
            assert act_v == exp_v, p


@pytest.mark.slow
def test_b0_default_score_predictions_matches_prefix_fixture():
    expected = json.loads(FIXTURE_PATH.read_text())

    cfg = data.get_window_config("default")
    close = data.load_close(start=cfg["warmup_start"])
    X = features.build_features(close)
    Y = targets.build_targets(close, open_lockbox=False)
    model_pred, clim_pred, folds = runner.run_walkforward(
        lambda k: Climatology(), {}, X, Y, window_config=cfg
    )
    metrics = runner.score_predictions(model_pred, clim_pred, Y, eras=cfg["eras"])
    metrics.pop("_rps_by_h", None)
    actual = _clean_for_compare(metrics)

    _assert_metrics_equal(actual, expected)
