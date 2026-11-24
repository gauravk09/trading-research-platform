# SPEC — nifty_roc30_dual_momentum        status: S1 | 2026-08-06 | reddit_x_strategy_ideas.md #4 (doc's own #3)

Source: `scratchpad/reddit_x_strategy_ideas.md` candidate #4 ("Dual momentum
NIFTYBEES / GOLDBEES", ValuePickr forum 2015). Claimed edge: absolute
momentum (a rolling rate-of-change filter) keeps you out of the index during
extended downtrends, avoiding the worst of the drawdown; parking in an
uncorrelated asset (gold) during risk-off periods should outperform holding
cash outright. Who is on the other side: buy-and-hold investors who ride the
full drawdown of a multi-month index bear leg that a trend filter would have
sidestepped — the standard time-series-momentum story. Credibility: HIGH for
a forum thread — a second, independent poster rebuilt the backtest from Yahoo
data and got a similar result to the original author's Amibroker run.

## Honesty preamble

- **Original claimed backtest (2008-2015) predates our data entirely.** Our
  index series (`data/parquet/indices/nifty50.parquet`) starts ~2015. This
  spec is a NEW out-of-sample test of the same rule from 2015-2026, not a
  replication of the source's 16.45% CAGR / -18.4% maxDD number. Frame all
  S2 results as "does the rule work 2015-2026," never as "we matched them."
- **No gold / GOLDBEES series in the platform.** The risk-off leg is proxied
  as cash, exactly as the source's own "TESTABLE-HERE" note suggests. This
  tests a *weaker* claim than the original (absolute-momentum timing alone,
  no relative-strength choice between two assets) — a FAIL does not fully
  falsify the gold-based original, and a PASS likely *understates* it, since
  gold's diversification value shows up most in exactly the inflationary/
  crisis regimes this cash-proxy can't capture.
- **NIFTYBEES itself is not held** — `nifty50.parquet` (real index OHLC,
  not a proxy series) stands in for it. NIFTYBEES tracks Nifty50 almost
  exactly; tracking error and the ETF's own liquidity are assumed away.
- **The stock-selection extension is untestable as specified.** The source's
  add-on ("when Nifty ROC>3 and > gold ROC, buy fundamentally sound stocks
  breaking out with weekly ROC(20)>30 and good volume") needs a *weekly*-bar
  ROC(20) feature that does not exist in `data/processed/features/` (all
  existing triggers — burst, four_pct, ep, bounce, pullback, four_pct_down —
  are daily-bar mechanics). Building a new weekly-return feature is out of
  scope here (we are not modifying the event store); this leg is marked
  **UNTESTABLE**, not proxied.
- **The regime-gate-equivalence question cannot be posed as a
  `research/machine/engine.py` spec.** engine.py's `market` condition type
  is hard-coded to `{score, pct40ma, ratio10, net4, net25q}` — there is no
  slot for an arbitrary computed index-ROC series without editing engine.py,
  which is out of scope. Instead, the S2 step below includes a plain pandas
  side-comparison (not a machine spec, no engine change) of this rule's
  on/off calendar against `mm_history.parquet`'s `regime_tier`/breadth score
  for the same dates — answering the doc's own theme-1 question ("does the
  crude ROC gate capture what the house breadth regime captures") without
  touching the fixed evaluator.
- **Event-count bars don't transfer.** This system trades a handful of times
  across 11 years (regime flips only), not hundreds of stock-level events —
  engine.py's `MIN_N=200/era` bar is calibrated for stock-trigger cohorts and
  does not apply. Substituted bar (written now, S4 section below): require
  >= 2 regime flips in era A and >= 2 in era B, each individually inspectable
  by eye, not a statistical N-count.

## Universe / liquidity floor

Single asset: Nifty50 (via `nifty50.parquet`). No stock-level universe.

## Event definition (point-in-time, exact)

Weekly (Friday close), compute `ROC_30w = close_this_week / close_30_weeks_ago - 1`
on Nifty50 weekly-resampled closes.
- `ROC_30w > 3%` → fully invested in Nifty50.
- `ROC_30w <= 3%` → flat (cash proxy for gold, see above).

## Entry variants (max 2 — this is a single-signal timing system, not a
multi-clock entry problem)

- V1 **Monday open** execution of the Friday-close signal (realistic lag).
- V2 **Friday close** execution (no-lag, optimistic control — bounds how
  much the weekend lag costs).

## Stop / Exits

None — this is a binary allocation switch, not a stop-based trade. Exit IS
the next signal flip to `ROC_30w <= 3%`.

## Costs / Eras

0.4% round-trip default per switch (house-standard convention; flag this is
conservative for a single liquid index-ETF switch a few times a year — real
cost would likely be lower, but we keep the house default rather than
inventing a favorable number). Eras: A 2015-19, COVID 2020-22 (reported,
never judged), B 2023-26, 2024-26 sub-era shown.

## Success bars (written now)

- S2: V1 must beat buy-and-hold Nifty50 on a **CAGR/maxDD basis**, with
  demonstrably shallower maxDD through the COVID crash and any other >15%
  index drawdown in-sample — that is the entire mechanism being tested.
  Also run the mm_history side-comparison described above and report the
  overlap % of "gate ON" weeks between this rule and the house's own
  `regime_tier`/breadth score.
- S4: substituted bar — >= 2 regime flips each in era A and era B, both
  individually reviewed (not just counted); 2024-26 sub-era result shown
  even if only 0-1 flips occurred in it (report as INSUFFICIENT if so,
  rather than silently omitting it).
- S5: must beat plain buy-and-hold Nifty50 by more than round-trip costs,
  on a drawdown-adjusted basis, to be worth the switching complexity at all
  — this is a stricter bar than the generic "+3%/yr" STYLE.md floor, because
  the alternative (just holding the index) is nearly free.

## Style expectations

Est. signal frequency: a handful of flips across 11 years — this is a
buy-and-forget overlay, not a swing-trading signal, and sits outside
STYLE.md's hold-horizon/win-rate framing entirely (it's an allocation
switch, not a trade book). S6 should treat it as a capital-allocation
decision, not score it against the win-rate/DD tolerances built for the
stock-picking sleeves.
