import json

import numpy as np
import pandas as pd
import pytest

from research.regime import data, features, runner, synthetic, targets
from research.regime.models.base import Climatology, RegimeModel, HORIZONS


def test_long_config_folds_never_touch_lockbox_dates():
    # The "long" config's last_test_year is 2024, so its real folds never
    # reach the lockbox -- confirm that directly.
    df = synthetic.generate_synthetic(n_rows=7600, seed=9, start="1995-01-03")
    close = df["close"]
    assert close.index.max() < data.LOCKBOX_START
    X = features.build_features(close)
    Y = targets.build_targets(close, open_lockbox=False)
    model_pred, clim_pred, folds = runner.run_walkforward(
        lambda k: Climatology(), {}, X, Y, window_config="long"
    )
    assert [f["year"] for f in folds] == list(range(2000, 2025))
    assert model_pred.index.max() < data.LOCKBOX_START


def test_run_walkforward_refuses_any_config_reaching_the_lockbox():
    # The lockbox rule is enforced by run_walkforward for whatever config it
    # is given -- not something only the "default"/"long" configs happen to
    # respect by having last_test_year=2024. A hypothetical config whose
    # last_test_year reaches 2026 must still be refused.
    df = synthetic.generate_synthetic(n_rows=8200, seed=9, start="1995-01-03")
    close = df["close"]
    assert close.index.max() >= data.LOCKBOX_START
    X = features.build_features(close)
    Y = targets.build_targets(close, open_lockbox=False)
    bad_config = dict(data.get_window_config("long"))
    bad_config["last_test_year"] = 2026
    with pytest.raises(data.LockboxError):
        runner.run_walkforward(lambda k: Climatology(), {}, X, Y, window_config=bad_config)


def test_append_log_never_rewrites(tmp_path, monkeypatch):
    log_path = tmp_path / "experiments.jsonl"
    monkeypatch.setattr(runner, "EXPERIMENTS_LOG", log_path)

    runner._append_log({"exp_id": "a", "value": 1})
    first_line_after_first_write = log_path.read_text()

    runner._append_log({"exp_id": "b", "value": 2})
    content = log_path.read_text()

    lines = content.strip().split("\n")
    assert len(lines) == 2
    # the first append's bytes are untouched by the second append
    assert content.startswith(first_line_after_first_write)
    row_a = json.loads(lines[0])
    row_b = json.loads(lines[1])
    assert row_a == {"exp_id": "a", "value": 1}
    assert row_b == {"exp_id": "b", "value": 2}


def test_append_log_survives_many_appends_in_order(tmp_path, monkeypatch):
    log_path = tmp_path / "experiments.jsonl"
    monkeypatch.setattr(runner, "EXPERIMENTS_LOG", log_path)
    for i in range(5):
        runner._append_log({"exp_id": str(i)})
    lines = log_path.read_text().strip().split("\n")
    assert [json.loads(l)["exp_id"] for l in lines] == [str(i) for i in range(5)]


def test_binary_indicator_preserves_nan_for_missing_targets():
    # F1: `(y == level).astype(float)` on a NaN-containing array silently
    # turns every NaN into 0.0 (nan == level is False), which then scores a
    # lockbox-masked/missing target as a confirmed "did not happen".
    y = np.array([0.0, 1.0, 2.0, np.nan, np.nan])
    ind = runner._binary_indicator(y, 2)
    assert ind[2] == 1.0
    assert ind[0] == 0.0 and ind[1] == 0.0
    assert np.isnan(ind[3]) and np.isnan(ind[4])
    # the buggy version this replaces would produce 0.0 here instead of NaN
    buggy = (y == 2).astype(float)
    assert buggy[3] == 0.0 and not np.isnan(buggy[3])


def _full_toy_pred_and_Y(n=20, seed=1):
    """A minimal but COMPLETE pred/Y pair covering every column
    calibration_targets reads, so it can be called without KeyErrors."""
    dates = pd.bdate_range("2015-01-01", periods=n)
    rng = np.random.default_rng(seed)
    cols = {}
    for h in HORIZONS:
        cols[f"p_down_{h}"] = rng.uniform(0.1, 0.4, n)
        cols[f"p_flat_{h}"] = rng.uniform(0.1, 0.4, n)
        cols[f"p_up_{h}"] = rng.uniform(0.1, 0.4, n)
        cols[f"p_dd_{h}"] = rng.uniform(0.05, 0.3, n)
    for lab in ("low", "mid", "high"):
        cols[f"p_vol_{lab}_20"] = rng.uniform(0.2, 0.4, n)
    pred = pd.DataFrame(cols, index=dates)

    y_cols = {}
    for h in HORIZONS:
        band = rng.choice([0.0, 1.0, 2.0], size=n).astype(float)
        band[-3:] = np.nan  # the lockbox-masked tail
        y_cols[f"band_{h}"] = band
        dd = rng.choice([0.0, 1.0], size=n).astype(float)
        dd[-3:] = np.nan
        y_cols[f"dd_{h}"] = dd
    vol = rng.choice([0.0, 1.0, 2.0], size=n).astype(float)
    vol[-3:] = np.nan
    y_cols["vol_tercile_20"] = vol
    Y = pd.DataFrame(y_cols, index=dates)
    return pred, Y


def test_calibration_targets_excludes_nan_band_rows_from_ece():
    from research.regime import scoring

    pred, Y = _full_toy_pred_and_Y(n=20, seed=1)
    targets_map = runner.calibration_targets(pred, Y)
    p, y_binary = targets_map["20d_up"]

    nan_mask = Y["band_20"].isna().to_numpy()
    assert nan_mask.sum() == 3
    assert np.isnan(y_binary[nan_mask]).all()
    assert not np.isnan(y_binary[~nan_mask]).any()

    # ECE computed on this target must be identical whether or not the NaN
    # rows are present, since the scoring functions drop NaN rows -- proving
    # the NaN rows are excluded rather than silently counted as "no".
    ece_with_nan_rows = scoring.ece(p, y_binary)
    keep = ~np.isnan(y_binary)
    ece_manually_dropped = scoring.ece(p[keep], y_binary[keep])
    assert ece_with_nan_rows == pytest.approx(ece_manually_dropped)


def test_calibration_targets_covers_every_band_dd_and_vol_target():
    pred, Y = _full_toy_pred_and_Y(n=20, seed=2)
    targets_map = runner.calibration_targets(pred, Y)
    expected = set()
    for h in HORIZONS:
        for lab in ("down", "flat", "up"):
            expected.add(f"{h}d_{lab}")
        expected.add(f"dd_{h}d")
    for lab in ("low", "mid", "high"):
        expected.add(f"vol_{lab}_20d")
    assert expected == set(targets_map.keys())


def test_score_calibration_logs_observed_null_and_pvalue_per_target():
    pred, Y = _full_toy_pred_and_Y(n=300, seed=3)
    metrics = runner.score_calibration(pred, Y)
    assert "ece_20d_up" in metrics
    assert "ece_20d_up_null_pct" in metrics
    assert "ece_20d_up_pvalue" in metrics
    assert "ece_dd_60d" in metrics
    assert "ece_vol_high_20d" in metrics


def test_make_exp_id_varies_with_knobs():
    id1 = runner.make_exp_id("modelA", {"k": 1}, {})
    id2 = runner.make_exp_id("modelA", {"k": 2}, {})
    assert id1 != id2
    assert "modelA" in id1


class _RunningCountModel(RegimeModel):
    """Toy stateful model: reports, for every row it's given, how many rows
    (including itself) were in the frame passed to predict(). A model that
    only receives the test slice would report small counts restarting near 1
    every fold; a model that receives full history would report the true
    row position within the whole series -- this is exactly what an
    HMM/jump-model's running filter state depends on (F4).
    """

    name = "running_count"
    is_stochastic = False

    @property
    def n_fitted_knobs(self) -> int:
        return 0

    def fit(self, X_train, Y_train):
        return self

    def predict(self, X):
        out = self._empty_predictions(X.index)
        out["regime_p_up"] = np.arange(1, len(X) + 1, dtype=float)
        return out


def test_predict_receives_full_history_not_just_test_slice():
    # F4: run_walkforward used to call model.predict(X_test) with only the
    # fold's test rows, so a stateful model's filter would restart cold
    # every January 1st. It must instead receive every row from the start
    # of the series through the fold's test_end.
    df = synthetic.generate_synthetic(n_rows=1600, seed=5, start="2013-01-03")
    close = df["close"]
    X = features.build_features(close)
    Y = targets.build_targets(close, open_lockbox=False)

    model_pred, _, folds = runner.run_walkforward(lambda k: _RunningCountModel(), {}, X, Y)
    t0 = folds[0]["test"][0]

    # ground truth: predicting directly on the full series truncated at t0
    # (i.e. "every row up to and including t0") must give the same running
    # count as what run_walkforward produced for that date.
    direct_pred = _RunningCountModel().predict(X.loc[:t0])
    expected_count = direct_pred.loc[t0, "regime_p_up"]

    assert model_pred.loc[t0, "regime_p_up"] == pytest.approx(expected_count)
    # sanity: this must be much larger than 1 -- the count a test-slice-only
    # call (the pre-fix bug) would have produced for the first test day
    assert expected_count > 100


def test_run_experiment_smoke(tmp_path, monkeypatch):
    log_path = tmp_path / "experiments.jsonl"
    monkeypatch.setattr(runner, "EXPERIMENTS_LOG", log_path)
    monkeypatch.setenv("REGIME_OUT", str(tmp_path / "out"))

    df = synthetic.generate_synthetic(n_rows=1500, seed=2, start="2013-01-03")
    close = df["close"]
    assert close.index.max() < pd.Timestamp("2025-01-01")

    row = runner.run_experiment(
        lambda knobs: Climatology(), knobs={}, feature_config={}, tag="smoke-test",
        close=close, run_perturbations=False,
    )

    assert row["model"] == "B0_climatology"
    assert row["n_fitted_knobs"] == 0
    assert row["lockbox_opened"] is False
    assert "rps_skill_20" in row["metrics"]
    assert log_path.exists()
    logged = [json.loads(l) for l in log_path.read_text().strip().split("\n")]
    assert len(logged) == 1
    assert logged[0]["exp_id"] == row["exp_id"]
