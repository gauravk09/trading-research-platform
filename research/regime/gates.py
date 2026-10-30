"""Pass/fail gates (spec Section 4). Thresholds live in ONE dict so they are
visible and changeable in a single place — any change must be logged (the
runner records the GATE_THRESHOLDS dict verbatim in every experiments.jsonl
row, so a threshold edit shows up as a diff in the log history).

Regime-dependent gates (flip rate, whipsaw, duration, prob jump, lag) are
N/A (None) for models that don't produce regime probabilities at all.
"""
from __future__ import annotations

import math

GATE_THRESHOLDS = {
    "rps_skill_20d_ci_lower_gt": 0.0,
    # CHANGED 2026-09-26 (see CHANGELOG.md, two entries): dropped the
    # pre-registered fixed "ECE <= 0.05" bound, then dropped its first
    # replacement too. History:
    #   1. Fixed "ECE <= 0.05": the synthetic Oracle (knows the true regime
    #      state) failed it purely from finite-sample noise.
    #   2. Independent-per-day consistency resampling (Broecker & Smith
    #      2007): the fix for #1, but its null draws each day's outcome
    #      independently, which ignores the autocorrelation that OVERLAPPING
    #      20d/60d targets introduce (day t's target shares most of its
    #      window with day t+1's). That makes the null too NARROW, and it
    #      still rejected the Oracle -- not a smaller version of the same
    #      problem, a different bug.
    #   3. Block-bootstrap Cox (1958) logistic calibration test (current):
    #      resamples (p, y) pairs in contiguous blocks instead of
    #      independent days, respecting the overlap. See
    #      scoring.cox_calibration_test. "ece_consistency_percentile" is kept
    #      only because consistency_resampling_ece is still computed and
    #      logged as a reported diagnostic (not a gate).
    "ece_consistency_percentile": 95.0,
    "cox_calibration_ci": 0.95,
    "flips_per_year_min": 2.0,
    "flips_per_year_max": 8.0,
    "whipsaw_rate_lt": 0.20,
    "mean_duration_ge": 20.0,
    "knob_perturbation_kappa_ge": 0.8,
    "knob_perturbation_skill_drop_lt": 0.25,
    "prob_jump_share_lt": 0.05,
    "data_perturbation_agreement_ge": 0.95,
    "median_lag_le": 15.0,
}


def _nan_safe(x):
    return x is None or (isinstance(x, float) and math.isnan(x))


def evaluate_gates(metrics: dict, has_regime_probs: bool) -> dict:
    """metrics: flat dict with keys matching what runner.py computes, e.g.
    'rps_skill_20_ci_lo', 'ece_band_up_20', 'flips_per_year', 'whipsaw_rate',
    'mean_duration', 'knob_perturbation_min_kappa', 'knob_perturbation_max_skill_drop',
    'prob_jump_share', 'data_perturbation_agreement', 'median_lag'.
    Returns {gate_name: True/False/None}. None means not applicable.
    """
    g = {}

    v = metrics.get("rps_skill_20_ci_lo")
    g["rps_skill_20d_ci_lower_positive"] = (
        None if _nan_safe(v) else v > GATE_THRESHOLDS["rps_skill_20d_ci_lower_gt"]
    )

    # Block-bootstrap Cox calibration gate on the 20d bands (down/flat/up):
    # passes only if EVERY band's calibration is good -- the worst-performing
    # band determines the gate. A band with a defined slope passes if its
    # intercept CI contains 0 AND its slope CI contains 1 (both from
    # scoring.cox_calibration_test's moving-block bootstrap). A band with an
    # undefined slope (constant p, e.g. Climatology) falls back to
    # calibration-in-the-large only: passes if its citl CI contains 0.
    band_checks = []
    for lab in ("down", "flat", "up"):
        slope_defined = metrics.get(f"cal_20d_{lab}_slope_defined")
        if slope_defined is None:
            band_checks.append(None)
            continue
        if slope_defined:
            a_lo, a_hi = metrics.get(f"cal_20d_{lab}_a_lo"), metrics.get(f"cal_20d_{lab}_a_hi")
            b_lo, b_hi = metrics.get(f"cal_20d_{lab}_b_lo"), metrics.get(f"cal_20d_{lab}_b_hi")
            if any(_nan_safe(v) for v in (a_lo, a_hi, b_lo, b_hi)):
                band_checks.append(None)
            else:
                band_checks.append((a_lo <= 0 <= a_hi) and (b_lo <= 1 <= b_hi))
        else:
            citl_lo = metrics.get(f"cal_20d_{lab}_citl_lo")
            citl_hi = metrics.get(f"cal_20d_{lab}_citl_hi")
            if _nan_safe(citl_lo) or _nan_safe(citl_hi):
                band_checks.append(None)
            else:
                band_checks.append(citl_lo <= 0 <= citl_hi)
    valid_checks = [c for c in band_checks if c is not None]
    g["calibration_20d_within_bound"] = None if not valid_checks else all(valid_checks)

    if not has_regime_probs:
        g["flips_per_year_in_range"] = None
        g["whipsaw_rate_within_bound"] = None
        g["mean_duration_within_bound"] = None
        g["prob_jump_share_within_bound"] = None
        g["median_lag_within_bound"] = None
    else:
        v = metrics.get("flips_per_year")
        g["flips_per_year_in_range"] = (
            None if _nan_safe(v)
            else GATE_THRESHOLDS["flips_per_year_min"] <= v <= GATE_THRESHOLDS["flips_per_year_max"]
        )
        v = metrics.get("whipsaw_rate")
        g["whipsaw_rate_within_bound"] = None if _nan_safe(v) else v < GATE_THRESHOLDS["whipsaw_rate_lt"]
        v = metrics.get("mean_duration")
        g["mean_duration_within_bound"] = None if _nan_safe(v) else v >= GATE_THRESHOLDS["mean_duration_ge"]
        v = metrics.get("prob_jump_share")
        g["prob_jump_share_within_bound"] = None if _nan_safe(v) else v < GATE_THRESHOLDS["prob_jump_share_lt"]
        v = metrics.get("median_lag")
        g["median_lag_within_bound"] = None if _nan_safe(v) else v <= GATE_THRESHOLDS["median_lag_le"]

    kappa = metrics.get("knob_perturbation_min_kappa")
    drop = metrics.get("knob_perturbation_max_skill_drop")
    if _nan_safe(kappa) and _nan_safe(drop):
        g["knob_perturbation_within_bound"] = None
    else:
        ok_kappa = (not _nan_safe(kappa)) and kappa >= GATE_THRESHOLDS["knob_perturbation_kappa_ge"]
        ok_drop = (not _nan_safe(drop)) and drop < GATE_THRESHOLDS["knob_perturbation_skill_drop_lt"]
        g["knob_perturbation_within_bound"] = bool(ok_kappa and ok_drop)

    v = metrics.get("data_perturbation_agreement")
    g["data_perturbation_within_bound"] = (
        None if _nan_safe(v) else v >= GATE_THRESHOLDS["data_perturbation_agreement_ge"]
    )

    return g


def all_pass(gate_results: dict) -> bool:
    """True only if every non-N/A gate passed."""
    return all(v for v in gate_results.values() if v is not None)
