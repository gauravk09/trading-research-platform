# SPEC — smallcap_ema_regime_swing        status: S1 | 2026-08-06 | reddit_x_strategy_ideas.md #2 (doc's own #1)

Source: `scratchpad/reddit_x_strategy_ideas.md` candidate #2 ("Full swing
system with EMA regime gate", r/IndianStreetBets "An year of swing trading in
review", thehumblecuriousinvestor.substack.com). Claimed edge: a mechanical
market-direction gate (dual-index 9/20 EMA stack) keeps the trader OUT during
corrections, so a plain consolidation-breakout entry only has to work in
favorable tape; a fundamental quarterly-growth screen further filters for
names institutions are already accumulating. Who is on the other side: traders
who hold the same breakout setups through a regime flip and give back gains in
the correction the gate would have sidestepped. Credibility: one year of
candid live-trading retrospective including a stated "0 wins 10 losses"
stretch — no verified P&L, but reads as a genuine practitioner log, not a sale.

## Honesty preamble — what is proxy, what is dropped

- **Regime gate, real data available (better than the source doc assumed):**
  the doc's own `reddit_x_strategy_ideas.md` note guessed we'd have to proxy
  the index gate via house breadth series. We do not — `data/parquet/indices/
  smallcap250.parquet` and `nifty500.parquet` hold real daily OHLC back to
  ~2015. `smallcap250` (Nifty Smallcap 250) is a close family-match for the
  source's "CNX Smallcap". **`nifty500` is a genuine proxy** for the source's
  "Nifty Equal-Weight 100" — nifty500 is cap-weighted, not equal-weight, and
  will therefore under-represent small/mid names relative to the real EW100.
  Flagged; no equal-weight index series exists in the platform.
- **Intraday gate-flip rule dropped.** The source's "exit all losing positions
  the moment the index trades under its 9 EMA intraday" needs intraday index
  data we don't have. Approximated to the EOD close-based gate only — the
  live intraday reaction speed of the source's system is NOT replicated.
- **Promoter / FII-DII holding direction: UNTESTABLE, dropped.** The platform
  has bulk/block deals and categorized announcements, not a systematic
  shareholding-pattern time series. This leg of the fundamental filter is
  dropped, not proxied.
- **Overlap with existing house work.** The base "consolidation → breakout"
  shape is already covered by `ryan_52wk_high` (S3, MIXED→promising),
  `minervini_trend_template` (S3, COVID-carried) and the faithful Qullamaggie
  breakout (S5, incubate, `src/backtest/studies/fno_qullamaggie.py`). The
  house's own breadth-based regime gates (pct40ma, net4, ti65) are already
  extensively tested against the `burst` cohort (`specs/lh_rg/rg_burst_*`,
  SCOREBOARD.md batch 1/2/7) — **we do not duplicate that here.** What is
  genuinely new: (1) a literal dual-index 9/20 EMA cross gate computed from
  real index OHLC (not a stock-count breadth proxy), (2) a quarterly
  revenue-growth pre-filter stacked on top of a technical breakout, (3) a
  9-EMA (not 10/20-DMA) trailing exit. S2 must report how much of this
  overlaps the already-measured Ryan/Minervini/Qullamaggie shape.

## Universe / liquidity floor

All NSE EQ, ₹5cr 20-day avg turnover floor (house default), price >= Rs 20
(penny-stock exclusion, house convention). Not restricted to a smallcap-only
universe — the source's rules apply the setup to any stock passing the
filters below, gated by the smallcap/broad-market regime, not by the traded
stock's own market-cap band.

## Event definition (point-in-time, exact)

**Market regime state** (daily, computed once, joined onto every candidate
date — never look ahead: uses only that day's close):
`regime_ON[t] = (smallcap250.close[t] > EMA9(smallcap250)[t])
             AND (EMA9(smallcap250)[t] > EMA20(smallcap250)[t])
             AND (nifty500.close[t]    > EMA9(nifty500)[t])
             AND (EMA9(nifty500)[t]    > EMA20(nifty500)[t])`
Regime flips OFF the day either index closes back below its own 9 EMA.

**Fundamental filter** (joined on `filing_date` from `financials.parquet`,
point-in-time — the quarter used is the most recent one whose filing_date is
<= the candidate date):
- Revenue: `revenue_cr[latest] / revenue_cr[same quarter, prior year] - 1 >= 0.20`.
- Earnings: `eps_basic[latest] > 0 OR eps_basic[latest] > eps_basic[prior quarter]`
  (proxy for "earnings positive OR rapidly improving toward zero").

**Technical filter** (existing `src/filters/trend.py` building blocks):
`above_ma_filter` on 20/50/200 DMA (close above all three) AND
`ma_stack_filter` (20DMA > 50DMA).

**Setup** (existing `src/filters/consolidation.py` building blocks):
`tightening_range_filter` (20-bar consolidation ADR < prior 60-bar trend ADR)
AND `higher_lows_filter` over the same 20-bar window, with the signal bar
closing above the prior 10-day high (breakout trigger, matching the house
Qullamaggie breakout definition in `src/backtest/studies/fno_qullamaggie.py`).
Signal bar must close green (drops the source's "exit same day if breakout
day closes red" rule into an entry filter rather than a same-day exit).

## Entry variants (max 3)

- V1 **D+1 open** — faithful/naive replication of "buy the breakout" as
  literally stated (house prior: this is usually the loser, expect it to
  underperform V2).
- V2 **signal-day close + range_pos >= 0.75** — house lever 1 (FACTORY.md
  S3 lever 1), tests whether the source's system actually needs the stronger
  entry clock the house has repeatedly found necessary.

## Stop / Exits

- Initial stop: `min(signal-bar low, 20-bar swing low)`, capped at 8% loss
  (house convention, `indicators/volatility.max_stop_distance`).
- At **+1R**: stop ratchets up daily to `max(current stop, close - 1x ADR20)`
  (concrete rule standing in for the source's undefined "ratcheting daily").
- At **+2R**: sell 50%, move stop to breakeven, trail the remainder on a
  9-EMA close-below (literal — the one exit rule the source states exactly).
- Regime flip OFF (EOD, per the dropped-intraday note above): exit ALL open
  losing positions (unrealized R < 0) at next open; tighten stops on the rest
  to `min(prior day low, signal day low)`.
- Earnings overlay: flat by end-of-day if `results_due_days <= 1`
  (`data/processed/earnings_calendar.parquet`, already built).
- Time cap: 50 bars (house convention, matches dan_zanger/Ryan-Minervini).

## Costs / Eras

0.4% round-trip default. Eras: A 2015-19, COVID 2020-22 (reported, never
judged), B 2023-26, 2024-26 sub-era shown separately (per the champion-
strategies-batch lesson that a "passing" full-period number can hide a dead
2024-26 tail).

## Success bars (written now)

- S2: either variant, close-entry PF >= 1.2 in BOTH eras A and B, n >= 150 →
  proceed to S3 (report the fundamental-filter's coverage %, since
  financials.parquet history starts 2016 and filing lag applies).
- S4: standard bars (era split, parameter neighborhood on the EMA lookback
  9/20 vs 8/21 and 10/20, random-recipe null since the fundamental filter was
  *selected* from the source, not house-standard).
- S5: >= 3%/yr on ₹10L trading capital (STYLE.md bar), AND must add
  uncorrelated trades or a return/DD improvement over the already-incubating
  Qullamaggie sleeve, not merely replicate its shape at a smaller n.

## Style expectations

Est. hold 5-15 sessions core, longer on the trailed remainder (source
implies weeks). Checked against STYLE.md at S6: manual execution is fine
(daily EOD signal, alert-driven); the regime-flip same-day exit rule is a
soft mismatch against the user's 09:15-09:40 / last-45-min screen windows if
it needs to fire mid-day — flag for S6, dropped to EOD here anyway.
