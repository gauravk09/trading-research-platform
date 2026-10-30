import numpy as np
import pytest

from research.regime import scoring


def test_rps_hand_computed_single_day():
    # probs = (Down=0.2, Flat=0.3, Up=0.5), true = Up (index 2)
    # CDF_pred = (0.2, 0.5, 1.0), CDF_true = (0, 0, 1)
    # RPS = (0.2-0)^2 + (0.5-0)^2 = 0.04 + 0.25 = 0.29 (drop the always-0 last term)
    probs = np.array([[0.2, 0.3, 0.5]])
    y = np.array([2])
    r = scoring.rps_per_day(probs, y)
    assert r[0] == pytest.approx(0.29)


def test_rps_perfect_forecast_is_zero():
    probs = np.array([[1.0, 0.0, 0.0]])
    y = np.array([0])
    assert scoring.rps_per_day(probs, y)[0] == pytest.approx(0.0)


def test_rps_worst_forecast_ordered_penalty():
    # predicting all-Down when truth is Up should score worse than predicting
    # all-Down when truth is Flat, because RPS respects the ordering
    probs = np.array([[1.0, 0.0, 0.0], [1.0, 0.0, 0.0]])
    y_up = np.array([2])
    y_flat = np.array([1])
    rps_up = scoring.rps_per_day(probs[:1], y_up)[0]
    rps_flat = scoring.rps_per_day(probs[:1], y_flat)[0]
    # Down predicted, truth Up: CDF_pred=(1,1), CDF_true=(0,0) -> (1-0)^2+(1-0)^2=2
    assert rps_up == pytest.approx(2.0)
    # Down predicted, truth Flat: CDF_pred=(1,1), CDF_true=(1,0) -> (1-1)^2+(1-0)^2=1
    assert rps_flat == pytest.approx(1.0)
    assert rps_up > rps_flat


def test_rps_skill_hand_computed():
    rps_model = np.array([0.1, 0.2, 0.3])
    rps_clim = np.array([0.2, 0.2, 0.2])
    # skill = 1 - mean(model)/mean(clim) = 1 - 0.2/0.2 = 0
    assert scoring.rps_skill(rps_model, rps_clim) == pytest.approx(0.0)
    rps_model2 = np.array([0.1, 0.1, 0.1])
    # skill = 1 - 0.1/0.2 = 0.5
    assert scoring.rps_skill(rps_model2, rps_clim) == pytest.approx(0.5)


def test_log_loss_hand_computed():
    # p_true = 0.5 -> -log(0.5) = 0.693147...
    probs = np.array([[0.2, 0.3, 0.5]])
    y = np.array([2])
    assert scoring.log_loss_multiclass(probs, y) == pytest.approx(-np.log(0.5))


def test_log_loss_two_days_average():
    probs = np.array([[0.5, 0.25, 0.25], [0.1, 0.1, 0.8]])
    y = np.array([0, 2])
    expected = np.mean([-np.log(0.5), -np.log(0.8)])
    assert scoring.log_loss_multiclass(probs, y) == pytest.approx(expected)


def test_brier_binary_hand_computed():
    p = np.array([0.7, 0.3])
    y = np.array([1.0, 0.0])
    # (0.7-1)^2=0.09, (0.3-0)^2=0.09 -> mean 0.09
    assert scoring.brier_binary(p, y) == pytest.approx(0.09)


def test_brier_multiclass_hand_computed():
    probs = np.array([[0.2, 0.3, 0.5]])
    y = np.array([2])
    # onehot=(0,0,1); diffs^2 = 0.04+0.09+0.25=0.38
    assert scoring.brier_multiclass(probs, y) == pytest.approx(0.38)


def test_ece_perfect_calibration_is_zero():
    p2 = np.array([0.1, 0.1, 0.1, 0.1, 0.1, 0.1, 0.1, 0.1, 0.1, 0.1])
    y2 = np.array([1, 0, 0, 0, 0, 0, 0, 0, 0, 0])  # obs freq = 0.1, matches mean_pred exactly
    assert scoring.ece(p2, y2) == pytest.approx(0.0)


def test_ece_hand_computed_two_bins():
    # bin A: 5 points at p=0.05, 1 positive -> mean_pred=0.05, obs=0.2, weight 5/10
    # bin B: 5 points at p=0.95, 4 positive -> mean_pred=0.95, obs=0.8, weight 5/10
    p = np.array([0.05] * 5 + [0.95] * 5)
    y = np.array([1, 0, 0, 0, 0] + [1, 1, 1, 1, 0])
    expected = 0.5 * abs(0.05 - 0.2) + 0.5 * abs(0.95 - 0.8)
    assert scoring.ece(p, y, n_bins=10) == pytest.approx(expected)


def test_reliability_diagram_counts_and_bins():
    p = np.array([0.05, 0.06, 0.15, 0.95])
    y = np.array([0, 1, 0, 1])
    diag = scoring.reliability_diagram_data(p, y, n_bins=10)
    assert diag.loc[0, "count"] == 2  # both 0.05 and 0.06 fall in bin 0
    assert diag.loc[1, "count"] == 1  # 0.15 -> bin 1
    assert diag.loc[9, "count"] == 1  # 0.95 -> bin 9
    assert diag.loc[9, "obs_freq"] == pytest.approx(1.0)


def test_bootstrap_ci_contains_point_estimate():
    rng = np.random.default_rng(0)
    rps_model = rng.uniform(0.05, 0.15, size=500)
    rps_clim = rng.uniform(0.18, 0.22, size=500)
    result = scoring.rps_skill_ci(rps_model, rps_clim, block=20, n_reps=500, seed=1)
    assert result["lo"] <= result["point"] <= result["hi"]


def test_bootstrap_ci_reproducible_with_fixed_seed():
    rng = np.random.default_rng(0)
    rps_model = rng.uniform(0.05, 0.15, size=300)
    rps_clim = rng.uniform(0.18, 0.22, size=300)
    r1 = scoring.rps_skill_ci(rps_model, rps_clim, block=20, n_reps=200, seed=42)
    r2 = scoring.rps_skill_ci(rps_model, rps_clim, block=20, n_reps=200, seed=42)
    assert r1 == r2


def test_bootstrap_ci_widens_with_more_noise():
    rng = np.random.default_rng(0)
    n = 500
    rps_clim = np.full(n, 0.2)
    low_noise_model = 0.1 + rng.normal(0, 0.001, n)
    high_noise_model = 0.1 + rng.normal(0, 0.05, n)
    r_low = scoring.rps_skill_ci(low_noise_model, rps_clim, block=20, n_reps=500, seed=3)
    r_high = scoring.rps_skill_ci(high_noise_model, rps_clim, block=20, n_reps=500, seed=3)
    assert (r_high["hi"] - r_high["lo"]) > (r_low["hi"] - r_low["lo"])


def test_consistency_resampling_perfectly_calibrated_passes_about_95_percent():
    # A forecaster whose outcomes are LITERALLY drawn from its own p (i.e.
    # genuinely, exactly as calibrated as the null assumes) should have
    # observed ECE <= the null's 95th percentile in roughly 95% of repeated
    # experiments -- that's the definition of the test. Run many independent
    # "experiments" (each with its own p/y draw) and check the pass rate.
    rng = np.random.default_rng(123)
    n_days = 400
    passes = 0
    n_experiments = 60
    for i in range(n_experiments):
        p = rng.uniform(0.05, 0.95, size=n_days)
        y = (rng.random(n_days) < p).astype(float)  # perfectly calibrated by construction
        result = scoring.consistency_resampling_ece(p, y, n_reps=300, seed=1000 + i)
        if result["observed_ece"] <= result["null_ece_pct"]:
            passes += 1
    pass_rate = passes / n_experiments
    # allow generous slack for n_experiments=60 sampling noise around 0.95
    assert 0.80 <= pass_rate <= 1.0, pass_rate


def test_consistency_resampling_miscalibrated_forecaster_fails():
    rng = np.random.default_rng(5)
    n_days = 500
    true_p = rng.uniform(0.05, 0.95, size=n_days)
    y = (rng.random(n_days) < true_p).astype(float)
    # forecaster reports p shrunk toward 0.9 -- systematically overconfident
    # on the "up" side and wrong almost everywhere the truth is actually low
    reported_p = 0.9 - 0.1 * (0.9 - true_p)
    result = scoring.consistency_resampling_ece(reported_p, y, n_reps=1000, seed=7)
    assert result["observed_ece"] > result["null_ece_pct"]
    assert result["p_value"] < 0.05


def test_consistency_resampling_reproducible_with_fixed_seed():
    rng = np.random.default_rng(0)
    p = rng.uniform(0.1, 0.9, size=200)
    y = (rng.random(200) < p).astype(float)
    r1 = scoring.consistency_resampling_ece(p, y, n_reps=200, seed=42)
    r2 = scoring.consistency_resampling_ece(p, y, n_reps=200, seed=42)
    assert r1 == r2


def test_consistency_resampling_ignores_nan_rows():
    p = np.array([0.5, np.nan, 0.5, 0.5])
    y = np.array([1.0, 1.0, np.nan, 0.0])
    result = scoring.consistency_resampling_ece(p, y, n_reps=100, seed=1)
    assert result["n"] == 2  # only the two fully-valid rows count


def test_cox_calibration_perfectly_calibrated_forecaster():
    rng = np.random.default_rng(11)
    n = 2000
    p = rng.uniform(0.05, 0.95, size=n)
    y = (rng.random(n) < p).astype(float)  # exactly calibrated by construction
    result = scoring.cox_calibration_test(p, y, block=20, n_reps=500, seed=1)
    assert result["slope_defined"] is True
    assert result["a_lo"] <= 0 <= result["a_hi"]
    assert result["b_lo"] <= 1 <= result["b_hi"]


def test_cox_calibration_miscalibrated_forecaster_fails():
    rng = np.random.default_rng(12)
    n = 2000
    true_p = rng.uniform(0.05, 0.95, size=n)
    y = (rng.random(n) < true_p).astype(float)
    # Overconfident forecaster: reported logit = 1.8x the true logit (a
    # smooth logit-space stretch, not a hard [0,1] clip -- clipping the
    # exaggerated probability directly saturates a wide range of true_p onto
    # the same reported value, which creates near-perfect separation and an
    # unstable/unbounded MLE that isn't really "miscalibration", it's just
    # numerically degenerate). With this transform the true calibration
    # slope is exactly 1/1.8 ~= 0.556, well below 1.
    true_logit = scoring._logit(true_p)
    reported_p = scoring._sigmoid(1.8 * true_logit)
    result = scoring.cox_calibration_test(reported_p, y, block=20, n_reps=500, seed=2)
    assert result["slope_defined"] is True
    assert result["b"] < 1
    assert not (result["b_lo"] <= 1 <= result["b_hi"])


def test_cox_calibration_constant_p_marks_slope_undefined():
    n = 500
    p = np.full(n, 0.3)
    rng = np.random.default_rng(13)
    y = (rng.random(n) < 0.3).astype(float)
    result = scoring.cox_calibration_test(p, y, block=20, n_reps=300, seed=3)
    assert result["slope_defined"] is False
    assert np.isnan(result["a"]) and np.isnan(result["b"])
    # calibration-in-the-large is still reported and has a real CI
    assert not np.isnan(result["citl"])
    assert result["citl_lo"] <= result["citl"] <= result["citl_hi"]


def test_cox_calibration_reproducible_with_fixed_seed():
    rng = np.random.default_rng(0)
    p = rng.uniform(0.1, 0.9, size=300)
    y = (rng.random(300) < p).astype(float)
    r1 = scoring.cox_calibration_test(p, y, block=20, n_reps=200, seed=42)
    r2 = scoring.cox_calibration_test(p, y, block=20, n_reps=200, seed=42)
    assert r1 == r2


def test_cox_calibration_ignores_nan_rows():
    p = np.array([0.5, np.nan, 0.6, 0.4, 0.5, 0.6, 0.4, 0.5])
    y = np.array([1.0, 1.0, np.nan, 0.0, 1.0, 0.0, 0.0, 1.0])
    result = scoring.cox_calibration_test(p, y, block=2, n_reps=50, seed=1)
    assert result["n"] == 6


def test_paired_skill_diff_zero_when_identical_predictions():
    rng = np.random.default_rng(0)
    rps_model = rng.uniform(0.05, 0.15, size=300)
    rps_clim = rng.uniform(0.18, 0.22, size=300)
    result = scoring.paired_skill_diff_ci(rps_model, rps_clim, rps_model, rps_clim, block=20, n_reps=200, seed=5)
    assert result["point"] == pytest.approx(0.0)
    assert result["lo"] <= 0.0 <= result["hi"]
