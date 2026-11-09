# Roadmap

Single source of truth for what this platform is becoming, what's built, what's
next, and — just as important — what was **rejected and why**, so the same ideas
don't get re-litigated every session.

**Maintenance rules (for humans and LLMs):**
- Every item carries a status: `DONE (date)` / `IN PROGRESS` / `NEXT` / `LATER` / `DEFERRED` / `REJECTED`.
- When you build something, move it to DONE with the date and the files it landed in.
- When an idea is turned down, don't delete it — move it to Rejected with the reason.
- Open questions that block work go in Decisions Needed until the user answers.
- `docs/` describes full trading methods (the *what could be built*); this file
  tracks what we chose to build. Rule files (`SETUP_RULES.md`, `SCAN_RULES.md`,
  `SCANS_REFERENCE.md`) describe what exists today.

## North star

A trading research platform whose **outputs are machine-readable first** (files
are the API; dashboards just render them), with **deterministic layers producing
facts** (scans, breadth, exposure rules) and **one judgment layer on top**
(human or LLM), everything logged so decisions can be graded later.
Guiding quote (Raj Kumar / "Ragi"): *the hard part is not getting trades, it's
not getting bad trades.*

## The five overhauls (agreed 2026-07-10)

1. **Daily state file** — machine-readable snapshot per trading day.
   `DONE (2026-07-10)`: `src/daily_state.py` → `output/state/<date>.json` +
   `latest.json`; regime, monitor tail, FII/DII, 6 Stockbee scans with feature
   vectors, 40-bar OHLCV windows, open trades. Step 5/5 of `eod_update.py`.
2. **Situational awareness → deterministic exposure model.**
   `DONE (2026-07-10)`: `src/preprocessing/breadth.py` — 5 breadth signals → tier
   (AGGRESSIVE/NORMAL/CAUTIOUS/DEFENSIVE) → knobs (risk/trade, max positions,
   exposure cap, leverage, allowed entry types). `dashboard/breadth.py`
   delegates its Market Monitor math here (single code path).
   - `LATER`: calibrate tier thresholds & knobs empirically once the
     regime-conditioned backtest (item 5) exists. Current levels are Bonde's
     published US levels, unvalidated for NSE.
3. **Decision journal / post-study — grade every decision.**
   - `DONE (2026-07-10)`: passive capture — `output/brief/journal.jsonl`
     (recommendations + gates), `triage_verdicts.json`, `stockbee_trades.json`,
     daily state files.
   - `DONE (2026-07-18)`: forward-return grader — `src/grade_decisions.py`
     (step 8/8 of `eod_update.py`) rebuilds
     `output/grader/forward_returns.parquet` nightly: +1/+3/+5/+20d returns for
     every scan candidate in the state files, every /brief journal line
     (recommendations / passed-over / watchlist), every triage verdict, plus a
     `_MARKET_` median-universe row per date for grading regime tiers. Two
     bases per horizon: decision-day close (signal) and D+1 open (realizable —
     the champion-strategies bleed). Horizons fill in as days elapse.
     Answers (once enough days accrue): which scan has NSE edge; does human
     triage beat the raw scan; does the DEFENSIVE tier coincide with drawdowns.
     Only ~6 decision dates exist as of 2026-07-18 — read nothing into the
     early medians.
4. **Daily Brief agent — one page instead of 40 charts.**
   `DONE (2026-07-10)`: `.claude/skills/brief/SKILL.md` — reads
   `output/state/latest.json` + live Kite account, mechanical sizing from
   regime knobs, Ragi-style PASS/BLOCK gates, writes `output/brief/<date>.md`
   + journal line. Never places orders.
   - `DONE (2026-07-10)`: dashboard "Daily Brief" tab
     (`dashboard/tabs/daily_brief.py`) — renders the same state + journal
     files: regime banner, exposure-gate status, stop-first candidate cards
     sized from `regime.size_position()`, and **flagged/rejected candidates
     with reasons** (`candidate_flags()` in `daily_state.py`: wide stop vs
     ADR, thin turnover, low RS, extended leg, deep below 52w high).
   - `LATER`: schedule it (cron/scheduled agent) so the brief exists before
     the user asks.
5. **Regime-conditioned point-in-time backtests of the live scan code.**
   `NEXT (after item 3's grader)`: extend `src/backtest/` (pointintime.py
   already reuses live scanner code) to run each Stockbee scan through history
   split by regime tier; replace US-calibrated thresholds (4%, TI65 ≥ 1.05,
   ₹-floor equivalents) with NSE-calibrated ones. Known caveats tracked in
   memory: split repair, no historical ASM/GSM, daily-bar entry approximations.
   - **Threshold-validation plan (agreed 2026-07-20, not yet implemented):**
     five phases, cheapest first, all point-in-time on `mm_history.parquet` +
     `src/backtest/`:
     1. *Signal-level sweeps* — for each of the 5 regime signals, sweep its
        bull/bear thresholds (ratio 1.5–3.0 / 0.3–0.8; breadth 50–70 / 30–50;
        net25q around 0) and demand monotone fwd-5/10/20d separation that
        holds in BOTH eras (2015–2020 vs 2021–2026 walk-forward split).
        Kill rule: a signal with no monotone separation at ANY threshold is
        dropped from the score, not tuned (this is the test that would settle
        Bonde's "ratios are bloatware" claim with NSE data).
     2. *Score→tier mapping* — event study around tier transitions (fwd
        returns after entering/leaving DEFENSIVE), tier-duration/whipsaw
        stats, alternate cutpoints (AGGRESSIVE ≥3 vs ≥4). Hysteresis only if
        whipsaw cost is demonstrated.
     3. *Regime-conditioned scan backtests* (the core build) — replay each
        live scan through history via pointintime.py with the honest
        mechanics (D+1-open entry, LOD stop, 3–5-day scale-out); split
        expectancy by tier at signal date. Answers whether each tier's
        `allowed_entries` matches where each scan's edge actually lives, and
        sweeps scan knobs (TI65 1.00/1.05/1.10, EP gap 6/8/10%) with ≤3
        pre-registered candidates per knob judged out-of-sample — no grid
        mining (bias rules per research/PROGRAM.md).
     4. *Knob calibration* — per-tier risk%/max-positions from Monte Carlo
        resampling of phase-3 trade streams (target: P(20% drawdown) under a
        chosen tolerance per tier), not from opinion.
     5. *Promote + forward-test* — encode NSE constants in regime.py with
        evidence dates; the nightly grader (item 3) becomes the live forward
        test of the calibration.
     Statistical guards baked in: overlapping forward windows → block
     bootstrap / non-overlapping samples; regime days cluster → effective N
     = regime episodes (~dozens), not ~2,800 days; survivorship inflates
     pre-2018 breadth (report both eras separately).

## Other tracked items

- **Risk regime = validated HMM crash-risk dial; breadth tiers retired (2026-09-28)**
  — `DONE`.
  - **What it is:** `src/risk/regime.py` runs H1, a 3-state Gaussian HMM on Nifty 500 ret_20 and rvol_20. It is refit yearly, uses filtered (real-time) probabilities, and outputs P(≥5% drop in 20d).
  - **Sizing:** ELEVATED = half the CALM knobs, when the dial is above its historical average. CALM = the old NORMAL knobs. This 2-level mapping is **untested**.
  - **Evidence:** selected from 9 pre-declared candidates in `research/regime/` (harness, walk-forward 2000–2024, experiment log, CHANGELOG).
    - Direction skill: none, for any model.
    - H1 risk skill vs climatology: drop +4.4% [+2.3, +6.7]; vol-tercile +6.7% [+3.1, +10.3].
    - Survives price noise: forecast correlation 0.98 or higher.
    - Sealed lockbox 2025–26: CONSISTENT (drop +10.0% [+0.4, +26.8]; vol +5.8%, CI spans 0).
    - Selection rule 1A was locked after the scores were seen (disclosed).
  - **Removed:** the regime score, the tiers AGGRESSIVE/NORMAL/CAUTIOUS/DEFENSIVE, the TIER_KNOBS in `regime.py`, `market_signals.py` (index trend / divergence / distribution / FTD), the mm_history regime columns, and the dashboard regime banners/charts.
  - **Kept:** the breadth Market Monitor. `regime.py` now does breadth only.
  - **Docs:** `Docs/regime_filter_research_2026-09.md` (survey) and `Docs/regime_system_design.md` (design).

- **Agentic-quant survey adoption — attribution, GA gates, archive + ledger, plan contract, protocol header (2026-09-03)**
  — `DONE`. Source: arXiv:2608.31041 (survey) + 22 cited papers read in full;
  synthesis and the do-later list in `Docs/agentic_quant_survey_2026-09.md`.
  The survey's own findings back our existing choices (gating over aggregation,
  no multi-agent debate, no LLM regime, no auto-execution); what transferred is
  scoring, search memory and contracts, not more brakes.
  **(1) Return decomposition** `src/backtest/attribution.py` (KTD-Fin,
  arXiv:2605.28359): one cross-sectional OLS per day on nine OHLCV style
  factors (exposures lagged, winsorised, z-scored INSIDE the tradeable
  universe — standardising over the whole panel let the illiquidity factor
  swallow the market term on the first run), so every trade's close-to-close
  return over its hold splits exactly into market + style + SELECTION.
  `canonical_runner` now requires an `attribution` check for PASS (or an
  explicit `N/A (<why no cross-section>)`). First real-data read, raw trigger
  cohorts, 20-bar hold, vs same-date control: **EP is the only trigger with
  selection alpha** (+0.68%/trade, t +3.4; control +0.03); burst −0.05 (t −0.6)
  vs control +0.10 — a raw 4%-day name has no selection edge over a random
  same-day name once market and style are removed; pullback +0.12 (t +2.0) vs
  control +0.09; bounce 0.00; four_pct_down short −0.04 vs control −0.10. The
  market term is +1.3 to +2.2%/20d in every cohort. Caveats: these are
  unconditional cohorts, not strategies; the stop-managed R is not decomposed
  (fixed window only); universe is survivors-only; D+1 open→close entry-day
  slice is outside the factor model.
  **(2) GA fitness gates** in `research/machine/evolve.py`: coverage charge
  `COV_PEN=0.5` z per unit of silently-NaN'd panel (Hubble, arXiv:2604.09601 —
  bounce finalists carried d_drop 0.52–0.86 on days_since_52wh / tightness /
  pct_52wl, i.e. they were scored on a survivor subset), and a perturbation
  fidelity finalist gate `PFS_MIN=0.80` (AlphaEval, arXiv:2508.13174: label
  agreement under 10%-of-spread Gaussian and t(3) input noise, worst case).
  Calibration on every past run log: 38 real finalists 0.47–1.00 (5 below
  0.80, incl. `consol_days <= 0.0` at 0.47 — the knife-edge case it exists
  for); 13 placebo champions 0.25–1.00 (5 below 0.80). It separates fragile
  from robust rules, NOT placebo from real — the holdout + null test still do
  that. AlphaEval's 0.90 would kill half the real finalists; not adopted.
  **(3) MAP-Elites archive + motif ledger**: parents drawn 50/50 from a
  behaviour archive (cell = series-family set × log2 event count; QuantEvolve
  arXiv:2510.18569) and `research/machine/motif_ledger.{py,json}` — cross-run
  memory keyed on the EDIT (op + family + parent-score bucket), residual
  δ = z(child) − z(parent) − bucket baseline, confidence n/(n+5)·min(1,|μ|/σ),
  veto only (c ≥ 0.5 and μ < 0), one-year half-life, never written by placebo
  runs (AlphaMemo arXiv:2606.20625). `--no-archive --no-ledger` restore the old
  GA for an A/B. `LATER`: that A/B on a full-size run — smoke runs only so far.
  **(4) Plan contract** `src/risk/plan_contract.py` (AgenticAITA arXiv:2605.12532,
  Orchestration arXiv:2512.02227): the brief writes a draft, the contract
  computes every hard gate in code with its measured value, moves failures to
  `rejected` with a `reject_reason`, and only the gated JSON enters the
  journal. `/trade` (`plans.validate_plan`) refuses a symbol the day's contract
  rejected and warns on a discretionary one. `grade_decisions.py` grades
  rejected names and prints **FalseBlock** (share of blocked names that gained;
  SAE arXiv:2603.10092) — the only number that catches an over-tight gate.
  Verified on the 2026-08-21 journal entry: 2/2 pass, risk 7,013 vs cap 7,017.
  **(5) Protocol header**: `survivorship` is now a required canonical-spec
  parameter (Xia et al. arXiv:2605.19337: 1 of 19 studies disclosed it);
  `canonical_runner.py --replay <result.json>` re-runs a persisted result and
  diffs every metric (R2 reproducibility). Git SHA + dataset fingerprints were
  already in the mlflow index. Tests: 56 pass (`src/test_attribution.py`,
  `src/test_plan_contract.py`, `src/test_canonical_runner.py` extended).
  **Mining round 1 (same day), three results, all in `research/factory/LEDGER.md`:**
  (a) board re-graded by selection alpha (`output/studies/attribution_regrade_2026-09-03.csv`):
  84/131 real experiments beat their same-date control on selection, 24 with
  t ≥ 2, 9 significantly below; cheat canaries rank 1-3 (t 16-25). Keeps
  selection: 4%-down eff_ratio short, breakdown shorts, TI65 bounce, delivery
  family, near-high ret63. Market/style only: lcbounce_ret21, caldeliv expiry
  bounce, lclowvol burst. Registry sleeves: Ryan/Minervini +1.60%/trade
  selection (t 2.4, all eras), lone-loser short +0.60, Qullamaggie +0.34 thin,
  Darvas −1.71 (pure market; REJECTED confirmed).
  (b) EP is NOT sharpenable by a filter stack: era-A protocol run scored 0 by
  construction (naked era-A EP negative on every ruler — check condition (c)
  before spending a pocket run); pre-registered modern-track variant
  (`--train-end 2023 --ruler stop_r_20`, new flags) best z 0.95 vs placebo
  0.99-1.11, both finalists FAIL era B. EP's alpha lives in the trigger.
  (c) GA A/B (24 runs, fitness only): new engine = old in 4/6, better in 2/6,
  never worse; placebo floor 0 for burst/four_pct fitted-pocket at pop 24 /
  gens 15, so noise-fitting is unmeasured there; ledger vetoes 55-180/run.
  New engine stays default. `DONE`.
  **Ryan/Minervini → S7 incubation (2026-09-03)** `DONE`: `src/incubation.py`
  adds a `ryan_minervini` paper block to the state file using the SAME signal
  functions the backtest used (`ryan_52wk_high.build_signal` + dedup,
  `minervini_trend_template.signal_mask`) on the nightly matrices;
  `precompute.py` now also writes `high_matrix` / `low_matrix` (Minervini
  needs them); gate = regime tier allows breakouts; entry filter = close in
  the top quarter of the day's range; stops as in the book (7% / max(5-bar
  low, 8%)). Registry status RESEARCH_ONLY → INCUBATING. Promotion bar
  unchanged: ≥30 graded signals or 8 weeks inside the backtest band.
  `LATER` (premise untested, see the synthesis): ContestTrade trailing-
  performance strategy weights (needs a journal far longer than 6 dates);
  drawdown ladder vs the validated binary circuit-breaker; decorrelation cap
  at plan level; Thompson-sampling direction scheduler for `llm_evolve.py`.

- **Commodity data layer, offshore-research / MCX-execution (2026-08-20)** — `DONE (data)`.
  `src/data_collection/commodity_map.py` whitelists the 5 MCX contracts with a genuine offshore
  twin (GOLD, SILVER, CRUDEOIL, NATURALGAS, COPPER); ZINC/ALUMINIUM/LEAD/NICKEL
  excluded (LME-referenced, no free feed), agri excluded (domestic discovery).
  `src/data_collection/other/global_commodities.py` -> 26yr daily OHLCV for GC/SI/CL/NG/HG + USDINR.
  `src/data_collection/other/spot_commodities.py` -> LBMA gold/silver (1968), EIA WTI/Brent/HenryHub
  (1986). `src/preprocessing/commodities/basis.py` converts USD reference -> MCX-equivalent INR
  and measures tracking. `src/preprocessing/commodities/research.py` picks the substrate.
  Findings: (a) MCX-vs-offshore alignment is same-day, lag 0, lags +/-1 ~zero;
  (b) roll gaps on the continuous series are negligible for GOLD/SILVER
  (sd 0.15%/0.21%) but term structure dominates CRUDE/NATGAS (sd 2.48%/3.95%),
  so natgas continuous history is misleading — graded red;
  (c) spot is close-only and venue-mismatched (NATGAS spot residual sd 6.87% —
  Henry Hub cash is a physical market), so FUTURES are the research substrate
  and spot is a cross-check only.
  `BLOCKED`: MCX history. Kite lists only live contracts, so the reachable bars
  belong to what were then DEFERRED months — genuine front-month coverage is
  10 bars for GOLD, 0 for CRUDEOIL (`is_front_month` flags this). mcxindia.com
  is 403 to scripts and blocked by browsing policy. Real MCX history needs a
  manual bhavcopy pull or a paid vendor. Deferred by user 2026-08-20: research
  offshore, adapt to India by hand (positional holds absorb the basis).

- **Factor model — PCA crowding gauge + residual momentum + breakout gate (2026-08-14)**
  — `DONE`. `src/indicators/factor_model.py` is the "500 stocks are really ~5 forces" engine
  (correlation-matrix eigen-decomposition; standardized returns so a few high-vol
  names don't own PC1). Two features, one engine:
  **#1 Absorption ratio (PC1 crowding)** — `absorption_series()` on a fixed liquid
  basket (250 most-traded names, 63d window, sampled every 5d); share of universe
  variance in the single largest force. Surfaced as `market_signals.absorption`
  (bearish top-quintile of its own history = correlations toward 1, breakouts fail
  together; bullish bottom-quintile = dispersion). **Display-only, NOT in the regime
  tier** — same discipline as the other non-breadth axes, pending the calibration
  backtest. `marchenko_pastur_max()`/`n_significant_factors()` report how many
  eigenvalues clear the RMT noise band (3 on 2026-08-13 — the article's picture in
  our data). Today's read: PC1 = 16.1% of variance, 29th pct (dispersed).
  **#2 Residual (idiosyncratic) momentum** — `residual_momentum()` / `residual_rs_rank()`
  (in `indicators/relative_strength.py`): each stock's cumulative return AFTER
  regressing out the equal-weight market and its sector factor (grouped-by-sector
  OLS, one solve per sector). Idiosyncratic slice = intercept·n (NOT sum of
  residuals — with an intercept those are ~0 by construction; that was a caught bug).
  0.925 correlated with plain `composite_rs_rank`, but the gap correctly flags
  sector-carried strength (e.g. the pharma cohort PANACEABIO/IOLCP/HIKAL/SUVEN reads
  as sector, not stock).
  **Breakout gate** — `residual_ranks`/`min_residual_pct` in `breakout.scan` +
  `scanner.run` (`--residual-pct`, both ranks from one universe read); shows a
  `residual_rs` column. Lenient-on-missing (a name we can't score isn't dropped on
  residual grounds — residual is a refinement, not a Qullamaggie prerequisite).
  Finding: breakout prereqs already pre-select high-residual names (candidates span
  65-100, median 93), so the gate is a **tail cleaner, not a bulk filter** — default
  moved 50 (inert, 0 dropped) → **80**, which keeps 75/79 and drops 4 genuinely
  sector-driven breakouts (GABRIEL residual 65 = auto-sector move; SAPPHIRE, SHK,
  ORISSAMINE). Caveats: gauge basket is survivorship-selected by design (a stable
  market-state basket, like market_rhythm's frozen basket); sector factor built only
  for sectors ≥5 members to keep self-inclusion bias negligible; both features use
  realized in-window returns only (no look-ahead). `LATER`: calibration backtest to
  (a) promote absorption into the regime tier (overhaul item 5 machinery) and
  (b) prove the residual gate improves breakout outcomes vs raw RS before trusting it.

- **Portfolio book sim — all certified strategies as ONE ₹10L book (2026-08-06)**
  — `DONE`. `src/backtest/studies/portfolio_book.py` (report + PNG + PDF in
  `output/studies/portfolio_book_*`): the four registry sleeves (lone-loser
  short, tape-gated Qullamaggie MA20, gated Darvas 60d, Ryan/Minervini risk1
  stream) rebuilt at their exact certified recipes, combined additively in
  fixed-base risk units (linear in the risk knob), plus a constrained
  one-account compounding run (2.5x lev / 8% heat, skip-when-full) and a
  10k-path 3-month-block bootstrap MC of maxDD over a risk-multiplier grid.
  Findings: sleeves are near-uncorrelated monthly (max +0.35 qull-darvas);
  every-signal book REQUIRES 81% peak heat / 37x peak leverage → capacity, not
  signal supply, is the binding constraint (constrained book skips 30-55% of
  trades and its maxDD WORSENS because skips cluster); leave-one-out says
  darvas+ryan carry ret/DD, short/qull dilute in risk units; MC knob answer
  (pre-registered bar P(maxDD>=20%) <= 10%): **0.5x base → short 0.38% /
  qull 0.38% / darvas 0.25% / ryan 0.38% risk per trade** (~14%/yr geometric,
  median maxDD -7%). Caveats: P&L realized at exit (maxDD understated on
  long-hold sleeves), ryan stop_pct approximated 7-8%, era-A survivorship.
  `LATER`: daily-MTM version of the combined curve; slot-based (max positions)
  capacity model instead of the raw heat cap; feed the recommended knobs into
  regime.py tier knobs.

- **Strategy book surfaced in both dashboards (2026-08-03)** — `DONE`.
  `src/strategy_registry.py` is the single source of truth for the validated
  strategies (lone-loser short, tape-gated Qullamaggie, gated Darvas
  incubate, Ryan/Minervini small/mid) — status, gates, stats, caveats, and a
  Google-Doc playbook link each. Trading desk: new ⚔️ Strategies tab
  (`dashboard/tabs/strategy_book.py`) with live gate lights from
  `mm_history` + tonight's S7 paper candidates from `latest.json`. Live
  scanner: per-row TAKE/CAUTION/SKIP Signal column (hover = which rule and
  the live gate values) on the 4% Breakout / Breakdown / Anticipation /
  Reversal tabs (`live_scanner.annotate`), plus a tape strip
  (net4/pct40ma/ti65). Gate thresholds mirror the backtests
  (net4≥18 & ti65<1.04 short; pct40ma≥55 Qullamaggie; ≥60 Darvas;
  washout<40 blocks dip-buys; net4≥130 strong-tape cell for 4% longs).
  Follow-up same day: `src/conviction.py` ranks every Setups-tab and
  brief-watchlist hit into a research queue — Pri 0-100 from validated
  factors only, plus Signal (TAKE/CAUTION/SKIP; closed playbook gate always
  caps at CAUTION), Playbook fit, and a "why ranked here" per row. Daily
  workflow doc: "Daily Research Routine" (Google Doc, linked from Setups +
  Strategies tabs). Third piece: 🧾 Order Pad tab
  (`dashboard/tabs/order_pad.py` + `src/order_pad.py`) turns tonight's
  candidates into sized punch-in cards for the Kite app — read-only, never
  places anything (manual-execution mode still applies). Its point of care
  is ENTRY TIMING per playbook: D+1-open books (lone-loser short,
  Qullamaggie) are punched as AMOs tonight; Bonde's same-day setups must go
  in during the 15:20-15:30 window and the card says "MISSED for today"
  after that. Sizing uses the regime risk knob against user equity and
  works for both directions (regime.size_position is long-only).
  Moved to the LIVE dashboard same day: a desk pad reading last night's
  state file is useless at 15:20 (tonight's file does not exist yet), so
  `live_scanner.order_tickets` + `/orderpad` + a 🧾 Order Pad tab in
  live_anticipation build tickets from LIVE quotes (entry = last trade,
  stop = today's realized low/high) with a minutes-to-close countdown.
  **Mid-session sizing trap found and guarded**: intraday the day's high/low
  is only the range SO FAR, so a stop off it is too tight and the
  risk-based size too big (LICI showed ₹297k notional at 12:16 on a 1.68%
  stop vs ~₹100k for peers). Tickets built while session == "open" are
  flagged `provisional`, forced non-actionable, and the card prints
  "DO NOT PUNCH YET — re-read at 15:20". Sizes are only firm once the
  range is complete.

- **Live strategy-decay tripwire (expectation envelope)** — `PARKED` (2026-07-31,
  deliberately not building yet). Test-time regime robustness already exists
  (era-split PASS bar, `market:` conditions, habitat gates like net4-LOW
  kill-switch); the missing half is live decay detection. Design when picked
  up: per certified strategy, bootstrap the backtest R-series into a
  rolling-N-trade expectancy / losing-streak envelope (5th-pct bounds);
  daily-state check grades GREEN (inside) / AMBER (below median → halve
  size) / RED (below 5th pct → stop, send back to the machine for
  re-certification). Natural home: `research/machine/envelope.py` + a check
  in the daily state pipeline. Known limits: slow detection on low-frequency
  strategies (~10 weeks to fill a 20-trade window); per-event regime scores
  stay out (calibration study showed breadth anti-predictive per event —
  regime protects via event scarcity + circuit-breaker + participation floor).

- **Research machine — fixed evaluator + agent swarms (2026-07-29)** — `DONE`
  (v1 + first batch). `research/machine/engine.py`: agents author small
  experiment specs (cohort from events.parquet × condition from the 22
  feature matrices / market series / derived long-horizon features); the
  FIXED engine judges era-split top-vs-bottom-bucket effects on stop-R with
  a within-date (stock) / date-block (market) permutation luck test —
  pre-registered bars PASS/WEAK/FAIL/INSUFFICIENT in the docstring. Controls
  validated: placebo FAILs (±0.01R), mechanical adr20 PASSes (null 97%),
  known ti65-bounce result graded WEAK (real, top-quintile, partly date-
  composition — machine is stricter than the old studies by design). Batch 1
  (6 finder + 3 verifier agents via Workflow, ~3.5 min): 27 experiments →
  `research/machine/SCOREBOARD.md`. PASS+red-team-CONFIRMED: net4 HIGH →
  bursts better (+0.38/+0.20R, monotone; the kill-switch upgraded to
  confirmed); turn_decile → avoid illiquid bursts (+0.21/+0.15, bottom-
  quartile drag); bounce_low21 INVERSION on 4% days (nearer 21d low better,
  −0.17/−0.10). Strong-but-uncertifiable: EP-on-1yr-loser avoidance
  (+0.25/+0.20, era-A n=113); deliv_x20 (+0.20 B, data starts 2020-10).
  Killed: pct40ma washout gate as a per-event qualifier (era-inconsistent
  +0.14/−0.30); ret_504 "proven mover" on bursts. Bug found: days_since_burst
  all-NaN at event coordinates (fix queued). Open policy: judgment bar for
  post-2020-only features; EP cohort era-A thinness (consider B-era sub-split
  bars). **Control battery (same day, `research/machine/CONTROLS.md`)**: 16
  controls — 12 assorted placebos (per-symbol, per-date, shuffled-real-
  feature, huge-cohort) all FAIL, cheat canary (future return as condition)
  PASSes at +2.34R, determinism byte-identical; WEAK bars recalibrated from
  the battery (min 0.04R + null 90%) so noise grades FAIL — 8 borderline
  batch-1 WEAKs demoted, the 3 confirmed PASSes untouched.
  **Batch 2 — survivor combinations (2026-07-30, 87 experiments on the
  board)**: `market:` filter support added (battery rerun ✓). CONFIRMED:
  strong tape is a THRESHOLD not a gradient — liquid non-extended 4%-days
  at net4 ≥ 161 run +0.38R absolute era-B (n=3,715, win5 61.5%); at
  net4 ≥ 134 all non-extended buckets positive (+0.20-0.28R); below ~160
  flat-to-negative; net4 ≤ 44 unsalvageable at ANY liquidity (kill-switch
  asymmetry confirmed). Liquid bounces gated on stock ti65 top quintile
  +0.27R era-B (n=6,568) — P9 upgraded to confirmed. Exposed as shadows:
  burst_success & eff_ratio (vanish on the liquid half); consol_days the
  only surviving burst overlay (era-B +0.10, base-intact cell +0.117).
  EP "better in weak tapes" prior CONTRADICTED — EPs also want net4 top
  (winner-EP × net4 ≥ 134 → +0.067; × delivery mid → +0.128, era-B only).
  Leader-washout pocket (ti65 top + pct40ma < 20 → +1.3-1.75R era-B)
  engine-PASSes but red-team declined: single-cell phenomenon + washout
  episodes cluster → needs episode-level effective-N before promotion.
  Promotion caveat (unresolved): net4 thresholds are RAW counts while the
  universe grew ~1400→2100 names — normalize to % of active universe
  before wiring into the live regime/brief.
  **Genetic search over specs (2026-07-30, `research/machine/evolve.py`)** —
  `DONE` (v1). Holdout-safe GA: evolves {filters, condition} genomes on
  pre-2020 data ONLY (fitness = Stouffer z of date-clustered t-stats across
  era-A halves; bucket edges train-only), finalists judged once by the
  unmodified engine. Fitness had to be evidence-units — R-unit fitness let a
  placebo GA (condition series shuffled per engine's two null modes) fake
  +1.04R via tiny buckets; placebo floor with z-fitness: z 2.2-3.2 across
  6 seeds, 0 noise certifications. Protocol: ONE run per trigger+mode;
  re-running until era B agrees destroys the holdout. Gradient runs: burst
  smoke rediscovered net4+turn_decile from scratch; bounce run → top-z
  champion (z 4.29 net25q) FAILED era B (textbook selection artifact),
  1 engine-PASS `ga_bounce_s1_3f8ff7` (ti65 on mild-dip volatile not-at-low
  cohort, B +0.18R, null 98%) but train z 1.13 < placebo floor → red-team
  before trusting. Pocket mode (`--mode pocket`: absolute-expectancy filter
  stacks = tradeable-rule claim; own pre-registered bars in docstring, judged
  in evolve.py not engine.py, results stay in evolve_runs/): naked bounce
  era B is +0.18R/trade (t 3.5, era tailwind — vs-naked null is the real
  bar); bounce pockets 2 WEAK (low-vol off-the-lows, +0.24/+0.39R, vs-naked
  90/94%) 0 PASS; burst pockets: 158 stacks, ZERO positive in both era-A
  halves (naked burst bleeds −0.06R both eras — confirms D+1-open bleed at
  machine level). Next: red-team the bounce gradient PASS (v_ + min_gap
  variant).
  **Fitness v2 + trader genes (2026-07-31)** — XGBoost-style anti-overfit
  core: 4 chronological era-A CV folds + 21-day embargo (no outcome-window
  straddle; genomes never fitted per fold so no train-on-future leak),
  score = mean cross-fold clustered t − 0.5·std − 0.15/filter parsimony,
  early stopping (3 stale gens). Placebo floors collapsed 3.0→~1.0
  (gradient) / ~0.6 (pocket) while known-real turn_decile scores 1.46 —
  real signal now ranks ABOVE noise during search. New genes in the feature
  store: trend_template, updown_vol50, pocket_pivot, rsline_pct52wh.
  Remaining trigger shots spent: four_pct long pockets 0 (era-B negative),
  ep gradient 0 (cohort too thin for per-fold floors). **FIND:
  four_pct_down SHORT pocket — 4 engine-PASSes, one theme: short the 4%-down
  day when tape is healthy (net25q ≥ −135, ratio10 ≥ 0.65) and volume not
  drying (volc5_50 ≥ 0.93); era-B +0.15R/trade t 4.1. Red-team 9/9 PASS
  (`evolve_runs/four_pct_down_s1_pocket_short_redteam.md`); edge
  CONCENTRATES liquid: turn_decile ≥ 0.9 → +0.19R, 250 trades/yr —
  converges with the large-cap F&O short-the-lone-loser finding. **S5 run
  (`src/backtest/studies/ga_short_pocket.py`, reuses batch5 portfolio layer;
  0.05%/side, heat cap 6%, D+1-open entry, 6% stop, 5d exit): turn_decile
  ≥ 0.9 variant era-B CAGR 11-21% at maxDD −16..−18%, ~160-225 tr/yr, avg
  net R +0.10-0.13; top-150-mcap variant weaker (5-16%, DD −21..−26%).
  39% trade overlap with batch5's green-tape short → 61% incremental.
  Open: true F&O-list membership (turn_decile is a proxy), 20d-horizon
  variant.** **S7 incubation wired (2026-07-31)**: `src/incubation.py`
  generates nightly PAPER short signals for both short strategies
  (batch5-refined w/ Nifty-extension stand-down + GA pocket) into
  `state["incubation"]` — clearly fenced "PAPER — do not trade", never in
  the actionable candidate flow; grader collects them (`source =
  "incubation"`) so a live forward-test record accrues; /brief renders
  them under a 🧪 paper-only banner. First live night: batch5 stood down
  (net4 15 < 18), GA pocket fired 5 candidates. Promotion rule: paper
  record must match the backtest before real money.
  **Pullback trigger + GA long shot (2026-07-31)** — event-store v2 trigger
  `pullback` (leader touches rising 20DMA: close>200DMA, 20DMA rising, 63d
  high within 15 sessions, low<=20DMA*1.01, close>=20DMA*0.97; 31.5k
  events, old triggers byte-identical). GA one-shot: pockets 4/4 FAIL
  vs-naked (no filter beats the naked trigger); gradient ret7 PASS is
  engine-certified but CV-fold-unstable (z 0.13) — unpromoted. S5
  (`src/backtest/studies/pullback_long.py`): naked +0.20R is a TIGHT-STOP
  ILLUSION — median stop 1.84%, cash cost 0.15%/side = 0.16R ≈ the whole
  edge; portfolio sim −30% CAGR/−97% DD; wide-stop (6%) rescue also fails
  (gross collapses +0.03R, net −0.02R). Same family as near-expiry-bounce
  FAIL. LESSON: stop-R ruler is cost-blind and flatters tight stops —
  sanity-check any pocket as gross_R × stop_pct before excitement;
  cost-aware pocket bar = open decision (needs battery rerun).
- **Strategy Factory — pipeline for building/copying/adapting strategies
  (2026-07-29)** — `IN PROGRESS`. `research/FACTORY.md`: S0 source →
  S1 pre-registered spec → S2 replicate-as-published → S3 the four proven
  adaptation levers (entry clock, exit-shape-matches-tail, universe floors,
  delete NSE-inverted confirmations) → S4 robustness bars (ex-COVID era
  splits, 2024-26 sub-era, neighborhood, random-recipe null) → S5 economics
  (≥3%/yr bar; PF is not payable) → S6 style fit (`research/factory/STYLE.md`
  — hard/soft constraints, has [FILL]s awaiting user) → S7 incubation via
  daily state + grader → S8 live with per-strategy rolling-R edge-death
  monitor (EP9M 2024-26 lesson). Run accounting in
  `research/factory/LEDGER.md`. Trader ingestion via the
  trader-setup-researcher skill → `docs/<trader>_trading_setup.md`.
  **S5 DONE 2026-07-29 — ryan_minervini_book** (first factory run,
  `src/backtest/studies/ryan_minervini_book.py`, report
  `output/studies/ryan_minervini_book_study.md`): close+strong-close entry,
  published exits, ₹10L account. PASSES all pre-registered bars in all 3
  variants — live knobs +8.3%/yr (maxDD −10.5%, ₹1.3L/yr), risk-1% +24.7%/yr
  (maxDD −16.7%); per-trade edge identical across variants → the RISK KNOB is
  the binding constraint (open user decision). Tier gate added nothing
  per-trade (avg R 0.91 gated vs 1.33 ungated — matches regime_calibration).
  Caveats: pre-2020 survivorship, no ASM/GSM (ATGL +60R best trade), top-5
  trades ≈ half of net. Next: S7 incubation wiring; MC drawdown pass;
  dan_zanger spec'd (S1, `research/factory/dan_zanger/SPEC.md` — codable
  proxy, Ryan-overlap flagged) awaiting S2.
- **Non-breadth regime axes + delivery % pipeline (2026-07-25)** — `DONE` (candidate
  stage). The regime tier was 100% breadth; added the orthogonal axes established
  swing traders use, as **display-only candidates** (not in the tier score — same
  status as `up20_5d`, pending the item-5 weight calibration). `src/market_signals.py`:
  `index_trend` (Qullamaggie NIFTY 500 10>20-DMA both rising), `divergence`
  (A/D-style: index new-high on falling breadth), `distribution_days` + `follow_through`
  (O'Neil/Minervini, using aggregate rupee turnover as the index's volume proxy →
  2020+ only). Wired into `daily_state.py` → `state["market_signals"]` and rendered
  under the regime banner. Stock-level institutional intent via `src/data_collection/nse/delivery.py`
  — delivery % from NSE `sec_bhavdata_full` into `delivery_matrix.parquet`, nightly in
  `eod_update.py`, 65-day backfill (delivery is EOD-settled → next-day signal only).
  Next: surface delivery on candidate cards / scan flag; up-down-volume breadth
  (collinearity test); then fold survivors into the weighted score via item 5.
- **Regime calibration stages 1+2 (2026-07-25)** — `DONE`. Stage 1
  (`src/backtest/studies/regime_calibration.py`): all 9 signals vs the 4%-burst
  cohort (23,646 events, D+1-open entry, prev-close signal rule); incumbent
  5-signal score is ANTI-predictive per-event (rank 9,777/19,655 weight combos,
  negative OOS spread) — the regime's channel is event scarcity, not per-event
  return. Stage 2 (`regime_stops.py`): stop-based R outcomes, burst + EP9M
  cohorts, auto-mined era-stable insights, report in the new template format
  (`docs/backtest_report_example.md`). Findings: burst ≈ breakeven with stops in
  every zone (edge must come from selection); **EPs are better in weak tapes**
  (idx_trend/net25q bearish, both eras — validates CAUTIOUS keeping EP allowed);
  **FTD confirmed on both cohorts** (the one green-light signal; caveat: EP
  gap-through losses rise on FTD days). FTD promotion to the tier score pending
  user sign-off.
- **Sector monitor: cap-weighted + equal-weight group returns (2026-07-25)** — `DONE`.
  Trendlyne-style "where is the money going" view as the Market Monitor tab's
  fourth radio (`dashboard/tabs/sector_monitor.py`), aggregating per-stock
  horizon returns from `universe_summary` (new `r1w_pct`/`r12mo_pct` columns
  in precompute; 1Y computed from full history *before* the tail-252 trim so
  52w-high semantics are untouched) into NSE-taxonomy groups (22 sectors /
  183 industries). Two lenses: cap-weighted (what the group's mcap did) and
  equal-weight (majority participation — same reason Trendlyne's TJI baskets
  are equal-weighted, to catch small/microcap moves NSE 500 misses). Index
  membership problem solved by not using index lists at all: weights and
  top-N universe cutoffs are point-in-time per column via start-of-window
  mcap = today's mcap ÷ (1 + return) — a stock that crashed out of the top
  500 still counts in the 6M column, recent IPOs drop out of longer windows
  only. Universe options: Liquid (T/O ≥ 1 Cr, today's filter), All, Top
  500/1000 by mcap. Drill-down: group row → constituents → chart dialog.
  Follow-ups (2026-07-25): suspended/delisted names (no trade in 7+ days) are
  excluded — their horizon windows end at the last trade, so a stale "3M
  return" would pollute today's aggregate (JBCHEPHARM post-suspension was the
  live case); `company_master.py` now archives nightly (date, symbol,
  shares_out) to `data/processed/shares_out_history.parquet` so true
  point-in-time mcap becomes reconstructable going forward (can't backfill).
  Accepted limits (won't fix): shares_out constant within a window until the
  archive matures (ignores QIP/buyback — second-order, affects weights not
  returns); sector labels are today's (no historical NSE feed; reclassifi-
  cations rare); Liquid filter is today's turnover, not point-in-time — use
  the Top-N options (PIT by construction) when reading 6M/1Y critically.
- **Market Rhythm: leader follow-through + winner attribution (2026-07-20)** — `DONE`.
  `src/preprocessing/market_rhythm.py` (rebuilt nightly by precompute alongside mm_history,
  sharing one matrix load) → `data/processed/market_rhythm.parquet`; rendered
  as the Market Monitor tab's third view (`dashboard/tabs/market_rhythm.py`).
  Two point-in-time series: (1) leader spread — RS>90 basket **frozen at T−5**
  (freeze kills the circularity of ranking on the returns being measured),
  median 5-day return minus eligible-universe median; (2) winner attribution —
  ≥10%-in-5-sessions movers classified by state at T−5 with fixed priority
  bounce (≥25% off 252d close-high, <200DMA) → pullback reversal (>200DMA,
  3+ down closes) → breakout (≤15% off high, >50DMA) → other. Validation
  (2015–2026): attribution flips with regime as the washout study predicted
  (breakout share 42% AGGRESSIVE vs 23% DEFENSIVE; bounce share 49% DEFENSIVE
  vs 27% AGGRESSIVE); leader-spread terciles grade fwd-20d monotonically
  (−0.24% / +0.18% / +1.40%); breakout-share terciles are NON-monotonic vs
  forward returns — attribution is a coincident "which conveyor to feed"
  switch, not a timing signal. Close-only by design (252d high is a closing
  high; no ADR — fixed 10% threshold keeps the nightly build to the existing
  close+volume matrices). Rejected: classifying winners by state at week-end
  (a finished bounce looks like a breakout — look-ahead); ADR-scaled winner
  threshold (needs high/low matrices nightly for little gain).
- **Sector rotation lens on Market Rhythm (2026-07-20)** — `DONE`.
  `market_rhythm.build_history` now also writes
  `data/processed/market_rhythm_sectors.parquet` (long format: date, sector,
  winners, eligible — same ≥10%/5d winners and T−5 eligibility, grouped by
  company_master's 22 NSE sectors) and `sector_rotation()` compares the last
  N sessions vs the prior N (dashboard shows 5 and 21). Hot % (winners ÷
  sector's eligible names) is the headline column because raw share always
  crowns the biggest sector (Capital Goods, 337 names). Honest limit: sector
  labels are TODAY's NSE classification applied to history (no historical
  sector feed exists) — fine live, mildly anachronistic pre-2020.
- **Earnings-date proximity (results_due_days) (2026-07-20)** — `DONE`.
  `src/data_collection/nse/earnings_calendar.py` fetches NSE's event-calendar API (forward-looking
  board meetings, ~2-3 weeks out, results-purpose rows only) in eod_update
  step 2 and UPSERTS into `data/processed/earnings_calendar.parquet` (one-day
  API hiccups can't blank it; past dates accumulate as a free last-results
  history). `results_due_days` rides on: every scan candidate + open trade in
  the daily state (new candidate flag "results in Nd — binary event risk" at
  ≤5d), and a 📅 chip in the dashboard chart panel (amber ≤10d, red ≤3d) —
  the "don't hold a fresh breakout into a binary event" check.
- **pct40ma denominator fix (2026-07-20)** — `DONE`. `regime.compute_market_monitor`
  divided by all stocks with a close; stocks with <40 bars (recent IPOs) sat
  in the denominator but could never be above a MA they don't have. Now uses
  the same "close AND MA both present" denominator as pct20ma (live value
  moved 52.3 → 52.9, no zone/tier flip; mm_history rebuilt).
- **Quarterly financials from official NSE filings (2026-07-16)** — `DONE`.
  `src/data_collection/nse/financial_results.py` + `src/data_collection/nse/backfill_financials.py` →
  `data/processed/financials.parquet`: Nifty 500, 2016→now, one row per
  (symbol, quarter, consolidated/standalone) with revenue/other-income/PBT/PAT
  (₹ cr) + basic/diluted EPS and `filing_date` (join on filing_date in
  backtests, never quarter_end — look-ahead). Three source eras handled:
  old-HTML tables (2016–2018, lakhs→cr), legacy XBRL (2019→Dec-2024), and
  SEBI Integrated Filing XBRL (post-Dec-2024 — the legacy API is FROZEN at
  Dec-2024; new quarters only exist under `api/integrated-filing-results`).
  Banks (InterestEarned) and insurers (IRDAI taxonomy, `index=insurance`)
  mapped. XBRL trap: context definitions are unreliable — quarter facts are
  always `contextRef="OneD"` (period-matching returns YTD silently).
  Daily upkeep: `src/data_collection/nse/update_financials.py` = step 4/7 of `eod_update.py`
  (today's IF feed + rotating 1/5-universe weekly reconciliation backstop;
  no new cron). Known gaps: ~4 MNCs absent from NSE's API (ABBOTINDIA,
  BAYERCROP, MCX — would need BSE fallback), 2025 IPOs self-heal as they file.
  `LATER`: earnings-surprise / YoY-growth columns for the EP scanner;
  pre-2016 history (API reaches 2005, one-line SINCE_YEAR change + rerun).

- **Overnight-news scanner + ORB backtest (2026-07-16)** — `DONE`.
  `src/overnight_news.py`: deterministic (no-LLM) ranking of every filing
  broadcast between prior close 15:30 and next open 09:15 — results signed by
  actual YoY PAT from financials.parquet (turnaround +3 / loss-swing −3,
  ±75% YoY caps), order wins sized by ₹-cr regex vs annualized revenue,
  rest via signed keyword lexicon on subject+attchmnttext; NOISE regex drops
  routine paperwork. CLI prints tomorrow's ± watchlist →
  `output/overnight_news/`. Study `src/backtest/studies/overnight_news_orb.py`
  (1,673 events 2018→Mar-2025, |score|≥1.5, turnover≥₹10cr point-in-time,
  no look-ahead — selection uses only pre-open info) + positive events into
  `ep_intraday_orh.py` (126 ORB trades 2024→Mar-2025).
  Findings: the scorer's DIRECTION is real (positive news gaps up 75% of the
  time, median +1.1%; negative gaps down 71%) but the open fully prices it —
  buy-the-open D+5 median −0.8% (win 43%), and next-day long ORB is negative
  too (win 11.1%, mean −0.6%; avg winner +22% doesn't cover 89% stop-outs).
  Bigger gaps do WORSE (5-10% gap bucket mean −3.5%); no score/gap subset is
  positive. Conclusion: after-close news alone ≠ EP edge — the tradable EP
  needs the market's own confirmation (extreme relative volume à la EP9M),
  news is the *why*, not the trigger. Caveats: trades window only 15 months
  (financials end Mar-2025 → backfill pending), results-dominated event mix,
  neglect/novelty gate not yet layered in.
  `LATER`: rerun after financials backfill; test neglected-only subset and
  news × EP9M-volume intersection; short side of negative filings (daily
  study says negative-news names actually mean-revert UP, D+20 +2.0% median
  — shorting them is NOT supported).

- **Washout-reversal event study (2026-07-16)** — `DONE`.
  `src/backtest/studies/washout_reversal.py` (152,135 events 2015–2026: 3rd
  consecutive down close, price≥₹30, turnover≥₹1cr, D+1-open entry; breadth
  score vectorized from regime.py's 5 signals; RS quintiles from the scanner's
  composite formula) + report `output/studies/washout_reversal_study.pdf`.
  Findings: the premise INVERTS — in a good market (score≥+1) 3-down-day buys
  are negative-edge at every horizon (D+5 median −0.40%, win 45.8%), improving
  monotonically with RS rank but only to break-even (RS 80-100 D+20 +0.11%).
  The bounce edge lives in BAD markets (score≤−2): all events D+20 median
  +1.42%/win 55.4%; leader washouts (RS≥80, above 50 DMA, 3-day drop ≤−6%)
  D+5 +1.33%/57.2%, D+20 +2.18%/57.4%. Caveat: bad-market events cluster in
  corrections — overlapping windows riding the market rebound (beta, not
  proven alpha); no benchmark-relative version yet. Data bug found en route:
  405 daily parquets carry stray INTRADAY rows (2016–18, worst PETRONET/ONGC/
  COALINDIA/NMDC ~719 each) which NaN'd close.diff() market-wide and silently
  erased 3 years of events; the study drops non-midnight bars at load, file
  cleanup queued separately.

- **EP volume-spike event study, Stockbee EP9M replication (2026-07-15)** — `DONE`
  (all 3 phases).
  `src/backtest/studies/ep_volume_spike.py` (16,242 events 2015–2026: RVOL≥3×50d,
  turnover≥₹10cr, gain≥5%, ADR≥4, 20-bar cooldown) + `ep_catalyst_overlay.py`
  (catalyst/sector tagging). Data unlocked along the way: NSE announcements API
  serves history to 2015 via date-range queries — `src/data_collection/nse/backfill_announcements.py`
  backfilled 4,046 daily files; `src/preprocessing/build_sector_map.py` maps 1,845 symbols
  (niftyindices lists + filings' smIndustry; niftyindices blocks the microcap CSV).
  Findings: raw signal negative median (D+20 −1.9%, win 44.6%) with a fat right
  tail (10.4% events ≥+20% by D+20); daily-bar LOD stop does NOT flip expectancy
  (72.6% stop-outs — stop too wide from Day 1 open); results-catalyst events beat
  technical-only (win 49.2% vs 44.1%, median −0.2% vs −2.0%); HV180 corr ≈ 0
  (article's US edge not reproduced). Phase 3 (`ep_intraday_orh.py`, 5,246
  trades 2024–2026, Day-0 minute candles cached in data/raw/intraday/minute_day0/):
  the intraday ORH entry + low-so-far stop flips MEAN expectancy positive —
  +4.13%/trade (win 21.8%, avg loss −4.12% vs avg win +32.74%, ~8:1 payoff),
  and unstopped D+5 median +4.4% (win 69.8%) validates the 80% scale-out at
  3–5 days. Fixed stop held 60d still tags 77.6% of trades (median stop-out
  D+8) — the edge REQUIRES scaling out, matching the article. `LATER`:
  catalyst attribution is keyword-based on filing subjects (only ~12% of
  events tagged — generic "Reg 30" subjects miss catalysts; attachment text
  would fix it); phase-3 selection shares the article's look-ahead (full-day
  volume known only at close — live proxy is gap + early RVOL).
  History: the original zigzag/25%-reset stage counted volatility wobbles and
  rarely reset; a TI65 burst-count replaced it, then user challenge + source
  research split it into the two published concepts:
  - `trend_age_d` — Bonde's **Young TI65** scan (stockbee.blogspot.com Trend
    Intensity post): established while TI65 latched ≥1.05 (hysteresis off
    <1.00); **young = established ≤25 bars ago** (his exact scan:
    `avgc7/avgc65 ≥ 1.05 AND avgc7.25/avgc65.25 ≤ 1.05`).
  - `base_count` — Minervini base counting / Bonde 2LYNCH "Y",
    **volatility-normalized 2026-07-10** (fixed 4% was blind to sub-2%-ADR and
    circuit-band stocks): burst = c2c move ≥ 1×ADR20 (floor 2.5%, cap 8%) AND
    new 20-day closing high; quiet day = within 1×ADR20; ≥5 quiet days between
    bursts; ADR shifted one bar (point-in-time). Calibrated on a universe grid —
    1.5×/0.75× collapsed everything to B1; 1.0×/1.0× keeps spread (B1 63%,
    B2 25%, B3 8%, B4+ 4%, ADR-bias corr ≈0.1) and matches fixed-4% counts on
    mid-ADR probes. The Breakout Setup scan keeps Bonde's fixed 4% (setup
    definition). Rejected alternatives: pure structure counting (loses the
    range-expansion character), full IBD weekly base patterns (too slow for
    3-5 day swings; its undercut-reset rule is a `LATER` refinement).
  Display label: "Young 14d · B2" (maturity_label). Old `trend_stage` column
  is gone; old Qullamaggie scan CSVs carry stale values, dashboard always
  re-merges from the universe summary. `LATER`: validate both metrics' edge
  (young-vs-old, B1-2 vs B4+ forward returns) in the regime-conditioned
  backtest.

- **Consolidation definition: volatility-normalized (2026-07-11)** — `DONE`.
  `consol_days`' fixed ±4% reset had corr −0.61 with ADR on the liquid universe:
  calm large caps sat capped at 30d "consolidating forever" (half the bottom ADR
  quintile), 6%-ADR stocks never accumulated a base (61% at ≤2d) — the Breakout
  Setup scan structurally couldn't fire on exactly the high-ADR names the method
  wants. Now: quiet day = |c2c| < 1× prior-20d ADR (clipped 2.5–8%, same
  constants as base counting), and the scan's trigger is the same per-stock
  threshold (new `burst_thr_pct` summary column) — reset and trigger share one
  definition. The implicit volatility filter the fixed 4% provided is now an
  explicit `min_adr_pct=3.0` knob. Normalized: corr −0.08, identical day-counts
  on mid-ADR probes (MUTHOOTMF 10d, EIEL 12d, IONEXCHANG 12d).
  **Kept fixed-4% by design:** the plain 4% Breakout scan and the Market
  Monitor's up4/dn4 counts — cross-sectional breadth vocabulary must stay
  absolute. Boundary: fixed 4% = market-level breadth language; ADR-normalized
  = single-stock structure language. Rejected alternatives: tightness-percentile
  gate (loses the interpretable "N-day base", lags), VCP/structural pattern
  detection (fragile zigzag parameters — same reason as for base counting).
  `LATER`: the Anticipation scan's fixed `range_pct_5d ≤ 12%` has the same
  (milder) bias — revisit with the regime-conditioned backtest.
  - **ADR window 20 → 50 (2026-07-11, same day)** — user spotted that the
    threshold's trailing-20d window overlaps the base it measures: during a
    base, ADR20 sags to ~87% of the stock's characteristic (100d) volatility,
    so a routine intra-base pop spuriously resets the clock (cap-rate 7% at
    ADR20 vs 12-13% at longer windows — ADR20 was truncating real bases).
    ADR50 halves the sag, keeps adaptivity, applied to BOTH `consol_days` and
    `base_count` (one vocabulary). Rejected: lagged window `[i-60..i-20]`
    (zero base-contamination but inherits the prior *trend's* wide bars —
    swaps one contamination for a worse one).
  - **Containment as a complementary definition (2026-07-11)** — researched
    how the canon defines consolidation: Darvas boxes (ceiling/floor untouched
    3+ sessions), O'Neil flat base (≤15% depth, 5+ weeks), Minervini VCP
    (successive contractions each ~half the prior, volume dry-up), Crabel
    NR7/inside days, Bonde quiet-days. Four lenses: event-quiet, containment,
    progressive contraction, volume confirmation. **Conclusion: the Breakout
    Setup scan already combines all four** — `consol_days` (event-quiet) ×
    `consol_range_pct ≤ 15%` (containment; O'Neil's flat-base depth) ×
    `consol_vol_ratio` (dry-up), and Anticipation adds NR7/inside-days;
    Qullamaggie side has `tightening_range_filter` (contraction). The
    containment gate also neutralizes quiet-day counting's drift-leak failure
    mode (a stock drifting +2%/day never has an outsized day but blows
    through the 15% range cap). No new machinery added — deliberately kept
    lean. `LATER` (with the backtest): make the 15% containment cap
    ADR-relative; VCP-style progressive-contraction detection.
- **Momentum-burst quality: linearity + prior-day check (2026-07-11)** — `DONE`.
  Closed the two gaps vs Bonde's "How to identify good momentum burst" post
  (stockbee 2014-01):
  - `trend_quality` (TQ) — his "linear and orderly move ... avoid drunken man
    walk", implemented as Clenow slope×R² over **6 months**, ranked 0-100
    cross-sectionally; **display/sort column only, deliberately not a gate or
    flag** (user decision): the window under-scores young trends
    (EIEL R²=0.03 at trend age 14d) and flat bases (KFINTECH ER≈0 before a
    valid Darvas-style breakout), so gating would kill good candidates. Shown
    in 4% Breakout / Breakout Setup / Anticipation / Breakdown tables + state
    file. Alternatives measured on 300-stock sample: Kaufman ER (corr 0.62
    with R², same window problem), hard ER gate (rejected — false-kills),
    conditional choppy-flag (offered, not chosen).
    **Scoring = min(rank@60d, rank@126d) (2026-07-11, same day, user's visual
    catch):** each window alone is foolable in opposite directions. 60d alone
    scored a 2-month bounce inside a downtrend as linear — INDOAMIN TQ 95
    while down over the year (raw +425 at 60d vs 0 at 6mo); EQUITASBNK 84
    after a year of churn (6mo R² 0.22). 126d alone kept scoring a broken
    trend on its old rise — AXISCADES (+64% four months, then −20% two
    months) ranked 92 at 6mo. min(ranks) = "linear long term AND still
    linear now": AXISCADES→16, INDOAMIN→52, SANSERA→92. Clenow's standard
    90d single window also rejected — fooled both ways (EQUITASBNK raw +140
    at 90d).
    **Scale-dominance check (2026-07-11, user question):** does unbounded
    slope swamp bounded R² in the product? Measured on 400 liquid stocks at
    126d: among positive-slope names the final rank correlates 0.979 with
    slope AND 0.962 with R² (log-dispersion: slope 1.40 vs R² 1.76 — R²
    spreads MORE; its bounded scale punches downward, log(0.02)≈−4 for
    chop); 0 of 24 top-decile names have R² < 0.55. Balanced as-is, no
    reweighting. If a frothy regime ever tilts it slope-ward, the fix is a
    50/50 rank-blend (mean of percentiles per horizon) — revisit only with
    grader evidence.
  - `prior_day_quiet` — his "day prior to range expansion day will be narrow
    range day or negative day": yesterday's range < 0.75× prior-20d average,
    or yesterday red. Default-ON toggle in the Breakout Setup scan.
  `LATER`: leg-scoped linearity (measure orderliness per rally leg once swing
  detection exists) would fix the young-trend blind spot; grade TQ deciles in
  the forward-return grader to decide if it should ever gate.
- **EP family + two-conveyor dashboard (2026-07-12, from Bonde's TraderLion
  2026 talk — transcript in ~/Downloads/stockbee_2026_traderlion_transcript.md)**
  — `DONE` (phase 1 of the talk's setups).
  - `strategies/stockbee/ep_family.py`: **EP9M** (top 2% of NSE by share
    volume today + novelty gate [not usually top decile] + ₹30 price floor +
    ₹10cr event turnover; direction-agnostic; ~5/day; user chose share-volume
    + qualifiers over turnover), **DEP** (F&O or ₹25cr+ names, EP9M event 2-25
    sessions back with ≥4% event move, still defended, within 15% of
    post-event high, range_pct_5d ≤ 8), **EP Checklist** (tonight's
    catalyst-category filings × neglect, for tomorrow's open). All three in
    daily_state + Setups tab.
  - **Critical data fix**: NSE announcements endpoint without from_date/
    to_date returns only its latest ~20 filings — every cached day was a
    20-row stub, which is what starved EP catalyst tagging all along.
    Fixed + backfilled 26 sessions (~500-900 filings/day).
  - **Dashboard two-conveyor reorg**: tabs now Daily Brief / Universe /
    🔍 Scans (4% up/down, TI65 — market vocabulary) / 🎯 Setups (EP9M, DEP,
    EP Checklist, Breakout Setup, Anticipation, Swing Exhaustion) / Market
    Monitor / How Scans Work. `show_table` moved to ui.py.
  - `DONE (2026-07-12, phase 2)` — the rest of the talk:
    - **Reversal Bullish** (`scans.reversal_bullish` + Setups tab):
      institutional-quality only (F&O/₹25cr), `down_streak` ≥ 2 cascade ending
      yesterday, today reverses with range_pos ≥ 0.6. New `down_streak`
      summary column.
    - **Bottom Bounce** (`scans.bottom_bounce`): ≥25% off 52w high, +4% on
      volume; **context-gated on pct40ma < 20** — daily state suppresses
      candidates when the context is off; dashboard shows study-only banner.
    - **Weak Structure short** (`scans.weak_structure_short`): precomputed
      flag — 3 down closes, 2-3 day pause (±1.5%), selling resumes today;
      TI65 < 1 gate.
    - **T2108 analog + 20%-in-5-days oscillator**: `up20_5d`/`dn20_5d` (close
      ≥ ₹30) added to `regime.compute_market_monitor`; Market Monitor tab got
      both oscillator charts + reading guides (washout exception: first spike
      off pct40ma<20 is ignition, not a warning). Display-only — NOT regime
      signals until the backtest calibrates them. **Ratios kept by explicit
      user choice** despite Bonde calling them bloatware (2026-07-12).
    - **Stop-half rule**: "Stop ½-day" chip in the chart level strip
      (late-in-day entries stop at half the day's range); rule added to
      /brief skill.
    - **3-stop-outs circuit-breaker**: red banner in Daily Brief + BLOCK gate
      in /brief when ≥3 tracked trades sit on stop-outs. Approximation: uses
      tracker *status* (no per-day stop timestamps) — counts currently-stopped
      trades, not literally "today"; clear stopped trades from the tracker to
      reset.
  - `LATER` (talk items still open): anticipation late-day timing + Bonde's
    ≤±1% tight variant (needs intraday); listings-count bubble indicator
    (needs historical listings series).
  - `LATER` data: ~~shares-outstanding/market-cap feed~~ — `DONE` 2026-07-20:
    `src/data_collection/other/company_master.py` refreshes shares_out nightly (BSE whole-exchange
    mcap API joined to NSE EQUITY_L on ISIN — NSE's own quote API is
    bot-blocked; ~95% coverage, NSE-only listings keep the 2026-07-15 values);
    precompute writes `mcap_cr` into the universe summary, shown across both
    dashboards. Still open: actually USING mcap as an EP9M cap qualifier /
    "fund quality" leg; analyst price-target and short-interest feeds have no
    free NSE source (MAGNA "5"/"3" legs stay manual research).
- **research/ — Bonde-style mover studies (2026-07-12)** — `DONE` (v1).
  Autoresearch-pattern framework (fixed engine + one spec file per idea +
  comparable reports + LOG.md): `framework.py` detects merged episodes
  (X% within Y bars; pivot = lowest close before the peak; overlapping
  windows collapse to one episode), computes ~30 pre-pivot features (strictly
  ≤ pivot; MAs, consolidation, linearity, volume, RS percentile, MM state,
  EP9M footprint) + during-move features (4% days, consec-ups, circuit-like
  days, drawdown, volume multiple), joins pivot-date NSE announcements
  (--fetch-catalysts backfills missing dates), and — the methodological core —
  draws a **same-date non-mover baseline** so every stat is a lift, not a
  description. Studies: `up20_in_5d`, `up50_in_63d`. See research/PROGRAM.md
  for the agent contract and the bias rules (descriptive-not-predictive,
  survivorship, tradability/circuits, catalyst coverage, multiplicity).
  Found + fixed in passing: tz-aware/naive date mixing and duplicate date
  rows in 9 parquets (spawned cleanup task for the updater root cause).
  `LATER`: promote strong, cross-study lifts into backtestable rules;
  down-move studies (dn20 in 5d for the short book); catalyst backfill to
  2 years (~500 API days).
- **F&O mover anatomy study (2026-07-28)** — `DONE`.
  `src/backtest/studies/mover_anatomy_fno.py` — companion to the research/
  framework, on the F&O universe (210 current names; no point-in-time
  membership — survivorship caveat) at +20%/22 bars, 2016→now, 2,927 episodes.
  Adds what the framework specs don't cover: during-move anatomy (62% up days,
  max 3 consecutive red, -6.4% median pullback, 42% of gain from overnight
  gaps), the ignition day (first ≥4% day, median day 6, 1.85x vol, only 40%
  are 20d-high breakouts), archetype mix (60% reversal/washout vs 18%
  near-high consolidation), week-burst rarity (3.5%), post-peak retrace (~24%
  of move in 21d). Report: `output/studies/mover_anatomy_fno_study.pdf`.
  `LATER`: run an F&O-only +20%/22d spec through research/framework.py to get
  non-mover baseline lifts for the same findings; down-move twin for shorts.
  **Survivorship-corrected rerun (same day)** — `DONE`.
  `src/backtest/studies/mover_anatomy_size.py`: full universe (19,726 episodes,
  1,663 symbols, point-in-time tradeability gate at D0) with size class ON the
  move day via mcap rank (today's shares x that-day close; large 100 / mid 250 /
  small 500 / micro). Verdict: anatomy is size-invariant (gain ~30%, ignition
  day ~6 at ~+5.5% on ~2x vol, -6 to -7% pullback, 3 red days, ~42% gap share) —
  F&O-study conclusions survive; size changes frequency/speed/aftermath
  monotonically (micro: 7.1% week-bursts, 24d to peak, 0.32 retrace vs large
  2.6%/33d/0.26). F&O-list bias measured: sits between PIT large and mid,
  ~+1.7pp gain flattery, no conclusion flips. Mid-caps (101-250) = sweet spot
  (45% of ignitions are 20d-high breakouts, cleanest scannability).
  Report: `output/studies/mover_anatomy_size_study.pdf`.
  **Lifecycle teaching report (same day)** — `DONE`.
  `mover_lifecycle.py` (day-level sequence features: 4% day count/timing, red
  days, CLV/reversal days, pullback count, volume by phase, peak character,
  death) + `mover_lifecycle_examples.py` (annotated VOLTAS/WIPRO/RVNL/GENESYS
  charts) + `output/studies/mover_lifecycle_report.pdf` (11-page self-contained
  "Life of a Big Move" synthesis incl. research/ framework baselines). New
  sequence findings: 4% days back-loaded (46% in final third), volume crescendo
  0.74→1.18x, median move has 3 reversal days + 39% red days, peak day is a
  +3.3% climax on 2.6x vol (43% a 4% day), death = 10% off high within median
  7 days, only 17% of moves start with a 4% day.
  **Controls + failure cohort (same day)** — `DONE`.
  `mover_controls_failures.py`: (1) 18,539 matched controls (same date/size/
  length, non-mover) — distinctive: 4x burst count, 2x gap-ups, crescendo
  (control volume flat 0.64x), climactic peak (43% vs 20% 4%-day, 2.55x vs
  1.19x vol); wallpaper: pullbacks identical (2 vs 2), movers have FEWER red
  days than controls (39% vs 50%). (2) 12,352 failed moves (+10% but died
  <+20%, slow completers excluded): P(20|10)=61% base; day-10 burst count
  0→51% / 3+→87%; ignition 3d follow-through <-3%→56% / >+4%→80%; polite
  0-5% drift by d10 = worst bucket (48%), deep early pullback/undercut beats
  it. Report updated to 13pp with referee + almost-made-it sections.
  `LATER` from the improvement review: hazard curves (P(peaked|state)),
  peak-day vs mid-move new-high-day mechanical check, threshold robustness
  (15/25/30%, 8/12% retrace), ignition-day catalyst tagging, per-era
  stability, circuit-proxy counts, PIT backtest of ignition entry.
- **Order execution module (2026-07-14)** — `DONE`. `src/orders/`
  (plans.py / execute.py / trail.py / cli.py) + `/trade` skill: natural
  language → validated plan JSON (`output/orders/plans/`) → preview (funds,
  ASM/GSM, GTT trigger-gap, tick rounding) → **human types PLACE** → entry
  order + GTT stop or OCO stop+target; `trail.py` engine ratchets GTT stops
  (long-only) during market hours, state in the GTT itself. Action log:
  `output/orders/orders_log.jsonl`. **Deliberately distinct from the
  rejected "automatic order placement from the brief"**: that item = the
  brief firing orders autonomously; this = user-initiated, AI prepares,
  human confirms every placement. The AI layer (skill rule) never runs
  `place`/`cancel`/`delete-gtt`/`trail-run` itself.
  `LATER`: short-side trailing; ATR-based trails; move-to-breakeven rule;
  launchd/cron auto-start of the trail engine on market open.
  - **Execution path blocked → manual mode (2026-07-14).** SEBI (eff.
    2026-04-01) requires a whitelisted static IP for order-placement API
    calls; user is on CGNAT JioFiber (verified: private hops after the
    router, shared egress IP) so no stable IP exists to whitelist, and the
    list allows only ONE change per calendar week. Decision: **skip for
    now, punch orders manually in the Kite app** — plans/previews/status
    still come from this module; the /trade skill emits a manual punch-in
    card instead of `place`. Trailing via Kite's native trailing-GTT in
    the app (account has it), not `trail-run`. Revisit options (researched
    2026-07-14, cheapest first): Oracle Cloud always-free VM as SSH proxy
    (₹0, needs `KITE_PROXY` support in auth.py), budget annual VPS
    (~₹100/mo), Lightsail/DO Mumbai (~₹450/mo), JioFiber static-IP add-on
    by phone (₹200–500/mo, area-dependent, unofficial).
- **Dashboard UX: chart news popup + brief market context (2026-07-16)** — `DONE`.
  (1) Every chart shows 📰 dots on bars with catalyst-grade NSE filings
  (routine categories excluded: other / board_meeting / analyst_meet /
  insider_trade); clicking the bar opens a floating popup with category chip,
  filing text and PDF link. Weekend/holiday filings attach to the next trading
  bar. `data_loader.load_announcements` pools the last ~2y of daily CSVs
  (~1s, cached on newest file). (2) Daily Brief's anticipation table is
  row-clickable → full annotated chart panel below it. (3) Daily Brief adds a
  deterministic TL;DR line, a global-markets chip strip, and a Pulse headlines
  expander (`state["news"]` was written nightly but never rendered until now).
  (4) `src/data_collection/other/global_markets.py` — Nifty/Bank Nifty, S&P 500, Nasdaq, Dow,
  Nikkei, Hang Seng, USD/INR, Brent, Gold from Yahoo's public chart endpoint
  via plain requests (Stooq now sits behind an anti-bot wall); fetched live
  by the dashboard (15-min cache) because the 10 PM state snapshot predates
  the US close. Context only — never a regime input. The "yfinance rejected"
  entry stands: no yfinance dependency, no NSE OHLCV touched; there is no
  NSE-native source for global indices. /brief SKILL.md gains matching TL;DR
  and Other-markets sections.
- **Dashboard UX round 2: SA narrative + company info + roomier charts
  (2026-07-16)** — `DONE`.
  (1) `state["participation"]` — market-wide turnover today vs prior-20d avg
  (`daily_state._participation`), the deterministic anchor for the
  situational-awareness read; shown in the Daily Brief TL;DR.
  (2) **#SituationalAwareness** — /brief now writes a trader's-notebook
  narrative (watchlist-size trend from recent state files, participation
  read, which setup families deserve preference, what would change the view)
  plus a graded **review of yesterday's SA**, both persisted as
  `situational_awareness` / `sa_review` fields in journal.jsonl; the Daily
  Brief tab renders them from the journal (dashboard never authors prose —
  LLM narrates, regime stays deterministic).
  (3) Company identity everywhere: `company_master.parquet` (name, sector,
  industry, shares_out→mcap_cr, about) merged into the universe summary at
  load; Sector column auto-injected into every scan/setup table
  (`ui.show_table`); chart panel gets a name · sector · industry · Mcap line
  and an "About" expander with the business description + last 4 quarters
  from financials.parquet.
  (4) Chart de-compaction: table/chart split 50/50 → 40/60 on Universe /
  Scans / Setups, height 560→620, price pane 64%→70%.
  (5) Modern-compact pass (same day, user feedback "too big / toggles take
  space"): the 2×4 st.metric grid in the chart panel replaced by a one-row
  stat-chip strip (`ui._stat_strip`); ALL filter sliders/toggles on
  Universe / Scans / Setups moved into a single `st.popover("⚙️ Filters &
  thresholds")` per tab (branch-specific params re-enter the same popover
  container); radio groups restyled as pills via CSS in app.py (dot hidden,
  `:has(input:checked)` highlight — needs a Chromium/Safari-era browser).
- **Dashboard performance pass (2026-07-16)** — `DONE`. Profiled, then fixed
  the four real bottlenecks: cold start 7.3s → 3.8s, warm rerun (every
  slider/click) 1.0s → 0.22s.
  (1) EP9M+DEP walked the full matrices on every rerun (~1.4s) → results
  cached on close_matrix mtime (`setups._ep9m_cached`/`_dep_cached`).
  (2) `st.cache_data` pickle-copied the ~50MB matrices and the universe
  summary on every hit → switched to `st.cache_resource` (shared read-only
  frames; verified no consumer mutates them — scans/tabs all filter into new
  frames).
  (3) Global-markets fetch was 10 sequential HTTP calls (~3s) → parallel
  ThreadPoolExecutor (~0.5s).
  (4) Announcement pooling re-read ~500 CSVs per session (~0.8s) → persisted
  to `data/processed/announcements_pool.parquet`, auto-rebuilt when a newer
  daily CSV lands (~20ms reads after).
  Rule of thumb encoded here: big frames = cache_resource + treat as
  read-only; small derived results = cache_data keyed on source-file mtime.
- **Intraday EP alerts** — `LATER`. `src/data_collection/kite/intraday.py` exists; wire into the EP
  scanner for opening-range breakout detection on gap days (Indian EPs pin at
  upper circuits — intraday confirmation matters more here than in the US).
- **More strategies** — `LATER`. Scaffold under `strategies/<name>/` from the
  existing filter blocks. Use `docs/` (e.g. the Stockbee reference) to pick the
  next subset to implement.
- **Auto-push daily anticipation list to a Kite watchlist** — `LATER`. Official
  Kite Connect has no watchlist API; only the unofficial enctoken route
  (`kiteext`/`kitetrader`) can write native marketwatch — fragile, needs a daily
  web-session token. For now export the list to `output/watchlist/` for manual add.
- **Nightly split/bonus integrity repair (2026-07-10)** — `DONE`. eod_update
  step 5/6: vectorized 22% d/d scan over the last 60 sessions of the close
  matrix (22% ≈ just above the 20% circuit band; the old 35% CLI threshold
  missed GOLDIAM's −29% break), auto re-fetch of flagged symbols from Kite,
  precompute re-runs when repairs land. Breaks that survive a re-fetch are
  genuine (F&O crashes, demergers — Kite does NOT adjust demergers, e.g. VEDL
  2026-04-30) and are remembered in
  `data/processed/price_breaks_confirmed.json` to avoid nightly re-fetch
  loops. First sweep repaired 10 symbols incl. TRENT, VEDL, GOLDIAM, E2E.
  - `LATER` hardening: NSE corporate-actions feed for sub-threshold actions
    (small bonuses, dividends) and demerger-aware return adjustment.

- **Backtest engine extensions** — `LATER`: EP/parabolic setups, slippage/cost
  model (STT, stamp duty, GST, SEBI charges), historical ASM/GSM lists.
- **Broker-upgrades filter** — `DEFERRED`: no reliable free data source;
  StockEdge (~₹2K/yr) is the cleanest option, not subscribed.
- **PR to ai-hedge-fund-india (Zerodha integration / Indian backtesting)** —
  `LATER`, side quest: `src/data_collection/kite/historical.py`/`updater.py` map closely onto their
  open ask. Independent of this platform's roadmap.

## Removed from the UI (code retained)

- **Qullamaggie Setups + Zanger tabs** — removed 2026-07-12 in the
  two-conveyor reorg ("drop for now" — user). Scanner code retained under
  `strategies/qullamaggie/` and `strategies/zanger/`;
  `dashboard/tabs/zanger_scans.py` deleted 2026-07-20 (with the side-panel
  helpers it depended on, replaced by the chart popup); `stockbee_scans.py`
  deleted (replaced by `tabs/scans.py` + `tabs/setups.py`). **Triage mode lost its UI
  surface** with the Qullamaggie tab — `triage.py` and its W/X verdicts file
  are retained (the post-study grader depends on them); re-attach triage to
  the Setups tab if the review workflow is missed. The trend-maturity
  explainer that lived in the Qullamaggie tab moved to How Scans Work.

- **Shortlists / watchlists** — removed 2026-07-10 at user request ("just an
  overhead"). Deleted: the ⭐ Shortlists tab, `dashboard/tabs/watchlists.py`,
  `dashboard/watchlist_store.py`, the ⭐ Add button on chart panels, and
  triage's W-key side effect of adding to a "Focus" list. **Triage W/X
  verdicts still persist** in `data/processed/triage_verdicts.json` — the
  post-study grader depends on them. Old saved lists remain on disk in
  `data/processed/` (data untouched, only code removed). The curated-names
  role is now served by the Daily Brief tab (clean candidates + anticipation
  watchlist from the state file).

- **Episodic Pivot, both dashboard surfaces** — removed 2026-07-10 at user
  request ("not working"). Diagnosis: the Qullamaggie EP tab read a scanner
  CSV that was never generated (always empty), and catalyst tagging has no
  data. The EP *condition itself* is alive — 8% gap + 3× volume fired on 54 of
  the last 60 sessions, ~2.7 candidates/day pre-filters — and still runs in
  `daily_state.py` and the /brief. Restore a UI surface only alongside the
  catalyst feed fix and/or intraday EP alerts (see LATER items).

## Rejected (do not re-propose without new evidence)

- **Multi-agent investor-personality debate (22 LangGraph agents, à la
  ai-hedge-fund-india)** — rejected 2026-07-10. Architecture theater for a
  mechanical-setup swing system; adds cost/latency/noise, no edge. Adopted
  instead: deterministic gates + one judgment pass (the /brief skill).
- ~~**Rebuilding the dashboard off Streamlit (React/other framework)**~~ —
  rejected 2026-07-10, **reversed by user 2026-08-06**: the goal changed from
  "frozen human viewer" to a third-party-facing website. Built as `webapp/`
  (FastAPI :8700 + React/Vite :5173, CRED-style dark UI); all Streamlit tabs
  ported (Brief, Setups, Screener, Scans, Monitor+Rhythm, Sectors, Strategies,
  Order Pad, docs) plus the live scanner merged in via an `/api/live/*` proxy
  to the 8602 engine. `dashboard/` Streamlit code deleted (only `assets/`
  remains, used by `src/live_anticipation.py`); cron no longer restarts
  Streamlit. Machine consumers still read `output/state/*.json` — the webapp
  renders the same files.
- **LLM-defined market regime** — rejected 2026-07-10. The regime tier and
  exposure knobs are deterministic (`src/preprocessing/breadth.py`); LLMs may narrate them,
  never override them.
- **Automatic order placement from the brief** — rejected 2026-07-10. The
  brief prepares decisions; the human executes. Revisit only after the journal
  grader (overhaul 3) proves the recommendations have edge over months.
- **yfinance as a data source** — rejected long-standing. Kite + NSE bhavcopy
  with reconciliation is already built and more reliable for NSE.
- **Re-running `src/migrate.py`** — one-time CSV→parquet migration, done.
- **"Lifetime-high trend + weekly-RSI-oversold pullback"** (YouTube
  "millionaire trader" 3-timeframe setup) — rejected 2026-08-07 at factory
  S2/S4/S5. The published rule is **empty**: lifetime-high eligibility and
  weekly RSI(14)<30 are near mutually exclusive (1 event in 11.5 years across
  64,777 base-breakouts; the 0.1st-percentile weekly RSI among eligible names
  is 36). Loosening the oversold bar to a within-cohort bottom decile gives
  +0.32R in era B but only +0.06R over the no-oversold control, a per-year
  edge that is negative in 6 of 10 years, and a heat-capped book of
  **+1.8–2.9%/yr ex-COVID** (below the +3% bar) because the 14.8% median stop
  refuses ~85% of signals. **Reusable finding: the ATH-proximity filter is a
  2015-19 artifact** (+0.12/+0.05/+0.31R edge in 2017-19, ≈0 or negative every
  year 2020-26) — do not add an all-time-high gate to a live strategy expecting
  it to pay. Full verdict + red-team:
  `research/factory/lifetime_high_pullback/VERDICT.md`.

- **Turn-of-month timing** (buy the close of the 5th-last trading day, sell the
  close of the 3rd trading day of the new month; 7 trading days, 12x/yr) —
  rejected 2026-08-19 **as a return strategy**. The anomaly is real and one of
  the best-evidenced tested here: S&P 500 1928-2026 shows +8.54 bps/day in-window
  (permutation p<0.0001, positive in *every* era, unchanged at 8.43 bps when
  2020-23 is dropped), and BSE Sensex 1997-2026 shows +0.880%/trade **excluding**
  2020-23 (n=301, t=4.20, permutation p=0.0002). It is **not tradeable for excess
  return**: the window does not create return, it concentrates it, so buy-and-hold
  collects the same rupees. Being out of the market 66% of the time forfeits ~2/3
  of dividends (-0.8%/yr), and 12 realised trades a year pay 20% STCG annually
  (plus slab-rate tax on the idle-cash interest) against buy-and-hold's deferred
  12.5% LTCG. Ex-boom forward economics: Nifty 2007-2026 **8.1% vs 10.5%**
  buy-and-hold; Sensex 1997-2026 **12.2% vs 11.6%** — a tie at best, negative
  after tax. What *does* survive is risk: max drawdown **-13% vs -38%** with ~57%
  of the volatility. Revisit only as a defensive / drawdown overlay, never as an
  alpha source. Vehicle ranking (share of the edge captured): **ETF 100% >
  futures ~90% > deep-ITM call 71% > naked short put 59% > long ATM call 22% >
  bull put spread 10%**.

  **Reusable findings (these generalise well beyond this study):**
  1. **The stored universe is 100% survivors.** 0 of 2,005 symbols in the
     backtest cache have a price series ending early; DHFL, RELCAPITAL,
     JETAIRWAYS, RCOM, VIDEOIND, COX&KINGS, SINTEX are simply absent. Any CAGR
     from a reconstructed basket is fiction. For anything survivorship-sensitive,
     anchor on a **published index** — it already contains its own deletions.
     Cost here was small (+1.24 bps of a 16.18 bps spread) only because the test
     was large-cap; the smallcap version would be uninterpretable.
  2. **11 years cannot test a monthly seasonal.** 90-138 trades detects only
     effects >=0.61%/trade at 80% power; the true effect is 0.57-0.88%. The first
     pass here wrongly concluded "no effect in India" — it needed ~27 years.
     **Never read "not significant" as "no effect" on a 12-events-a-year study.**
  3. **Breadth does not buy power.** Nifty 500 vs Nifty 50 daily correlation is
     **0.978**. For a market-wide seasonal the effective sample is the number of
     MONTHS, not stocks x months. Only more years help.
  4. **A drift edge cannot be expressed in options.** Across six structures P&L
     ranked *perfectly* by delta. Realised vol in the window (16.5%) equals the
     rest of the month (16.1%), so there is no vol mispricing to offset premium.
     A 14-DTE ATM call held 10 days needs **+1.21%** to break even against a
     +0.88% edge. Applies to every drift/seasonal signal: express it in delta-1.
  5. **Month-end futures rollover tax.** Holding the far Nifty contract across
     the turn costs **0.101%/trade (-1.2pp/yr) more than a mid-month control**
     (n=90 paired months, t=-3.55, assumption-free — cancels the carry rate).
     Far-contract basis peaks ~4 days before expiry and collapses across the
     turn. **Applies to ANY strategy holding Nifty futures across a month
     boundary** — prefer the ETF when the calendar allows.
  6. **Never price a spread on a flat vol surface.** Flat-vol pricing overstates
     a bull put spread by 2.5x (+0.244% vs +0.097% at skew 1.2 pts/1% OTM; it hits
     exactly zero at skew 2.0, which is a normal Nifty weekly skew). Spreads are
     also near vega-neutral, so "sell premium when IV is high" does almost nothing.

  **Data added, reusable:** `data/processed/nifty_futures.parquet` (5,622 near/far
  NIFTY futures contract-days, 2019-01 to 2026-07) via `src/data_collection/nse/fo_bhavcopy.py`
  (NSE F&O bhavcopy fetcher, handles both the legacy and post-2024-07 UDiFF
  formats). Kite only exposes the 3 *live* contracts, so this archive is the only
  free route to expired-contract history.

  **Note on sources:** long index history (S&P 1928+, Sensex 1997+, Nifty 2007+)
  came from the Yahoo chart API because Kite history starts 2015. This is a
  research-only one-off for pre-2015 index series and does **not** reopen the
  standing rejection of yfinance for the NSE data pipeline.

  Studies: `src/backtest/studies/turn_of_month{,_audit,_options,_basis,_robustness,_longhistory,_putspread}.py`.


## Decisions needed (blocking)

- (none open)

## Decisions resolved

- **Is the F&O book ring-fenced from the swing risk budget?** (asked
  2026-07-10, **answered 2026-07-18: NO — one bucket**). F&O notional counts
  against the regime's gross-exposure cap; while it exceeds the cap, all new
  swing entries stay BLOCKed by design. Encoded in
  `.claude/skills/brief/SKILL.md`. Revisit only if the forward-return grader
  shows blocked recommendations consistently outperforming over months.
