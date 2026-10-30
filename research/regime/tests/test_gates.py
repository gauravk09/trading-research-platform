import numpy as np

from research.regime import gates


def _good_band_calibration(lab):
    return {
        f"cal_20d_{lab}_slope_defined": True,
        f"cal_20d_{lab}_a_lo": -0.1, f"cal_20d_{lab}_a_hi": 0.1,
        f"cal_20d_{lab}_b_lo": 0.9, f"cal_20d_{lab}_b_hi": 1.1,
        f"cal_20d_{lab}_citl_lo": -0.02, f"cal_20d_{lab}_citl_hi": 0.02,
    }


def _base_metrics(**overrides):
    m = {
        "rps_skill_20_ci_lo": 0.02,
        "flips_per_year": 5.0,
        "whipsaw_rate": 0.10,
        "mean_duration": 30.0,
        "knob_perturbation_min_kappa": 0.9,
        "knob_perturbation_max_skill_drop": 0.10,
        "prob_jump_share": 0.02,
        "data_perturbation_agreement": 0.97,
        "median_lag": 10.0,
    }
    for lab in ("down", "flat", "up"):
        m.update(_good_band_calibration(lab))
    m.update(overrides)
    return m


def test_all_gates_pass_on_good_metrics():
    result = gates.evaluate_gates(_base_metrics(), has_regime_probs=True)
    assert gates.all_pass(result)
    assert all(v is True for v in result.values())


def test_rps_skill_gate_fails_when_ci_touches_zero():
    m = _base_metrics(rps_skill_20_ci_lo=-0.01)
    result = gates.evaluate_gates(m, has_regime_probs=True)
    assert result["rps_skill_20d_ci_lower_positive"] is False
    assert not gates.all_pass(result)


def test_flips_per_year_out_of_range_fails():
    m = _base_metrics(flips_per_year=15.0)
    result = gates.evaluate_gates(m, has_regime_probs=True)
    assert result["flips_per_year_in_range"] is False
    m2 = _base_metrics(flips_per_year=1.0)
    result2 = gates.evaluate_gates(m2, has_regime_probs=True)
    assert result2["flips_per_year_in_range"] is False


def test_flips_per_year_boundary_inclusive():
    m = _base_metrics(flips_per_year=2.0)
    assert gates.evaluate_gates(m, has_regime_probs=True)["flips_per_year_in_range"] is True
    m2 = _base_metrics(flips_per_year=8.0)
    assert gates.evaluate_gates(m2, has_regime_probs=True)["flips_per_year_in_range"] is True


def test_regime_gates_na_without_regime_probs():
    result = gates.evaluate_gates(_base_metrics(), has_regime_probs=False)
    assert result["flips_per_year_in_range"] is None
    assert result["whipsaw_rate_within_bound"] is None
    assert result["median_lag_within_bound"] is None
    # N/A gates don't block all_pass
    assert gates.all_pass(result) is True


def test_nan_metric_yields_na_gate():
    m = _base_metrics(**{
        f"cal_20d_{lab}_slope_defined": None for lab in ("down", "flat", "up")
    })
    result = gates.evaluate_gates(m, has_regime_probs=True)
    assert result["calibration_20d_within_bound"] is None


def test_calibration_gate_uses_worst_of_down_flat_up():
    # flat band's slope CI excludes 1 -> gate fails even though down/up are fine
    m = _base_metrics(cal_20d_flat_b_lo=1.2, cal_20d_flat_b_hi=1.5)
    result = gates.evaluate_gates(m, has_regime_probs=True)
    assert result["calibration_20d_within_bound"] is False


def test_calibration_gate_fails_when_intercept_ci_excludes_zero():
    m = _base_metrics(cal_20d_up_a_lo=0.3, cal_20d_up_a_hi=0.6)
    result = gates.evaluate_gates(m, has_regime_probs=True)
    assert result["calibration_20d_within_bound"] is False


def test_calibration_gate_passes_when_all_bands_well_calibrated():
    result = gates.evaluate_gates(_base_metrics(), has_regime_probs=True)
    assert result["calibration_20d_within_bound"] is True


def test_calibration_gate_undefined_slope_falls_back_to_citl():
    # constant-p forecaster (e.g. Climatology): slope undefined, citl CI
    # contains 0 -> passes on calibration-in-the-large alone
    m = _base_metrics(
        cal_20d_down_slope_defined=False,
        cal_20d_down_a_lo=np.nan, cal_20d_down_a_hi=np.nan,
        cal_20d_down_b_lo=np.nan, cal_20d_down_b_hi=np.nan,
        cal_20d_down_citl_lo=-0.01, cal_20d_down_citl_hi=0.01,
    )
    result = gates.evaluate_gates(m, has_regime_probs=True)
    assert result["calibration_20d_within_bound"] is True


def test_calibration_gate_undefined_slope_fails_on_bad_citl():
    m = _base_metrics(
        cal_20d_down_slope_defined=False,
        cal_20d_down_a_lo=np.nan, cal_20d_down_a_hi=np.nan,
        cal_20d_down_b_lo=np.nan, cal_20d_down_b_hi=np.nan,
        cal_20d_down_citl_lo=0.05, cal_20d_down_citl_hi=0.10,
    )
    result = gates.evaluate_gates(m, has_regime_probs=True)
    assert result["calibration_20d_within_bound"] is False


def test_calibration_gate_partial_nan_still_evaluates_available_bands():
    m = _base_metrics(cal_20d_down_slope_defined=None, cal_20d_flat_b_lo=1.5, cal_20d_flat_b_hi=2.0)
    result = gates.evaluate_gates(m, has_regime_probs=True)
    assert result["calibration_20d_within_bound"] is False


def test_knob_perturbation_requires_both_kappa_and_drop():
    m = _base_metrics(knob_perturbation_min_kappa=0.5, knob_perturbation_max_skill_drop=0.10)
    result = gates.evaluate_gates(m, has_regime_probs=True)
    assert result["knob_perturbation_within_bound"] is False  # kappa too low


def test_gate_thresholds_single_source_of_truth():
    assert gates.GATE_THRESHOLDS["flips_per_year_min"] == 2.0
    assert gates.GATE_THRESHOLDS["flips_per_year_max"] == 8.0
    assert gates.GATE_THRESHOLDS["median_lag_le"] == 15.0
