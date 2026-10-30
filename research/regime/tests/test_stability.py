import numpy as np
import pandas as pd
import pytest

from research.regime import stability


def _labels(values):
    dates = pd.bdate_range("2015-01-01", periods=len(values))
    return pd.Series(values, index=dates)


def test_flips_per_year_hand_computed():
    # 10 rows, 3 flips -> flips_per_year = 3 / (10/252) = 75.6
    labels = _labels(["up", "up", "down", "down", "down", "up", "up", "chop", "chop", "chop"])
    fpy = stability.flips_per_year(labels)
    assert fpy == pytest.approx(3 / (10 / 252))


def test_flips_per_year_no_flips():
    labels = _labels(["up"] * 10)
    assert stability.flips_per_year(labels) == 0.0


def test_whipsaw_rate_hand_computed():
    # flip up->down at pos2, then back to up at pos4 (within window=5) -> reversed
    # flip up->chop at pos6, never returns to up within 5 rows -> not reversed
    labels = _labels(["up", "up", "down", "down", "up", "up", "chop", "chop", "chop", "chop"])
    # flips: pos2 (up->down), pos4 (down->up), pos6 (up->chop) = 3 flips
    wr = stability.whipsaw_rate(labels, window=5)
    # flip@2: pre=up, window=labels[3:8]=[down,up,up,chop,chop] contains 'up' (pre-flip value) -> reversed
    # flip@4: pre=down, window=labels[5:10]=[up,chop,chop,chop,chop] no 'down' -> not reversed
    # flip@6: pre=up, window=labels[7:10]=[chop,chop,chop] no 'up' -> not reversed
    assert wr == pytest.approx(1 / 3)


def test_mean_duration_hand_computed():
    # runs: up(3), down(2), chop(5) -> mean = (3+2+5)/3
    labels = _labels(["up", "up", "up", "down", "down", "chop", "chop", "chop", "chop", "chop"])
    assert stability.mean_duration(labels) == pytest.approx((3 + 2 + 5) / 3)


def test_prob_jump_share_hand_computed():
    dates = pd.bdate_range("2015-01-01", periods=4)
    pred = pd.DataFrame({
        "regime_p_down": [0.1, 0.1, 0.6, 0.6],
        "regime_p_chop": [0.8, 0.8, 0.3, 0.3],
        "regime_p_up": [0.1, 0.1, 0.1, 0.1],
    }, index=dates)
    # day1->day2: no change (jump 0). day2->day3: |0.6-0.1|=0.5>0.3 jump. day3->day4: 0 jump.
    # of 3 transitions, 1 is a jump -> share = 1/3
    assert stability.prob_jump_share(pred, threshold=0.3) == pytest.approx(1 / 3)


def test_cohens_kappa_perfect_agreement():
    a = _labels(["up", "down", "chop", "up", "down"])
    assert stability.cohens_kappa(a, a) == pytest.approx(1.0)


def test_cohens_kappa_hand_computed():
    # 2 categories, simple confusion: agree 3/4 times, with balanced marginals
    a = _labels(["up", "up", "down", "down"])
    b = _labels(["up", "down", "down", "down"])
    # po = 3/4 = 0.75
    # pa(up)=0.5, pa(down)=0.5 ; pb(up)=0.25, pb(down)=0.75
    # pe = 0.5*0.25 + 0.5*0.75 = 0.125+0.375=0.5
    # kappa = (0.75-0.5)/(1-0.5) = 0.5
    assert stability.cohens_kappa(a, b) == pytest.approx(0.5)


def test_perturb_numeric_knobs_rounds_ints_and_floors_at_one():
    knobs = {"k": 2, "threshold": 0.5, "mode": "fast"}
    variants = stability.perturb_numeric_knobs(knobs, factors=(0.1,))
    k_variant = [v for v in variants if v["knob"] == "k"][0]
    assert k_variant["knobs"]["k"] == 1  # round(2*0.1)=0 -> floored to 1
    assert all(v["knob"] != "mode" for v in variants)  # non-numeric skipped


def test_data_perturbation_agreement_hand_computed():
    base = _labels(["up", "down", "chop", "up"])
    seed1 = _labels(["up", "down", "chop", "down"])  # 3/4 agree
    seed2 = _labels(["up", "up", "chop", "up"])        # 3/4 agree
    agreement = stability.data_perturbation_agreement(base, [seed1, seed2])
    assert agreement == pytest.approx(0.75)


def test_refit_stability_hand_computed():
    a = _labels(["up", "down", "chop"])
    b = _labels(["up", "down", "chop"])  # identical -> kappa 1
    c = _labels(["up", "up", "up"])  # different
    result = stability.refit_stability([a, b, c])
    kappa_ab = stability.cohens_kappa(a, b)
    kappa_ac = stability.cohens_kappa(a, c)
    kappa_bc = stability.cohens_kappa(b, c)
    assert result == pytest.approx(np.nanmean([kappa_ab, kappa_ac, kappa_bc]))
