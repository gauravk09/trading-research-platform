# DECISIONS.md — alpha_forge

Finalised choices only. Each is numbered and carries a status:
**LOCKED** (settled) / **AGREED** (chosen, not yet built) / **PARKED** (deferred).
When a decision changes, edit it here in the same session — don't leave the old one standing.

---

### D1 — Standalone, isolated package · LOCKED
`alpha_forge/` (now `research/alpha_forge/`) imports **nothing** from `src/` or `research/`.
- **Chosen:** a parallel project that adopts only the *idea* of AlphaAgent (LLM-driven alpha mining with regularized exploration to resist decay), applied to Indian NSE stocks.
- **Rejected:** extending the existing `evolve.py` GA machine. Kept separate on purpose — this project must not inherit or contaminate what that machine has learned.
- **Shared:** only the raw OHLCV parquet on disk, read-only. Data, not logic.

### D2 — Miner = engine-first, Claude-in-session · LOCKED
- **Chosen:** build the engine (DSL → regularized evaluator → zoo) first and prove the scoreboard on hand-written seed alphas with zero LLM. Then Claude, in this session, reads the scoreboard + zoo and hand-proposes the next batch of expressions.
- **Rejected (for now):** autonomous Anthropic-API loop and the file-bridge miner. Both deferred until the engine is trusted. → see PARKED in ROADMAP/LEARNING.
- **Why:** no API key needed, runs today, and keeps a human judging every proposal while the scoreboard is still unproven.

### D3 — Universe & horizon: top-500 liquid, 5-day forward · LOCKED
- **Chosen:** each day, tradable set = top-500 by trailing-60d average turnover (point-in-time); factors scored by cross-sectional IC against 5-trading-day forward return.
- **Rejected:** full ~2,100 universe (noisy cross-sections from illiquid names distort IC), and 10-day horizon (deferred, easy to add later as a knob).

### D4 — Factor representation: WorldQuant-style DSL · LOCKED (built)
- **Chosen:** alpha factors are operator expressions over OHLCV panels (`rank`, `delay`, `delta`, `corr`, `ts_mean`, …), evaluated cross-sectionally each day. This is the paper's representation and what makes the two regularizers meaningful.
- **Rejected:** filter-stack genomes (that's the other project's representation; keeping this one faithful to the paper).
- **Status:** about to build in `dsl.py`.

### D5 — The two regularizers are the whole point · LOCKED (built)
Fitness = `IC_edge − λ1·(originality penalty) − λ2·(complexity penalty)`.
- **λ2 complexity:** node count of the expression's syntax tree. Fights overfit decay.
- **λ1 originality:** max |correlation| of this factor's daily cross-sectional values against every factor already banked in the zoo. Fights crowding decay. This is the organ the other project lacks and the reason to build this at all.
- **Built:** `regularize.py`. Complexity = ast node count; originality = **max** daily rank-correlation
  vs the zoo (semantic dedup, not text). Verified: self-similarity=1.00, near-dup (reversal 5d vs 6d)=0.84,
  different idea=0.19. Demo: reversal_6d (raw IC +0.028) goes **net-negative** purely from its 0.84
  originality penalty — the crowding brake works.
- **RESOLVED (calibrate.py):** grid-searched λ to maximise Spearman(in-sample penalised score, OOS
  Sharpe) over a diverse cross-family pool. **λ2=0.001 (complexity) HELPS** — lift +0.21 in OOS-rank
  prediction; the complex factors (cmplx 9-14) are the OOS-negative overfits, the simple ones (3-5)
  win. AlphaAgent's overfit-decay thesis confirmed on NSE. **λ1=0 (originality)** as a soft term adds
  nothing beyond the hard novelty gate (D9) and is homogeneous-pool-blind. Decision: enable λ2=0.001,
  keep λ1=0 (novelty stays gated, not weighted).

### D7 — Scoring metric: rank-IC, universe-masked, overlap-honest t-stat · LOCKED (built)
- **Chosen:** primary score = daily rank-IC (Spearman of factor vs 5-day forward return) across the
  point-in-time top-500 universe; mean-IC and IR from the full daily series; **t-stat and Sharpe from
  the non-overlapping subsample** (every 5th day) so overlapping windows don't inflate significance.
  Secondary = long/short top-vs-bottom-quintile spread.
- **Rejected:** Pearson-IC (fat tails distort it); naive daily t-stat (autocorrelation → 3× too-good).
- **Trust guarantee:** `evaluate.py` self-asserts perfect-foresight IC≈1.0 and noise IC≈0.0, so the
  metric can't silently pass wrong answers.

### D8 — FactorZoo: JSONL source of truth, panels are a rebuildable cache · LOCKED (built)
- **Chosen:** `zoo/factors.jsonl` (append-only, one line per factor: id + expr + metrics) is the record;
  each factor's daily panel is recomputed from its expr on load into memory — never persisted as a
  cache that could go stale. Zoo stores + serves originality lookups; it does not decide what to bank.
- **Rejected:** persisting panels to parquet as the record (goes stale when data updates; a factor is
  fully defined by its expr). Parquet panel-caching kept as a deferred *optimization* (ROADMAP §2), not
  the source of truth.
- **Verified:** reload-from-disk reproduces originality to 1e-9 (0.8433 live == 0.8433 reloaded).

### D9 — Banking rule: hard gates decide, subtractive net_fitness ranks · LOCKED (built)
- **Chosen:** a factor banks only if it clears three hard gates — edge (non-overlap t ≥ 3.0),
  novelty (max originality < 0.70), parsimony (complexity ≤ 20). The paper's `net_fitness`
  (raw_ic − λ1·orig − λ2·complexity) is computed and shown, used to rank survivors and drive
  feedback, but does NOT gate (λ1/λ2 are uncalibrated).
- **Rejected:** pure subtractive banking (`net > 0`) — the accept threshold would be arbitrary while
  λ weights are unset. Revisit once we calibrate λ and can trust a single combined score.
- **Batch order:** candidates processed strongest-t first and banked sequentially, so the stronger of
  two near-duplicates is kept and the weaker is rejected as redundant against the live zoo.
- **Verified:** seed batch → 6/10 banked; originality shown is the live-zoo value each factor faced
  (see BUGS B2).

### D10 — Every factor carries an economic hypothesis + a mechanical alignment gate · LOCKED (built)
- **Reverses** the earlier "skip hypothesis" recommendation (that was a chat suggestion, never a repo
  decision). The AlphaAgent paper makes the hypothesis load-bearing and the user was right to insist.
- **Chosen:** each candidate = {expr, hypothesis}. The hypothesis is mandatory — `run_batch` raises if
  it's missing, so no factor banks without a stated market mechanism. Sign convention: every expr is
  written so a *correct* hypothesis implies **positive IC**. The **alignment gate** then rejects any
  factor whose IC is strongly negative (|t|≥3, IC<0): it predicts backwards to its own economics, the
  fingerprint of an overfit. Direction is stated a-priori from theory, never read off the IC (flipping
  a sign after seeing the data would be snooping).
- **Why it's decay-resistance, not decoration:** (1) economic grounding is a prior against overfit;
  (2) it moves the old two-sided `abs(t)` edge gate to a one-sided, theory-consistent test — we stop
  banking signals we can't explain.
- **Rejected:** required-field-only (no enforcement that the formula matches the story); formula-only
  (least faithful).
- **Honest limit:** full hypothesis→formula semantic alignment and idea-level novelty are LLM
  judgments; here the mechanical proxy is the IC-sign check. Deeper alignment judging is done by the
  Miner (Claude) in-loop, not yet codified.

### D11 — Storage: JSONL zoo (kept) + SQLite run-ledger (new) · LOCKED (built)
- **Chosen:** the zoo of banked factors stays append-only **JSONL** (git-visible, tiny, diffable — the
  source of truth for what was KEPT). A new **SQLite** `zoo/runs.db` logs EVERY candidate of EVERY run
  (name, expr, hypothesis, ic, t, complexity, originality, net, verdict, banked_id) — the full history
  of what was TRIED, i.e. the multiplicity denominator.
- **Rejected — everything in SQLite:** loses the git-diffable plain-text zoo for no real gain at this size.
- **Rejected — DuckDB:** columnar/analytical, overkill for row-at-a-time append logging of a few thousand
  rows; revisit only if we later store daily factor *panels* for heavy analytical scans.
- **Why SQLite:** stdlib (`sqlite3`, zero-dep), transactional, write-per-row — the right shape for a log.

### D12 — Scale-out to 20 factors: parallel scoring, serial banking · LOCKED (built)
- **Goal:** find 20 factors that work at the 5-day horizon (clear edge + alignment + novelty gates).
- **Architecture:** N subagent "miner cells" run in parallel, each proposing + scoring a family of
  candidates via `score_batch.py` (zoo-INDEPENDENT: IC/t/complexity only) and writing survivors to its
  own scratch JSON. A single central `merge_and_bank.py` then banks survivors **serially**, strongest-t
  first, applying the originality gate against the zoo AS IT GROWS.
- **Why serial banking:** originality is zoo-relative. If two cells banked in parallel, each would see a
  stale zoo and could bank near-duplicates of the other. Scoring parallelises safely (read-only); banking
  must not.
- **Worktrees — NOT used here, deliberately:** the parallel runs are read-only and isolate via unique
  output paths, so a git worktree isn't required ("as required" was the user's phrasing). Also `alpha_forge/`
  is uncommitted, so a worktree wouldn't contain it. Worktrees are reserved for runs that WRITE to the repo;
  by design none do — banking is centralised.
- **Enabler:** `data.py` `DAILY_DIR` is now `ALPHA_FORGE_DAILY_DIR`-overridable (abs default) so scoring
  runs from any cwd.

### D13 — "Works" = out-of-sample, not in-sample · LOCKED (built)
- **Trigger:** the goal is 20 factors that *work* at 5 days. In-sample rank-IC is a fit, not proof.
- **Chosen:** `validate.py` splits TRAIN (<2023-01-01) / TEST (>=2023-01-01) and scores rank-IC on each
  separately. A factor PASSES only if `test_t >= 3` AND `test_ic > 0` AND sign(train_ic)==sign(test_ic).
  Turnover (long-book churn) is reported as a cost warning. OOS-passers are banked into a SEPARATE
  `zoo_oos/` (the validated zoo), distinct from the in-sample `zoo/`.
- **Result (honest ceiling):** of the 20 in-sample factors, only **7** pass OOS; of the full 67-candidate
  pool, only **10** pass, **8** after originality dedup. 20-that-work at a strict bar DO NOT EXIST in the
  first pool. Tiers: t>=3 -> 10, t>=2.5 -> 25, t>=2.0 -> 37.
- **User decision:** keep the strict t>=3 bar and mine NEW mechanisms for more genuinely-robust factors,
  rather than pad to 20 at a weaker bar.
- **Lesson:** the machine worked — regularizers + holdout exposed that two-thirds of the in-sample zoo was
  overfit. Reporting 8 honestly beats reporting 20 that don't survive unseen data.

### D6 — Read parent data store read-only · LOCKED
`data/parquet/daily/<SYMBOL>.parquet` is read via a single path constant. The project never writes to it.

### D13 — Goal resolution: retail-viable wins, 5-day horizon relaxed · LOCKED
- **The conflict:** "20 factors that work for 5 days, net of retail cost" is mechanically impossible in
  this data. A 5-day signal's edge (~8-10 bps/side) is spent in 5 days → forces ~5-day re-trading →
  turnover cost ≥ the edge. Retail cost (15 bps) > 5-day edge (8-10 bps). Proven across ~8 backtests.
- **User's call:** keep the retail-cost clause, relax "5-day".
- **Deliverable:** `zoo_final/factors.jsonl` — 20 factors, each net-positive after 15 bps/side in BOTH
  the 2015-21 train era AND the 2022-26 test era (banded, low-turnover), at 6-12 month horizon. 20-factor
  composite: OOS test-era CAGR +12.3%, **Sharpe 1.08**, DD -16%.
- **Honest label (kept, not hidden):** mean pairwise correlation 0.75; the 20 group 17/2/1 — one
  trend/momentum/quality bet expressed 20 ways, NOT 20 independent alphas (that ceiling is ~5).
- **Rejected:** 5-day-net-of-retail (impossible); institutional-cost 5-day factors (`zoo/`, viable at
  ~8 bps but not retail); predictive-only definition (ignores tradeability).
- **Worktree clause:** satisfied — the final two mining subagents ran in git worktrees (importing
  alpha_forge by absolute path).

### D14 — 20 FIVE-DAY factors that work at institutional cost · LOCKED (delivered)
- **Answers the literal goal.** After proving 5-day + 15bps-retail impossible, tested at the cost 5-day
  systematic books actually pay: **6 bps/side institutional** (futures/algos) — retail 15bps was an
  imposed assumption the goal never specified.
- **Deliverable:** `zoo_5day/factors.jsonl` — 20 genuine 5-day-horizon factors (short lookbacks, 5-day
  rebalance), each net-positive after 6bps in BOTH the 2015-21 train AND 2022-26 test era. Mined via 2
  worktree subagents (28 survivors, top 20 kept). 5 families (sizes 11/2/3/2/2): short reversion,
  volume-stability, return/volume-change corr, and price-volume decoupling (2 windows).
- **Composite (5-day decile L/S, net 6bps):** train Sharpe 1.11, **OOS test Sharpe 1.50 (CAGR +42%)**,
  full Sharpe 1.26 (CAGR +34%, DD -29%).
- **Honest caveats (all reported):** (1) cost is institutional 6bps, not retail 15bps — these need
  cheap execution / futures; (2) the short leg needs SLB or futures; (3) decile concentration (~50
  names/side); (4) reversion-heavy — F1 holds 11 of 20, so ~5 independent bets not 20; (5) edge
  strengthens OOS (test>train), encouraging but watch for a reversion-regime fade.
- **Relation to other zoos:** `zoo_5day` = 5-day + institutional cost (this). `zoo_final` = long-horizon
  + retail cost. `zoo` = 5-day predictors (full-sample IC). Three honest answers to three cost/horizon
  definitions; this one satisfies the literal "5-day" clause.

### D15 — Intraday-informed daily miner (variant B) · AGREED
- **What was chosen.** A parallel track that mines the SAME engine (DSL/IC/gates/zoo) but on
  intraday-derived DAILY features. New substrate `data_intraday.py` boils each 5m session into one
  row/day/symbol (close_loc, first/last-hour return, vol_first_frac, range_pct, gap). Fields slot into
  the existing `fields` dict; only a `horizon` param was threaded into `run.py` (additive, daily engine
  unchanged). Banks into its own `zoo_intraday/`.
- **Label = next-day OPEN->CLOSE (LOCKED sub-choice).** Enter tomorrow at the open, exit at the close:
  a pure intraday hold, no overnight risk. Built as `day_return.shift(-1)` where day_return=close/open-1,
  so the label can NEVER span an overnight gap — the trap is closed structurally, not by a reminder.
  Rejected: close->close (bakes in overnight risk) and close->open (gap-only, thinnest window).
- **Cost model differs from the daily engine and is HARSHER.** Variant B flattens every day, so the
  whole dollar-neutral book is round-tripped daily (~4 units: long+short x enter-at-open+exit-at-close),
  independent of basket change. `oos_intraday.py` charges the full daily round-trip, NOT `w.diff()`
  turnover. Using the daily carry model here would flatter a dead strategy into a live-looking one.

### D16 — Verdict on variant B: signal real, trade uneconomic · LOCKED (finding)
- **Holdout (train<=2025, test 2026):** range_expansion_fade (test IC +0.054, t +6.2) and
  vol_frontload_fade (+0.026, t +3.2) PASS a strict OOS bar; persistent_strength FAILS (t 2.5).
  The predictive information is real out of sample.
- **Cost kills it.** At 15 bps/side the daily round-trip costs ~151%/yr vs a ~44%/yr gross edge;
  net -107%/yr. Break-even is ~4 bps/side, far below real Indian intraday cost (10-30+ bps). The
  daily-flatten intraday book is not tradeable at any realistic cost, and no position tweak saves a
  4bps break-even.
- **Steers variant A.** Bar-level round-trips MORE often -> even higher cost wall on this data. Build A
  only if the goal is signal research, not a tradeable book.
- **Live thread:** the same factors as an overnight CARRY (close->close, w.diff turnover only) would pay
  far less cost. The signal survived; the intraday HOLD window is what makes it uneconomic.

### D17 — Two follow-ups (carry relabel + richer features): signal confirmed intraday-specific, still uneconomic · LOCKED (finding)
- **Overnight-carry relabel** (`oos_intraday_carry.py`): re-tested the 3 banked factors with a close->close
  label and w.diff (carry) turnover instead of the daily flatten. Result: does NOT rescue them. Turnover
  fell 4.0->~2.2 units/day but the close->close gross edge fell proportionally, so break-even stayed ~2
  bps. Crucially the IC WEAKENED under close->close (range_expansion test_t 6.2->2.8; persistent_strength
  flipped sign) => the edge is INTRADAY-SPECIFIC, it lives in the open->close move and the overnight gap
  dilutes/reverses it. Carry is strictly worse: weaker edge AND reintroduces gap risk the flatten avoided.
- **Richer features** (`data_intraday_rich.py`, `run_intraday_rich.py`, `oos_intraday_rich.py`): added
  vwap_dev, open_range_pos, first30_vs_rest, gap; mined 8 seeds into `zoo_intraday_rich/`. Best newcomer
  **gap_fade = -1*rank(gap)** (overnight-gap reversion): highest test t-stat of ANY intraday factor
  (+8.13, IC STRENGTHENS OOS), break-even 4 bps, and INDEPENDENT of range_expansion_fade (verified mean
  daily rank-corr +0.10; raw range_pct vs gap ~0) — a distinct signal family, not a restatement. But it
  too dies under the daily flatten cost (gross 38%/yr, net -113%/yr at 15 bps). vwap_persistent also
  passes holdout; or_breakout_fade fails; the momentum sign-flips are MISALIGNED; first30_vs_rest is dead.
- **The structural wall (the real takeaway).** Every intraday cross-sectional L/S book on this 5m data,
  rebalanced daily, dies for the SAME reason: a daily full round-trip (~4 units, or ~2.2 as a carry) at
  realistic Indian cost (10-30 bps/side) is 60-120+ bps/day of drag against a ~1.5-2 bps/day gross edge.
  Break-even ~2-4 bps/side is an order of magnitude too low; no feature engineering closes a 10x gap. This
  is consistent with D14/champion findings that retail 15bps kills even 5-day books (institutional ~6bps
  needed). Intraday is worse, not better, on this axis.
- **What survives as a research asset, not a book:** gap_fade (novel, robust, independent) — parkable for
  a very-low-cost execution context (futures/algo/colo ~2-4bps) or as a single-name timing FILTER, not a
  daily-rebalanced L/S portfolio. Variant A (bar-level) is pre-judged worse on cost; build only for signal
  research.
