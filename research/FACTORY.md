# FACTORY.md — the strategy factory

One repeatable pipeline that turns a strategy idea — ours, or a published
trader's — into either a live strategy adapted to the user's style, or a
documented rejection that never gets re-litigated. This is the layer ABOVE
`research/PROGRAM.md` (mover studies feed hypotheses into it) and it reuses
the existing machinery at every stage; the factory adds **order and pass
bars**, not new engines.

**The core lesson the factory encodes** (from 46 studies, 2026-07): published
strategies mostly fail as published on NSE, the fix is usually the entry
clock, the danger is post-hoc pockets and COVID flattery, and a per-trade
edge is not a system until frequency × size × exposure says so. Every stage
below exists because some study died at that stage.

## Pipeline

| stage | question | tooling | artifact |
|---|---|---|---|
| S0 Source | what is the claimed edge? | `/trader-setup-researcher` skill → `docs/<trader>_trading_setup.md`; or own hypothesis / article claim | rules doc |
| S1 Spec | exact, point-in-time testable rules — written BEFORE any backtest | copy the template below | `research/factory/<slug>/SPEC.md` |
| S2 Replicate | does it work as published? | `src/backtest/studies/` + `common.py` cache + `report_full.py` | study md/pdf, verdict |
| S3 Adapt | do the four proven levers flip or improve it? | same harness; ≤3 pre-registered variants per knob | variant table |
| S4 Robustness | is it real? | era splits, nulls, neighborhoods (bars below) | pass/fail per bar |
| S5 Economics | does it pay as a book, not per trade? | portfolio sim (`ep9m_portfolio.py` pattern), Monte Carlo DD | ₹/year estimate |
| S6 Style fit | can THIS user actually trade it? | `research/factory/STYLE.md` | fit line in VERDICT |
| S7 Incubate | does live match backtest? | wire into `daily_state.py` scans + `/brief` (paper tag); `grade_decisions.py` watches | grader rows |
| S8 Live + monitor | is the edge still alive? | small size at regime knobs; edge-death monitor | rolling-R chart |

Every stage appends one line to `research/factory/LEDGER.md`. A strategy may
die at any stage; record the death in the ledger AND in ROADMAP's Rejected
section with the stage and reason.

### Local experiment index (optional)

`src/backtest/experiment_tracking.py` can index a completed run in local SQLite MLflow
with its spec/data fingerprints and path-only artifact manifest. It is a search
and reproducibility aid, not a promotion workflow: `research/factory/LEDGER.md`
remains append-only and is the authority for factory stage and verdict. Start
from `research/experiment_manifest.template.json`; validate without writes via
`PYTHONPATH=src python -m backtest.experiment_tracking manifest.json --dry-run`.

## S1 — the spec template (pre-registration)

```
# SPEC — <slug>            status: S1 | date | source doc
Claimed edge + WHY it should exist (who is on the other side of the trade?)
Universe / liquidity floor:
Event definition (point-in-time, exact):
Entry variants (max 3, name them now): e.g. D+1 open / signal-close + range_pos>=0.75 / ORH
Stop:                Exits:
Costs: 0.4% round trip default
Eras: A 2015-19, B 2023-26, COVID 2020-22 reported separately, 2024-26 sub-era shown
Success bars (write numbers NOW): S2 bar, S4 bars, S5 bar
Style expectations: est. win rate, hold, signals/yr — checked against STYLE.md at S6
```

Nothing may be added to the spec after results are seen. New ideas from the
results = a new spec (that is what killed the gap-quality composite and the
DEP young-base pocket: both were shapes noticed in the output).

## S3 — the four proven adaptation levers (in this order)

1. **Entry clock.** D+1 open is the house loser (9/10 champions negative).
   Test: signal-day close + strong-close gate (`range_pos >= 0.75`), and for
   gap/news setups the 09:15-09:35 opening-range-high with low-so-far stop.
2. **Exit shape must match the tail.** Burst-type edges pay at 3-5 days with
   scale-out; trend-tail edges (Ryan/Minervini/Darvas) pay at 20-60 days with
   a trail and ~70% stop-outs. Stop GEOMETRY barely matters (both exit grids);
   do not sweep stops looking for magic.
3. **Universe floors.** ₹5cr turnover default, ₹10cr for EP-type; quiet
   (low-ATR) names for slow systems (Donchian lesson).
4. **Delete inverted confirmations.** On NSE these measured neutral-to-harmful:
   >3x breakout volume, volume dry-up, EP novelty gate, "avoid 3+ up days",
   tighter-flag preference. RS floors help only at D+20+ horizons.

Anything beyond these four levers is a mutation → back to S1 as a new spec.
**Style-driven mutations too**: shortening a 60-day edge to fit a 5-day
preference is a NEW strategy that must re-earn S2-S5; if it fails, the honest
output is "does not fit this user — pass", not further mutation.

## S4 — robustness bars (all required)

- Era A AND era B profitable ex-COVID (PF > 1 both; COVID shown separately).
- 2024-26 sub-era shown and not catastrophic (the EP9M death arrived inside
  a "passing" full-period number).
- Parameter neighborhood flat (a knob that only works at one value is luck).
- **Random-recipe null** whenever features/filters were *selected*: beat ≥95%
  of ~500 random same-arity recipes (`gap_quality_oos.py` is the pattern).
- Effective N = episodes/regime-blocks, not days; block bootstrap for
  overlapping windows (ROADMAP item-5 guards).
- Multiplicity: the ledger counts every variant ever run against this idea.

## S5 — economics bar

Expected annual contribution ≈ signals/yr × avg R × risk-per-trade at
NORMAL-tier knobs, haircut for overlap/capacity. Default bar: **≥ +3%/yr**
expected on trading capital, after 0.4% RT costs, with Monte Carlo
P(DD > 20%) acceptable. Canonical fail: DEP young-base — PF 1.48, 27
signals/yr, 0.2% CAGR. PF is not payable; frequency × size × exposure is.

## S6 — style fit

Check against `research/factory/STYLE.md`. Hard-constraint fail (execution
infeasible: needs API speed, mid-day screen, cash shorting) = REJECT for
style regardless of edge. Soft mismatches (win-rate discomfort, hold horizon)
= size one tier down per mismatch, or pass. The fit line is mandatory in
every VERDICT.md.

## S7/S8 — incubation and the edge-death monitor

Incubation: candidates flow through the existing daily state + /brief with a
`paper` tag; `grade_decisions.py` accumulates forward returns. Promotion bar:
≥30 graded signals or 8 weeks, live grades inside the backtest band, no
mechanical-execution surprises.

Live: every factory strategy gets a **rolling 30-event avg-R monitor** and a
per-year trend line. Two consecutive negative windows → back to incubation
size. Lesson encoded: EP9M went +1.48R (2023) → −0.19R (2026) while event
count ROSE — breadth/regime gates cannot detect setup-level edge death; only
per-strategy outcome tracking can.

## Copying a trader — the flow

1. User names a trader (or drops a video/blog) → `/trader-setup-researcher`
   compiles `docs/<trader>_trading_setup.md`.
2. One SETUP at a time becomes an S1 spec (traders bundle many setups; the
   factory processes setups, not personas).
3. S2 replicate as published — **expect FAILS at D+1 open; that is normal,
   not disqualifying** (it killed 9/10 champions before adaptation).
4. S3 levers → S4/S5/S6 decide → incubate or record the death.

## Agent execution contract

- Each stage of each strategy is one subagent task; parallel strategies run
  in separate git worktrees; all use the same harness and report template —
  comparability across runs is the asset (autoresearch rule).
- Batches of ≤ ~10 hypotheses; at most 1-2 promotions per batch no matter
  how many "pass"; every run appends to LEDGER.md (multiplicity accounting).
- Bias rules of `research/PROGRAM.md` apply verbatim (look-ahead, baseline
  controls, circuits/tradability, catalyst coverage, lucky-lift discounting).
- Feature/context research (the ML program: odds tables → logistic → GBM,
  judged by within-date lift + calibration + economic replay) is the S3/S4
  research engine and runs under this same contract and ledger.

## Seed state (2026-07-29) — where existing work already sits

| strategy | stage reached | verdict so far |
|---|---|---|
| ryan_52wk_high | S3 (close-entry variant measured) | MIXED→promising: PF 0.70/0.97 at open → 1.59/1.46 at close+gate; needs S5 economics + S6 |
| minervini_trend_template | S3 partial | +0.47R tail edge, RS 80-100 carries it; n=176 — needs S5 |
| stockbee 4% burst | S3 | marginal: 1.17/1.16 at close+gate; S5 doubtful |
| EP9M (EOD) | S8 death case | edge died 2024-26 in all 40 exit variants; keep as monitor lesson |
| EP intraday ORH | S2 (look-ahead caveat) | +4.13%/trade 2024-26; needs live-selection proxy → separate live task |
| washout leader bounce | S2 | bad-markets-only context edge; beta caveat; feeds regime, not a standalone book |
| kell / pocket_pivot / HTF / connors / darvas / donchian-S1 / weinstein | rejected at S2 | see MASTER_SUMMARY.md; do not re-run without a new entry mechanic |
| dan_zanger | S0 only | docs/dan_zanger_trading_setup.md exists, never spec'd — first clean S1 candidate |

Pre-factory verdict details: `output/studies/MASTER_SUMMARY.md` + individual
study reports. The ledger starts empty; history stays where it is.
