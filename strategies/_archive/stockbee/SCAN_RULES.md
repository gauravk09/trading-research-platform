# Stockbee Scans — Rules & Indian Adaptation

Source of truth for the Stockbee (Pradeep Bonde) scans in this repo. Scans run
on `data/processed/universe_summary.parquet` (one row per NSE EQ stock), so the
dashboard stays instant. Columns used here are produced by `src/preprocessing/precompute.py`.

## Universe & global filters (applied to every scan)
- **Liquidity:** `avg_turnover_cr` ≥ slider (default ₹1 Cr) — replaces Bonde's
  US dollar-volume / share-count floors. Indian liquidity is best gauged by
  rupee turnover, not share count.
- **Price floor:** `close` ≥ slider (default ₹0). Bonde's "$100+ high-priced"
  rule maps to a ₹100–200 floor in India — used mainly in Momentum Burst (Phase 2).
- **ASM/GSM excluded** by default (`load_excluded_symbols`) — avoids manipulated
  / trade-to-trade names. Toggle off to include them.
- **F&O flag + toggle** — every result shows whether the stock is in F&O.

## Phase 1 scans (implemented)

### 1. 4% Breakout  (`scans.four_pct`)
Bonde's primary day-one momentum scan.
- `chg_pct` ≥ **4%** (slider)
- today's `volume` > `prev_volume` (volume confirmation)
- `range_pos` ≥ **0.70** → close in the top 30% of the day's range (toggle)
- optional freshness: `up_streak` ≤ 2 → not already up 3 days straight (toggle)
- Ranked by % change, then volume ratio.

### EP family  (`ep_family.py` — TraderLion 2026, India-adapted)

**EP9M** (`ep9m_today`) — Bonde's institutional-footprint scan. US original:
stock traded > 9M shares = top ~2% of ~13,000 instruments that day. India
version (per the ep9m_redefined study):
- today's share volume ≥ **15M** — a fixed absolute threshold equal to the
  top ~2% of all NSE stock-days (India's "9M"); AND
- today's volume ≥ **3× the highest volume of the prior 20 sessions** (today
  excluded from its own benchmark). 26 NSE names (ETERNAL, SUZLON, IDEA,
  TATASTEEL, HDFCBANK …) have a *median* daily volume above 15M, so the
  absolute bar alone fired on them ~20% of all sessions; AND
- close ≥ ₹30 and event-day turnover ≥ ₹10 cr (proxy for "no penny stocks" —
  true market-cap filter needs a shares-outstanding feed, tracked in ROADMAP).
- No novelty gate: the backtest showed repeat volume-outlier names outperform
  first-timers, so the gate was removed (it measurably hurt returns). The 3×
  prior-peak gate above is a *per-event* test, not a per-stock exclusion, but
  it carries the same cost — see the caveat below.
- Direction-agnostic by design (footprints of accumulation AND distribution);
  catalyst tag joined from that day's cached NSE announcements. ~3 events/day.

> **Caveat (2026-07-28, user-specified):** the 3× prior-20d-peak gate is a
> deliberate signal-to-noise choice, not an edge improvement. Re-scored against
> the 5,209 ep9m_redefined events it keeps 22% of them and cuts avg R from
> +0.46 to +0.12 (PF 1.55 → 1.15, trail20 exit). It makes the scan human-usable;
> it does not make the events better. `EP9M_VOL_MULT` in `ep_family.py` is the
> single knob if this is revisited.

**DEP** (`dep_watchlist`) — delayed-reaction EP:
- institutional quality: F&O member OR avg turnover ≥ ₹25 cr;
- an EP9M event 2–25 sessions ago whose event-day move was ≥ 4%;
- move still defended (close > pre-event close) and within 15% of the
  post-event high;
- tight now: `range_pct_5d` ≤ 8, tightest first. Bonde execution rules:
  watch like a hawk, 3 tight-stop tries, then wait for confirmed breakout.

**EP Checklist** (`ep_checklist`) — the evening half of classic EP (catalysts
on NSE surface EOD via corporate filings, not pre-market wires): tonight's
filings in catalyst categories (results, guidance, order wins, acquisitions,
regulatory, buyback, ratings, fundraise) joined with neglect (no TI65 trend +
flat half-year) — neglected names sort first; review before tomorrow's open.
Classic gap-EP detection (gap ≥ 8%, volume ≥ 3×) stays in `episodic_pivot.py`.

> Data note (fixed 2026-07-12): the NSE announcements endpoint returns only
> its latest ~20 filings without a date range — every cached day was a 20-row
> stub, silently starving catalyst tagging. `nse_announcements.py` now passes
> from_date/to_date and gets the full ~500-900 filings/day.

### 2. Breakout Setup  (`breakout_setup.breakout_from_consolidation`)
Bonde's core momentum-burst setup, done properly: not just today's 4% move, but
the *quality of the base that preceded it* — "buy range expansion at the beginning
of a swing," from a 5-10+ day orderly, quiet consolidation (his "2Lynch" checklist).
- `consol_days` between **5 and 20** (slider) — days since the last outsized move
  *at the stock's own scale*: a day whose close-to-close move ≥ 1× its prior-50d
  ADR (clipped 2.5–8%) resets the base, so this is literally how old the base is.
  (Volatility-normalized 2026-07-11 — the fixed ±4% reset had corr −0.6 with ADR:
  calm large caps read as consolidating forever, 6%-ADR stocks never held a base.
  Window is 50d not 20d: a base *is* the trailing 20 days, so ADR20 sagged ~13%
  during bases and let routine intra-base pops cut them short.)
- `consol_range_pct` ≤ **15%** (slider) — the base's high-low range as % of price;
  tighter = higher quality ("buyer/seller in equilibrium").
- `consol_vol_ratio` ≤ **1.10×** (slider) — base's average volume vs. 20-day
  average; volume drying up in the base is Bonde's "quiet" signature.
- today: `chg_pct` ≥ `burst_thr_pct` (the same per-stock threshold that would have
  reset the base), volume > prior day, `range_pos` ≥ 0.70 (close top 30% of range,
  toggle), `up_streak` ≤ 2 (not already up 3 days, toggle).
- `adr_pct` ≥ **3%** (slider) — the volatility preference the fixed 4% used to
  smuggle in, now explicit: only stocks where a 3-5 day swing pays.
- `prior_day_quiet` (toggle, default on) — Bonde: "day prior to range expansion
  day will be narrow range day or negative day". Yesterday's range < 0.75× the
  20 days before it, or yesterday closed red.
- `trend_quality` (TQ column, display/sort only — no gate): Clenow slope×R²
  ranked 0-100 across the universe at BOTH 60d and 6mo, final score = the
  weaker rank — "linear over the longer term AND still linear now". One
  window alone is foolable: 60d scores a 2-month bounce inside a downtrend
  as linear; 6mo keeps scoring a trend that broke 2 months ago. High =
  persistent linear riser (Bonde's "linear and orderly move"); low =
  drunken-walk churn OR a young trend / flat base the windows can't see yet
  — which is exactly why it isn't a gate.
- The plain 4% Breakout scan (above) and the Market Monitor's up4/dn4 counts keep
  the fixed 4% — cross-market breadth vocabulary must stay absolute.
- **Entry** = today's close, **Stop** = today's low — Bonde's own stated rule
  ("I put my stop at low of the entry day").
- Each row gets a plain-English `reason` string built from the actual passing
  values (base length, tightness, volume dry-up %, breakout size, volume
  multiple, close position) so it's obvious *why* a stock is in the list.
- **Open Trade** button attaches the pick to `trade_tracker` (below), which
  applies his stated 3-day/5-day rule: hold, and if profitable by day 3 move
  the stop to breakeven; exit by day 5 regardless. See `trade_tracker.py`.

> Sources: https://stockbee.blogspot.com/2014/01/buy-range-expansion-at-beginning-of.html,
> https://stockbee.blogspot.com/2014/01/how-to-identify-a-quality-setup.html,
> https://stockbee.blogspot.com/2014/07/my-swing-trading-process-flow.html,
> https://stockbee.blogspot.com/2014/08/how-i-control-my-risk.html

### 3. TI65 — Trend Intensity  (`scans.ti65`)
- `ti65` = avg(close, 7) / avg(close, 65) ≥ **1.05** (slider)
- i.e. the 7-day average is ≥5% above the 65-day average → established up-trend.
- Ranked by TI value.

### 4. Episodic Pivot  (`episodic_pivot.episodic_pivot`)
A neglected stock gapping up on a catalyst.
- `gap_pct` ≥ **8%** (slider, 3–20%) — open vs prior close
- `volume_ratio` ≥ **3×** 20-day average (slider)
- exclude already-parabolic names (`r1mo_pct` > 100%)
- catalyst tag joined from cached NSE announcements (`attach_catalysts`); the
  "Has catalyst" toggle keeps only stocks with a qualifying filing.
- Shows distance from the 52-week low (base context).

> Note: Indian EP gaps can hit the **upper circuit** (5/10/20%); a name pinned at
> circuit may not be enterable intraday. Bulk/block-deal confirmation is planned
> but the cached feed is currently empty, so it is not used yet.

### 5. Anticipation  (`scans.anticipation`)
Bonde's pre-breakout setup: don't chase the momentum burst on the day it fires —
**anticipate** it the evening before. After a stock makes a move it often pauses
in a tight, low-volume range near its highs; you enter the coil and ride the next
burst with a tighter stop and less slippage.
- prior up-leg: `r3mo_pct` ≥ **20%** (slider 0–100) — the 3-month base trend we expect to continue
- tight now: `range_pct_5d` ≤ **12%** (slider 4–30) — last 5 bars' high-low as % of price
- volume drying up: `vol_contraction` ≤ **0.85** (slider 0.3–1.5) — 5-day avg ÷ 20-day avg
- optional `NR7` toggle: today is the narrowest range of the last 7 days
- Ranked tightest first (`range_pct_5d` asc), then driest (`vol_contraction` asc).

> Reads `inside_days` (consecutive inside-day count) as an extra contraction cue in
> the table. Source: https://stockbee.blogspot.com/2008/06/anticipation.html

### 6. Short side — 4% Breakdown & Swing Exhaustion  (`scans.four_pct_down`, `scans.swing_exhaustion`)
Bonde's bearish setups — the long playbook in reverse. **Only valid in a confirmed
10-day+ downtrend or an active correction**; in a bull market they mostly squeeze.
Full method in [`docs/stockbee_pradeep_bonde_trading_setup.md`](../../docs/stockbee_pradeep_bonde_trading_setup.md) (Setup 3).

**4% Breakdown** — mirror of the 4% breakout:
- `chg_pct` ≤ **−4%** (slider 4–20) — close down 4%+ vs prior close
- today's `volume` > `prev_volume` — selling on expanding volume
- Ranked by biggest drop (`chg_pct` ascending).

**Reversal Bullish** (`scans.reversal_bullish`) — TraderLion 2026:
- institutional quality only: F&O member OR avg turnover ≥ ₹25 cr ("if you try
  it on a random stock, you're going to get killed")
- `down_streak` ≥ **2** — closes fell 2+ days in a row ending *yesterday*
- today reversed: `chg_pct` > 0 and `range_pos` ≥ **0.60**
- Bonde enters at 3:58 pm; EOD this is tonight's list for tomorrow.

**Bottom Bounce** (`scans.bottom_bounce`) — TraderLion 2026, context-gated:
- ONLY when the T2108 analog (`pct40ma`) is **< 20** — a market washout. The
  daily state suppresses candidates when the context is off; the dashboard
  shows them for study with a warning banner.
- candidate: ≥ **25%** below its 52-week high, up ≥ **4%** today on volume >
  prior day — the beaten-down name's first real turn.

**Weak Structure** (`scans.weak_structure_short`) — TraderLion 2026 short:
- precomputed `weak_structure` flag: 3 consecutive down closes, then a 2-3 day
  pause (each day within ±1.5%), then today selling resumes (close down)
- `ti65` < 1.0 (confirmed downtrend) unless toggled off
- weak markets only — in a bull tape these squeeze.

**Swing Exhaustion** — short an exhausted rally leader on its first down day:
- precomputed `swing_exhaustion`: 3 green, ascending-close days (`C>O` each day,
  `C1>C2>C3`), then today `C < C1`
- Ranked by `r1mo_pct` descending (most extended runner first).

> Sources: Bonde's "How to find shorts" posts — https://stockbee.blogspot.com/

## Precomputed columns these scans rely on
`prev_volume`, `gap_pct`, `volume_ratio`, `range_pos`, `ti65`, `up_streak`,
`range_pct_5d`, `nr7`, `inside_days`, `vol_contraction`, `swing_exhaustion`,
`pct_from_52w_high`, `pct_from_52w_low`, `consol_days`, `consol_range_pct`,
`consol_vol_ratio`, `burst_thr_pct`, `prior_day_quiet`, `trend_quality`
(plus the existing returns / ADR / turnover / RS / F&O columns).

## Trade tracker (`trade_tracker.py`)
Small JSON store (`data/processed/stockbee_trades.json`)
that remembers Breakout Setup picks you've opened and
applies Bonde's stated hold/stop rule from "My swing trading process flow":
day-count advances once per new trading day; if the trade is profitable by
day 3 the stop moves to breakeven; by day 5 it's flagged `exit_due` regardless
of P&L. A stop-loss hit at any point marks it `stopped`.

## Phase 2 (planned, not yet built)
- **Double Trouble** — strong 6-month ROC AND within ~5% of the 52-week high.
- **Momentum / YTD Leaders** — rank by 3M/6M return × RS.
- **Market Monitor (breadth)** — #up4%/#down4% (5/10-day ratios), 25%-in-a-quarter
  and 25%-in-a-month counts, T2108 (% above 40-DMA), 13/34 EMA breadth.

## Sources
- 4% breakout — https://stockbee.blogspot.com/2015/11/how-to-use-4-breakout-scan-to-make-money.html
- Trend Intensity / TI65 — https://stockbee.blogspot.com/2017/05/how-to-use-ti65-to-find-low-risk-entry.html
- Market Monitor — https://stockbee.blogspot.com/p/mm.html
- Bonde's screens overview — https://deepvue.com/screener/pradeep-bonde-screens/
