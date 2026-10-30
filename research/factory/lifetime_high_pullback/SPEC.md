# SPEC — lifetime_high_pullback     status: S1 | 2026-08-07 | user-supplied rules doc from YouTube interview "What I Did To Become a Millionaire Trader" (https://www.youtube.com/watch?v=s-nNC0idizE)

## Claimed edge + WHY it should exist

Three nested timeframes. **Monthly:** only stocks whose most recent major
pivotal high is a *lifetime* high are eligible — a stock still far below a
high made years ago is range-bound, not trending, and inflation alone should
have roughly doubled it every ~8 years. **Weekly:** inside that eligible set,
wait for weekly RSI to go oversold — "the strong student had a bad test."
**Daily:** enter on the first breakout out of a small base (≥5-6 sessions with
no new low, reversal candle present). Stop = prior swing low − 1–3× ATR(14),
trailed; no fixed target.

Who is on the other side: dip-buyers who screen on *cheapness* (oversold RSI,
% off high) without conditioning on structural trend, and who therefore buy
the Yes Banks and Vodafone Ideas of the market alongside the Titans and SBIs.
The claim is that the oversold signal is only tradeable when the underlying
structure is a lifetime-high uptrend.

Credibility: an interview, not a track record. The source gives a philosophy
and a filter logic, not a rulebook; the numeric parameters below are OUR
translation into testable form, explicitly flagged as such by the user.

## Honesty preamble — overlap with existing house work

This is **not** a fresh idea in this repo and the ledger must not double-count
it. Prior overlapping results, all of which constrain the prior here:

- `ryan_52wk_high` (S3): 52-week-high base *breakout*. MIXED→promising, but
  that is a **strength** entry, not a pullback entry. Different trigger.
- `multiyear_high_sector_cluster` (S1): the same multi-year-high eligibility
  bar, with a *first-pullback* entry variant (V3) spec'd but never run. This
  spec's V-A/V-B triggers are close cousins; S2 must report the overlap.
- **`washout_reversal` (memory: washout_reversal_study)**: 3-down-day dip buys
  have **no edge in good markets**; the bounce edge appears only in bad
  markets on leader washouts. This is the single most damaging prior.
- **`setup-conditions-habitat`**: dip-buys only paid in strong-TI65 markets.
- **`brief-hypotheses-excovid`**: "market-TI65 dip-buy" was demoted as
  COVID-flattered. Any dip-buy result that lives in 2020-22 is presumed dead.
- `pullback_long` (S5): leader touching rising 20DMA, +0.20R naked. That is a
  *shallow* pullback; weekly RSI < 30 is a much deeper one. Genuinely
  different depth regime — this is the main thing that is new here.

What is genuinely new and is what this spec actually tests:
1. **Weekly-timeframe oversold** as the trigger clock (house dip work has all
   been daily-timeframe).
2. The **conditioning interaction**: does lifetime-high eligibility rescue a
   deep-oversold buy that is otherwise known to be a loser?
3. **ATR-multiple stop-and-trail geometry** on a pullback entry.

## Universe / liquidity floor

All NSE EQ in the study cache. Price ≥ ₹30, 20-day avg turnover ≥ ₹5cr
(house default), ≥ 130 bars of history for tradeability, and additionally
**≥ 504 bars (2 years) of stored history** before any event so that the
running-maximum "lifetime high" is not computed off a stub series.

**Known limitation, stated before results:** our history starts 2015-01-01.
"Lifetime high" is operationally "highest close since 2015 (or since listing)".
A stock that topped in 2008 or 2010 and is 60% below that level can still be
marked eligible here. This biases the eligible cohort toward *more* names than
the true rule would allow, i.e. it makes the filter look **weaker** than it is,
not stronger. Directional bias is therefore conservative for the filter.

## Event definition (point-in-time, exact)

All conditions evaluated at the close of bar `t` using data ≤ `t`.

**L1 — lifetime-high eligibility (the "monthly" filter):**
- `ath[t] = max(close[0..t])` (expanding max, point-in-time)
- `eligible[t] = (close[t] >= 0.80 * ath[t]) AND (bars since ath was last set <= 252)`
- The second clause implements "reject a stock whose ATH was set >2 years ago
  and is still well below it"; combined the two clauses mean *made an all-time
  high within the last 12 months and is within 20% of it*.

**L2 — weekly oversold:**
- Resample close to weekly (W-FRI), Wilder RSI(14) on the weekly series.
- Map back to daily using **only completed weeks** (value as of the prior
  Friday, forward-filled). No in-progress-week value is ever used.
- `oversold[t] = weekly_rsi[t] < 30` (primary). Neighborhood: 35, 40.

**L3 — daily base + breakout:**
- `pivot_low[t] = min(low[t-24..t])`; `bars_since_pivot_low[t] >= 6`
  ("no new daily low for at least 5-6 candles").
- `reversal_candle` = any of {hammer, bullish engulfing, bullish harami} on any
  of the last 6 bars. Definitions fixed in code before running.
- `breakout[t]: close[t] > max(high[t-6..t-1])` — first close above the base high.
- Dedup: drop an event if the same symbol had a kept event within 10 bars.

## Entry variants (max 3, named now)

- **E1 — D+1 open** (the published/naive clock; house expectation: this loses).
- **E2 — signal-day close** with strong-close gate `range_pos >= 0.75`
  (FACTORY lever 1).
- **E3 — signal-day close, no gate** (to separate the gate's contribution
  from the clock's).

## Stop / exits

- Stop = `pivot_low − k × ATR(14)`, k ∈ {0, 1, 2, 3}. k=0 is the naked swing
  low and is the control.
- Trail: recompute `rolling_min(low, 25) − k × ATR(14)` each bar, ratcheting
  up only. No fixed target (source is explicit: "upside undefined").
- Max hold 120 bars (trend-tail horizon per FACTORY lever 2).
- Fixed-horizon returns (D+1/5/20/40/60) also reported for comparability with
  every other study in this repo.

## Costs

0.4% round trip, applied in the R/economics tables.

## Eras

A = 2015-2019, COVID = 2020-2022 (**reported separately, never pooled into the
verdict**), B = 2023-2026, plus a 2024-2026 sub-era shown explicitly.

## The controls that decide this (mandatory, pre-registered)

The headline number is meaningless alone. The verdict rests on a **2×2
factorial** on the identical L3 daily trigger:

| cohort | L1 lifetime-high | L2 weekly oversold |
|---|---|---|
| **A** (the strategy) | yes | yes |
| **B** | yes | no |
| **C** | no | yes |
| **D** | no | no |

- **The lifetime-high filter earns its keep only if A > C** (and B > D).
- **The weekly-oversold trigger earns its keep only if A > B** (and C > D).
- Plus a same-date universe-median baseline for every horizon.

If A is profitable but A ≈ C, the ATH filter is decoration and the finding is
"deep weekly pullbacks work", not "lifetime-high pullbacks work".
If A is profitable but A ≈ B, the RSI trigger is decoration and this collapses
into the already-known `ryan_52wk_high` family.

## Success bars — written NOW

- **S2 bar:** cohort A avg net R > 0 at the best of E1/E2/E3, in **both** era A
  and era B ex-COVID, at n ≥ 100 per era. Fail = replicate FAIL.
- **S4 bars:** (i) A > C and A > B by ≥ 0.10R in both eras — otherwise the
  finding is downgraded to whichever single factor carries it; (ii) parameter
  neighbourhood flat across RSI 30/35/40 and k 1/2/3 (no single-value spike);
  (iii) 2024-26 sub-era not catastrophic.
- **S5 bar:** ≥ +3%/yr expected on trading capital after costs at NORMAL-tier
  risk, with signals/yr high enough to matter. Frequency is a live worry: a
  near-ATH stock printing weekly RSI < 30 is rare by construction; if
  signals/yr is in single digits this dies at S5 regardless of per-trade R.

## Style expectations (checked at S6)

Est. win rate 35-45%, hold 20-60 bars, signals/yr **unknown and the main risk**.
EOD-only, no intraday execution needed → no hard-constraint style fail expected.

## Pre-registered kill conditions

1. n < 100 in either non-COVID era at RSI<30 → the strategy is untradeable as
   specified; report frequency and stop (do not loosen RSI to manufacture n
   and then present that as the finding — that becomes a new spec).
2. A ≈ C → record as "lifetime-high filter adds nothing", do not promote.
3. Edge concentrated in 2020-22 → dead on arrival (the house COVID rule).
