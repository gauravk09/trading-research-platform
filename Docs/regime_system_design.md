# Regime & Market-Odds System — Design (DRAFT v0.1, 2026-09-26)

**Status:** design only. Nothing is built. Every section ends with open questions, and the design is frozen only after the user approves it.
**Research basis:** `Docs/regime_filter_research_2026-09.md`.
**Decided by user so far:**
- Regime index = **Nifty 500**.
- Regime output is used to **size down**, not to switch trading off.
- The output is **probabilities / odds**, not hard bands.
- **Provisional defaults (applied 2026-09-26 for the first scoring run; user may change → re-score, logged):**
  - Q1.1: bands ±0.5σ; drawdown thresholds 5% (20d) / 10% (60d).
  - Q5.1: lockbox 2025-01-01 → 2026-09, sealed.
  - Q6.1: primary horizon = 20d.
  - Q6.2: §4 gates as written.
  - Only T-Index is scored in Phase 1; T-Breadth needs the stock store and comes later.
  - Pre-2015 rows of the long history may be used **only as feature warm-up** (so 250-day lookbacks exist on 2015-01-01), never for training or scoring.
  - §4.5 (trading usefulness) is deferred until the strategy trade lists are re-verified.
- **DECIDED 2026-09-26 (Option A, supersedes the Phase 1 / Phase 2 split below):**
  - **Dev window:** `long` config. Training from 1996-01-01 (1995 = feature warm-up only), walk-forward test years **2000–2024** (25 folds).
  - **Lockbox:** unchanged, 2025-01-01 onward.
  - **Eras:** 2000–02, 2003–07, 2008–09, 2010–14, 2015–19, 2020–22, 2023–24.
  - **Breadth (T2) features:** still evaluated on 2015+ only.
  - **Reason:** the harness power test showed that on 2015–2024 alone, even a synthetic perfect-knowledge model is detected in only 1 of 10 seeds at realistic regime separation. Phase 1 could not have confirmed anything.
- *(Superseded)* **Phase 1 validates on existing data only (2015-01 → 2026-09).** Extending to 1995 history is Phase 2, run with the *same frozen harness* once Phase 1 proves the approach.

---

## 0. Purpose and non-goals

**Purpose:** give situational awareness each evening, answering three questions:
1. **Where are we?** The long-term regime: trending up, choppy, or trending down, each with a probability.
2. **What is the short-term push?** Momentum over the last 1–4 weeks.
3. **What usually happens next from here?** Historical odds for the next 5 / 20 / 60 trading days, shown as bands.

Strategies then scale their size by the regime they are known to work in.

**Non-goals:**
- Not a buy/sell signal.
- Not a direction forecast with high accuracy. Research says direction is weakly predictable (≈55–60% at best), while volatility and drawdown risk are strongly predictable. The system must say this on screen.

---

## 1. What exactly are we predicting? (targets)

These must be pinned down first. "Does it predict anything" is meaningless until we say *what*.

### 1.1 Two "markets" — both, kept separate

| Target | Definition | Why | Caveat |
|---|---|---|---|
| **T-Index** | Nifty 500 index (cap-weighted) | Clean official series; can reach back to 1995 | Driven by ~50 large caps; says little about small/mid breakouts |
| **T-Breadth** | % of stocks in our universe whose forward return is > 0 ("participation"), plus the median stock's forward return | This is what breakout traders feel. The index can rise while most stocks fall | Built from our stock store: 2015+, currently-listed names only (survivorship). Treated as a secondary target |

### 1.2 Horizons (fixed, not tuned)
- **5 trading days** (1 week): the short-term momentum question.
- **20 trading days** (1 month): the main regime question.
- **60 trading days** (1 quarter): the long-term question.

### 1.3 Outcome bands (what the "odds" are about)
Each horizon's forward return falls into one of **3 ordered bands**. The bands are **scaled by volatility**, so "a big move" means the same thing in calm and wild markets:

- **Down:** forward return < −0.5 × σ_h
- **Flat:** in between
- **Up:** forward return > +0.5 × σ_h

Here σ_h = trailing 1-year daily volatility × √h, measured at the forecast date (no look-ahead).

Fixed-percentage bands (e.g. ±3% at 20 days) are reported alongside as a readable sanity check.

**Plus two risk targets.** Research says these are the most predictable:
- **P(drawdown):** probability the index falls ≥ X% from today's close at any point in the next h days (X = 5% for 20d, 10% for 60d).
- **Forward volatility tercile:** will the next 20 days be calm, normal, or wild vs the trailing year?

### 1.4 The hindsight "truth" regime (evaluation only — never a feature)
To measure **lag** and **descriptive accuracy**, each past day gets a label that uses the *future*:
- **Trending up:** next-60d return > +0.5σ **and** efficiency ratio > 0.3
- **Trending down:** next-60d return < −0.5σ **and** efficiency ratio > 0.3
- **Choppy:** otherwise

*Efficiency ratio* = |net move| ÷ sum of |daily moves|, from 0 to 1. Near 0 means lots of movement going nowhere (chop); near 1 means a clean straight trend.

This label is **only** a scoring answer key. It must never feed a model.

**Open Q1.1:** are these three bands (Down/Flat/Up at ±0.5σ) and the drawdown thresholds (5% / 10%) right for how you think about risk?

---

## 2. Features (inputs)

### 2.1 Tiered, and added one tier at a time
A tier is added **only** if it improves the out-of-sample score beyond noise (Section 5). This is a *nested* build: simple first, complexity must earn its place.

| Tier | Features | History available | Evidence it helps | Status |
|---|---|---|---|---|
| **T1 Price (Nifty 500 only)** | returns, distance from moving average, MA slope, realized volatility, vol ratio (short/long), efficiency ratio, drawdown from 1-yr / 2-yr high | **1995+** if we fetch history (have 2015+) | Strong (trend + volatility literature) | Core |
| **T2 Breadth (our stock universe)** | % above 40-DMA and 200-DMA, 4%-up/down 10-day ratio, net new 52-week highs | 2015+ | Thin academically; practitioners rely on it | Must beat T1 alone |
| **T3 Macro / cross-asset** | India VIX, 10y G-sec yield + 3-month change, term spread (10y − 91d T-bill), USD/INR 60d change, Brent 60d change, S&P 500 vs 200-DMA, FPI net flows (NSDL) | Varies: VIX 2008+, yields/FX/crude long; **none stored in repo today** | Rates/credit known mostly at long horizons; VIX mainly predicts volatility | Needs new data collection. Test only after T1/T2 |
| **T4 Earnings** | aggregate earnings growth, % of companies beating, revision breadth | Our financials store starts ~2021 | Plausible, but history far too short to train regimes | **Parked.** Revisit once we have more than 1 cycle |

### 2.2 How do we choose n (the lookback)? — we don't tune it
Tuning n is the #1 overfitting trap (Zakamulin: "no single optimal lookback"). Instead:

- **A fixed ladder of conventional lookbacks**, chosen before seeing any results:
  **5, 10, 20, 60, 120, 250 trading days** = 1 week, 2 weeks, 1 month, 1 quarter, half a year, 1 year. These are the standard horizons in the momentum literature (1–12 months).
- A model gets the **whole ladder** (or a pre-declared subset). Picking "the best n" from results is not allowed.
- **Robustness check:** swapping any rung for its neighbour (20 → 15 or 25; 250 → 200 or 300) must not change the score materially (Section 4, stability).

**On "above the 50-DMA?":**
- The 50-DMA is a **medium-term** trend (about 2.5 months).
- The research standard for **long-term** trend is 200 days or 10 months.
- Both stay in as **naive baselines**: "Naive-50" and "Naive-200". Every fancy model must beat them. If it can't, the naive rule wins.

**Open Q2.1:** OK to fetch Nifty 500 history back to 1995? It roughly triples the number of regime cycles, including the 2000 and 2008 crashes.
**Open Q2.2:** is T3 macro in scope for v1, or only after T1/T2 are scored? Recommended: after.

---

## 3. Components and candidate approaches

### 3.1 C1 — Long-term regime (Up / Choppy / Down, with probabilities)

| Code | Approach | How probabilities arise | Fitted knobs | Notes |
|---|---|---|---|---|
| **B0** | Climatology | Always the historical average frequencies | 0 | The floor. Everything must beat it |
| **B1** | Naive-50 | Hard label: above 50-DMA = up | 0 | User's naive idea, kept as a baseline |
| **B2** | Naive-200 | Hard label: above rising 200-DMA = up, below falling = down, else choppy | 0 | Literature standard |
| **R1** | Rule grid | Trend axis (price vs 200-DMA + slope) × chop axis (60-day efficiency ratio). Probabilities = historical outcome frequencies per cell | 1–2 thresholds | Transparent |
| **R2** | R1 + hysteresis | Must cross the threshold by a margin, or persist N days, before flipping | +1 | Directly targets whipsaw |
| **H1** | Gaussian HMM, 3 states | Model's own **filtered** state probability (real-time only) | Fixed 3 states | States usually = calm/volatile, not up/down. Must be checked, not assumed |
| **J1** | Statistical jump model (sticky HMM) | Filtered probabilities with a penalty for switching | +1 (jump penalty) | Research's best persistence fix |
| **L1** | Multinomial logistic regression | Directly predicts P(Down / Flat / Up) from features | ~features × 2 | Supervised: optimises the odds question itself |
| **K1** | Historical analogs (k nearest days) | Share of the k most-similar past days in each band | k | "What happened last time it looked like this" |

**Important distinction:**
- B/R/H/J produce **descriptive states** ("where are we"). They get judged by whether those states predict anything.
- L1/K1 predict the **odds** directly.

We may end up with, for example, R2 for the regime label and L1 for the odds. That's fine.

### 3.2 C2 — Short-term momentum (descriptive)
From the T1 ladder's short rungs (5, 10, 20 days):
- **Momentum:** 5/10/20-day return as a z-score (today's value vs the last year's distribution).
- **Volatility:** 10-day realized vol vs 1-year vol.
- **Location:** where the close sits in the 20-day high–low range.

Named states (display only):
- **Thrust** (strong up, rising vol)
- **Drift up**
- **Pullback** (down within an uptrend)
- **Oversold / washout**
- **Drift down**

C2 feeds C3 as a feature. It is judged by the same Section 4 tests on the 5-day horizon.

### 3.3 C3 — Odds engine (the "what happens next" panel)
For each horizon (5 / 20 / 60) and each target (T-Index, T-Breadth), show:
- P(Down / Flat / Up), with a confidence range
- P(drawdown ≥ X%)
- The sample size behind the estimate, e.g. "based on 212 similar days". If the sample is below 100, show **"insufficient history"** rather than a number.

---

## 4. The scorecard (how every candidate is judged)

**Rule:** pass/fail **gates** first, then rank on one **primary metric**. No weighted sum of many metrics: the weights themselves would be a knob to overfit.

### 4.1 Does it predict anything? (primary)
- **Primary metric: Ranked Probability Score (RPS) skill vs B0 climatology**, per horizon, fully out of sample.
  - RPS is the proper score for **ordered** bands (Down < Flat < Up). It penalises "said Up, got Down" more than "said Up, got Flat".
  - Skill = 1 − RPS_model / RPS_climatology. Above 0 means better than always guessing the average.
- **Also reported:**
  - **Log loss:** punishes confident wrong calls.
  - **Brier score:** for the binary drawdown target.
- **State separation** (for descriptive models B/R/H/J): forward 20/60-day return, volatility and drawdown by state, with **block-bootstrap confidence intervals**. The states must differ, in **both** eras.

### 4.2 Are the probabilities honest? (calibration)
- **Calibration plots (reliability diagrams): yes, one per band and horizon.**
  - Predicted probability on the x-axis, observed frequency on the y-axis. Points on the diagonal = honest.
  - Each point carries its sample size and a confidence bar.
- **Expected Calibration Error (ECE):** one-number summary of distance from the diagonal.
- ~~**Gate:** ECE ≤ 0.05 on out-of-sample data.~~
- **Gate (changed 2026-09-26, before any candidate was scored):**
  - **What:** observed ECE must be ≤ the 95th percentile of the ECE a *perfectly calibrated* forecaster with the same forecasts would show by chance. Computed by consistency resampling: simulate outcomes ~ Bernoulli(p), 1000 reps (Bröcker & Smith 2007).
  - **Where:** checked on the 20d bands, using the worst of down/flat/up.
  - **Why:** the harness review found that a synthetic *oracle* that knows the true state scored ECE 0.04–0.13 across seeds on ~1,700 out-of-sample days. A fixed 0.05 bar would reject a perfect model, so it measured sample size, not calibration.
  - **Recorded:** in `research/regime/CHANGELOG.md`.

### 4.3 Is it stable? (the sensitivity question)
| Test | Measures | Gate (proposed) |
|---|---|---|
| **Flip rate** | Regime changes per year | 2–8 per year |
| **Whipsaw rate** | % of flips reversed within 5 days | < 20% |
| **Mean regime duration** | Average days in a state | ≥ 20 days |
| **Knob perturbation** | Shift every knob/threshold ±10% and ±25%, and each ladder rung to its neighbour. Measure day-label agreement (Cohen's κ) and change in RPS skill | κ ≥ 0.8; skill drop < 25% |
| **Probability smoothness** | Day-to-day change in P(state); share of days with a jump > 0.3 | < 5% of days |
| **Refit stability** (H1/J1) | Refit on shifted windows / different seeds; state agreement | κ ≥ 0.8 |
| **Data perturbation** | Add small noise to prices (±0.1%) and re-run | Labels ≥ 95% unchanged |

### 4.4 How late is it?
- **Detection lag:** median trading days between a hindsight-truth regime change (§1.4) and the model catching it. Reported separately for turns into trending up and into trending down.
- **Gate:** median lag ≤ 15 trading days.

### 4.5 Does it help trading? (secondary — strategy trade lists unverified)
- Re-size existing strategy trades (Ryan/Minervini, lone-loser) by regime probability.
- Compare against (a) unsized, and (b) **random sizing at the same average exposure** (the regime version of the random-entry control).
- This stays **secondary** until the strategy trade lists themselves are re-verified. It cannot promote or reject a model on its own.

### 4.6 Tie-breaker: simplicity
If two models' skill confidence intervals overlap, **the one with fewer fitted knobs wins.**

---

## 5. Avoiding overfitting (the core of the plan)

1. **Pre-registration.** This document lists every candidate, feature ladder, knob grid, metric and gate **before** any run. Anything added after seeing results is logged as a new variant (rule 7).
2. **Locked final holdout ("lockbox").** The most recent period is sealed and scored **once**, at the very end, for the chosen model only. If we peek or iterate on it, it's burned and we must say so. *(Phase 1 lockbox: 2025-01 → 2026-09. See Open Q5.1.)*
   **Phase 1 caution:** 2015–2024 has only about 4–5 real regime transitions. The HMM/jump models (H1/J1) will be fitted on very few cycles, so their Phase 1 scores are provisional. Simple rules are favoured until Phase 2 confirms.
3. **Walk-forward on everything else.** Expanding window, refit every 12 months, predict the next 12 months strictly out of sample. Scores are the concatenation of those out-of-sample predictions.
4. **Purge + embargo.** Forward labels overlap: day t's 20-day return shares 19 days with day t+1's. So leave a gap of the horizon length (20 or 60 days) between train and test.
5. **Effective sample, not rows.** Confidence intervals come from a **block bootstrap** (block ≥ horizon), not from treating every day as independent. Report regime transitions per era next to every score.
6. **Degrees-of-freedom cap.** Rule models ≤ 3 fitted knobs. HMMs fixed at 3 states. No automated feature selection. The feature set is fixed per tier.
7. **Experiment log (append-only).** Every run gets one row: variant, knobs, data window, scores. The count of variants tried is reported with the winner, like a multiple-testing correction.
8. **Winner must beat the baseline with confidence.** The skill difference vs **Naive-200** needs a bootstrap CI excluding zero. Otherwise **pick the simpler model.**
9. **Eras reported separately (Phase 1, 2015+ data):**
   - 2015–19 (includes the 2018 small-cap bear)
   - 2020–22 (COVID crash + V-rebound + 2022 chop)
   - 2023–24 (strong bull)
   - 2025–26 (chop; lockbox)
   A model that only works in one era fails. Phase 2 adds 1995–2014 (2000 and 2008 crashes) as extra eras.
10. **Fresh code, not repo code.** Every feature and label is re-implemented from this spec, with unit tests on hand-computed examples. No reuse of existing filter/regime code (user distrust; pre-audit studies).

---

## 6. The validation loop (process once the plan is frozen)

```
Step 0  Freeze this doc (v1.0). User sign-off.
Step 1  Build the TEST HARNESS FIRST: targets, truth labels, walk-forward splitter,
        purge/embargo, scorers (RPS/log-loss/Brier/ECE), stability suite, block bootstrap.
        Validate the harness on synthetic data with a KNOWN answer
        (simulated regimes; a harness that can't find a planted regime is broken).
Step 2  Score the baselines B0, B1, B2 → reference row in the log.
Step 3  For each candidate (R1 → R2 → H1 → J1 → L1 → K1), tier T1 only:
          run walk-forward → full scorecard → log row → gates pass/fail.
Step 4  Tier T2 (breadth) added to the gate-passers; keep only if skill CI improves.
Step 5  (Optional) Tier T3 macro, same rule.
Step 6  Select: gates passed → best primary metric → simplicity tie-break.
Step 7  Open the lockbox ONCE for the selected model. Report whatever it says.
Step 8  User review → decide whether to wire it into the dashboard / sizing.
```
Each step ends with a written scorecard for the user and **waits for approval** before the next step.

---

## 7. Open decisions (need user answers before v1.0)

| # | Question | Recommendation |
|---|---|---|
| Q1.1 | Bands at ±0.5σ, drawdown thresholds 5% (20d) / 10% (60d)? | Yes, as the starting point |
| Q2.1 | Fetch Nifty 500 back to 1995? | **DECIDED: not in Phase 1.** Validate on 2015+ first, extend in Phase 2. **Data fetched 2026-09-26:** `data/raw/index_history_long/nifty500_daily.csv`. Official niftyindices.com, 1995-01-01 → 2026-09-25, 7,865 rows. Matches the live 2015+ file within 0.1% on all 2,907 overlapping days. Only 5 moves above 10% (2004, 2008 ×2, 2009, 2020, all real). The 1995-01-01 row is the base value only (close 1000, no OHL) |
| Q2.2 | Macro (T3) in v1? | No, only after T1/T2 are scored |
| Q5.1 | Lockbox period? | **2025-01 → 2026-09** (21 months of chop). Walk-forward: 3-year minimum training (2015–17), out-of-sample tests 2018–2024. Downside: a short lockbox with no crash, so its verdict is weak. Phase 2's 1995–2014 data acts as a second, older out-of-sample check |
| Q6.1 | Primary horizon for choosing the winner: 20d or 60d? | 20d (matches regime-sizing use); 60d reported |
| Q6.2 | Are the §4 gate numbers acceptable, or tighter/looser? | Accept as v1 and revisit after the baselines run (logged as a change) |
