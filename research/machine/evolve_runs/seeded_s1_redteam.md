# Red-team — seeded GA runs, burst + four_pct (2026-08-06)

Mode `seeded` (registered today): gradient genomes whose initial population is
27 hand-written seeds translated from the external idea corpus (48% of pop 56)
plus 29 random genomes. Seeds live in `specs/ga_seeds/{burst,four_pct}.json`
with a `src` field mapping each back to its source idea.

## Pre-registered placebo floor for this mode

`--mode seeded --placebo`, 3 RNG seeds per trigger, same seed file, pop 56:

| trigger | s1 | s2 | s3 |
|---|---|---|---|
| burst | 1.43 | 1.33 | 1.30 |
| four_pct | 1.07 | 1.60 | 0.95 |

**Floor = 1.60** (largest noise fitness observed). Higher than the incumbent
gradient floor (0.90–1.04 on bounce) because the population is larger (56 vs
24) and the seed file adds 8 mm_history series to the search space — more
search, higher noise ceiling. Measured before any real run was interpreted.

## Pre-run era-A check that changed the genome family (no holdout cost)

`--genome pocket` was pre-registered but NOT spent. On era A (training data),
**27/27 seed stacks and 200/200 random stacks score 0 on both triggers**: the
naked long-breakout triggers bleed −0.060R (burst) and −0.043R (four_pct) on
the D+1-open ruler, and no external gate — index 10/20-DMA, dual-index, TI65,
breadth, base, dry-up, near-52wh, vol-scaled momentum, liquidity — makes era-A
expectancy positive. `evaluate_pocket` gates on `mean(r) > 0`, so the absolute-
pocket run is predetermined to return zero finalists. Confirms and extends the
2026-07-30/31 pocket runs ("burst: 158 stacks, zero positive in both era-A
halves"; "four_pct long pockets 0"). The single seeded run per trigger was
therefore spent on `--genome gradient`.

## Run outcomes (one run per trigger, seed 1, pop 56, gens 30)

| trigger | genomes searched | best train z | finalists judged | verdicts |
|---|---|---|---|---|
| burst | 447 | 1.46 (**below** floor 1.60) | 3 | PASS / WEAK / FAIL |
| four_pct | 650 | 2.12 (above floor) | 2 | PASS / FAIL |

- `ga_burst_s1_seeded_f1c6cc` — **zero filters**, condition `turn_decile`
  quartiles. A +0.209 / B +0.154, null 100, n 23,467. This is a rediscovery of
  the incumbent `h3_burst_turn_decile` (already PASS, already red-teamed with
  two `v_` perturbations on the board). Train z 1.46 sits **below** the seeded
  placebo floor, so under pre-registered condition (a) it is not promotable on
  this run's evidence — but it needs no new promotion: it is already certified.
- `ga_four_pct_s1_seeded_250d79` — filters `market:pct40ma >= 15.9` and
  `rs >= 66.72`, condition `turn_decile` quartiles. A +0.191 / B +0.131,
  null 100, n 36,899; 20-day horizon PASS too (B +0.236). Above the floor.
  `verdict_close` = FAIL (+0.042R) — the effect is an open-ruler finding.

## Battery on the four_pct champion (the only above-floor result)

| attack | verdict | era A | era B | null | n |
|---|---|---|---|---|---|
| baseline | PASS | +0.191 | +0.131 | 100 | 36,899 |
| min_gap 20 | PASS | +0.185 | **+0.148** | 100 | 25,251 |
| min_gap 60 | PASS | +0.211 | **+0.166** | 100 | 16,338 |
| quintiles | PASS | +0.182 | +0.144 | 100 | 36,899 |
| 5 custom edges | INSUFFICIENT | +0.233 | +0.405 | 98 | 36,899 |
| 3 custom edges | INSUFFICIENT | +0.588 | +0.265 | 100 | 36,899 |
| pct40ma 10 / 25 | PASS / PASS | +0.156 / +0.201 | +0.115 / +0.124 | 100 | 38,551 / 33,983 |
| rs 60 / 75 | PASS / PASS | +0.217 / +0.177 | +0.122 / +0.122 | 100 | 44,883 / 26,617 |
| drop breadth filter | PASS | +0.144 | +0.109 | 100 | 39,333 |
| drop rs filter | PASS | +0.190 | +0.088 | 100 | 77,285 |
| **naked cohort** | PASS | +0.161 | +0.080 | 100 | 83,452 |

11/11 comparable perturbations PASS. The two INSUFFICIENTs are custom-edge
re-cuts that thin era-A extreme buckets below MIN_N; their effects are *larger*,
not smaller, so they are a sample-size artefact, not a failure.

- **Overlap:** min_gap 20 and 60 both STRENGTHEN era B (+0.148, +0.166). Not a
  serial-overlap mirage.
- **Tails:** clipping stop_r at ±5R moves the effect by ≤ +0.012R in every era
  (A +0.191→+0.198, B +0.131→+0.143). Not carried by a handful of events.
- **Era stability:** positive in **every entry-year 2015–2026** — 2015 +0.03,
  2019 +0.58 (peak), 2023 +0.17, 2024 +0.11, 2025 +0.13, 2026 +0.14. A real
  decay from the 2018-19 peak, but no year flips sign.

**The honest caveat: `rt_naked` is already PASS.** `turn_decile → four_pct` is
the incumbent `b4il_turn_4pct` (PASS, B +0.080). The GA's two filters buy
+0.05R of era B on top of a known effect. This is a refinement of something
already on the board, not a discovery.

## Did seeding beat random init? No.

Era-A fitness of the 27 seeded genomes vs 200 random draws from the same ctx:

| trigger | seeded best | seeded >0 | random best | random >0 |
|---|---|---|---|---|
| burst | 0.21 (`x1_quiet_breakout`) | 2 / 27 | **1.46** | 35 / 200 |
| four_pct | 1.06 (`g1_ma1020_n500`) | 6 / 27 | **1.34** | 46 / 200 |

Random initialisation dominates on both triggers, at both the best draw and the
hit rate. Neither champion contains a seed threshold: `pct40ma >= 15.9` and
`rs >= 66.72` are auto-generated quantile edges on series a plain `gradient`
run already searches. **No mm_history series the seeds unlocked
(`ma1020_*`, `net50m`, `dd2y_*`) survived into any finalist.**

The best-performing seed on either trigger is `g1_ma1020_n500` — the index
10/20-DMA regime gate that five independent external systems bolt on — at
z 1.06, still below the placebo floor. That is consistent with the board's own
`b7mb_burst_ma1020` / `b7mb_fourpct_ma1020` FAILs: index-MA gates are noise
per-event, and per-stock breadth beats them.

3 of 30 seeds (`d1_deliv_veto`, `d2_deliv_regime`, `c3_R5_system`) were
**unevaluable by construction** — delivery data starts 2020-10, so a delivery
filter empties the era-A training cohort. Reported, never scored as negative.
