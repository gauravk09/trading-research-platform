import numpy as np
import pandas as pd
import pytest

from research.regime import lag


def _series(values):
    dates = pd.bdate_range("2015-01-01", periods=len(values))
    return pd.Series(values, index=dates, dtype=float)


def test_truth_change_points_requires_min_persist():
    # truth: chop(10), up(25 rows, persists), down(3 rows, too short -> ignored), chop(20 rows, persists)
    vals = [1] * 10 + [2] * 25 + [0] * 3 + [1] * 20
    truth = _series(vals)
    cps = lag.truth_change_points(truth, min_persist=20)
    # the short 3-row "down" blip never qualifies; the up-run and the final
    # chop-run (both >= 20 rows) do
    assert len(cps) == 2
    assert cps.iloc[0]["new_regime"] == 2
    assert cps.iloc[0]["run_len"] == 25
    assert cps.iloc[1]["new_regime"] == 1
    assert cps.iloc[1]["run_len"] == 20
    assert 0 not in cps["new_regime"].to_numpy()


def test_detection_lag_hand_computed():
    # truth changes to "Up" (2) at position 10 and persists 25 rows
    truth_vals = [1] * 10 + [2] * 25
    truth = _series(truth_vals)
    # model labels lag behind by 4 rows: still "chop"(1) for positions 10-13, then "up"(2) from 14 on
    model_vals = [1] * 14 + [2] * 21
    model = _series(model_vals)
    lag_df = lag.detection_lag(model, truth, min_persist=20, cap=120)
    assert len(lag_df) == 1
    assert lag_df.iloc[0]["lag"] == 4
    assert lag_df.iloc[0]["censored"] == False


def test_detection_lag_censored_when_never_catches_up():
    truth_vals = [1] * 10 + [2] * 25
    truth = _series(truth_vals)
    model_vals = [1] * 35  # never switches to "up"
    model = _series(model_vals)
    lag_df = lag.detection_lag(model, truth, min_persist=20, cap=10)
    assert lag_df.iloc[0]["censored"] == True
    assert lag_df.iloc[0]["lag"] == 10


def test_median_lag_by_direction():
    lag_df = pd.DataFrame({
        "date": pd.bdate_range("2015-01-01", periods=4),
        "new_regime": [2, 2, 0, 0],
        "lag": [4, 8, 10, 20],
        "censored": [False, False, False, False],
    })
    result = lag.median_lag_by_direction(lag_df, up_value=2, down_value=0)
    assert result["median_lag_into_up"] == pytest.approx(6.0)
    assert result["median_lag_into_down"] == pytest.approx(15.0)
    assert result["n_events"] == 4


def test_median_lag_empty_events():
    result = lag.median_lag_by_direction(pd.DataFrame(), up_value=2, down_value=0)
    assert np.isnan(result["median_lag_into_up"])
    assert result["n_events"] == 0
