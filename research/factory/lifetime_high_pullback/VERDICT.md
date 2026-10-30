# VERDICT — lifetime_high_pullback        REJECT (S2 empty / S4 + S5 fail) | 2026-08-07

Spec: `SPEC.md` (pre-registered before any run).
Code: `src/backtest/studies/lifetime_high_pullback{,_s3,_s4}.py`.
Data: study cache 2015-01-01 → 2026-07-24, 2,005 symbols, ₹30 price floor,
₹5cr 20-day turnover floor, ≥504 bars of history before any event.

## Plain-language summary

The strategy as literally written **cannot fire**. A stock that is within 20%
of an all-time high it set in the last 12 months essentially never prints a
weekly RSI(14) below 30 — the two filters describe mutually exclusive states.
Over 11.5 years and 64,777 daily base-breakouts, exactly **one** event
satisfied both. This is not a data limitation; it is arithmetic.

Loosening "oversold" until the strategy fires produces something that does
work per-trade but does not survive the controls: the lifetime-high filter
itself has added nothing since 2020, the oversold condition adds nothing
beyond noise year to year, and after position-overlap constraints the book
returns **+1.8% to +2.9%/yr ex-COVID**, below the +3%/yr factory bar.

## S2 — replicate as published: EMPTY

| cohort (identical daily trigger) | events, 11.5 yr |
|---|---|
| **A** lifetime-high **and** weekly RSI<30 (the strategy) | **1** |
| B lifetime-high, any RSI | 15,590 |
| C weekly RSI<30, not lifetime-high | 361 |
| D neither | 17,910 |

Why. Weekly RSI(14) on the signal bar, all L3 base-breakouts:

| cohort | p0.1% | p1% | p5% | p25% | median |
|---|---|---|---|---|---|
| lifetime-high eligible | 36.0 | 42.2 | 47.7 | 56.7 | 64.5 |
| not eligible | 21.0 | 28.0 | 35.2 | 45.2 | 53.3 |

The *one-in-a-thousand* weakest weekly reading among eligible names is RSI 36.
Kill condition 1 in the spec (n < 100 per era) fired at n = 1.

At RSI<40 the strategy yields 12 signals/yr and −0.16R (era A) / +0.06R
(era B) — n = 33 and 52, both below any decision threshold.

## S3 — adaptation the source itself authorises

The source doc leaves the threshold explicitly open ("validate threshold per
stock/sector via backtest"). Two readings tested, both on the identical
trigger, each against its not-eligible twin. Entry = signal close, stop =
pivot low − 2×ATR(14) trailed, 120-bar cap, 0.4% RT.

**REL-10** — weekly RSI in the bottom decile *of the eligible cross-section
that date* ("the strong student had a bad test") — was the only form that
was both flat across its neighbourhood (bottom 10/20/33% → +0.320/+0.318/
+0.312R in era B) and positive in both non-COVID eras:

| variant | A 2015-19 | B 2023-26 | 2024-26 |
|---|---|---|---|
| lifetime-high & bottom-10% weekly RSI | +0.079R (n 268) | **+0.320R** (n 850) | +0.097R (n 663) |
| not-lifetime-high & bottom-10% | −0.250R (n 189) | +0.164R (n 721) | −0.049R (n 528) |
| lifetime-high, no RSI condition | +0.110R (n 2,701) | +0.260R (n 8,540) | +0.019R (n 6,497) |

- **A > C holds**: +0.33R (era A), +0.16R (era B). Conditioning a deep weekly
  pullback on lifetime-high structure does help. This is the one part of the
  interview's thesis the data supports.
- **A > B fails**: −0.03R (era A), +0.06R (era B), both under the
  pre-registered +0.10R bar. Inside the eligible cohort the oversold
  condition is not adding reliable value.

Absolute RSI ceilings (40/45/50/55/60) are not flat — they ramp monotonically
toward the no-condition case, i.e. the "edge" is just sample size returning.

## S4 — red-team of REL-10: FAIL

**1. Per-year edge over the all-lifetime-high control** (the thing that must
be positive if the oversold trigger is real): +0.033, −0.180, −0.005, −0.284,
−0.107, −0.149, +0.086, +0.142, +0.061, −0.087 for 2017→2026. **Four positive
years, six negative.** This is noise, not an effect.

**2. The pullback premise is contradicted.** Within lifetime-high names, avg
net R by distance below the all-time high (ex-COVID): −20..−10% +0.170R,
−10..−5% +0.231R, −5..−2% +0.248R, −2..0% +0.244R. **The shallower the
pullback, the better.** REL-10 by construction sits in the deep bucket
(n 897 at −20..−10% vs n 177 at −10..−5%). Buying deep weekly weakness is
giving up return relative to buying near the high — which is
`ryan_52wk_high` / `pullback_long` territory, not this spec's.

**3. Regime.** ex-COVID: good tape +0.291R (n 901), bad +0.302R (n 89),
neutral +0.033R (n 128). No damaging regime dependence, but n is thin outside
good tape.

**4. Tail dependence.** avg net R +0.262 raw → +0.217 clipped at ±5R → +0.137
at ±3R. **The top 5% of trades contribute 103% of total R** — the other 95%
are net negative. The source predicts exactly this ("~90% of P&L from ~10% of
trades"), so it is not a bug, but it means effective n is ~55 trades, and a
1,118-trade sample is not 1,118 independent observations.

**5. Stop geometry.** Median stop is **14.8% of entry** (pivot low − 2×ATR on
a deep pullback), median hold 65 bars, 72% stopped out. That stop width is
what forces tiny position sizes and kills the economics below.

## S5 — economics: FAIL

Fixed-fractional risk, 6% portfolio-heat cap, risk sized off the real stop:

| window | risk/trade | trades taken | CAGR | max DD |
|---|---|---|---|---|
| ex-COVID | 0.50% | 245 (26/yr) | **+2.9%** | 10.0% |
| ex-COVID | 0.75% | 167 (18/yr) | **+2.2%** | 8.5% |
| ex-COVID | 1.00% | 122 (13/yr) | **+1.8%** | 12.6% |
| 2024-26 | 0.75% | 73 (30/yr) | +3.0% | 5.9% |

Bar is ≥ +3%/yr ex-COVID. It misses at every risk level. Note the skip
counts: **~85% of signals are refused by the heat cap**, because a 14.8%
stop consumes risk budget fast and the signals cluster. Per-trade R does not
convert into a book.

## S6 — style fit

Not reached. (EOD-only, no execution constraint, so it would have passed —
the strategy dies on evidence, not feasibility.)

## What is actually worth keeping

1. **The lifetime-high filter is a 2015-19 artifact.** Edge of eligible over
   non-eligible on the identical trigger, by year: +0.119 (2017), +0.049
   (2018), +0.305 (2019), then −0.127, −0.063, −0.211, −0.003, +0.018,
   −0.004, −0.016 (2020→2026). It separated leaders from junk in the 2018-19
   smallcap bear and has been worthless for six years. Do not add an
   all-time-high proximity gate to any current strategy expecting it to pay.
2. **Distance-below-ATH is monotone the "wrong" way** — closer is better.
   Reinforces the house finding that NSE pays strength entries, not depth.
3. **Deep weekly oversold + lifetime-high structure does beat deep weekly
   oversold alone** (+0.33R / +0.16R). It is the correct *conditioning*
   insight from the interview — it just is not worth more than simply taking
   the lifetime-high breakouts without waiting for the dip.

## Consistency with prior house work

Fully consistent, no contradiction to reconcile:
- `washout_reversal`: dip buys have no edge in good markets → here the
  deep-dip bucket underperforms the shallow one.
- `brief-hypotheses-excovid`: dip-buy positives were COVID-flattered → here
  COVID 2020-22 is the strongest window for every non-eligible cohort.
- `ryan_52wk_high` / `pullback_long`: strength and shallow pullbacks pay;
  this study measures the deep-pullback end of the same axis and finds less.

## Multiplicity

Runs spent on this idea: 1 × S2 factorial (4 cohorts × 2 entry clocks ×
4 ATR multiples, all pre-registered), 1 × S3 (5 absolute + 3 relative
thresholds), 1 × S4 red-team (5 pre-declared checks). 3 scripts, 0 promotions.

## Decision

**REJECT.** Recorded in `LEDGER.md` and ROADMAP → Rejected. Do not re-litigate
without (a) pre-2015 price history that makes "lifetime high" literal, or
(b) a materially different entry mechanic — a mutation of the oversold
threshold is not new evidence.
