import numpy as np
import pandas as pd
import pytest

from research.regime import features, targets
from research.regime.models.base import PREDICT_COLUMNS
from research.regime.models.rules import (
    THETA_DEFAULT,
    RuleGrid1,
    RuleGrid2,
    hysteresis_label,
)


def test_theta_is_2_over_sqrt_60():
    # theta = 2 * E[ER_60] under the iid-Gaussian random-walk null = 2/sqrt(60)
    assert THETA_DEFAULT == pytest.approx(2.0 / np.sqrt(60))
    assert THETA_DEFAULT == pytest.approx(0.2582, abs=1e-4)


@pytest.fixture(scope="module")
def world():
    close = 100.0 * np.exp(np.cumsum(np.random.default_rng(1).normal(0.0003, 0.01, 1500)))
    dates = pd.bdate_range("2015-01-01", periods=1500)
    close = pd.Series(close, index=dates, name="close")
    X = features.build_features(close, ladder=(5, 10, 20, 60, 120, 200, 250))
    Y = targets.build_targets(close, open_lockbox=False)
    return {"close": close, "X": X, "Y": Y}


def _fit_slice(X, Y, end):
    idx = X.index[X.index <= end]
    return X.loc[idx], Y.loc[idx]


# --- R1 ----------------------------------------------------------------

def test_r1_hand_computed_label():
    dates = pd.bdate_range("2015-01-01", periods=4)
    X = pd.DataFrame({
        "dist_ma_200": [0.05, -0.02, 0.05, 0.05],
        "ma_slope_200": [0.01, -0.01, 0.01, 0.01],
        "er_60": [0.5, 0.5, 0.10, np.nan],
    }, index=dates)
    label = RuleGrid1(theta=0.25)._label(X)
    assert label.iloc[0] == 2  # trending up, not choppy -> Up
    assert label.iloc[1] == 0  # trending down, not choppy -> Down
    assert label.iloc[2] == 1  # trend says up but er below theta -> Choppy override
    assert np.isnan(label.iloc[3])


def test_r1_one_fitted_knob():
    assert RuleGrid1().n_fitted_knobs == 1
    assert RuleGrid1().knobs == {"theta": THETA_DEFAULT}


def test_r1_causal(world):
    model = RuleGrid1()
    X_train, Y_train = _fit_slice(world["X"], world["Y"], "2017-12-31")
    model.fit(X_train, Y_train)
    t = pd.Timestamp("2019-06-14")
    full_pred = model.predict(world["X"]).loc[t]
    truncated_pred = model.predict(world["X"].loc[world["X"].index <= t]).loc[t]
    pd.testing.assert_series_equal(full_pred, truncated_pred, check_names=False)


def test_r1_all_predict_columns_present(world):
    model = RuleGrid1()
    X_train, Y_train = _fit_slice(world["X"], world["Y"], "2017-12-31")
    model.fit(X_train, Y_train)
    pred = model.predict(world["X"])
    for col in PREDICT_COLUMNS:
        assert col in pred.columns


# --- hysteresis / R2 -----------------------------------------------------

def test_hysteresis_hand_computed():
    # k=3: a new value must appear 3 times in a row before it is displayed
    raw = pd.Series([0, 0, 2, 2, 2, 2, 0, 2, 2, 0, 0, 0], dtype=float)
    out = hysteresis_label(raw, k=3)
    # rows 0-1: only 2 in a row of 0 so far -> never reached k=3 yet -> NaN
    assert np.isnan(out.iloc[0]) and np.isnan(out.iloc[1])
    # row 4 is the 3rd consecutive 2 (indices 2,3,4) -> switches to 2
    assert np.isnan(out.iloc[2]) and np.isnan(out.iloc[3])
    assert out.iloc[4] == 2
    assert out.iloc[5] == 2
    # single 0 at index 6 breaks the streak, displayed label stays 2
    assert out.iloc[6] == 2
    assert out.iloc[7] == 2  # streak of 2s reset to 1, still shows old value 2
    assert out.iloc[8] == 2
    # indices 9,10,11 are three consecutive 0s -> switches to 0 at index 11
    assert out.iloc[9] == 2
    assert out.iloc[10] == 2
    assert out.iloc[11] == 0


def test_hysteresis_nan_resets_streak_but_keeps_displayed_value():
    raw = pd.Series([0, 0, np.nan, 2, 2], dtype=float)
    out = hysteresis_label(raw, k=2)
    assert out.iloc[0] is np.nan or np.isnan(out.iloc[0])  # no displayed value yet
    assert out.iloc[1] == 0  # two 0s in a row -> switches to 0
    assert out.iloc[2] == 0  # NaN row: nothing new to display, keeps showing 0
    assert out.iloc[3] == 0  # streak of 2s restarts at 1 -> not yet k=2 -> still 0
    assert out.iloc[4] == 2  # second consecutive 2 (post-NaN) -> switches to 2


def test_r2_two_fitted_knobs():
    assert RuleGrid2().n_fitted_knobs == 2
    assert RuleGrid2().knobs == {"theta": THETA_DEFAULT, "k": 5}


def test_r2_causal(world):
    model = RuleGrid2()
    X_train, Y_train = _fit_slice(world["X"], world["Y"], "2017-12-31")
    model.fit(X_train, Y_train)
    t = pd.Timestamp("2019-06-14")
    full_pred = model.predict(world["X"]).loc[t]
    truncated_pred = model.predict(world["X"].loc[world["X"].index <= t]).loc[t]
    pd.testing.assert_series_equal(full_pred, truncated_pred, check_names=False)


def test_r2_fewer_or_equal_flips_than_r1(world):
    # hysteresis is meant to reduce whipsaw -- the smoothed label should
    # never flip MORE often than the raw R1 label it is built from.
    from research.regime.models.rules import _raw_trend_chop_label

    raw = _raw_trend_chop_label(world["X"], THETA_DEFAULT)
    smoothed = hysteresis_label(raw, k=5)
    raw_valid = raw.dropna()
    smoothed_valid = smoothed.dropna()
    raw_flips = int((raw_valid.to_numpy()[1:] != raw_valid.to_numpy()[:-1]).sum())
    smoothed_flips = int((smoothed_valid.to_numpy()[1:] != smoothed_valid.to_numpy()[:-1]).sum())
    assert smoothed_flips <= raw_flips


def test_r2_all_predict_columns_present(world):
    model = RuleGrid2()
    X_train, Y_train = _fit_slice(world["X"], world["Y"], "2017-12-31")
    model.fit(X_train, Y_train)
    pred = model.predict(world["X"])
    for col in PREDICT_COLUMNS:
        assert col in pred.columns
