import numpy as np
import pandas as pd
import pytest

from research.regime import features


def _toy_close(n=800, seed=1):
    dates = pd.bdate_range("2013-01-01", periods=n)
    rng = np.random.default_rng(seed)
    log_rets = rng.normal(0.0002, 0.011, size=n)
    close = 100.0 * np.exp(np.cumsum(log_rets))
    return pd.Series(close, index=dates, name="close")


def test_ret_n_hand_computed():
    dates = pd.bdate_range("2015-01-01", periods=10)
    close = pd.Series([100, 102, 104, 103, 105, 108, 110, 109, 111, 115], index=dates, dtype=float)
    X = features.build_features(close, ladder=(5,), er_ns=(), dd_windows=())
    # ret_5 at t=5 (0-indexed) = close[5]/close[0]-1 = 108/100-1 = 0.08
    assert X["ret_5"].iloc[5] == pytest.approx(0.08)
    assert np.isnan(X["ret_5"].iloc[3])  # not enough history


def test_dist_ma_n_hand_computed():
    dates = pd.bdate_range("2015-01-01", periods=12)
    close = pd.Series([100, 100, 100, 100, 100, 100, 100, 100, 100, 100, 150, 100], index=dates, dtype=float)
    X = features.build_features(close, ladder=(10,), er_ns=(), dd_windows=())
    # SMA_10 at t=9 (rows 0..9, all 100) = 100 -> dist_ma = 0
    assert X["dist_ma_10"].iloc[9] == pytest.approx(0.0)
    # SMA_10 at t=10: rows 1..10 = nine 100s + one 150 = (9*100+150)/10 = 105
    assert X["dist_ma_10"].iloc[10] == pytest.approx(150 / 105 - 1)


def test_ma_slope_n_hand_computed():
    dates = pd.bdate_range("2015-01-01", periods=45)
    close = pd.Series(np.linspace(100, 144, 45), index=dates)  # simple linear ramp
    X = features.build_features(close, ladder=(20,), er_ns=(), dd_windows=())
    sma20 = close.rolling(20, min_periods=20).mean()
    k = min(20, 20)
    expected = sma20.iloc[40] / sma20.iloc[40 - k] - 1
    assert X["ma_slope_20"].iloc[40] == pytest.approx(expected)


def test_rvol_n_hand_computed():
    dates = pd.bdate_range("2015-01-01", periods=15)
    rng = np.random.default_rng(3)
    log_rets = rng.normal(0, 0.01, size=15)
    close = pd.Series(100.0 * np.exp(np.cumsum(log_rets)), index=dates)
    X = features.build_features(close, ladder=(10,), er_ns=(), dd_windows=())
    lr = np.log(close / close.shift(1))
    expected = lr.iloc[1:11].std() * np.sqrt(252)
    assert X["rvol_10"].iloc[10] == pytest.approx(expected)


def test_vol_ratio_is_short_over_long_rvol():
    close = _toy_close(400)
    X = features.build_features(close, ladder=(10, 20, 60, 250))
    pd.testing.assert_series_equal(
        X["vol_ratio"].rename(None), (X["rvol_10"] / X["rvol_250"]).rename(None)
    )


def test_efficiency_ratio_hand_computed():
    dates = pd.bdate_range("2015-01-01", periods=6)
    close = pd.Series([100, 105, 103, 108, 106, 110], index=dates, dtype=float)
    X = features.build_features(close, ladder=(), er_ns=(5,), dd_windows=())
    # net move over 5 rows (t=5): |110-100| = 10
    # daily diffs: |5|,|2|,|5|,|2|,|4| = 5+2+5+2+4=18
    expected = 10 / 18
    assert X["er_5"].iloc[5] == pytest.approx(expected)


def test_dd_high_n_hand_computed():
    dates = pd.bdate_range("2015-01-01", periods=6)
    close = pd.Series([100, 110, 105, 95, 108, 90], index=dates, dtype=float)
    X = features.build_features(close, ladder=(), er_ns=(), dd_windows=(5,))
    # rolling max over 5 rows ending at t=5 (rows1..5): max(110,105,95,108,90)=110
    assert X["dd_high_5"].iloc[5] == pytest.approx(90 / 110 - 1)


def test_causality_random_dates():
    """The defining property: recomputing features on a series truncated at t
    must reproduce the full-series value at t exactly, for every column."""
    close = _toy_close(900, seed=11)
    X_full = features.build_features(close)
    rng = np.random.default_rng(0)
    probe_positions = rng.integers(260, len(close), size=15)  # past full warm-up
    for pos in probe_positions:
        t = close.index[pos]
        X_trunc = features.build_features(close.loc[:t])
        row_full = X_full.loc[t]
        row_trunc = X_trunc.loc[t]
        for col in X_full.columns:
            a, b = row_full[col], row_trunc[col]
            if pd.isna(a) and pd.isna(b):
                continue
            assert a == pytest.approx(b), f"{col} differs at {t}: full={a} trunc={b}"


def test_ladder_is_configurable_for_stability_swap():
    close = _toy_close(400)
    X20 = features.build_features(close, ladder=(5, 10, 20, 60, 120, 250))
    X15 = features.build_features(close, ladder=(5, 10, 15, 60, 120, 250))
    assert "ret_20" in X20.columns and "ret_20" not in X15.columns
    assert "ret_15" in X15.columns
