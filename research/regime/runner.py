"""Ties the harness together: walk-forward fit/predict, scoring, stability,
lag, calibration plots, and one append-only line per experiment.

run_experiment() is the single entry point every candidate model uses.
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from . import data, features, gates, lag, scoring, splits, stability, targets
from .models.base import Climatology, HORIZONS

REGIME_COLS = ["regime_p_down", "regime_p_chop", "regime_p_up"]
EMBARGO = 60  # covers the longest target window (truth_regime, dd_60) for every fit

PKG_DIR = Path(__file__).resolve().parent
EXPERIMENTS_LOG = PKG_DIR / "experiments.jsonl"

ERAS = {
    "2018_19": (2018, 2019),
    "2020_22": (2020, 2021, 2022),
    "2023_24": (2023, 2024),
}


def _git_commit_hash() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=PKG_DIR, stderr=subprocess.DEVNULL
        ).decode().strip()
    except Exception:
        return "unknown"


def _out_root() -> Path:
    return Path(os.environ.get("REGIME_OUT", str(Path(__file__).resolve().parents[1] / "output/regime")))


def _hash_config(knobs: dict, feature_config: dict) -> str:
    payload = json.dumps({"knobs": knobs, "feature_config": feature_config}, sort_keys=True, default=str)
    return hashlib.sha1(payload.encode()).hexdigest()[:10]


def make_exp_id(model_name: str, knobs: dict, feature_config: dict) -> str:
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"{ts}_{model_name}_{_hash_config(knobs, feature_config)}"


def run_walkforward(model_factory, knobs: dict, X: pd.DataFrame, Y: pd.DataFrame,
                     embargo: int = EMBARGO, open_lockbox: bool = False, window_config=None):
    """Fit/predict across all walk-forward folds. Returns (model_pred, clim_pred,
    folds) where clim_pred is a freshly-fit-per-fold B0 Climatology used as the
    out-of-sample skill reference (never the same object as the model, even
    when the model under test IS Climatology).

    `window_config` is a data.WINDOW_CONFIGS name or dict (default: "default",
    2015 dev_start / 2018-2024 test years) -- see data.get_window_config.

    fit() only ever sees the fold's train rows. predict() is given every row
    of X from the very first available row (including pre-config warm-up)
    through the END of the fold's test year -- not just the test slice -- so
    a stateful model (HMM/jump-model filtering) can carry its state across
    the fold boundary instead of restarting cold every January 1st. The
    output is then sliced down to the test dates only. Only rows through the
    current fold's test_end are ever passed, so no later fold's test data
    can leak into an earlier fold's predict() call.
    """
    folds = splits.get_walkforward_folds(X.index, embargo=embargo, config=window_config)
    model_chunks, clim_chunks = [], []
    for fold in folds:
        train_idx, test_idx = fold["train"], fold["test"]
        data.assert_no_lockbox(train_idx, open_lockbox=open_lockbox)
        data.assert_no_lockbox(test_idx, open_lockbox=open_lockbox)
        X_train, Y_train = X.loc[train_idx], Y.loc[train_idx]

        test_end = test_idx.max()
        predict_idx = X.index[X.index <= test_end]
        data.assert_no_lockbox(predict_idx, open_lockbox=open_lockbox)
        X_predict_input = X.loc[predict_idx]

        model = model_factory(knobs)
        model.fit(X_train, Y_train)
        model_chunks.append(model.predict(X_predict_input).loc[test_idx])

        clim = Climatology()
        clim.fit(X_train, Y_train)
        clim_chunks.append(clim.predict(X_predict_input).loc[test_idx])

    model_pred = pd.concat(model_chunks).sort_index() if model_chunks else pd.DataFrame()
    clim_pred = pd.concat(clim_chunks).sort_index() if clim_chunks else pd.DataFrame()
    return model_pred, clim_pred, folds


def _binary_indicator(y: np.ndarray, level) -> np.ndarray:
    """1.0/0.0 indicator that y == level, preserving NaN.

    `(y == level).astype(float)` on a NaN-containing array silently turns
    every NaN into 0.0 (since `nan == level` is False) -- which then scores
    a lockbox-masked or otherwise-missing target as a confirmed "did not
    happen", biasing ECE and reliability diagrams. This keeps NaN as NaN so
    downstream scoring functions (which already drop NaN rows) exclude them.
    """
    y = np.asarray(y, dtype=float)
    return np.where(np.isnan(y), np.nan, (y == level).astype(float))


def calibration_targets(model_pred: pd.DataFrame, Y: pd.DataFrame) -> dict:
    """Every (forecast probability column, binary outcome) pair that gets a
    calibration score: bands down/flat/up at each horizon, the drawdown
    probability at each horizon, and the 20d vol terciles. Returns
    {target_name: (p, y_binary)}, y_binary NaN wherever the underlying
    target is NaN (see _binary_indicator).
    """
    idx = model_pred.index
    out = {}
    for h in HORIZONS:
        band_y = Y.loc[idx, f"band_{h}"].to_numpy()
        for level, lab in ((0, "down"), (1, "flat"), (2, "up")):
            out[f"{h}d_{lab}"] = (model_pred[f"p_{lab}_{h}"].to_numpy(), _binary_indicator(band_y, level))
        dd_y = Y.loc[idx, f"dd_{h}"].to_numpy()
        out[f"dd_{h}d"] = (model_pred[f"p_dd_{h}"].to_numpy(), np.asarray(dd_y, dtype=float))
    vol_y = Y.loc[idx, "vol_tercile_20"].to_numpy()
    for level, lab in ((0, "low"), (1, "mid"), (2, "high")):
        out[f"vol_{lab}_20d"] = (model_pred[f"p_vol_{lab}_20"].to_numpy(), _binary_indicator(vol_y, level))
    return out


CALIBRATION_SEED = 42


def _target_horizon(name: str) -> int:
    """The horizon (5/20/60) a calibration_targets key belongs to, so its
    block-bootstrap block size can match (block = max(h, 20)).
    """
    if name.startswith("dd_"):
        return int(name.split("_")[1].rstrip("d"))
    if name.startswith("vol_"):
        return 20
    return int(name.split("d_")[0])


def score_calibration(model_pred: pd.DataFrame, Y: pd.DataFrame) -> dict:
    """Calibration for every target in calibration_targets. Two things per
    target:

    - cox_calibration_test (scoring.py): the GATE-relevant test. A
      block-bootstrap (block = max(h, 20), respecting the target's own
      overlap window) logistic-calibration intercept/slope with CIs. Keys
      like 'cal_20d_up_a', '..._a_lo', '..._a_hi', '..._b', '..._b_lo',
      '..._b_hi', '..._slope_defined', '..._citl', '..._citl_lo', '..._citl_hi'.
    - consistency_resampling_ece (scoring.py): DIAGNOSTIC ONLY, not gated
      (see CHANGELOG.md -- its independent-per-day null is too narrow for
      overlapping targets). Keys like 'ece_20d_up', '..._null_pct', '..._pvalue'.
    """
    metrics = {}
    percentile = gates.GATE_THRESHOLDS["ece_consistency_percentile"]
    for name, (p, y_binary) in calibration_targets(model_pred, Y).items():
        h = _target_horizon(name)
        block = max(h, 20)

        cox = scoring.cox_calibration_test(
            p, y_binary, block=block, n_reps=1000, seed=CALIBRATION_SEED,
            ci=gates.GATE_THRESHOLDS["cox_calibration_ci"],
        )
        metrics[f"cal_{name}_slope_defined"] = cox["slope_defined"]
        metrics[f"cal_{name}_a"] = cox["a"]
        metrics[f"cal_{name}_a_lo"] = cox["a_lo"]
        metrics[f"cal_{name}_a_hi"] = cox["a_hi"]
        metrics[f"cal_{name}_b"] = cox["b"]
        metrics[f"cal_{name}_b_lo"] = cox["b_lo"]
        metrics[f"cal_{name}_b_hi"] = cox["b_hi"]
        metrics[f"cal_{name}_citl"] = cox["citl"]
        metrics[f"cal_{name}_citl_lo"] = cox["citl_lo"]
        metrics[f"cal_{name}_citl_hi"] = cox["citl_hi"]

        ece_res = scoring.consistency_resampling_ece(
            p, y_binary, n_reps=1000, seed=CALIBRATION_SEED, percentile=percentile
        )
        metrics[f"ece_{name}"] = ece_res["observed_ece"]
        metrics[f"ece_{name}_null_pct"] = ece_res["null_ece_pct"]
        metrics[f"ece_{name}_pvalue"] = ece_res["p_value"]
    return metrics


def _score_horizon(model_pred, clim_pred, Y, h, block=None):
    idx = model_pred.index
    y = Y.loc[idx, f"band_{h}"].to_numpy()
    model_probs = model_pred[[f"p_down_{h}", f"p_flat_{h}", f"p_up_{h}"]].to_numpy()
    clim_probs = clim_pred[[f"p_down_{h}", f"p_flat_{h}", f"p_up_{h}"]].to_numpy()
    rps_m = scoring.rps_per_day(model_probs, y)
    rps_c = scoring.rps_per_day(clim_probs, y)
    blk = block or max(h, 20)
    ci = scoring.rps_skill_ci(rps_m, rps_c, block=blk)
    out = {
        f"rps_skill_{h}": ci["point"],
        f"rps_skill_{h}_ci_lo": ci["lo"],
        f"rps_skill_{h}_ci_hi": ci["hi"],
        f"log_loss_{h}": scoring.log_loss_multiclass(model_probs, y),
    }
    dd_y = Y.loc[idx, f"dd_{h}"].to_numpy()
    out[f"brier_dd_{h}"] = scoring.brier_binary(model_pred[f"p_dd_{h}"].to_numpy(), dd_y)
    return out, rps_m, rps_c


def score_predictions(model_pred: pd.DataFrame, clim_pred: pd.DataFrame, Y: pd.DataFrame,
                       eras: dict | None = None) -> dict:
    eras = eras if eras is not None else ERAS
    metrics = {}
    rps_by_h = {}
    for h in HORIZONS:
        m, rps_m, rps_c = _score_horizon(model_pred, clim_pred, Y, h)
        metrics.update(m)
        rps_by_h[h] = (rps_m, rps_c)

    idx = model_pred.index
    metrics.update(score_calibration(model_pred, Y))

    vol_y = Y.loc[idx, "vol_tercile_20"].to_numpy()
    vol_probs = model_pred[["p_vol_low_20", "p_vol_mid_20", "p_vol_high_20"]].to_numpy()
    metrics["brier_vol_tercile_20"] = scoring.brier_multiclass(vol_probs, vol_y)
    metrics["log_loss_vol_tercile_20"] = scoring.log_loss_multiclass(vol_probs, vol_y)

    # per-era breakdown, 20d primary + transitions-per-era context (spec 5.9)
    era_metrics = {}
    for era_name, years in eras.items():
        mask = idx.year.isin(years)
        if mask.sum() == 0:
            continue
        sub_model = model_pred.loc[mask]
        sub_clim = clim_pred.loc[mask]
        era_row = {}
        for h in HORIZONS:
            m, _, _ = _score_horizon(sub_model, sub_clim, Y, h)
            era_row.update(m)
        truth_sub = Y.loc[idx[mask], "truth_regime"]
        era_row["n_truth_transitions"] = int((truth_sub.dropna().diff().fillna(0) != 0).sum())
        era_row["n_days"] = int(mask.sum())
        era_metrics[era_name] = era_row
    metrics["_era"] = era_metrics
    metrics["_rps_by_h"] = rps_by_h
    return metrics


def score_stability_and_lag(model_pred: pd.DataFrame, Y: pd.DataFrame) -> tuple[dict, pd.Series | None]:
    metrics = {}
    has_regime_probs = bool(model_pred[REGIME_COLS].notna().any().any())
    if not has_regime_probs:
        return metrics, None

    labels = stability.labels_from_probs(model_pred)
    metrics["flips_per_year"] = stability.flips_per_year(labels)
    metrics["whipsaw_rate"] = stability.whipsaw_rate(labels)
    metrics["mean_duration"] = stability.mean_duration(labels)
    metrics["prob_jump_share"] = stability.prob_jump_share(model_pred)

    truth = Y.loc[model_pred.index, "truth_regime"]
    model_codes = stability.labels_to_truth_codes(labels)
    lag_df = lag.detection_lag(model_codes, truth)
    metrics.update(lag.median_lag_by_direction(lag_df, up_value=2, down_value=0))
    metrics["median_lag"] = float(lag_df["lag"].median()) if len(lag_df) else np.nan
    return metrics, labels


def _draw_reliability(ax, p: np.ndarray, y_binary: np.ndarray, title: str) -> None:
    diag = scoring.reliability_diagram_data(p, y_binary)
    ax.plot([0, 1], [0, 1], "k--", lw=1, label="perfect")
    valid = diag["count"] > 0
    if valid.any():
        yerr = np.vstack([
            (diag.loc[valid, "obs_freq"] - diag.loc[valid, "ci_lo"]).to_numpy(),
            (diag.loc[valid, "ci_hi"] - diag.loc[valid, "obs_freq"]).to_numpy(),
        ])
        # Wilson bounds can land ~1e-17 past obs_freq (e.g. zero hits); matplotlib rejects negative yerr
        yerr = np.clip(yerr, 0.0, None)
        ax.errorbar(diag.loc[valid, "mean_pred"], diag.loc[valid, "obs_freq"],
                    yerr=yerr, fmt="o", capsize=3, label="observed")
    ax.set_xlabel("predicted probability")
    ax.set_ylabel("observed frequency")
    ax.set_title(title)
    ax.legend(fontsize=8)


def _make_reliability_plots(model_pred: pd.DataFrame, Y: pd.DataFrame, out_dir: Path) -> list[str]:
    """Reliability diagrams for a representative slice of the full
    calibration coverage (score_calibration covers every band/horizon/dd/vol
    target; plotting all of them isn't useful, so this saves the ones the
    review specifically asked for): 20d down/flat/up as one 3-panel figure,
    dd_20, dd_60, 5d up, 60d up, and 20d vol-high.
    """
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    out_dir.mkdir(parents=True, exist_ok=True)
    paths = []
    targets_map = calibration_targets(model_pred, Y)

    fig, axes = plt.subplots(1, 3, figsize=(14, 5))
    for ax, lab in zip(axes, ("down", "flat", "up")):
        p, yb = targets_map[f"20d_{lab}"]
        _draw_reliability(ax, p, yb, f"20d {lab}")
    path = out_dir / "reliability_20d_bands.png"
    fig.savefig(path, dpi=100, bbox_inches="tight")
    plt.close(fig)
    paths.append(str(path))

    singles = [
        ("dd_20d", "reliability_dd_20.png", "20d drawdown"),
        ("dd_60d", "reliability_dd_60.png", "60d drawdown"),
        ("5d_up", "reliability_up_5.png", "5d up"),
        ("60d_up", "reliability_up_60.png", "60d up"),
        ("vol_high_20d", "reliability_vol_high_20.png", "20d vol high"),
    ]
    for target_name, fname, title in singles:
        p, yb = targets_map[target_name]
        fig, ax = plt.subplots(figsize=(5, 5))
        _draw_reliability(ax, p, yb, title)
        path = out_dir / fname
        fig.savefig(path, dpi=100, bbox_inches="tight")
        plt.close(fig)
        paths.append(str(path))

    return paths


def run_experiment(model_factory, knobs: dict | None = None, feature_config: dict | None = None,
                    tag: str = "", close: pd.Series | None = None,
                    run_perturbations: bool = True, seed: int = 0, window_config="default") -> dict:
    """Full pipeline for one candidate: walk-forward -> score -> stability ->
    lag -> gates -> one appended experiments.jsonl line. Returns the log row.

    `window_config` is a data.WINDOW_CONFIGS name or dict (default: "default").
    """
    knobs = dict(knobs or {})
    feature_config = dict(feature_config or {})
    cfg = data.get_window_config(window_config)

    if close is None:
        close = data.load_close(start=cfg["warmup_start"])

    X = features.build_features(close, **feature_config)
    Y = targets.build_targets(close, open_lockbox=False)

    model_pred, clim_pred, folds = run_walkforward(model_factory, knobs, X, Y, window_config=cfg)

    probe_model = model_factory(knobs)
    model_name = getattr(probe_model, "name", "model")

    metrics = score_predictions(model_pred, clim_pred, Y, eras=cfg["eras"])
    era_metrics = metrics.pop("_era")
    metrics.pop("_rps_by_h", None)
    stab_metrics, labels = score_stability_and_lag(model_pred, Y)
    metrics.update(stab_metrics)
    has_regime_probs = labels is not None

    metrics["knob_perturbation_min_kappa"] = np.nan
    metrics["knob_perturbation_max_skill_drop"] = np.nan
    metrics["data_perturbation_agreement"] = np.nan

    if run_perturbations and has_regime_probs:
        base_skill_20 = metrics.get("rps_skill_20", np.nan)
        variants = stability.perturb_numeric_knobs(knobs)
        perturbed_runs = []
        for v in variants:
            mp, cp, _ = run_walkforward(model_factory, v["knobs"], X, Y, window_config=cfg)
            if mp[REGIME_COLS].notna().any().any():
                lab = stability.labels_from_probs(mp)
                y20 = Y.loc[mp.index, "band_20"].to_numpy()
                rm = scoring.rps_per_day(mp[["p_down_20", "p_flat_20", "p_up_20"]].to_numpy(), y20)
                rc = scoring.rps_per_day(cp[["p_down_20", "p_flat_20", "p_up_20"]].to_numpy(), y20)
                skill = scoring.rps_skill(rm, rc)
                perturbed_runs.append({"knob": v["knob"], "factor": v["factor"], "labels": lab, "skill": skill})
        if perturbed_runs:
            kp = stability.knob_perturbation(knobs, labels, base_skill_20, perturbed_runs)
            metrics["knob_perturbation_min_kappa"] = float(kp["kappa"].min())
            metrics["knob_perturbation_max_skill_drop"] = float(kp["skill_drop"].max())

        perturbed_labels = []
        for seed_i in range(5):
            rng = np.random.default_rng(9000 + seed_i)
            noisy = close * (1 + rng.normal(0, 0.001, size=len(close)))
            noisy = pd.Series(noisy.to_numpy(), index=close.index, name="close")
            X_n = features.build_features(noisy, **feature_config)
            Y_n = targets.build_targets(noisy, open_lockbox=False)
            mp_n, _, _ = run_walkforward(model_factory, knobs, X_n, Y_n, window_config=cfg)
            if mp_n[REGIME_COLS].notna().any().any():
                perturbed_labels.append(stability.labels_from_probs(mp_n))
        if perturbed_labels:
            metrics["data_perturbation_agreement"] = stability.data_perturbation_agreement(labels, perturbed_labels)

    gate_results = gates.evaluate_gates(metrics, has_regime_probs)

    exp_id = make_exp_id(model_name, knobs, feature_config)
    out_dir = _out_root() / exp_id
    out_dir.mkdir(parents=True, exist_ok=True)
    preds_path = out_dir / "preds.parquet"
    model_pred.to_parquet(preds_path)
    plot_paths = _make_reliability_plots(model_pred, Y, out_dir / "plots")

    log_row = {
        "exp_id": exp_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "git_commit": _git_commit_hash(),
        "model": model_name,
        "tag": tag,
        "knobs": knobs,
        "n_fitted_knobs": probe_model.n_fitted_knobs,
        "feature_config": feature_config,
        "data_windows": {
            "window_config": window_config if isinstance(window_config, str) else "custom",
            "warmup_start": str(cfg["warmup_start"].date()),
            "dev_start": str(cfg["dev_start"].date()),
            "dev_end": str(pd.Timestamp(f"{cfg['last_test_year']}-12-31").date()),
            "lockbox_start": str(data.LOCKBOX_START.date()),
            "test_years": list(range(cfg["first_test_year"], cfg["last_test_year"] + 1)),
        },
        "lockbox_opened": False,
        "gate_thresholds": gates.GATE_THRESHOLDS,
        "metrics": {k: (None if isinstance(v, float) and np.isnan(v) else v) for k, v in metrics.items()},
        "era_metrics": era_metrics,
        "gates": gate_results,
        "gates_all_pass": gates.all_pass(gate_results),
        "n_oos_days": int(len(model_pred)),
        "preds_path": str(preds_path),
        "plot_paths": plot_paths,
    }
    _append_log(log_row)
    return log_row


def _append_log(row: dict) -> None:
    EXPERIMENTS_LOG.parent.mkdir(parents=True, exist_ok=True)
    with open(EXPERIMENTS_LOG, "a") as f:
        f.write(json.dumps(row, default=str) + "\n")
