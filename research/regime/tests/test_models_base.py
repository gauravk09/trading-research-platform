import numpy as np
import pandas as pd
import pytest

from research.regime.models.base import Climatology, StateToOdds, PREDICT_COLUMNS


def _toy_targets(n=100, seed=0):
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range("2015-01-01", periods=n)
    Y = pd.DataFrame({
        "band_5": rng.choice([0, 1, 2], size=n, p=[0.2, 0.5, 0.3]),
        "band_20": rng.choice([0, 1, 2], size=n, p=[0.25, 0.5, 0.25]),
        "band_60": rng.choice([0, 1, 2], size=n, p=[0.3, 0.4, 0.3]),
        "dd_5": rng.choice([0, 1], size=n, p=[0.9, 0.1]),
        "dd_20": rng.choice([0, 1], size=n, p=[0.8, 0.2]),
        "dd_60": rng.choice([0, 1], size=n, p=[0.7, 0.3]),
        "vol_tercile_20": rng.choice([0, 1, 2], size=n),
        "truth_regime": rng.choice([0, 1, 2], size=n, p=[0.3, 0.4, 0.3]),
    }, index=dates)
    return Y


def test_climatology_predicts_train_frequencies_exactly():
    dates = pd.bdate_range("2015-01-01", periods=10)
    Y = pd.DataFrame({
        "band_5": [0, 0, 1, 1, 1, 2, 2, 2, 2, 0],   # Down=3,Flat=3,Up=4 -> freqs 0.3/0.3/0.4
        "band_20": [1] * 10,
        "band_60": [1] * 10,
        "dd_5": [1, 0, 0, 0, 0, 0, 0, 0, 0, 0],       # 1/10 = 0.1
        "dd_20": [0] * 10,
        "dd_60": [0] * 10,
        "vol_tercile_20": [0, 1, 2] * 3 + [0],
        "truth_regime": [2] * 6 + [0] * 4,            # Up=0.6, Down=0.4, Choppy=0
    }, index=dates)
    X = pd.DataFrame(index=dates)

    model = Climatology()
    model.fit(X, Y)
    pred = model.predict(X)

    assert pred["p_down_5"].iloc[0] == pytest.approx(0.3)
    assert pred["p_flat_5"].iloc[0] == pytest.approx(0.3)
    assert pred["p_up_5"].iloc[0] == pytest.approx(0.4)
    assert pred["p_dd_5"].iloc[0] == pytest.approx(0.1)
    assert pred["regime_p_up"].iloc[0] == pytest.approx(0.6)
    assert pred["regime_p_down"].iloc[0] == pytest.approx(0.4)
    assert pred["regime_p_chop"].iloc[0] == pytest.approx(0.0)
    # identical row for every date
    assert (pred["p_down_5"] == pred["p_down_5"].iloc[0]).all()


def test_climatology_all_predict_columns_present():
    Y = _toy_targets()
    X = pd.DataFrame(index=Y.index)
    model = Climatology()
    model.fit(X, Y)
    pred = model.predict(X)
    for col in PREDICT_COLUMNS:
        assert col in pred.columns


def test_climatology_zero_fitted_knobs():
    assert Climatology().n_fitted_knobs == 0


def test_climatology_skips_nan_targets_in_frequency():
    dates = pd.bdate_range("2015-01-01", periods=6)
    Y = pd.DataFrame({
        "band_5": [0, np.nan, 2, 2, np.nan, 0],  # valid: 0,2,2,0 -> Down=0.5, Up=0.5
        "band_20": [1] * 6, "band_60": [1] * 6,
        "dd_5": [0] * 6, "dd_20": [0] * 6, "dd_60": [0] * 6,
        "vol_tercile_20": [1] * 6, "truth_regime": [1] * 6,
    }, index=dates)
    X = pd.DataFrame(index=dates)
    model = Climatology().fit(X, Y)
    pred = model.predict(X)
    assert pred["p_down_5"].iloc[0] == pytest.approx(0.5)
    assert pred["p_flat_5"].iloc[0] == pytest.approx(0.0)
    assert pred["p_up_5"].iloc[0] == pytest.approx(0.5)


def test_state_to_odds_hand_computed():
    dates = pd.bdate_range("2015-01-01", periods=6)
    # state A on rows 0-2, state B on rows 3-5
    state_probs = pd.DataFrame({
        "A": [1, 1, 1, 0, 0, 0],
        "B": [0, 0, 0, 1, 1, 1],
    }, index=dates, dtype=float)
    targets_df = pd.DataFrame({
        "band": [0, 0, 2, 2, 2, 1],  # A: 0,0,2 -> with alpha=1 smoothing over 3 levels
    }, index=dates)
    s2o = StateToOdds(alpha=1.0)
    s2o.fit(state_probs, targets_df, {"band": [0, 1, 2]})
    # state A raw counts: level0=2, level1=0, level2=1 -> +1 smoothing each -> 3,1,2 / total 6
    freq_a = s2o.cond_freq_["band"].loc["A"]
    assert freq_a[0] == pytest.approx(3 / 6)
    assert freq_a[1] == pytest.approx(1 / 6)
    assert freq_a[2] == pytest.approx(2 / 6)

    # predicting for a 50/50 mix of A and B should be the average of the two state freqs
    mix = pd.DataFrame({"A": [0.5], "B": [0.5]}, index=[dates[0]])
    pred = s2o.predict(mix, "band")
    freq_b = s2o.cond_freq_["band"].loc["B"]
    expected = 0.5 * freq_a + 0.5 * freq_b
    assert pred.iloc[0][0] == pytest.approx(expected[0])
    assert pred.iloc[0][1] == pytest.approx(expected[1])
    assert pred.iloc[0][2] == pytest.approx(expected[2])
