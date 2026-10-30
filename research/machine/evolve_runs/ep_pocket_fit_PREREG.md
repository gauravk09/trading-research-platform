# Pre-registration — EP fitted-pocket search (2026-09-03)

Why EP: the attribution module's first read (ROADMAP "Agentic-quant survey
adoption") found EP the only trigger with positive selection alpha
(+0.68%/trade over 20 bars, t 3.4, era B +0.79 t 3.2; same-date control +0.03).
That is the one cohort where a filter has something to sharpen.

Training: era A (< 2020), 925 EP events (fold floors met). Era B (>= 2023)
untouched until the pocket judge. Seed 1, pop 24, gens 20, 4 finalists.
Placebo floor: seeds 1-3 with `--placebo`, same settings.

A finalist counts as a finding ONLY if all three hold, decided before the run:
1. pocket judge verdict PASS (era-B date-clustered t >= 2, era A t >= 1,
   vs-naked null >= 95%);
2. PFS >= 0.80 (enforced by the gate);
3. era-B selection alpha (attribution, 20-bar hold) > its same-date control's,
   with date-clustered t >= 2.

Anything short of all three is logged in LEDGER.md as a non-finding.

## Amendment (same day, before the second run)
The era-A run returned 0 finalists: EP's naked era-A expectancy is negative on
every ruler (stop_r −0.06R, daily-t −1.5; stop_r_20 −0.08R), so an absolute-
return pocket cannot score there — the docstring's condition (c), which should
have been checked first. No holdout was touched (no finalists).
EP's edge is a 2020-onward, 20-bar phenomenon (COVID stop_r_20 +0.25R t 2.3;
era B +0.10R; attribution selection alpha era B +0.79%). Second run, declared
as a MODERN-TRACK variant with its own placebo floor, not a repeat of the
first: `--train-end 2023 --ruler stop_r_20` (train = 2015-2022, 2,470 events;
era B >= 2023 remains the single holdout look; the COVID second-holdout is
given up). Bars 1-3 above unchanged; the pocket judge's era-A stats now mean
"< 2023".
