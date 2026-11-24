# ADDENDUM — ATH-conditioning overlay on `pullback_long`     REJECT | 2026-08-07

Follow-up to `VERDICT.md`. Code: `src/backtest/studies/pullback_long_ath_overlay.py`.
Base cohort = `pullback_long.py` variant A exactly (event-store `pullback`
trigger, `turn_decile >= 0.5`, precomputed `stop_r`: D+1 open entry, stop =
signal-day low or −6%, 5-day time exit), 0.15%/side, 6% heat cap.
Bars were pre-registered in the script docstring before the run; expectation
was NULL.

## Correction to record first: the base is not a +0.20R candidate

`pullback_long.py`'s docstring quotes "+0.20R/event naked". That is the **raw,
pre-cost** figure. Reproduced today: raw avg R **+0.165**, and net of the
house 0.15%/side model it is **−0.160R**. `pullback_long.py` run unchanged
prints −28.7% CAGR / −97.2% maxDD at 0.5% risk. My harness reproduces its
numbers to the digit, so this is not an overlay artifact.

Cause: the trigger is a 20-DMA touch, so the stop sits very close to entry.
Stop distance as % of entry: p10 0.58%, p25 1.07%, **median 1.98%**, p75 3.76%.
Cost in R is `2 × cost_side / stop_pct`, so a tight stop is charged
proportionally more — median cost 0.151R, **mean cost 0.325R**.

| cost/side | net avg R |
|---|---|
| 0.00% | +0.165 |
| 0.05% | +0.057 |
| 0.10% | −0.051 |
| 0.15% (house) | −0.160 |

Breakeven is ~0.07%/side. Cash-equity delivery STT alone is 0.1% on the sell,
before brokerage or slippage. **The trigger does not clear its own costs.**

## The overlay result

| cohort | A 2015-19 | COVID 20-22 | B 2023-26 | 2024-26 |
|---|---|---|---|---|
| ATH-eligible (≤20% off an ATH set ≤252 bars ago) | **+0.238R** (n 1,982) | −0.254R | −0.158R | −0.258R |
| not eligible | −0.048R (n 1,183) | −0.233R | −0.208R | −0.322R |
| control, all pullbacks | +0.131R (n 3,165) | −0.243R | −0.180R | −0.285R |

Gate keeps 53.5% of events. Scorecard against the four pre-registered bars:

1. **Lift ≥ +0.05R in both non-COVID eras — FAIL.** Era A +0.107R, era B
   +0.022R.
2. **Per-year edge positive in ≥7 of 10 — FAIL.** Positive in **6 of 12**
   (2016 +0.151, 2017 +0.121, 2021 +0.111, 2023 +0.046, 2025 +0.035, 2026
   +0.244; negative 2015, 2018, 2019, 2020, 2022, 2024).
3. **Portfolio CAGR ex-COVID improves — PASS.** −25.0/−23.9/−29.3% →
   −18.0/−12.6/−9.9% at 0.50/0.75/1.00% risk. An improvement from
   catastrophic to merely bad; the gate is a loss-reducer, not a
   return-generator.
4. **Neighbourhood flat — FAIL, and instructively so.** Sweeping the
   proximity threshold (no recency clause):

| gate | kept | A 2015-19 | B 2023-26 |
|---|---|---|---|
| within 5% of ATH | 22.7% | **+0.408R** | **−0.273R** |
| within 10% | 45.3% | +0.244R | −0.170R |
| within 15% | 57.3% | +0.214R | −0.167R |
| within 20% | 64.9% | +0.193R | −0.188R |
| within 30% | 76.0% | +0.186R | −0.198R |

   Era A is cleanly monotone — tighter to the high is better, exactly the
   shape the main study found. **Era B inverts it.** A gradient whose sign
   flips between eras is a regime artifact, not an effect. This is the third
   independent confirmation of the main verdict's finding that ATH proximity
   is a 2015-19 phenomenon on NSE.

Depth gradient (O2, ex-COVID) is non-monotone and negative everywhere:
<−30% −0.131R, −30..−20% −0.180R, −20..−10% −0.162R, −10..−5% −0.033R,
−5..0% −0.112R. No usable shape.

## The finding that outlives both

**The pullback edge is unbankable because it clusters.** Take the single best
cell in the whole study — era A, ATH-gated:

| measure | value |
|---|---|
| cohort net avg R | **+0.238R** (n 1,982) |
| avg R of the trades a real book actually took | **−0.052R** (n 514) |
| signals refused by the 6% heat / 5× leverage caps | **74%** |
| peak leverage reached | 5.0× (capped) |
| CAGR at 0.75% risk | −8.0%, maxDD −42.6% |

A 2%-median stop means one position consumes ~1.3× equity of notional at
0.75% risk, so the heat cap admits only a handful at a time — and pullback
signals fire in bunches (many leaders touch their 20 DMA on the same day, at
market lows, which is precisely when the good ones occur). The book is forced
to hold the leftovers. Positive per-trade R, negative book. Any future
tight-stop, cluster-prone trigger must be judged on the **taken subset**, not
the cohort mean.

## Liquidity check — asked mid-run: does a real turnover floor fix it?

Code: `src/backtest/studies/pullback_long_liquidity.py`. `turn_decile` is a
cross-sectional decile, not money, so this sweeps **absolute 20-day average
turnover in ₹cr** (the house scan-layer unit) as well. Ex-COVID, n = 19,159
pullback events with a valid stop:

| floor | n | raw R | median stop | mean cost in R | net R @0.15/0.10/0.05%/side | breakeven /side |
|---|---|---|---|---|---|---|
| none | 19,159 | **+0.240** | 2.00% | 0.315 | −0.074 / +0.031 / **+0.135** | 0.115% |
| ≥ ₹5cr | 14,849 | +0.159 | 1.88% | 0.323 | −0.164 / −0.056 / +0.051 | 0.074% |
| ≥ ₹10cr | 12,354 | +0.125 | 1.81% | 0.333 | −0.208 / −0.097 / +0.014 | 0.056% |
| ≥ ₹25cr | 8,795 | +0.112 | 1.72% | 0.351 | −0.239 / −0.122 / −0.005 | 0.048% |
| ≥ ₹50cr | 6,197 | +0.083 | 1.65% | 0.362 | −0.279 / −0.158 / −0.038 | 0.034% |
| ≥ ₹100cr | 3,915 | **+0.069** | 1.57% | 0.350 | −0.281 / −0.164 / −0.048 | 0.030% |

**A liquidity floor makes this strictly worse, monotonically, and for two
compounding reasons:**

1. **Raw edge falls with liquidity** — +0.240R unfiltered → +0.069R at ₹100cr.
   The `turn_decile` gates say the same thing (≥0.5 +0.213R, ≥0.7 +0.170R,
   ≥0.8 +0.090R, ≥0.9 +0.094R), which is why `pullback_long.py`'s own variant
   C (≥0.8) already scored worse than variant A.
2. **Liquid names have TIGHTER stops, so cost-in-R rises** — median stop
   2.00% → 1.57%, mean cost-in-R 0.315 → 0.362. The one thing you would hope
   a liquidity floor buys you (cheaper slippage) is more than cancelled by
   the stop getting closer to entry, because `cost_R = 2 × cost / stop_pct`.

Net: breakeven cost per side collapses from 0.115% to 0.030%. **Cash-equity
delivery STT alone is 0.10% on the sell.** Even at a very generous
0.05%/side, only the *unfiltered* and ₹5cr cohorts are positive — i.e. the
edge lives in the illiquid tail, precisely where the 0.15% cost assumption is
most justified and where size cannot be deployed. That is an illiquidity
mirage, not a tradeable edge.

Era B 2023-26 alone shows the identical monotone decay (+0.198R unfiltered →
+0.082R at ₹100cr), so this is not an era artifact.

**One genuine signal in here:** the ATH gate's contribution *widens* with
liquidity — ATH-eligible minus not-eligible on raw R is +0.032R (no floor),
+0.033R (₹5cr), +0.066R (₹25cr), **+0.131R (₹100cr, +0.119 vs −0.012)**. On
large, liquid names, ATH proximity is the difference between a small positive
and a negative. It still does not rescue anything — every cell is negative
after costs and every book is −11% to −20% CAGR — but if an ATH-proximity
gate is ever used again, large caps are where to look, not the broad market.

The clustering finding holds at every liquidity level: the heat-capped book's
**taken-subset** avg R is negative (−0.13 to −0.29) in all 20 cells, including
those whose cohort raw R is +0.24.

## Decision

**REJECT the overlay** (fails 3 of 4 pre-registered bars), and **REJECT the
liquidity-floor rescue** (monotonically harmful). Separately,
`pullback_long` should not be carried forward as a live S5 candidate on the
strength of its raw +0.20R: net of realistic cash-equity costs it is −0.16R,
and its heat-capped book is negative in every window tested including
2015-19. Fixing it requires a wider stop (to cut the cost-in-R charge) or a
lower-frequency variant that does not cluster — either is a new spec, not an
overlay.
