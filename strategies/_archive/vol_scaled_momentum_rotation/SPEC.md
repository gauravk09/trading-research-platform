# SPEC — vol_scaled_momentum_rotation        status: S1 | 2026-08-06 | reddit_x_strategy_ideas.md #3 (doc's own #2, with #4 folded in as V2)

Source: `scratchpad/reddit_x_strategy_ideas.md` candidate #3 ("Smallcap
momentum rotation with regime hedge", sysedge, r/IndianStreetBets), with the
Nifty200-Momentum-30 clone (candidate doc's own #4, BacktestIndia) folded in
as variant V2 since both are the same top-N vol-scaled-momentum, equal-weight,
periodic-rebalance mechanic on a different universe/cadence. Claimed edge:
cross-sectional momentum persists in NSE smallcaps; scaling the score by
short-term volatility avoids chasing the most erratic movers; a trend-based
index exit sidesteps the deep bear drawdowns that plain momentum systems
suffer. Who is on the other side: momentum systems monetize under-reaction to
trend continuation (buyers who wait for "proof" before entering, sellers who
hold losers too long) — this is the standard cross-sectional momentum story,
now tested on NSE.

## Honesty preamble

- **AMFI point-in-time smallcap classification: not available, proxied.**
  We only have PIT market cap (`pit_mcap.parquet`, `mcap_decile.parquet`),
  not the AMFI large/mid/small bucket assignment used by the source. SEBI's
  own convention ranks by full-market average mcap: large = rank 1-100,
  mid = 101-250, small = 251+. Universe here is defined as **PIT mcap rank >
  250 among all NSE EQ names with >= ₹5cr 20d turnover** (excludes the
  large/mid tier by rank, not by decile threshold — decile bucketing was
  considered and rejected because deciles shift size with universe growth
  over 2015-2026 while a fixed rank cutoff does not). This is the closest
  achievable proxy; it will not exactly match AMFI's official classification
  list, particularly around the 250th-rank boundary.
- **Gold leg: unavailable, proxied as cash.** No gold/GOLDBEES series exists
  in the platform. Matches the source's own "TESTABLE-HERE" admission.
  Flag: this proxy likely UNDERSTATES the source's true system, since gold's
  main value-add is precisely in the risk-off windows this test approximates
  with plain cash.
- **Rebalance cadence: source says "periodically," unspecified — WE choose
  weekly** (Friday-close signal, Monday-open execution) as the primary
  cadence, since it pairs naturally with the weekly-Supertrend regime check.
  This is our assumption, not the source's; a monthly-cadence sensitivity
  check belongs at S3, not S1.
- **Exit-rank-buffer bookkeeping is stateful across time** (a holding is only
  sold when its rank crosses 50, not on every rebalance) — this cannot be
  expressed in `research/machine/engine.py`'s per-event trigger/condition
  schema (that engine grades fixed-entry, fixed-horizon events, not an
  evolving portfolio). This is why the whole strategy is a **factory spec**,
  requiring a bespoke portfolio backtest in the `src/backtest/studies/
  ep9m_portfolio.py` pattern (FACTORY.md S5), not a machine experiment.
- **STYLE.md tension, flagged now for S6:** weekly rebalancing of up to 15
  manually-punched positions is heavier than the user's preferred alert-
  driven overnight-swing workflow (STYLE.md: manual Kite execution, no order
  API). This is a real S6 risk regardless of the measured edge.

## Universe / liquidity floor

V1 (sysedge-style): PIT mcap rank > 250, ₹5cr 20d turnover floor.
V2 (Momentum-30-style): PIT mcap rank <= 200 (large/mid), PAT > 0 quality
filter (from `financials.parquet`, point-in-time on `filing_date`) — a
genuinely different, non-smallcap universe, reported separately, not blended
into the V1 result.

## Event definition (point-in-time, exact)

**Momentum score** (V1): `0.6 x ret_126 + 0.3 x ret_63`, divided by the
trailing-20-day stdev of daily returns (our choice for "short-term
volatility" — the source doc does not specify a window). `ret_126`/`ret_63`
are already-available `derived` condition types in engine.py's own
vocabulary (close/close.shift(n) - 1); reused here only as a *definition*,
not run through engine.py (this is a portfolio sim, see above).

**Momentum score** (V2, Momentum-30 clone): `ret_252 / stdev(daily returns,
252d)`. Semi-annual rebalance (Jan/Jul), as documented by the source.

**Rank & hold** (V1): rank eligible names by score, descending. Hold top 15,
equal-weight (1/15 each). Keep a holding while its rank stays <= 50; the
first Friday its rank is 51+, sell 100% Monday-open and buy the highest-
ranked eligible name not currently held.

**Rank & hold** (V2): top 30, equal-weight, no exit-rank buffer (as
published), rebalanced fully every 6 months.

**Regime gate** (V1 and V2): weekly Supertrend(10, 3) computed on
`data/parquet/indices/nifty500.parquet` real weekly-resampled OHLC — this is
literal, not a proxy (we have genuine index OHLC back to ~2015). When the
weekly close is below the Supertrend line, liquidate to cash; re-enter on
the first weekly close that reclaims it.

## Entry variants (max 3)

- V1 core — as above, weekly rebalance, Monday-open execution.
- V1b execution-lag control — same signal, Friday-close (no-lag) execution,
  to bound how much the weekly lag costs (FACTORY entry-clock discipline,
  adapted to a portfolio context).
- V2 Momentum-30 clone — semi-annual rebalance, large/mid universe, reported
  as a separate universe test, not a smallcap variant.
- V3 quality overlay — V1 + exclude the top quartile of `volc5_50` (scaled
  turnover; existing feature) at each rebalance, testing the source doc #4's
  "Quality Momentum" claim that low-turnover names cut drawdown.

(4 named above; V1/V1b count as one entry-clock pair per FACTORY's "max 3"
intent — V2 and V3 are the two independent levers under test.)

## Costs / Eras

0.4% round-trip default (conservative for a liquid-name rotation; flag that
real ETF/large-name switching costs would likely be lower). Eras: A 2015-19,
COVID 2020-22 (reported, never judged), B 2023-26, 2024-26 sub-era shown.
Source's own claimed backtest window (2018-2026, 8 years, PIT AMFI lists,
delisted names named: DHFL/Sintex/RCom) partially overlaps our era A/COVID/B
split — report the overlap window's numbers alongside the full 2015-2026
run, but do not claim to "match" the source's number (universe proxy and
gold-vs-cash substitution guarantee a different result).

## Success bars (written now)

- S2: V1 CAGR/maxDD ratio must beat plain buy-and-hold `smallcap250` over
  the same window, AND the weekly-Supertrend-gated equity curve must show a
  materially shallower maxDD than an ungated version of the same rotation
  (isolating the regime gate's actual contribution, per the source's own
  claim that this is where the edge is). Report V2 and V3 as auxiliary,
  not gating, results.
- S4: era A and B profitable ex-COVID; 2024-26 sub-era not catastrophic;
  random-recipe null does not apply (this is a fixed pre-registered rank
  rule, not a screened factor) — note explicitly in the S4 report rather
  than silently skipping it; block-bootstrap on non-overlapping annual
  blocks given weekly-rebalance serial overlap.
- S5: >= 3%/yr contribution on ₹10L (STYLE.md bar), Monte Carlo P(DD>20%)
  acceptable; must also survive turnover-driven costs at *actual* rebalance
  frequency measured in S2 (source claims ~29 trades/yr — report ours
  against that as a sanity check, not a target to hit).

## Style expectations

Est. hold: whatever a rank stays in the top 50 (likely weeks-to-months per
name, ~29 round trips/yr on the whole book per the source's claim). Checked
against STYLE.md at S6: hold horizon soft-mismatch is mild (fits the 20-60
day tolerance), but the weekly, multi-position manual rebalance load is the
harder S6 question, flagged above.
