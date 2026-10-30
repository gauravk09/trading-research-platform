# Changelog

Pre-registered gates and thresholds live in `gates.GATE_THRESHOLDS`. Per the
spec's anti-overfitting rules (Docs/regime_system_design.md Section 5, rule 1
and 7), any change to a pre-registered gate after seeing results must be
logged here, with the date and the reason.

## 2026-09-26 — Made the walk-forward window configurable (G2)

**Change:** `data.py` now exposes `WINDOW_CONFIGS`, a dict of named window
configs (`warmup_start`, `dev_start`, `first_test_year`, `last_test_year`,
`eras`), and `data.get_window_config(name_or_dict)`. `splits.get_walkforward_folds`,
`runner.run_walkforward`, `runner.score_predictions`, and `runner.run_experiment`
all take an optional `window_config` argument (default `"default"`, which
reproduces the exact prior behavior: dev_start 2015-01-01, test years
2018-2024, the original three eras). A new `"long"` config extends into the
1995+ history now in `INDEX_CSV`: warmup_start 1995-01-01, dev_start
1996-01-01, test years 2000-2024, eras 2000-02/2003-07/2008-09/2010-14/
2015-19/2020-22/2023-24. `LOCKBOX_START` (2025-01-01) is a module-level
constant, not part of any config, and is enforced identically regardless of
which config is active (`get_window_config` also rejects a config whose
train span is under `MIN_TRAIN_YEARS=3`).

**Reason:** switching to the long history for Phase 2 should be a config
change, not a code change, and every module that currently hardcodes
2015/2018-2024 needed to earn that instead of assuming it.

**Not done as part of this change (deliberately):** B0 Climatology has not
been rerun on the "long" config against real data — only the synthetic
Oracle's power curve was rerun on it (see the power-curve entry below and
README.md's "Statistical power" section). Real candidates stay on
"default" until the long config itself is validated the same way Phase 1
was.

**Compute note:** the "long" config's power curve used only `seeds=range(2)`
per scale, not the `range(10)` used for "default". A single long-config
walk-forward run (25 folds, ~6300 OOS days feeding the block-bootstrap
calibration) measured at 5+ minutes wall time versus ~22s for "default" —
roughly 25x, not the ~3.7x the OOS-day-count ratio alone would suggest, so
10 seeds x 4 scales would have taken multiple hours. The long-config power
table in README.md is correspondingly noisier (2 seeds) and is reported as
a secondary check, not a load-bearing claim.

## 2026-09-26 — Replaced the independent-per-day ECE-consistency gate with a block-bootstrap Cox calibration test (G1)

**Change:** the calibration gate introduced earlier the same day (see next
entry) is itself replaced. `GATE_THRESHOLDS["ece_consistency_percentile"]`
stays (consistency-resampling ECE is still computed and logged as a
reported diagnostic, just no longer gates anything), and
`GATE_THRESHOLDS["cox_calibration_ci"] = 0.95` is added. The gate
(`gates.evaluate_gates`'s `calibration_20d_within_bound`) now uses
`scoring.cox_calibration_test`: for each of the 20d down/flat/up bands, fit
`logit(P(y=1)) = a + b*logit(p)` (p clipped to [0.01, 0.99]), get 95% CIs
for `a` and `b` from a MOVING-BLOCK bootstrap (block = max(h, 20), 1000
reps, fixed seed), and pass only if `a`'s CI contains 0 AND `b`'s CI
contains 1 for every band (worst of the three decides). When a forecaster's
probability has no variance (slope undefined, e.g. Climatology's
fold-constant forecast), only calibration-in-the-large (mean p vs mean y,
with its own block-bootstrap CI) is checked instead.

**Reason:** the independent-per-day consistency-resampling null (same-day
review, same-day fix) was itself found to be too narrow, not merely
conservative as documented: on a harness review, the synthetic Oracle (knows
the true regime state) failed even that gate, because 20d/60d targets
overlap in time (day t's window shares 19/59 days with day t+1's), which
correlates nearby days' outcomes far more than an i.i.d.-per-day resample
accounts for. Real per-year regime persistence (whole years of a mostly-one
state moving together) meant the too-narrow null rejected genuinely correct
calibration. A block-bootstrap null, which resamples contiguous chunks
instead of single days, respects that autocorrelation.

**Test:** `tests/test_power_curve.py::test_oracle_cox_calibration_gate_pass_share_over_seeds`
(slow, `--runslow`) reruns the Oracle at the validated synthetic scale
(1.0) across 10 seeds and reports the gate's pass share. Measured result:
**5/10 (50%)**, reported as-is (see the test's comment) — below this
change's author's own informal 80% expectation, but a real majority where
the prior null rejected the Oracle on every seed. The remaining failures
trace to genuine year-to-year regime-mix sampling noise from only ~30 total
regime episodes in a 3000-row series, not to the null being narrow again.

## 2026-09-26 — Replaced the fixed ECE ≤ 0.05 gate with consistency resampling

**Change:** `GATE_THRESHOLDS["ece_20d_le"] = 0.05` (a fixed magnitude bound
on 20d-Up ECE) removed. Replaced with
`GATE_THRESHOLDS["ece_consistency_percentile"] = 95.0`, used by
`scoring.consistency_resampling_ece` (Broecker & Smith 2007): for each of
the 20d down/flat/up bands, observed ECE is compared to the ECE
distribution a PERFECTLY calibrated forecaster with the same predicted
probabilities would show, from 1000 resampled reps. The gate passes only if
every one of the three bands' observed ECE is at or below its own null's
95th percentile (`gates.evaluate_gates`).

**Reason:** a harness review reran the synthetic Oracle model (knows the
true generating regime state — as well-calibrated as a model can be) on
seeds 0-5 and found 20d ECE ranging 0.038-0.130, failing the fixed 0.05
bound on most seeds. A fixed magnitude threshold can't distinguish genuine
miscalibration from ordinary finite-sample noise in a 1,700-day walk-forward
OOS sample; a model can "look correct" on inspection and still fail it for
no real reason. The gate was wrong, not the model.

**Caveat carried forward (not fixed by this change):** the resampling draws
each day's null outcome independently, but real targets have overlapping
horizon windows (correlated outcomes), so the null distribution is narrower
than reality — the test is conservative in the strict direction (more
likely to flag a model as miscalibrated than a block-aware null would be,
never the reverse). Documented in `scoring.consistency_resampling_ece`.

## 2026-09-26 — Stage A initial build

First commit: targets, T1 features, walk-forward splitter, RPS/log-loss/
Brier/ECE scoring with block-bootstrap CIs, stability/lag/gates suites,
synthetic 3-state Markov validation, and the B0 Climatology baseline.

## 2026-09-28 — Selection rule locked (1A + 2A)

- **1A — primary metric = RISK skill.** Winner = best out-of-sample skill vs climatology on (a) P(≥5% drawdown within 20d) Brier and (b) 20d forward-volatility tercile Brier, each with a block-bootstrap 95% CI that must exclude 0. Direction (20d band RPS skill) is a tie-breaker only.
- **2A — calibration is a WARNING, not a gate.** Reason: the synthetic Oracle (true state known) passed the Cox calibration test in only 5/10 seeds.
- **Disclosure:** 1A/2A were recommended by the analyst BEFORE any Stage B score existed, but the user locked them AFTER seeing the Stage B scoreboard (all 9 models). The rule was not chosen blind. Treat the selection as partially post-hoc; the sealed 2025-26 lockbox is the unbiased check.

## 2026-09-28 — H1 noise / refit-seed follow-up (data_perturbation gate failed at 0.863 < 0.95)

Script: 5 price-noise seeds (×(1+N(0,0.001))) + 3 EM restart-seed offsets, long window, walk-forward only.
- Regime LABELS under noise agree 81-94% with the base run (the failed gate), but the P(≥5% drop in 20d)
  forecast correlates 0.980-0.988 with base, and 1A risk skill stays significant in every run:
  drop skill +3.9% to +4.3% (all CI lower bounds > +1.6%), vol skill +5.7% to +6.8% (all CI lower > +2.3%).
- Refit seeds +1/+2/+3: identical to base (EM reaches the same optimum; 100% agreement).
- Interpretation: noise flips labels between states that carry similar risk; the risk dial itself is stable.
  The label-agreement gate measures the wrong thing for a 1A (risk-primary) selection. Gate NOT changed —
  recorded as a known, explained failure.

## 2026-09-28 — LOCKBOX criteria (written BEFORE opening; lockbox opened once, H1 only)

Model: H1 Gaussian HMM, frozen code at 36c3833, no knob changes. Reference: B0 climatology.
Window: train from 1996-01-01, walk-forward test years 2025 and 2026 (2026 refit includes 2025 as train,
same expanding rule as dev). Targets computed with open_lockbox=True; rows whose 20d window runs past the
last available price (2026-09-25) are NaN and excluded.
Criteria (1A):
- CONFIRMED: drop-20d skill AND vol-tercile skill both > 0 with block-bootstrap 95% CI lower bound > 0.
- CONSISTENT: both point estimates > 0 but CI includes 0 (expected: only ~400 scorable days).
- FAILED: either point estimate <= 0.
Direction skill and calibration reported as information only (2A). Result is final; no re-runs.
