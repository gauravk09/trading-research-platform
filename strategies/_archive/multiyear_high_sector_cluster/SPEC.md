# SPEC — multiyear_high_sector_cluster        status: S1 | 2026-08-06 | reddit_x_strategy_ideas.md #5 (doc's own #6)

Source: `scratchpad/reddit_x_strategy_ideas.md` candidate #5 ("52-week-high /
all-time-high breakout after base", ValuePickr, hitesh2710 / Dr. Hitesh
Patel). Claimed edge: a multi-year high crossing after a genuine multi-month
base reflects institutional accumulation already in progress, not a chase;
requiring several sector peers to also be making new highs together confirms
an industry-wide catalyst or rotation rather than an idiosyncratic move,
raising the hit rate of pure price-pattern recognition. Who is on the other
side: pattern-blind traders who treat every 52-week high as equally chaseable
regardless of the base quality behind it or whether the move is isolated.
Credibility: author is one of ValuePickr's most-followed practitioners; a
real-time 2020 pharma-cluster call record (Sun, Cipla, Biocon, Laurus,
Alembic) aged well, though no consolidated P&L exists.

## Honesty preamble — heavy overlap, what is genuinely new

The base "consolidation → new-high breakout" shape is **already covered** by
`ryan_52wk_high` (FACTORY seed table: S3, close-entry variant measured, PF
0.70/0.97 at open -> 1.59/1.46 at close+gate, MIXED->promising, needs S5/S6).
S2 here MUST report what fraction of this spec's V1 events also qualify as
plain `ryan_52wk_high` events, so the ledger's multiplicity accounting stays
honest and this isn't silently double-counted as a second independent find.
Three elements are genuinely new and are what this spec actually tests:
1. A **stricter, multi-year (not 52-week) high bar**.
2. The **first-pullback entry** (V3) — a distinct, never-tested-in-house
   entry mechanic requiring its own price-path detection logic.
3. The **sector-clustering condition** — never tested on this cohort.

Also flagged: the source gives **no exit rule** ("discretionary trend-
reversal watch — the weakest part of the spec," in the author's own words).
We substitute the house-standard trend-tail exit (FACTORY.md lever 2: trail
on 20DMA, or a time cap) rather than inventing a discretionary rule to
replicate — this is OUR substitution, not the source's.

## Universe / liquidity floor

All NSE EQ, ₹5cr 20-day avg turnover floor (house default).

## Event definition (point-in-time, exact)

- **Multi-year high**: `close[t] >= rolling_max(close, 504 bars)[t]` (new
  ~2-year closing high) AND `close[t] >= 0.99 x max(close[0:t])` (within 1%
  of the highest close in our ENTIRE stored history for that symbol back to
  2015). Flag: for symbols listed before 2015, "all-time" here really means
  "since-2015" — a real pre-2015 all-time high we cannot see may sit above
  this level; this is an honest limitation of the platform's 2015+ coverage,
  not a proxy choice.
- **Base**: >= 120 trading bars (~6 months) since the prior 504-bar-high
  cross, and `tightening_range_filter` (existing, `src/filters/
  consolidation.py`) true over the most recent 20 bars vs. the prior 60-100
  bars (confirms genuine range contraction, not a straight-line run into the
  high).
- **Sector clustering** (condition, not a hard filter — see machine-spec
  companion below): `sector_rs` (existing feature, percentile rank of the
  stock's sector composite RS) in the top quartile at signal date. This
  stands in for "count of sector peers also at 52-week highs" — no literal
  cross-sectional count feature exists in the store; sector_rs is
  directionally related (a strong sector likely has several members near
  highs) but is not the same measurement. Flagged as an approximation.

## Entry variants (max 3)

- V1 **signal-day close + range_pos >= 0.75** (house lever 1).
- V2 **D+1 open** (control, faithful/naive replication).
- V3 **first-pullback-hold** (new mechanic, pre-registered exactly so it
  cannot be tuned after seeing results): after a V1-qualifying breakout,
  watch up to 10 bars for price to retrace into `[prior multi-year-high,
  prior multi-year-high x 1.03]` without closing back below the base floor;
  enter on the first day price closes back above the original breakout
  bar's high (the "resumption" bar). If no such pullback-and-resume occurs
  within 10 bars, the V3 signal simply does not fire for that event (V1 may
  still have fired on the same underlying breakout).

## Stop / Exits

- Stop: below the base floor for V1/V2; below the pullback-zone low for V3.
- Exit: house-standard trend-tail shape (FACTORY.md lever 2) — trail on
  20DMA close-below, OR 50-bar time cap, whichever comes first. Substituted
  for the source's undefined discretionary exit (see preamble).

## Costs / Eras

0.4% round-trip default. Eras: A 2015-19, COVID 2020-22 (reported, never
judged), B 2023-26, 2024-26 sub-era shown.

## Success bars (written now)

- S2: any variant, close-entry PF >= 1.2 in BOTH eras, n >= 150 → proceed.
  **V3 exception**: the first-pullback mechanic will likely have much lower
  n than V1/V2 (fewer qualifying pullback-then-resume patterns); if V3's
  n < 150, report **INSUFFICIENT**, not FAIL — do not force a verdict on an
  underpowered variant.
- S4: standard bars (era split, parameter neighborhood on the 504-bar /
  120-bar / 1% thresholds, random-recipe null since sector_rs-top-quartile
  was *selected* from the source's claim).
- S5: >= 3%/yr on ₹10L (STYLE.md bar); must beat the already-incubating
  ryan_52wk_high shape on the overlap-adjusted subset (see preamble), not
  merely replicate it at a smaller n.

## Style expectations

Est. hold: weeks (trend-tail shape, house convention says 20-60 days with a
trail and ~70% stop-outs for this family). Checked against STYLE.md at S6:
fits the "will run 20-60-day trail-exit tail strategies at reduced size"
soft allowance; manual execution is fine for a daily-EOD signal.

## Companion machine-experiment spec

The sector-clustering sub-claim (point 3 above) is ALSO directly testable
today, without a bespoke backtest, on the EXISTING event store: see
`research/machine/specs/reddit_x/d_freshhigh_sectorrs.json` — cohort
`trigger=pullback` (uptrend, recent-high, touched 20SMA — the closest
existing entry mechanic to "first pullback near a high") filtered to
`pct_52wh >= -5` (within 5% of the real 52-week high), bucketed by
`sector_rs` quartile. This does not replace V3's bespoke pullback-and-resume
mechanic above (a different, stricter definition), but gives an early,
lower-effort read on whether sector_rs carries any signal on this cohort
before investing in the full factory backtest.
