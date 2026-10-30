# Regime test harness (Stage A)

Test harness for evaluating market-regime models against
`Docs/regime_system_design.md`. This package builds the harness and its
tests plus the trivial B0 Climatology baseline. No real candidate models
(R1/R2/H1/J1/L1/K1) live here yet — that's Stage B.

Fresh code only: nothing here imports from `src/`, `strategies/`, or
`research/machine/`.

## Running tests

```bash
cd "<repo root>"   # or any worktree of this repo
python -m pytest research/regime/tests/ -q
```

124 tests should pass (3 more, marked slow, are skipped by default — see
"Statistical power" below; run them with `--runslow`). Notable groups:
- `test_data.py` — lockbox refusal (the sealed 2025-01-01+ period).
- `test_targets.py` — hand-computed labels + proof that lockbox masking
  never reads a lockbox-period price even when the mask is "closed".
- `test_features.py` — hand-computed T1 features + the causality property
  (recomputing on a truncated series reproduces the full-series value at t).
- `test_splits.py` — walk-forward embargo/purge correctness on a toy index.
- `test_scoring.py` — RPS/log-loss/Brier/ECE against hand arithmetic in the
  test comments, plus block-bootstrap CI sanity checks.
- `test_models_base.py`, `test_stability.py`, `test_lag.py`, `test_gates.py`
  — unit tests for each piece of the scorecard machinery.
- `test_synthetic.py` — the harness must recover a KNOWN planted 3-state
  Markov regime (Oracle clearly beats Climatology; Random does not).
- `test_runner.py`, `test_scoreboard.py` — the append-only log and the
  scoreboard renderer.

## Running an experiment

```python
from research.regime import runner
from research.regime.models.base import Climatology

row = runner.run_experiment(
    lambda knobs: Climatology(),   # model_factory: knobs -> unfitted model
    knobs={},
    feature_config={},             # kwargs forwarded to features.build_features
    tag="stage-a-baseline",
)
```

This walks forward over 2018-2024 (7 expanding-window, embargo+purged folds),
scores against a per-fold-refit B0 Climatology reference, runs the stability
and lag suites, evaluates the gates in `gates.GATE_THRESHOLDS`, saves
out-of-sample predictions + reliability plots under `$REGIME_OUT/<exp_id>/`
(default: `research/output/regime/`), and appends
one row to `experiments.jsonl` (tracked, append-only — never rewritten).

`run_perturbations=True` (the default) additionally reruns the walk-forward
for every numeric-knob perturbation (±10%/±25%) and for 5 seeds of small
(±0.1%) price noise, to populate the knob- and data-perturbation gates. This
is skipped automatically for models with 0 numeric knobs or no regime
probabilities (nothing to perturb). Pass `run_perturbations=False` to skip it
for a fast smoke run.

## Rebuilding the scoreboard

```python
from research.regime import scoreboard
scoreboard.build_scoreboard()   # writes research/regime/SCOREBOARD.md
```

## The model interface (models/base.py)

Every candidate implements `RegimeModel`:
- `name: str`, `is_stochastic: bool`, `knobs: dict`, `n_fitted_knobs: int`
  (used for the Section 4.6 simplicity tiebreak).
- `fit(X_train, Y_train) -> self`
- `predict(X) -> DataFrame` indexed like `X`, columns:
  `regime_p_up/chop/down` (NaN if the model has no regime probabilities),
  and for each horizon h in {5, 20, 60}: `p_down_h, p_flat_h, p_up_h, p_dd_h`,
  plus `p_vol_low_20, p_vol_mid_20, p_vol_high_20`.

**Causality contract:** `predict(X)` may only use, for each date t, rows of
`X` with index `<= t`. The harness does not sandbox this at runtime — the
structural defenses are that `features.py` is itself strictly causal (see
its causality test) and `splits.py`'s embargo+purge keeps target information
belonging to the test period out of every fold's train window. A model class
that peeks ahead inside its own `predict()` would not be caught automatically
and must simply not do that.

**`predict(X)` receives history, not just the dates being scored.**
`runner.run_walkforward` calls `fit()` on the fold's train rows only, but
calls `predict()` with every row from the start of the series through the
end of the fold's test year (including pre-fold history) and slices the
result down to the test dates afterward. This is so a stateful model (an
HMM/jump-model filter, anything path-dependent) can carry state across the
fold boundary instead of restarting cold every January 1st. See
`tests/test_runner.py::test_predict_receives_full_history_not_just_test_slice`.

Descriptive models (rule grids, HMM, jump models) that only produce a state
probability, not target odds directly, use the `StateToOdds` helper: fit it
on the train window's state probabilities + targets (Laplace-smoothed
per-state conditional frequencies), then mix by state probability at predict
time.

## The lockbox rule

`data.LOCKBOX_START = 2025-01-01`. `data.assert_no_lockbox(dates)` raises
`LockboxError` if any date is `>= LOCKBOX_START`, unless
`open_lockbox=True` is passed explicitly. `runner.run_walkforward` calls this
on every fold's train and test dates. Separately, every function in
`targets.py` masks (sets NaN) any target whose forward window would read a
price `>= LOCKBOX_START`, by default — so even a dev-date label near
2024-12-31 can never quietly leak a lockbox price, independent of whether the
lockbox is "open" for scoring purposes. `open_lockbox=True` is reserved for
the one, final, pre-registered lockbox run (validation-loop Step 7) — not yet
performed in Stage A.

## Statistical power

`synthetic.power_curve(scales, seeds, window_config)` measures the harness's
power to detect a planted regime at varying separation, instead of just
reporting that the Oracle validation test passes at whatever separation
made it pass. Both the drift gap and the vol gap of the up/down states
relative to chop are multiplied by `scale`; for each scale, the Oracle
model runs through the real walk-forward pipeline for every seed
(`window_config` controls both the folds used and the synthetic series'
start date, so a `"long"` run actually tests 2000-2024 on 1995+ data), and
this reports the share of seeds where the 20d skill's 95% block-bootstrap
CI lower bound clears zero.

Run it yourself (slow — skipped by default): `pytest research/regime/tests/test_power_curve.py --runslow`

**`"default"` config** (7 folds, ~1700 OOS days), `scales=(0.1, 0.25, 0.5, 1.0)`, `seeds=range(10)`, `n_rows=3000`, run 2026-09-26, nothing tuned:

| scale | up drift (ann.) | down drift (ann.) | share of seeds CI-lower > 0 | median 20d skill | median 20d-up ECE |
|---|---|---|---|---|---|
| 0.10 | +6.3% | -7.6% | 0.0 | -0.008 | 0.092 |
| 0.25 | +15.8% | -18.9% | 0.1 | 0.029 | 0.089 |
| 0.50 | +31.5% | -37.8% | 0.5 | 0.089 | 0.074 |
| 1.00 | +63.0% | -75.6% | 1.0 | 0.247 | 0.089 |

**`"long"` config** (25 folds 2000-2024, ~6300 OOS days), same scales, run
2026-09-26. **`seeds=range(2)` only** — a single long-config run measured at
5+ minutes wall time (vs ~22s for `"default"`, roughly 25x, from 25 folds
instead of 7 and ~3.7x more OOS days feeding the calibration bootstrap), so
10 seeds x 4 scales would have taken multiple hours. This table is
noisier than the default one as a result and is a secondary check, not the
primary claim:

| scale | up drift (ann.) | down drift (ann.) | share of seeds CI-lower > 0 | median 20d skill | median 20d-up ECE |
|---|---|---|---|---|---|
| 0.10 | +6.3% | -7.6% | 0.0 | -0.027 | 0.119 |
| 0.25 | +15.8% | -18.9% | 0.0 | 0.001 | 0.093 |
| 0.50 | +31.5% | -37.8% | 0.5 | 0.071 | 0.079 |
| 1.00 | +63.0% | -75.6% | 1.0 | 0.212 | 0.065 |

For comparison, `synthetic.real_nifty500_annualized_drift_vol()` on the real
dev window (2015-01-01..2024-12-31, overall, not per-regime): annualized
drift **+12.1%**, annualized vol **16.5%** (2,476 days).

**What this means, stated plainly and without spin:** `scale=1.0` — the
separation used by the pass/fail synthetic validation test elsewhere in this
package — has an up-state drift of +63%/yr and a down-state drift of
-76%/yr. That is far beyond anything the real Nifty 500 has ever shown as a
sustained annualized rate; the real index's whole-period drift is +12.1%.
Even `scale=0.25` (+15.8%/-18.9%, roughly the size of a real strong
bull/bear leg) only detects a real regime (CI lower bound > 0) in **1 of 10
seeds** on the default config (**0 of 2** on the noisier long-config check).
Power only becomes reliable (`share >= 0.5`) at `scale=0.50` in both
configs, which is still 2-3x more extreme than realistic annual drift
figures. The `"long"` config's larger sample (25 years vs 10) does not
obviously buy more power at low separation here — median skill and ECE both
improve somewhat at `scale=1.0` (more data to fit calibration on), but the
low-separation rows are too noisy (2 seeds) to conclude the long history
meaningfully raises power at REALISTIC separations; that would need more
seeds than this session's compute budget allowed.

This is a genuine limitation of this exact walk-forward design (many folds,
few independent regime episodes relative to fold count, block-bootstrap
CIs), not a bug: a real but moderate regime signal in the actual Nifty 500
data may well fail the `rps_skill_20d_ci_lower_positive` gate even if the
underlying skill is real. It does not invalidate the harness's synthetic
pass/fail test (that test only needs to show the harness CAN detect a
regime when one is strongly present, which it does at scale=1.0 in both
configs), but it means a "gate fail" on real data for a plausible future
candidate model should be read as "not enough power to confirm at this
sample size," not automatically as "no real signal exists."

## Calibration and the calibration gate

`runner.score_calibration` scores calibration for every band (down/flat/up
at 5/20/60d), every drawdown probability (5/20/60d), and all three 20d vol
terciles. Two things are computed per target:

- **`scoring.cox_calibration_test`** — the gate. Fits
  `logit(P(y=1)) = a + b*logit(p)` and gets 95% CIs for `a` and `b` from a
  MOVING-BLOCK bootstrap (block = max(h, 20), respecting each target's own
  overlap window). A forecaster is well-calibrated if `a`'s CI contains 0
  and `b`'s CI contains 1. When `p` has no variance (slope undefined, e.g.
  Climatology's fold-constant forecast), only calibration-in-the-large
  (mean `p` vs mean `y`, its own block-bootstrap CI) is checked. Only the
  20d bands feed the pass/fail gate (worst of down/flat/up); the rest are
  logged for inspection.
- **`scoring.consistency_resampling_ece`** — a reported DIAGNOSTIC only, not
  gated. See `CHANGELOG.md`'s two 2026-09-26 entries for the full history:
  a fixed "ECE <= 0.05" bound failed even the synthetic Oracle from
  ordinary finite-sample noise; its replacement (this independent-per-day
  resampling) turned out to have the same problem for a subtler reason —
  its null ignores the autocorrelation that overlapping 20d/60d targets
  introduce, making it too narrow, and it still rejected the Oracle. The
  Cox test's block bootstrap is the actual fix; this is kept only as a
  secondary number to look at.

Reliability plots are saved for 20d down/flat/up (one 3-panel figure),
dd_20, dd_60, 5d-up, 60d-up, and 20d vol-high.

## Walk-forward window configs

`data.WINDOW_CONFIGS` holds named configs (`warmup_start`, `dev_start`,
`first_test_year`, `last_test_year`, `eras`); `data.get_window_config(name)`
resolves one (or passes a dict through unchanged). `splits.get_walkforward_folds`,
`runner.run_walkforward`, `runner.score_predictions` and `runner.run_experiment`
all take an optional `window_config` argument (default `"default"`).

- **`"default"`** (used everywhere unless stated otherwise): dev_start
  2015-01-01, test years 2018-2024, the original three eras.
- **`"long"`**: warmup_start 1995-01-01 (the earliest real row in
  `INDEX_CSV`), dev_start 1996-01-01, test years 2000-2024, eras
  2000-02/2003-07/2008-09/2010-14/2015-19/2020-22/2023-24.

`LOCKBOX_START` (2025-01-01) is NOT part of any config — it's a
module-level constant enforced identically no matter which config is
active (see `tests/test_runner.py::test_run_walkforward_refuses_any_config_reaching_the_lockbox`).
B0 Climatology has **not** been rerun on `"long"` against real data yet —
only the synthetic Oracle's power curve has (below).

## Known scope limits (Stage A)

- Only B0 Climatology is implemented as a model. R1/R2/H1/J1/L1/K1 are
  Stage B.
- Knob- and data-perturbation gates are N/A for B0 (0 knobs, and its
  "regime" comes from unconditional truth-label frequencies with no free
  parameters to perturb) — the perturbation *machinery* itself
  (`stability.perturb_numeric_knobs`, `knob_perturbation`,
  `data_perturbation_agreement`) is unit-tested directly on toy data instead.
- Only T-Index (Nifty 500) is scored, matching the spec's Phase 1 scope.
  T-Breadth needs the stock store and is out of scope here.
