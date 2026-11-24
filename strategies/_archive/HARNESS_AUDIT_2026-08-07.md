# HARNESS AUDIT — 2026-08-07

Trigger: three consecutive "dead" verdicts against practitioner claims of real
money made. Question asked: **is the instrument wrong, or the strategy?**

Code: `src/backtest/studies/harness_audit.py`, `harness_audit_retest.py`.

## Headline

**The harness is not systematically broken — but it had three defects, and two
of them changed conclusions.** The single biggest finding is the opposite of
what the question anticipated: once the missing control is added, the strategy
looks *worse*, not better, because most of the measured return was market
beta that nothing was subtracting.

## Diagnostic D0 — is the data corrupt?

Split/bonus breaks in the study cache: **277 day-over-day drops beyond −30%
across 4,069,578 stock-days (0.007%)**, of which 57 carry a 1:2-split
signature and 7 a 1:3. `integrity.py` runs a 22% scan nightly and
`price_breaks_confirmed.json` holds only 2 confirmed genuine breaks. Residual
corruption is real but ~2 orders of magnitude too small to move a 30,000-event
mean. **Not the cause. Data cleared.**

## BUG 1 — sizing model does not match a cash equity account (MATERIAL)

`batch5_fno_portfolio.simulate()` sizes by **fixed-fractional risk**:
`notional = risk_amt / stop_pct`. That is correct for a leveraged F&O book,
which is what it was written for. It is wrong for delivery equity:

- The `pullback` incumbent stop is a 20-DMA touch, median **2% of entry**.
- At 0.75% risk that demands **37% of equity in one position**.
- Five such positions = 185% notional. The sim's 5× leverage cap and 6% heat
  cap then **refuse 74-90% of all signals**.
- A delivery trader does the opposite: fixes *capital* per slot (10 positions
  × 10%) and lets the stop determine risk — a 2% stop on a 10% slot is 0.2%
  of equity, not 0.75%.

Same trades, same period, only the sizing model changed:

| model | taken | CAGR | maxDD |
|---|---|---|---|
| house risk model @0.75% | 1,028 | +10.9% | 33.3% |
| cash capital model, 10 slots | 1,293 | **+16.9%** | **29.4%** |
| cash capital model, 5 slots | 644 | +18.5% | 29.8% |

Higher return *and* lower drawdown. **Every absolute CAGR/maxDD figure I
reported in the three prior studies was computed under the wrong model.**

## BUG 2 — selection order is arbitrary, and its variance swamps the verdicts (MATERIAL)

When the cap refuses most signals, *which* ones get taken is decided by
dataframe row order (symbol index), not by any rule. Identical trade pool,
identical model, only the same-day tie-break order changed:

| tie-break | CAGR | maxDD |
|---|---|---|
| index order (what the sim does) | +16.9% | 29.4% |
| random seed 100 | +10.6% | 38.7% |
| random seed 101 | +18.9% | 24.5% |
| random seed 102 | +8.5% | 47.3% |

**A 10-point CAGR swing and a 23-point drawdown swing from nothing but
ordering.** Over 20 seeds, era-B pullback at a 20-bar hold is median +17.1%
with a p10-p90 band of **+7.6% to +27.9%**.

Consequence: verdicts I stated as single numbers — "+3.7% CAGR", "+2.9% vs
+2.2%", "ret/DD 0.12" — had an undisclosed error bar **larger than the
differences I drew conclusions from**. Fine-grained comparisons between stop
variants were noise being read as signal.

Fix: report a seed distribution, never a point estimate, whenever the sim
skips a material fraction of signals.

## BUG 3 — no random-entry control (MATERIAL, and it cuts against the strategy)

`research/README.md` states the methodological rule this repo "dies on":
*every mover stat is shown against a same-date non-mover baseline*. The
R-based and portfolio-based studies never had one. So nothing was subtracting
the market.

Random long entries, drawn from the same tradeable universe, run through
**identical** exit geometry, sizing and cost model:

| hold | random control | `pullback` | lift |
|---|---|---|---|
| 20-bar, per-trade net R | +0.052 | +0.138 | **+0.087R** |
| 60-bar, per-trade net R | +0.230 | +0.404 | **+0.173R** |
| 20-bar, full-period CAGR | +12.5% | +15.1% | +2.6 pts |
| 60-bar, full-period CAGR | +16.0% | +18.1% | +2.1 pts |

**Most of the return was beta.** A +0.20R result at a 60-bar hold — which the
factory bars would have scored a pass — is *below* the random-entry baseline
of +0.230R.

By era (20-bar hold, capital sizing, 20-seed median):

| window | `pullback` | random | verdict |
|---|---|---|---|
| A 2015-19 | +1.9% | **+5.2%** | pullback **loses** to random |
| COVID 20-22 | **+38.4%** | +19.3% | big genuine win |
| B 2023-26 | +17.1% | +13.2% | small win |
| 2024-26 | +3.9% | +2.4% | wash |
| 2025-26 | **−11.5%** | −3.9% | pullback **loses** to random |

## What this means for the practitioner claim

Both things are true at once:

1. **They probably did make a lot of money, and the harness agrees.** Random
   long entries in this universe returned +12.5%/yr full period and
   +19.3%/yr through COVID 2020-22. Anyone trading almost any long setup in
   2020-2023 made a lot of money. The harness never disputed that — it was
   never asked, because no baseline was ever run.
2. **The setup contributed a few points on top of that, not the whole
   result.** +0.087R to +0.173R per trade, ~+2 points of CAGR — real, small,
   and absent in 2015-19 and 2025-26.

The gap between "I made a lot of money with this" and "the backtest says it's
marginal" is almost entirely the beta that the trader keeps and the control
subtracts.

## Corrections to the three prior verdicts

**Stands — unaffected by all three bugs** (these are counting results or
relative per-trade comparisons, immune to sizing/ordering/beta):
- Lifetime-high + weekly RSI<30 = **1 event in 11.5 years**; weekly RSI p0.1%
  among eligible names = 36.0. Pure arithmetic.
- ATH proximity is a 2015-19 artifact (eligible vs not, same trigger, per-trade).
- Depth gradient runs the wrong way (shallower pullback is better).
- A liquidity floor monotonically reduces raw edge.
- `cost_R = 2 × cost_side / stop_pct` — stop width is a first-order economic
  parameter.

**Withdrawn — computed under the wrong sizing model:**
- "`pullback_long` is −28.7% CAGR / −97% maxDD." That is the leveraged risk
  model. Under capital sizing with a 2×ATR stop and close entry it is
  **+15.1% CAGR full period** (though only +2.6 points over random).
- "Taken-subset R is negative" — an artifact of leverage-constrained
  admission, not a property of the strategy.
- "Wide-stop variant: +3.7% CAGR at 30% DD, ret/DD 0.12." Point estimate
  inside a ±10-point seed band; the correct statement is a distribution.
- My framing "there is no edge underneath to rescue" was too strong. There is
  an edge; it is ~+0.09R at 20 bars, and it is beta-dominated.

**~~Strengthened~~ — SUPERSEDED BY PART 4, see below:**
- ~~The 2025-26 death is now worse-supported: `pullback` returns −11.5% while
  random returns −3.9%, so the setup is actively subtracting value.~~
  **WRONG.** That control was frequency-matched but not DATE-matched, so it
  traded different days. Against a same-date control (Part 4) `pullback`'s
  lift is small but POSITIVE in every era including 2025-26 (+0.03%). The
  correct verdict is "too small to trade", not "negative edge".

## Residual caveat on this audit

The random control is drawn from the ₹5cr-turnover tradeable mask; the
`pullback` cohort is unfiltered and therefore contains more illiquid names.
Since the earlier liquidity sweep showed this trigger's raw edge is *larger*
in illiquid names, that mismatch flatters `pullback` relative to the control.
The measured lift is an upper bound.

---

# PART 2 — fixes built, F&O survivors re-run

Fixes shipped in **`src/backtest/bookrunner.py`** (one module, one job: turn a
trade list into an honest verdict):

- `run_book(..., mode="risk"|"capital")` — risk sizing for F&O where leverage
  is real; equal-capital slots for cash delivery.
- `seed_spread(...)` — ≥20 tie-break orders, returns p10/median/p90 and a
  `banned` flag set whenever the book skips >20% of signals, which is the
  threshold above which a point estimate is dishonest.
- `random_control(...)` — matched random entries: same universe, hold, stop
  rule, side, sizing and costs.

Runner: `src/backtest/studies/fno_survivors_retest.py`.

## Two more bugs found while building it

**BUG 4 — raw R is not comparable across cohorts with different stop widths.**
R is normalised by each trade's own risk, so a 1.3%-stop cohort mechanically
prints larger |R| than a 5%-stop cohort for the same price move. The first
control run showed random shorts at "+0.319R" vs the strategy's +0.175R, which
looks like the strategy losing; on the scale-free measure it is
**+0.49% vs −0.12% gross per trade**, the strategy winning. Any R-vs-R
comparison across different stop geometries is invalid. Compare gross %, or
compare books.

**BUG 5 — an unmatched control runs a different book.** The first control had
21,929 signals against the strategy's 1,392, so it hit the caps constantly
(84% skipped vs 4%) and its CAGR measured capacity constraint, not entries.
Controls must be **frequency-matched** to the strategy. Fixed.

Also fixed: `darvas_box_events.csv` carries tz-aware dates, and
`E.apply_filters`/`E.lookup` match against the tz-naive cache index, so every
lookup silently missed and the Darvas cohort came back **n=0**. Any study
loading a CSV event file must localise to naive *before* filtering.

## Results — the survivors against a matched random control

Primary = risk sizing (correct for F&O). Capital sizing shown as a
confound-free cross-check, since the strategies' stops are 3× wider than the
control's and stop width drives notional under risk sizing.

### S — SHORT the lone loser: **SURVIVES, and it is the real thing**

| window | strategy (risk) | random | strategy (capital) | random |
|---|---|---|---|---|
| full period | **+12.1%** [11.7, 12.5] | −5.6% | +5.3% [5.1, 5.5] | −2.7% |
| A 2015-19 | +7.7% | −3.6% | +4.3% | −2.4% |
| COVID 20-22 | +12.3% | −3.2% | +3.1% | −1.6% |
| B 2023-26 | +17.7% | −9.4% | +8.9% | −4.2% |
| 2024-26 | **+22.2%** | −12.3% | +11.1% | −4.3% |
| 2025-26 | **+21.7%** | −1.9% | +10.3% | −0.8% |

- Positive in **every era, in both sizing models, in 100% of seeds**.
- Random control is **negative in every era in both models, 0/20 seeds**.
- Scale-free gross lift **+0.61%/trade**.
- Skips only **4%** of signals, so the seed band is tight (±0.4 points) and a
  point estimate is legitimate here — the one strategy on the board where it is.
- **Strongest in the most recent era.** This is the opposite of every long
  strategy tested and the only genuine survivor.

### D — Darvas box gated: **DEMOTE. The ret/DD 0.63 does not survive a control**

| window | strategy (risk) | random | strategy (capital) | random |
|---|---|---|---|---|
| full period | +7.4% | **+7.6%** | +3.2% | **+3.0%** |
| A 2015-19 | −0.3% | **+8.4%** | +0.9% | **+3.3%** |
| COVID 20-22 | +19.8% | +3.7% | +7.5% | +1.8% |
| B 2023-26 | +7.2% | **+8.5%** | +3.6% | **+4.6%** |
| 2024-26 | +5.6% | +6.2% | +2.9% | −1.2% |

**Zero lift over random across the full period in both models.** It loses to
random in era A and in 2023-26, and wins decisively only during COVID. The
2024-26 cell is the one place the two models disagree (capital says +4 points
of lift, risk says none), so it is unresolved rather than positive. Darvas was
the board leader; on this evidence it was 60-bar long exposure in a rising
market, not a selection edge.

### B — near-expiry bounce: **REJECT**

Beats random everywhere (capital: +1.2% vs −7.5% full period) but is not
itself profitable when it matters: 2024-26 **−0.1%** (45% of seeds positive —
a coin flip), 2025-26 **−5.1%** vs random −7.8%. Beating a losing baseline is
not an edge you can bank.

### Q — Qullamaggie flag: **FAILS, with a fidelity caveat that must be honoured**

Capital model, full period −0.4% vs random +2.0%; 2024-26 −2.6% vs −0.3%.
Loses to random in four of five windows in both models.

**However — this is not a faithful rebuild of the certified variant.** I used
the event store's `stop_r_trail` ruler (cover half at +2R, trail the 20-day
close low, 60-bar cap). The ledger's +5.6% CAGR / ret-DD 0.37 came from
`fno_qullamaggie.py`'s own native sim (sell half into strength at +1R, then
MA20 trail). Different exit engine. **What this run shows is that the
qm_flag trigger fails under the house trail ruler — it does not refute the
native-exit result.** A faithful re-run through `fno_qullamaggie.py`'s own
simulator against a matched control is still owed.

## PART 3 — the faithful Qullamaggie re-run (debt settled)

Code: `src/backtest/studies/fno_qullamaggie_control.py`. It **imports
`fno_qullamaggie.detect()` and `sim_exit()` unmodified** — the certified
engine, not a reimplementation — and adds the missing control.

The design point that makes this valid: **the random control is run through
the same `sim_exit()`.** Random entry bars, then the identical stop (breakout
low capped 15%), identical sell-half-into-strength at +1R, identical MA20
trail, identical 120-bar cap. So the comparison isolates *entry selection* and
cannot be confounded by exit design — which is exactly what the Part 2
approximation could not claim.

Variant: F&O large cap (PIT rank ≤150), MA20 trail, tape gate pct40ma ≥ 55.

### Per-trade, identical exit engine on both rows

| cohort | n | raw avg R | gross/trade | median stop | median hold | win |
|---|---|---|---|---|---|---|
| strategy, ungated | 1,068 | +0.099 | +0.50% | 4.4% | 8d | 36% |
| strategy + gate55 | 752 | +0.176 | **+0.58%** | 4.5% | 9d | 38% |
| RANDOM + same gate | 752 | −0.016 | **+0.05%** | 1.4% | 1d | 27% |

**Entry-selection lift: +0.54% gross per trade.** That is a real effect, and
it is the first time on this board that a long strategy has beaten a control
sharing its own exit engine.

### Books

| window | strategy (risk) | random | strategy (capital) | random |
|---|---|---|---|---|
| full period | **+7.2%** [6.5, 8.2] | −1.2% | +2.9% [2.4, 3.5] | −0.4% |
| A 2015-19 *(n=56, thin)* | +12.4% | −2.5% | +1.9% | +0.1% |
| COVID 20-22 | +6.6% | −4.8% | +3.2% | −1.4% |
| B 2023-26 | +8.2% | +3.5% | +5.4% | −0.0% |
| **2024-26** | **−4.4%** (0% seeds) | +0.9% | −0.2% (30% seeds) | −0.1% |
| **2025-26** | **−13.3%** (0% seeds) | — | **−5.4%** (0% seeds) | +0.1% |

### Verdict: CONFIRMED-THEN-DIED

This is a materially different finding from the Part 2 approximation, and it
partly **vindicates the ledger**:

- **The edge was real.** 100% of seeds positive full period in both sizing
  models, control negative, and it won every era through 2023 — against a
  control that shared its exit engine. The ledger's +5.6% CAGR / ret-DD 0.37
  was not an artifact. This separates Qullamaggie sharply from **Darvas**,
  which never showed lift over random at all.
- **And it is dead now.** 2024-26 is negative-to-flat in both models; 2025-26
  is −13.3% / −5.4% with **0 of 20 seeds positive** (and only 5-7% skip, so
  that point estimate is legitimate, not noise). The control is flat over the
  same window, so this is the strategy losing, not the market.

Not tradeable today. Keep as a monitored, un-sized candidate: if the tape
regime that supported it returns, the entry selection has been shown to work.

Caveat: era A rests on 56 trades — the +12.4% there is thin. The full-period
and 2023-26 cells carry the weight.

## Board after the audit

| strategy | prior claim | after control | verdict |
|---|---|---|---|
| **S short lone-loser** | ret/DD 0.59 | +12.1% vs random −5.6%, strongest 2024-26 | **CONFIRMED** |
| D Darvas gated | ret/DD 0.63 (board leader) | zero lift full period, loses era A and 2023-26 | **DEMOTE** |
| Q Qullamaggie | ret/DD 0.37 | habitat-split: **+0.63% lift in moderate tape 2024-26**, zero in hot tape | **ALIVE IN PART OF HABITAT** (see Part 4) |
| B near-expiry bounce | passed batch 5 | beats random, unprofitable 2024-26 | **REJECT** |

One tradeable survivor of four, and it is a short.

The Part 3 re-run sharpens the picture rather than simply extending it. There
are now **three** distinct outcomes, not two:
- **Darvas** never beat a random control — it was long exposure in a rising
  market, full stop.
- **Qullamaggie** genuinely beat a control that shared its own exit engine
  (+0.54% gross/trade) and won every era through 2023, then died in 2024-26.
  Real edge, real decay.
- **The short** beat its control in every era and is *strongest* in 2024-26
  and 2025-26.

The common thread stands: every LONG on the board was substantially measuring
the fact that Indian equities rose, and the ones with genuine selection have
lost it in the last two years. A short has to fight the drift to print a
positive number, so beta cannot flatter it — which is likely why it is the
one thing still working.

---

# PART 4 — habitat-conditioned re-test (edge death vs habitat absence)

Prompted by the right objection: *the tape has been unfavourable for longs
since 2024, so "long strategy prints negative" may mean the habitat is absent,
not that the edge is dead.* Parts 1-3 could not tell those apart.

**BUG 7 — a frequency-matched control is not enough; it must be DATE-matched.**
`random_control` draws entries anywhere in the sample. If a strategy only
fires in good tape, its control still fires everywhere, so the two cohorts
face different market paths and a bad era confounds the comparison.
`same_date_control()` (added to `bookrunner.py`) draws, for every signal bar,
K random symbols tradeable on **that same bar**, then runs them through the
**same exit engine**. The control inherits the strategy's date — hence regime —
distribution exactly. This is the rule `research/README.md` already states
("every mover stat is shown against a **same-date** non-mover baseline");
Parts 1-3 used the weaker version.

Code: `src/backtest/studies/habitat_conditioned_retest.py`. Primary metric is
**gross % per trade** (scale-free; R is not comparable across stop widths and
CAGR adds capacity effects that muddy the habitat question). K=3.

## QM Qullamaggie — verdict changes: alive in part of its habitat

Lift over the same-date control, gross % per trade:

| window | n | strategy | control | **lift** |
|---|---|---|---|---|
| full period | 752 | +0.58% | −0.00% | **+0.59%** |
| A 2015-19 | 56 | +0.66% | +0.08% | +0.58% |
| COVID | 347 | +0.48% | −0.02% | +0.50% |
| B 2023-26 | 349 | +0.67% | +0.00% | +0.67% |
| 2024-26 | 225 | +0.25% | −0.04% | **+0.29%** |
| 2025-26 | 73 | −1.00% | −0.32% | −0.68% |

Split by tape strength at signal (`market:pct40ma`) — the test that separates
the two failure modes:

| pct40ma bucket | 2024-26 lift | 2015-2023 lift |
|---|---|---|
| 55-69 (moderate) | **+0.63%** (n=111) | +0.90% (n=184) |
| 70-100 (hot) | **−0.04%** (n=114) | +0.61% (n=343) |

**The edge did not die uniformly — it died in the hot-tape bucket.** In
moderate tape since 2024 the strategy still beats a same-date control by
+0.63%, against +0.90% historically: decayed, but alive. In the strongest
tape it has gone to zero, from +0.61% historically.

Verdict moves from **"dead"** to **"alive in moderate tape, dead in hot tape,
on thin samples."** Caveats that must travel with it: n=111 and n=114 are
small, and while the tape split was pre-registered as a design, *which* bucket
failed is a discovered shape, not a pre-registered prediction. It needs
out-of-sample confirmation before being sized.

## S short lone-loser — the symmetric criticism, answered

The same objection must be applied to the survivor: is a short looking good in
a flat-to-down tape just habitat luck? Lift over the same-date control:

| window | strategy | control | **lift** |
|---|---|---|---|
| A 2015-19 | +0.56% | +0.20% | +0.36% |
| COVID | +0.15% | −0.24% | +0.39% |
| B 2023-26 | +0.81% | −0.03% | +0.85% |
| 2024-26 | +1.01% | −0.04% | **+1.05%** |
| 2025-26 | +1.09% | +0.13% | **+0.96%** |

And within 2024-26, by tape bucket — **positive in all four**:

| pct40ma | 0-39 | 40-54 | 55-69 | 70-100 |
|---|---|---|---|---|
| 2024-26 lift | +0.45% | +0.87% | **+1.73%** | +1.25% |
| 2015-2023 lift | −0.25% | +0.41% | +0.76% | +0.50% |

**Not habitat luck.** It beats a date-matched control in every tape bucket in
the recent era, and it has *improved* in the weakest-tape bucket (−0.25% →
+0.45%). Its absolute magnitude is still flattered by a favourable regime, but
the selection edge is real and regime-independent.

## PB pullback — a prior verdict is WITHDRAWN

| window | strategy | control | lift |
|---|---|---|---|
| full period | +0.40% | +0.27% | +0.13% |
| A 2015-19 | +0.54% | +0.45% | +0.09% |
| COVID | +0.34% | +0.19% | +0.15% |
| B 2023-26 | +0.41% | +0.29% | +0.12% |
| 2024-26 | −0.03% | −0.11% | +0.08% |
| 2025-26 | −0.18% | −0.21% | **+0.03%** |

**Withdrawn:** Part 1's claim that *"`pullback` returns −11.5% while random
returns −3.9%, so the setup is actively subtracting value in the current
era."* Against a **date-matched** control the lift is small but **positive in
every era including 2025-26**. The apparent negative edge was an artifact of
comparing against a control that traded different days.

The corrected reading: `pullback` has a small, remarkably stable lift of
roughly **+0.1% gross per trade** that has never disappeared — and has never
been large enough to build a book on. Tape-conditioned in 2024-26 it is
+0.01 / +0.22 / −0.00 / +0.08 across buckets: not negative, just negligible.
"Too small to trade" is the right verdict, not "negative edge".

## What this changes about how verdicts get written

The user's objection was correct in substance for two of three cases. Going
forward, an era-negative long is **not** grounds for rejection on its own. The
required decomposition is:

1. **Lift over a same-date control** — is there selection at all?
2. **Lift within each habitat bucket** — where does the selection live?
3. **Habitat frequency** — how often does that bucket occur?

Expected contribution = (2) × (3). **Kill only when a strategy fails inside
its own habitat.** A strategy with real lift in a bucket that occurs 30% of
the time is a "size it when the tape is there" candidate, not a reject.

## Required harness changes

1. **Add a capital-sizing book** alongside the risk-sizing one; use the
   capital model for cash-equity strategies and the risk model only for F&O.
2. **Report a seed distribution** (≥20 tie-break orders, p10/median/p90)
   whenever the sim skips >20% of signals. Ban point estimates there.
3. **Make a matched random-entry control mandatory** in every R/portfolio
   study, at the same hold and exit geometry — the same rule
   `research/README.md` already imposes on mover stats.
4. Re-open any prior verdict in `LEDGER.md` whose pass/fail turned on an
   absolute CAGR under risk sizing, or on a difference smaller than the seed
   band. The F&O entries (short breakdown, Qullamaggie, Darvas) used the risk
   model **correctly** — leverage is real there — but their point estimates
   still need seed bands.
