import numpy as np
import pandas as pd
import pytest

from research.regime import features, targets
from research.regime.models.baselines import Naive50, Naive200
from research.regime.models.base import PREDICT_COLUMNS


@pytest.fixture(scope="module")
def world():
    close = 100.0 * np.exp(np.cumsum(np.random.default_rng(0).normal(0.0003, 0.01, 1200)))
    dates = pd.bdate_range("2015-01-01", periods=1200)
    close = pd.Series(close, index=dates, name="close")
    X50 = features.build_features(close, ladder=(5, 10, 20, 50, 60, 120, 250))
    X200 = features.build_features(close, ladder=(5, 10, 20, 60, 120, 200, 250))
    Y = targets.build_targets(close, open_lockbox=False)
    return {"close": close, "X50": X50, "X200": X200, "Y": Y}


def _fit_slice(X, Y, end):
    idx = X.index[X.index <= end]
    return X.loc[idx], Y.loc[idx]


# --- B1 Naive-50 -----------------------------------------------------------

def test_naive50_hand_computed_label():
    dates = pd.bdate_range("2015-01-01", periods=4)
    X = pd.DataFrame({"dist_ma_50": [0.05, -0.02, 0.0, np.nan]}, index=dates)
    label = Naive50()._label(X)
    assert label.iloc[0] == 2  # above 50-DMA -> Up
    assert label.iloc[1] == 0  # below 50-DMA -> Down
    assert label.iloc[2] == 0  # exactly at the 50-DMA -> Down (not > 0)
    assert np.isnan(label.iloc[3])


def test_naive50_never_choppy(world):
    model = Naive50()
    X_train, Y_train = _fit_slice(world["X50"], world["Y"], "2016-12-31")
    model.fit(X_train, Y_train)
    pred = model.predict(world["X50"])
    assert (pred["regime_p_chop"].dropna() == 0).all()
    for col in PREDICT_COLUMNS:
        assert col in pred.columns


def test_naive50_zero_fitted_knobs():
    assert Naive50().n_fitted_knobs == 0


def test_naive50_causal(world):
    model = Naive50()
    X_train, Y_train = _fit_slice(world["X50"], world["Y"], "2016-12-31")
    model.fit(X_train, Y_train)
    t = pd.Timestamp("2018-06-15")
    full_pred = model.predict(world["X50"]).loc[t]
    truncated_X = world["X50"].loc[world["X50"].index <= t]
    truncated_pred = model.predict(truncated_X).loc[t]
    pd.testing.assert_series_equal(full_pred, truncated_pred, check_names=False)


# --- B2 Naive-200 ------------------------------------------------------------

def test_naive200_hand_computed_label():
    dates = pd.bdate_range("2015-01-01", periods=4)
    X = pd.DataFrame({
        "dist_ma_200": [0.05, -0.02, 0.05, -0.02],
        "ma_slope_200": [0.01, -0.01, -0.01, 0.01],
    }, index=dates)
    label = Naive200()._label(X)
    # up-trend + rising slope -> Up; down-trend + falling slope -> Down;
    # everything else (mixed signs) -> Choppy
    assert label.iloc[0] == 2
    assert label.iloc[1] == 0
    assert label.iloc[2] == 1
    assert label.iloc[3] == 1


def test_naive200_zero_fitted_knobs():
    assert Naive200().n_fitted_knobs == 0


def test_naive200_causal(world):
    model = Naive200()
    X_train, Y_train = _fit_slice(world["X200"], world["Y"], "2016-12-31")
    model.fit(X_train, Y_train)
    t = pd.Timestamp("2018-06-15")
    full_pred = model.predict(world["X200"]).loc[t]
    truncated_X = world["X200"].loc[world["X200"].index <= t]
    truncated_pred = model.predict(truncated_X).loc[t]
    pd.testing.assert_series_equal(full_pred, truncated_pred, check_names=False)


def test_naive200_all_predict_columns_present(world):
    model = Naive200()
    X_train, Y_train = _fit_slice(world["X200"], world["Y"], "2016-12-31")
    model.fit(X_train, Y_train)
    pred = model.predict(world["X200"])
    for col in PREDICT_COLUMNS:
        assert col in pred.columns
