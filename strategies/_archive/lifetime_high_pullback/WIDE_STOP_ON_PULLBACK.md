# ADDENDUM 2 — wider-stop variant on `pullback`    MECHANISM CONFIRMED / STRATEGY REJECT | 2026-08-07

Code: `src/backtest/studies/pullback_long_wide_stop.py`. Bars pre-registered in
the script docstring before the run. Trigger unchanged (certified event-store
`pullback`, 31,516 events mapped to the cache); **only the exit geometry
changed**. Entry D+1 open, 0.15%/side, 6% heat cap, 5× leverage cap.

## The mechanism works exactly as predicted

| stop | median stop % | mean cost in R | cohort net R, ex-COVID (5-bar exit) |
|---|---|---|---|
| S0 signal low (incumbent) | 2.11% | **0.308** | −0.071 |
| S1 entry − 1×ATR | 4.15% | 0.079 | −0.039 |
| S2 entry − 2×ATR | 8.30% | 0.039 | +0.003 |
| S3 entry − 3×ATR | 12.44% | 0.026 | +0.008 |
| S5 20DMA − 2×ATR | 10.04% | 0.033 | +0.016 |

Cost-in-R collapses **12-fold** (0.308 → 0.026), and the heat cap stops
strangling the book — the clustering problem from Addendum 1 is genuinely
fixed. Both halves of the hypothesis are confirmed.

*S4 (20DMA − 1×ATR) is degenerate and is excluded from all conclusions:* when
D+1 opens near or below the 20 DMA the risk denominator approaches zero, so
mean cost-in-R reads 1.513 and era-B net R reads −2.7R. That is an artifact of
a near-zero risk denominator, not a result.

## But the 5-bar exit cannot pay a wide stop (as pre-registered)

Every wide-stop variant on the incumbent 5-bar clock has a **positive cohort R
and a negative book**: best is S5 at −1.3% CAGR. Widening a stop without
lengthening the hold just produces a flat, low-R cohort. My pre-registered
expectation on this was correct.

## E20 (20-bar exit) passes all four pre-registered bars

Best variant **S2 = entry − 2×ATR, 20-bar time exit**, ex-COVID:

| bar | result | verdict |
|---|---|---|
| 1. net R positive both non-COVID eras | era A +0.102, era B +0.111 | PASS |
| 2. book CAGR ex-COVID positive | +2.9 / +3.7 / +4.7% at 0.50/0.75/1.00% risk | PASS |
| 3. **taken-subset** R positive | +0.064 / +0.081 / +0.104 | PASS |
| 4. neighbourhood ≥2 adjacent widths | S1 +0.079, S2 +0.109, S3 +0.102, S5 +0.118 | PASS |

The bar-3 pass is the meaningful one — it is the bar the incumbent fails.

## And then it dies on the sub-era check

FACTORY S4 bar (iii): *"2024-26 sub-era shown and not catastrophic — the EP9M
death arrived inside a 'passing' full-period number."* Books at 0.75% risk:

| variant / exit | era A 15-19 | era B 23-26 | 2024-26 | 2025-26 |
|---|---|---|---|---|
| S1 −1×ATR, 20-bar | +8.9% | **+23.8%** | −21.3% | **−30.8%** |
| S2 −2×ATR, 20-bar | +4.9% | +7.1% | +5.2% | **−13.5%** |
| S3 −3×ATR, 20-bar | +0.5% | +8.6% | −2.4% | +0.4% |
| S2 −2×ATR, 20DMA trail | +3.4% | −3.8% | −3.9% | −19.9% |
| S3 −3×ATR, 20DMA trail | +3.2% | +1.3% | −1.1% | −13.3% |

**Cohort net R is negative in 2024-26 for every single variant** (S1 −0.148,
S2 −0.045, S3 −0.005, S5 −0.017). S1's headline +23.8% era B is entirely
2023 — it is −21% and −31% in the two years since. This is the canonical
"passing full-period number hiding a dead edge" the factory exists to catch.

Same shape as every other leadership/pullback long already in the ledger:
alive 2015-19, alive in 2023, dead 2025-26.

## The 20DMA trail is a mis-specified exit — do not read its pooled numbers

Median hold is **2-3 bars**. Entry is a 20-DMA *touch*, so "exit on the first
close below the 20 DMA" fires almost immediately. Its best pooled figure
(+8.7% CAGR at S2) is carried by era A and COVID; era B is −3.8%. Reported for
completeness only; any future trail on this trigger needs an arming condition
(e.g. trail only after +1R) before it means anything.

## Economics (S5 bar) — technically clears, not payable

S2/E20 at 0.75% risk ex-COVID: **+3.7% CAGR at 30.1% max drawdown**, ret/DD
**0.12**. The house bar is ≥+3%/yr, so it scrapes through on return — but
against the existing board (Darvas ret/DD 0.63, F&O short 0.59, Qullamaggie
gated large-cap 0.37) it is the worst candidate measured. S3 is the only
comfortable-drawdown cell (+0.5%/12.6% era A, +8.6%/22.6% era B) and it is
−2.4% in 2024-26.

## Secondary clock

Signal-close entry (20-bar exit, ex-COVID) is better than D+1 open at every
width — S1 +8.6%, S2 +5.2%, S3 +4.2% CAGR vs S0 +8.0% — consistent with
FACTORY lever 1. It does not change the sub-era verdict.

## Decision

**Mechanism: CONFIRMED and reusable.** `cost_R = 2 × cost_side / stop_pct`
means stop width is a first-order economic parameter, not a risk detail. A
2%-stop trigger pays a 0.31R toll per trade and needs ~1.3× equity of notional
per position; widening to 2×ATR cuts the toll 8× and de-clusters the book.
**Apply this check to any tight-stop trigger before judging it.**

**Strategy: REJECT.** The wider stop fixed the engineering problem and
revealed there is no current edge underneath to rescue. Positive 2015-19,
positive 2023, negative 2025-26 in every variant. `pullback` should not be
promoted; if revisited, it needs a fresh entry mechanic, not new exit
geometry — exit geometry has now been swept and is not the binding constraint.
