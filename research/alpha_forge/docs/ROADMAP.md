# ROADMAP.md — alpha_forge

Categorised. What's built, what's next, what's deferred and why. Update statuses
as blocks land. This is not a bug list (see BUGS.md) or a decision log (DECISIONS.md) —
it's the plan and the parked work.

---

## 1. Build progress (the 6 blocks)

| # | block | file | status |
|---|-------|------|--------|
| 1 | data substrate: panels, point-in-time universe, fwd returns | `data.py` | ✅ built + verified |
| 2 | factor language (DSL operators, string → panel) | `dsl.py` | ✅ built + verified |
| 3 | scoreboard: cross-sectional IC + long-short quantile spread | `evaluate.py` | ✅ built + verified |
| 4 | the two regularizers: complexity + originality-vs-zoo | `regularize.py` | ✅ built + verified |
| 5 | FactorZoo: bank accepted alphas + their daily values | `zoo.py` | ✅ built + verified |
| 6 | the loop: propose → evaluate → regularize → bank/reject | `run.py` + `miner.py` | ✅ built + verified |

**All 6 blocks built + 2 extensions. The machine runs end-to-end.**
- **D10 hypothesis + alignment gate** (`miner.py`/`run.py`): every factor states its economic mechanism;
  the IC-sign must agree or it's rejected as misaligned. Under this gate the seed batch banks 4 (not 6):
  accel & range_pos are MISALIGNED — they predict but *backwards* to their momentum story.
- **D11 run-ledger** (`ledger.py`): SQLite `zoo/runs.db` logs every candidate + hypothesis + result +
  the per-run feedback narrative. `python ledger.py zoo/runs.db` prints the summary.

**Two zoos:**
- `zoo/` — 20 IN-SAMPLE factors (f0000–f0019). Full-history rank-IC, no holdout. Kept as the research log.
- `zoo_oos/` — **10 OUT-OF-SAMPLE-VALIDATED factors** — the real deliverable. Each survived a strict
  2023–2026 holdout (test_t≥3, test_ic>0, sign-consistent) it was never selected on.

**GOAL RESOLVED (user accepted 10 as the honest answer):** "20 that work" does not exist at a strict OOS
bar. 145 candidates tried across 8 mechanism families + an OHLC feature extension → only 10 decorrelated
factors survive out of sample. Diminishing returns were stark: close/volume→8, illiq/higher-moment/VWAP→+0,
OHLC→+2. Reporting 10 real factors beats padding to 20 with in-sample mirages.

Open follow-up (parked, user-offered): transaction-cost/turnover haircut on the 10 — several have
turnover 0.6–0.9, so net-of-cost edge is the next real test.

### 2026-08-30 SESSION — cost wall SOLVED via non-price features (see SESSION_SUMMARY.md)
The OHLCV-only miner was starved, not exhausted. Wiring non-price, low-turnover info broke the
retail-cost wall. New zoos:
- `zoo_features/` — delivery% factors (deliv_high t+8.4 robust; deliv_persist tradeable at inst. cost)
- `zoo_fundamentals/` — GARP/earnings factors. **value_growth = `rank(earn_yield+pat_yoy)` clears
  RETAIL 15bps: long-only OOS Sharpe 1.36.** First family to do so.
- **DELIVERABLE: combined long-only book** (momentum + GARP + regime overlay), OOS Sharpe 1.37,
  DD -15% → `backtest_reports/combined_book.pdf`.
New engine: walk-forward gate (`walkforward.py`), tradeable-score (#4), λ2=0.001 calibrated on,
as-of-safe fundamentals + debt loaders. Rejected this session: leverage (dead), acceleration
(decaying), volume-character/sector-relative (fade OOS). New standing caveat: data-store
survivorship (0 delistings in 11yr — affects all absolute-return claims).

## 2. Known weaknesses / optimizations deferred

Real limitations we've chosen NOT to fix yet, each with the trigger that would make us fix it.

- ~~**`ts_rank` uses `.apply`**~~ RESOLVED during the 20-factor scale-out. The `.apply` version was not
  ~10× but ~**80× slower** (~409s for a single eval on the 2884×1858 panel) — it timed out family C and
  would have hung the central merge. Fixed by switching to pandas' native `Rolling.rank` (4.9s, same
  semantics). Lesson: the "no evidence it matters yet" deferral was wrong once real parallel scoring hit
  it; measure before assuming a slow path is cold.
- **Originality computed twice per candidate.** `run.py` calls `zoo.originality()` AND
  `regularized_fitness()` (which recomputes `originality_penalty` internally) → the rank-corr sweep
  runs twice, ~doubling batch wall-clock (10 seeds took ~130s). **Fix trigger:** first time batch
  latency annoys us — compute originality once and pass the value into the fitness call.
- **Thin universe on very early dates (2015).** `data.py`, `min_periods=lookback//2`. Universe can
  dip below 500 before 60d of turnover history accrues. **Fix trigger:** never, unless we start
  scoring on the 2015 slice — irrelevant to the modern era.

## 3. Parked features (deferred by decision, not yet weaknesses)

- **Autonomous miner** — Anthropic-API loop or file-bridge. Parked behind D2 until the engine is
  trusted and the scoreboard asserts real values. Today the Miner is Claude-in-session.
- **10-day forward horizon** — v0 is 5-day (D3). Add as a knob once IC is trusted at 5d.
- **Extra raw fields (open/high/low, VWAP)** — `build_fields` already accepts them; not wired into
  the default field set until an alpha needs them.

## 4. Open questions (decide with data, not by argument)

- **λ1 / λ2 weights** and subtractive-vs-multiplicative penalty form — settle once `evaluate.py` +
  `regularize.py` produce real IC numbers.
- **Originality metric cost** — daily cross-sectional correlation of a new factor vs every zoo
  factor is O(zoo size); may need to cache each banked factor's daily values.
- ~~**IC definition** — Spearman vs Pearson.~~ RESOLVED in Block 3 → rank-IC (Spearman), non-overlapping
  t-stat (see DECISIONS D7). Decay-slope gating still open, revisit when the loop runs.

---

## 5. Intraday track (variant B) — built, tested, verdict in

- **Built:** `data_intraday.py` (5m -> daily feature panels), `run_intraday.py` (seeds + engine),
  `oos_intraday.py` (holdout + honest daily-round-trip cost). Engine reused; `run.py` gained one
  additive `horizon` param. See DECISIONS D15/D16.
- **Result:** 2/3 seed factors survive a strict 2026 holdout (signal is real OOS) but ALL die after
  cost — break-even ~4 bps/side vs 10-30 bps real. The daily-flatten intraday book is uneconomic.
- **Parked / open:**
  - **Variant A (bar-level)** — deferred. Same data round-trips even more -> worse cost. Build only for
    signal research, not a tradeable book.
  - **Overnight-carry relabel** — the live thread. Same intraday features, label close->close, cost via
    `w.diff()` not daily round-trip. Tests whether the real signal is monetisable at a lower frequency.
  - **Richer intraday features** — VWAP deviation, opening-range breakout, first-30min vs rest, gap-fill.

### Intraday follow-ups (D17) — carry + rich features, both tested
- Carry relabel: does not rescue; edge is intraday-specific (weakens close->close). Files: oos_intraday_carry.py.
- Rich features: gap_fade (overnight-gap reversion) is the best intraday signal found — test t +8.13, IC
  strengthens OOS, independent of range_expansion_fade (corr +0.10) — but still dies on daily flatten cost.
  Files: data_intraday_rich.py, run_intraday_rich.py, oos_intraday_rich.py; zoo_intraday_rich/.
- CONCLUSION: intraday cross-sectional L/S on 5m data is not tradeable at retail cost (structural: ~4-unit
  daily round-trip vs ~1.5bps/day gross => break-even ~2-4bps). gap_fade parked as a research asset for a
  low-cost/futures context or a single-name filter. Variant A deferred (worse cost).
