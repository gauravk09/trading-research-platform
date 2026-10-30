"""Stability suite (spec Section 4.3). Regime label = argmax of
(regime_p_down, regime_p_chop, regime_p_up), skipped (NaN) if all three are NaN.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

REGIME_COLS = ["regime_p_down", "regime_p_chop", "regime_p_up"]


def labels_from_probs(pred: pd.DataFrame) -> pd.Series:
    probs = pred[REGIME_COLS]
    all_nan = probs.isna().all(axis=1)
    labels = probs.idxmax(axis=1)
    labels[all_nan] = np.nan
    return labels


# Matches targets.TRUTH_DOWN/TRUTH_CHOPPY/TRUTH_UP = 0/1/2, so model labels
# and hindsight truth labels can be compared directly (used by lag.py).
LABEL_TO_TRUTH_CODE = {"regime_p_down": 0, "regime_p_chop": 1, "regime_p_up": 2}


def labels_to_truth_codes(labels: pd.Series) -> pd.Series:
    return labels.map(LABEL_TO_TRUTH_CODE)


def flips_per_year(labels: pd.Series) -> float:
    labels = labels.dropna()
    if len(labels) < 2:
        return np.nan
    n_flips = int((labels.to_numpy()[1:] != labels.to_numpy()[:-1]).sum())
    years = len(labels) / 252.0
    if years == 0:
        return np.nan
    return n_flips / years


def _flip_positions(labels: pd.Series):
    vals = labels.to_numpy()
    return [i for i in range(1, len(vals)) if vals[i] != vals[i - 1]]


def whipsaw_rate(labels: pd.Series, window: int = 5) -> float:
    """Share of flips that are reversed (label returns to the pre-flip value)
    within `window` rows of the flip.
    """
    labels = labels.dropna().reset_index(drop=True)
    flips = _flip_positions(labels)
    if len(flips) == 0:
        return np.nan
    vals = labels.to_numpy()
    reversed_count = 0
    for i in flips:
        pre_val = vals[i - 1]
        post_val = vals[i]
        lookahead = vals[i + 1 : i + 1 + window]
        if pre_val in lookahead:
            reversed_count += 1
    return reversed_count / len(flips)


def mean_duration(labels: pd.Series) -> float:
    labels = labels.dropna().reset_index(drop=True)
    if len(labels) == 0:
        return np.nan
    vals = labels.to_numpy()
    durations = []
    run = 1
    for i in range(1, len(vals)):
        if vals[i] == vals[i - 1]:
            run += 1
        else:
            durations.append(run)
            run = 1
    durations.append(run)
    return float(np.mean(durations))


def prob_jump_share(pred: pd.DataFrame, threshold: float = 0.3) -> float:
    probs = pred[REGIME_COLS]
    valid_rows = probs.notna().all(axis=1)
    probs = probs[valid_rows]
    if len(probs) < 2:
        return np.nan
    deltas = probs.diff().abs().max(axis=1)
    deltas = deltas.iloc[1:]
    return float((deltas > threshold).mean())


def cohens_kappa(a: pd.Series, b: pd.Series) -> float:
    """Simple Cohen's kappa on paired categorical labels, common index."""
    idx = a.index.intersection(b.index)
    a2, b2 = a.loc[idx], b.loc[idx]
    valid = a2.notna() & b2.notna()
    a2, b2 = a2[valid], b2[valid]
    n = len(a2)
    if n == 0:
        return np.nan
    po = float((a2.to_numpy() == b2.to_numpy()).mean())
    cats = sorted(set(a2.unique()) | set(b2.unique()))
    pa = {c: (a2 == c).mean() for c in cats}
    pb = {c: (b2 == c).mean() for c in cats}
    pe = sum(pa[c] * pb[c] for c in cats)
    if pe == 1:
        return 1.0
    return (po - pe) / (1 - pe)


def knob_perturbation(base_knobs: dict, base_labels: pd.Series, base_skill: float,
                       perturbed_runs: list[dict]) -> pd.DataFrame:
    """perturbed_runs: list of {"knob": name, "factor": f, "labels": Series, "skill": float}.
    Returns a table of kappa vs base and skill-drop fraction per perturbation.
    """
    rows = []
    for run in perturbed_runs:
        kappa = cohens_kappa(base_labels, run["labels"])
        if base_skill and not np.isnan(base_skill) and base_skill != 0:
            skill_drop = (base_skill - run["skill"]) / abs(base_skill)
        else:
            skill_drop = np.nan
        rows.append({
            "knob": run["knob"], "factor": run.get("factor"),
            "kappa": kappa, "skill_drop": skill_drop,
        })
    return pd.DataFrame(rows)


def perturb_numeric_knobs(knobs: dict, factors=(0.75, 0.9, 1.1, 1.25)) -> list[dict]:
    """Generate perturbed knob dicts: one numeric knob shifted at a time.
    Ints are rounded and floored at 1; non-numeric knobs are left untouched.
    """
    variants = []
    for key, val in knobs.items():
        if not isinstance(val, (int, float)) or isinstance(val, bool):
            continue
        for f in factors:
            new_val = val * f
            if isinstance(val, int):
                new_val = max(1, int(round(new_val)))
            variant = dict(knobs)
            variant[key] = new_val
            variants.append({"knob": key, "factor": f, "knobs": variant})
    return variants


def data_perturbation_agreement(base_labels: pd.Series, perturbed_labels_list: list[pd.Series]) -> float:
    """Share of days where the label is unchanged, averaged across seeds."""
    agreements = []
    for pl in perturbed_labels_list:
        idx = base_labels.index.intersection(pl.index)
        a, b = base_labels.loc[idx], pl.loc[idx]
        valid = a.notna() & b.notna()
        if valid.sum() == 0:
            continue
        agreements.append(float((a[valid].to_numpy() == b[valid].to_numpy()).mean()))
    return float(np.mean(agreements)) if agreements else np.nan


def refit_stability(label_series_by_seed: list[pd.Series]) -> float:
    """Mean pairwise Cohen's kappa across refits with different seeds."""
    kappas = []
    for i in range(len(label_series_by_seed)):
        for j in range(i + 1, len(label_series_by_seed)):
            kappas.append(cohens_kappa(label_series_by_seed[i], label_series_by_seed[j]))
    return float(np.nanmean(kappas)) if kappas else np.nan
