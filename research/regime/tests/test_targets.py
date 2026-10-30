import numpy as np
import pandas as pd
import pytest

from research.regime import targets
from research.regime.data import LOCKBOX_START


def _toy_close(n=400, start="2015-01-01"):
    """A deterministic, mildly-trending toy price series with enough rows to
    exercise the 250-row sigma window fully (n well above 250+60).
    """
    dates = pd.bdate_range(start, periods=n)
    rng = np.random.default_rng(42)
    log_rets = rng.normal(0.0003, 0.01, size=n)
    close = 100.0 * np.exp(np.cumsum(log_rets))
    return pd.Series(close, index=dates, name="close")


def test_fwd_ret_h_hand_computed():
    close = pd.Series([100.0, 102.0, 101.0, 105.0, 110.0],
                       index=pd.bdate_range("2015-01-01", periods=5))
    r = targets.fwd_ret_h(close, 2, open_lockbox=True)
    # r[0] = close[2]/close[0] - 1 = 101/100 - 1 = 0.01
    assert r.iloc[0] == pytest.approx(0.01)
    # r[2] = close[4]/close[2] - 1 = 110/101 - 1
    assert r.iloc[2] == pytest.approx(110 / 101 - 1)
    # last two rows have no h=2 forward data
    assert np.isnan(r.iloc[3])
    assert np.isnan(r.iloc[4])


def test_sigma_h_hand_computed():
    # 251 flat-ish rows so the 250-row window is fully populated at the last row
    dates = pd.bdate_range("2015-01-01", periods=251)
    rets = np.zeros(251)
    rets[1:] = 0.01  # constant daily log return after day 0 (close[0] has no return)
    close = pd.Series(100.0 * np.exp(np.cumsum(rets)), index=dates)
    sig = targets.sigma_h(close, 5)
    # constant returns after the first day -> the 250-row std at the last row
    # includes one NaN-producing shift, but log returns rows 1..250 are all
    # exactly 0.01 -> std = 0
    assert sig.iloc[-1] == pytest.approx(0.0, abs=1e-9)


def test_sigma_h_matches_manual_std():
    close = _toy_close(500)
    sig20_5 = targets.sigma_h(close, 5)
    lr = np.log(close / close.shift(1))
    manual = lr.iloc[300 - 249 : 301].std() * np.sqrt(5)
    assert sig20_5.iloc[300] == pytest.approx(manual)


def test_band_h_thresholds():
    close = _toy_close(400)
    sig = targets.sigma_h(close, 5)
    r = targets.fwd_ret(close, 5)
    band = targets.band_h(close, 5, open_lockbox=True)
    t = 300  # well past warm-up
    if not np.isnan(sig.iloc[t]):
        expected = 1
        if r.iloc[t] < -0.5 * sig.iloc[t]:
            expected = 0
        elif r.iloc[t] > 0.5 * sig.iloc[t]:
            expected = 2
        assert band.iloc[t] == expected


def test_band_h_boundary_hand_computed():
    # Construct so fwd_ret is exactly known and sigma is controllable via
    # constant historical vol, then check the three regions explicitly.
    dates = pd.bdate_range("2015-01-01", periods=260)
    rets = np.zeros(260)
    rets[1:251] = 0.0  # 250 rows of exactly-zero log return -> sigma_5 = 0 at row 250
    close = pd.Series(100.0 * np.exp(np.cumsum(rets)), index=dates)
    # From row 250 (0-indexed 250 -> the 251st row), sigma_5 should be 0 since
    # all 250 trailing returns are 0. Any nonzero fwd_ret is then "Up" or "Down".
    close.iloc[255] = close.iloc[250] * 1.01  # a later row moves the price up
    band = targets.band_h(close, 5, open_lockbox=True)
    sig = targets.sigma_h(close, 5)
    assert sig.iloc[250] == pytest.approx(0.0, abs=1e-9)
    r250 = targets.fwd_ret(close, 5).iloc[250]
    assert r250 > 0
    assert band.iloc[250] == 2  # Up: positive fwd return vs sigma=0


def test_fixed_band_h_hand_computed():
    dates = pd.bdate_range("2015-01-01", periods=10)
    close = pd.Series([100, 101.6, 100, 100, 100, 100, 100, 100, 100, 100], index=dates, dtype=float)
    # h=5, threshold 1.5%: fwd_ret at t=0 = close[5]/close[0]-1 = 0 -> Flat
    fb = targets.fixed_band_h(close, 5, open_lockbox=True)
    assert fb.iloc[0] == 1  # flat, since close[5]==close[0]
    close2 = pd.Series([100, 100, 100, 100, 100, 102, 100, 100, 100, 100], index=dates, dtype=float)
    fb2 = targets.fixed_band_h(close2, 5, open_lockbox=True)
    # fwd_ret at t=0 = 102/100-1 = 0.02 > 0.015 -> Up
    assert fb2.iloc[0] == 2


def test_dd_h_hand_computed():
    dates = pd.bdate_range("2015-01-01", periods=8)
    # from t=0: next 5 rows are 100,95,105,90,110 -> min ratio = 90/100-1=-0.10 <= -0.03(5d thresh) -> dd=1
    close = pd.Series([100, 100, 95, 105, 90, 110, 100, 100], index=dates, dtype=float)
    dd = targets.dd_h(close, 5, open_lockbox=True)
    assert dd.iloc[0] == 1.0
    # a series that never drops 3% in 5 days from t=0
    close2 = pd.Series([100, 100.5, 101, 100.8, 101.2, 101.5, 100, 100], index=dates, dtype=float)
    dd2 = targets.dd_h(close2, 5, open_lockbox=True)
    assert dd2.iloc[0] == 0.0


def test_dd_h_nan_near_end_of_series():
    dates = pd.bdate_range("2015-01-01", periods=8)
    close = pd.Series(np.linspace(100, 110, 8), index=dates)
    dd = targets.dd_h(close, 5, open_lockbox=True)
    assert np.isnan(dd.iloc[-1])  # not enough forward rows
    assert np.isnan(dd.iloc[-2])


def test_lockbox_masks_dev_targets_whose_window_reaches_lockbox():
    # Rows in Dec 2024 whose h=20 forward window reaches into Jan 2025 must
    # be NaN by default (open_lockbox=False), and non-NaN when opened.
    dates = pd.bdate_range("2023-06-01", "2025-02-28", freq="B")  # enough history for the 250-row sigma window
    close = pd.Series(np.linspace(100, 150, len(dates)), index=dates)
    band_default = targets.band_h(close, 20, open_lockbox=False)
    band_open = targets.band_h(close, 20, open_lockbox=True)

    dec_dates = dates[(dates >= "2024-12-01") & (dates <= "2024-12-31")]
    leaking = [d for d in dec_dates if (d + pd.tseries.offsets.BDay(20)) >= LOCKBOX_START]
    assert len(leaking) > 0
    for d in leaking:
        pos = dates.get_loc(d)
        end_date = dates[pos + 20] if pos + 20 < len(dates) else None
        if end_date is not None and end_date >= LOCKBOX_START:
            assert np.isnan(band_default.loc[d])
            # opening the lockbox must actually recover a real (non-NaN) value
            assert not np.isnan(band_open.loc[d])

    # a row safely before the window (but with full sigma warm-up) never gets masked
    safe_date = pd.Timestamp("2024-10-01")
    assert not np.isnan(band_default.loc[safe_date])


def test_lockbox_masks_never_use_future_price_when_closed():
    # Direct proof: perturbing a lockbox-only price must NOT change a masked
    # (closed) dev-date target, since it was set to NaN before ever touching
    # that price's actual value.
    dates = pd.bdate_range("2024-11-01", "2025-02-28", freq="B")
    close = pd.Series(np.linspace(100, 120, len(dates)), index=dates)
    band_before = targets.band_h(close, 20, open_lockbox=False)

    close_mutated = close.copy()
    lockbox_mask = close_mutated.index >= LOCKBOX_START
    close_mutated[lockbox_mask] = close_mutated[lockbox_mask] * 5  # wild change to lockbox prices only
    band_after = targets.band_h(close_mutated, 20, open_lockbox=False)

    pd.testing.assert_series_equal(band_before, band_after)


def test_fwd_vol_tercile_causal_thresholds_dont_use_future():
    close = _toy_close(1200)
    vt_before = targets.fwd_vol_tercile(close, open_lockbox=True)
    # Perturbing prices strictly AFTER date t must not change vt at t, since
    # the tercile thresholds and the backward series are causal and the
    # forward-vol value only reads t+1..t+20 for row t itself (verified
    # separately by the leak test below); this test checks classification is
    # stable to values two years after a mid-series date.
    t = close.index[700]
    close_mutated = close.copy()
    far_future = close_mutated.index > (t + pd.Timedelta(days=400))
    close_mutated[far_future] = close_mutated[far_future] * 3
    vt_after = targets.fwd_vol_tercile(close_mutated, open_lockbox=True)
    assert vt_before.loc[t] == vt_after.loc[t] or (np.isnan(vt_before.loc[t]) and np.isnan(vt_after.loc[t]))


def test_truth_regime_hand_computed_trend_up():
    # A clean straight-line uptrend over 60 rows has ER close to 1 and a
    # large positive return -> Up.
    dates = pd.bdate_range("2015-01-01", periods=320)
    close = pd.Series(np.linspace(100, 100 * 1.5, 320), index=dates)
    tr = targets.truth_regime(close, open_lockbox=True)
    t = 250
    assert tr.iloc[t] == 2  # Up


def test_truth_regime_hand_computed_choppy():
    dates = pd.bdate_range("2015-01-01", periods=320)
    rng = np.random.default_rng(7)
    # zero-drift, oscillating series -> ER should be small -> Choppy
    close_vals = 100 + 2 * np.sin(np.arange(320) / 2.0)
    close = pd.Series(close_vals, index=dates)
    tr = targets.truth_regime(close, open_lockbox=True)
    t = 250
    assert tr.iloc[t] == 1  # Choppy


def test_build_targets_has_expected_columns():
    close = _toy_close(400)
    Y = targets.build_targets(close, open_lockbox=True)
    for h in (5, 20, 60):
        for col in (f"band_{h}", f"fixed_band_{h}", f"dd_{h}", f"fwd_ret_{h}", f"sigma_{h}"):
            assert col in Y.columns
    assert "vol_tercile_20" in Y.columns
    assert "truth_regime" in Y.columns
