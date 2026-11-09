# Scans Reference

What each scan in the web dashboard computes, the **exact** filters/conditions behind it,
and a link to the blog the scan is based on. Thresholds here are read straight from the
code — file:line references are given so you can trace anything.

This file is served verbatim by `GET /api/docs` ([`webapp/server/main.py:329`](../webapp/server/main.py))
and rendered on the **How Scans Work** page of the webapp.

---

## Two engines (read this first)

The webapp mixes two completely different scan engines. Knowing which page uses which
explains why some scans react instantly to filter changes and others only update once a day.

| | **Live scan engine** | **Nightly state engine** |
|---|---|---|
| Used by | Screener, Scans pages | Setups, Daily Brief pages |
| Reads | `data/processed/universe_summary.parquet` (one row per stock), served by `/api/universe` and `/api/scans/{name}` | the nightly state JSON written by [`src/daily_state.py`](../src/daily_state.py), served as-is by `/api/state` |
| Conditions are | simple threshold comparisons on **precomputed columns** | the same predicates, plus entry/stop/flags, frozen at EOD |
| Recomputed | on every request — the Scans page re-runs the scan when you change a filter | once nightly, by the EOD update |
| Code | [`webapp/server/main.py:185`](../webapp/server/main.py) → [`strategies/stockbee/scans.py`](../strategies/stockbee/scans.py) | [`src/daily_state.py:255`](../src/daily_state.py) → `strategies/stockbee/` |

So the Setups page is a **viewer** for whatever last night's `daily_state.py` run wrote;
its "conditions" were evaluated at EOD, not anything the webapp computes.

Two older scanners still exist as **offline modules not surfaced in the webapp**: the
Qullamaggie CSV scanner ([`strategies/qullamaggie/scanner.py`](../strategies/qullamaggie/scanner.py)
→ `output/*.csv`) and the Zanger scan ([`strategies/zanger/scans.py`](../strategies/zanger/scans.py)).
Their conditions are documented at the end of this file.

### Blog sources

**Qullamaggie (Kristjan Kullamägi)** — in-repo source of truth: [`strategies/qullamaggie/SETUP_RULES.md`](../strategies/qullamaggie/SETUP_RULES.md)
- 3 timeless setups (overview): https://qullamaggie.com/my-3-timeless-setups-that-have-made-me-tens-of-millions/
- Episodic Pivots deep-dive: https://qullamaggie.com/how-to-master-a-setup-episodic-pivots/
- FAQ: https://qullamaggie.com/faq/
- YouTube talk (cited in repo): https://www.youtube.com/watch?v=KciAjkEFA6s

**Stockbee (Pradeep Bonde)** — in-repo source of truth: [`strategies/stockbee/SCAN_RULES.md`](../strategies/stockbee/SCAN_RULES.md)
- 4% Breakout: https://stockbee.blogspot.com/2015/11/how-to-use-4-breakout-scan-to-make-money.html
- TI65 (Trend Intensity): https://stockbee.blogspot.com/2017/05/how-to-use-ti65-to-find-low-risk-entry.html
- Episodic Pivots (Bonde, via TraderLion): https://traderlion.com/profile/pradeep-bonde/episodic-pivots-delayed-reaction/
- Screens overview (deepvue): https://deepvue.com/screener/pradeep-bonde-screens/
- Market Monitor breadth: https://stockbee.blogspot.com/p/mm.html

---

## Shared building blocks

Every live scan compares against columns built once by [`src/preprocessing/precompute.py`](../src/preprocessing/precompute.py)
(from each stock's last 252 daily bars). Definitions:

| Column | Meaning / formula | Code |
|---|---|---|
| `chg_pct` | `(close − prev_close) / prev_close × 100` (today's % change) | `precompute.py:248` |
| `gap_pct` | `(open − prev_close) / prev_close × 100` (open vs prior close) | `precompute.py:249` |
| `range_pos` | `(close − low) / (high − low)` — where close sits in the day's range; `1.0` if range is 0. `≥ 0.70` = closed in top 30% | `precompute.py:264` |
| `volume_ratio` | today's volume ÷ average of the **prior** 20 days' volume | `indicators/volume.py:28` |
| `prev_volume` | yesterday's volume | `precompute.py:247` |
| `up_streak` | number of consecutive up-closes ending today | `precompute.py:165` |
| `ti65` | `mean(close, last 7) / mean(close, last 65)` — short avg vs long avg | `precompute.py:162` |
| `range_pct_5d` | last 5 bars' high-low as % of close: `(max(high,5) − min(low,5)) / close × 100` — consolidation tightness | `precompute.py:269` |
| `nr7` | today's range is the narrowest of the last 7 days (boolean) | `precompute.py:186` |
| `inside_days` | consecutive inside days ending today (`high ≤ prev high` and `low ≥ prev low`) | `precompute.py:190` |
| `vol_contraction` | 5-day avg volume ÷ 20-day avg volume — `< 1` means volume is drying up | `precompute.py:272` |
| `swing_exhaustion` | 3 green ascending-close days, then today closes lower — Bonde's exhaustion-short flag | `precompute.py:198` |
| `adr_pct` | `mean((high − low) / low × 100)` over last 20 bars (Average Daily Range %) | `indicators/volatility.py:16` |
| `avg_turnover_cr` | `mean(close × volume / 1e7)` over prior 20 days (₹ crore/day) | `indicators/volume.py:41` |
| `r1mo_pct` / `r3mo_pct` / `r6mo_pct` | return over 21 / 63 / 126 trading days | `indicators/returns.py:29` |
| `rs_rank` | composite percentile 0–100 across the universe: `0.40 × 1mo + 0.30 × 3mo + 0.30 × 6mo` percentile ranks | `indicators/relative_strength.py:38` |
| `pct_from_52w_high` / `_low` | distance from the highest high / lowest low in the stored window (≈252 bars) | `precompute.py:274` |
| `is_fo` / `lot_size` | in the current F&O list, and its lot size | `precompute.py:340` |

> **ADR / RS / turnover** all use a 20-day (or 252-bar) window over the data actually
> stored, so "52-week" really means "last ~252 trading days present."

---

## Screener page — 📊 Universe

Plain threshold filter over the whole universe summary, applied in the browser on
`/api/universe`. Number inputs, ANDed together, plus a symbol/name search box.
No surveillance (ASM/GSM) exclusion on this page.
Code: [`webapp/frontend/src/pages/Screener.jsx`](../webapp/frontend/src/pages/Screener.jsx).

| Control | Column tested | Default |
|---|---|---|
| ADR ≥ | `adr_pct ≥ x` | 0 |
| T/O ≥ (₹ Cr) | `avg_turnover_cr ≥ x` | 1.0 |
| 3M% ≥ | `r3mo_pct ≥ x` | 0 |
| RS ≥ | `rs_rank ≥ x` | 0 |
| F&O only (toggle) | `is_fo == True` | off |

**Match =** all active thresholds pass. **Ranked by** `r3mo_pct` descending (the `rank`
column assigned in `precompute.py:352`).

---

## Scans page — 🐝 Stockbee Scans

Runs live on the universe summary: the server re-runs the scan function on every request
(`GET /api/scans/{name}` — [`webapp/server/main.py:190`](../webapp/server/main.py)), so
changing a filter updates instantly. Logic lives in
[`strategies/stockbee/scans.py`](../strategies/stockbee/scans.py); per-scan thresholds are
the function defaults (not exposed as controls in the webapp).

**Base filters applied to every scan** (`scans.py:11`):
| Control | Condition | Default |
|---|---|---|
| Min T/O ₹Cr | `avg_turnover_cr ≥ x` | 1.0 |
| Excl ASM/GSM (toggle) | drop symbols in the surveillance set | **on** |
| F&O only (toggle) | `is_fo == True` | off |

(The API also accepts a `min_price` param — `close ≥ x` — not exposed in the UI.)

### 4% Breakout
Blog: https://stockbee.blogspot.com/2015/11/how-to-use-4-breakout-scan-to-make-money.html · Code: [`scans.py:23`](../strategies/stockbee/scans.py)

- `chg_pct ≥ 4` (`min_change`, default 4)
- `volume > prev_volume` — volume confirmation (default on)
- `range_pos ≥ 0.70` — closed in top 30% (default on)
- `up_streak ≤ max_up_streak` — freshness gate, **off by default** on this page
  (the nightly `four_pct` state scan runs it with `max_up_streak=2`)

**Ranked by** `chg_pct` desc, then `volume_ratio` desc.

### 4% Breakdown
Code: [`scans.py:160`](../strategies/stockbee/scans.py) — the bearish mirror of the 4% breakout:
- `chg_pct ≤ −4` (`min_change`, default 4)
- `volume > prev_volume` — selling on expanding volume (default on)
- **Ranked by** `chg_pct` ascending (biggest drop first).

### 4% Up · 7d / 4% Down · 7d
Code: [`scans.py:44`](../strategies/stockbee/scans.py) / [`scans.py:57`](../strategies/stockbee/scans.py)

Catch range-expansion movers that fired earlier in the week — the single-day scans miss
them. Qualifies if the largest single-day close-to-close gain (`max_up_7d`) / drop
(`max_down_7d`) over the last 7 sessions is ≥ 4% (≤ −4%). **Ranked by** that biggest
move, largest first.

### TI65 — Trend Intensity
Blog: https://stockbee.blogspot.com/2017/05/how-to-use-ti65-to-find-low-risk-entry.html · Code: [`scans.py:65`](../strategies/stockbee/scans.py)

- `ti65 ≥ 1.05` (`min_ti`, default 1.05) — i.e. the 7-day average close is ≥ 5%
  above the 65-day average → established up-trend.

**Ranked by** `ti65` desc.

### Anticipation
Blog: https://stockbee.blogspot.com/2008/06/anticipation.html · Code: [`scans.py:76`](../strategies/stockbee/scans.py)

Bonde's pre-breakout setup — find the coil the evening *before* the burst instead of
chasing the 4% day. A name that already moved goes quiet in a tight, low-volume range
near its highs; you enter the coil for a tighter stop and less slippage.

- `r3mo_pct ≥ 20` (`min_prior_move`, default 20) — the 3-month base trend we expect to continue
- `range_pct_5d ≤ 12` (`max_range_5d`, default 12) — last 5 bars are tight
- `vol_contraction ≤ 0.85` (`max_vol_contraction`, default 0.85) — volume below its 20-day avg
- `nr7 == True` — optional (`require_nr7`), off by default
- `inside_days` shown as an extra contraction cue (not filtered)

**Ranked by** `range_pct_5d` asc (tightest first), then `vol_contraction` asc (driest first).

### Bullish Reversal
Code: [`scans.py:100`](../strategies/stockbee/scans.py) — Bonde reversal (TraderLion 2026):
a 2–3 day selling cascade on an **institutional-quality** stock, then a reversal bar —
institutions defend their names at these levels.

- institutional quality: `is_fo` OR `avg_turnover_cr ≥ 25` (`inst_turnover_cr`)
- closes fell ≥ 2 days in a row ending yesterday (`down_streak ≥ min_cascade`)
- today reversed: `chg_pct > 0` and `range_pos ≥ 0.60` (top 40% of the day's range)

**Ranked by** `avg_turnover_cr` desc (biggest names first).

### Bottom Bounce
Code: [`scans.py:142`](../strategies/stockbee/scans.py) — a beaten-down stock's first big
up day. **Only tradeable when the market itself is washed out and turning** (T2108 /
%>40MA < 20) — the context gate lives with the caller, this scan just finds candidates.

- `pct_from_52w_high ≤ −25` (`min_off_high`, default 25) — beaten down, not extended
- `chg_pct ≥ 4` on `volume > prev_volume` — the turn, with confirmation

**Ranked by** `chg_pct` desc.

### 🐻 Short setups — Weak Structure & Swing Exhaustion
> Bonde's short side. **Only trade these in a confirmed 10-day+ downtrend or an active
> correction** — in a bull market they mostly produce failed breakdowns and squeezes.
> Full method: [`docs/stockbee_pradeep_bonde_trading_setup.md`](stockbee_pradeep_bonde_trading_setup.md) (Setup 3).

**Weak Structure** (`scans.py:177`) — a very weak stock that sold off 3 days in a row,
paused 2–3 days, and resumed selling today (precomputed `weak_structure` flag), kept to
broken names via `ti65 < 1.0`. **Ranked by** `chg_pct` asc.

**Swing Exhaustion** (`scans.py:189`) — an exhausted rally leader's first crack:
- precomputed `swing_exhaustion` flag: three green, ascending-close days
  (`close > open` each day, `C1 > C2 > C3`), then today `close < yesterday's close`
- **Ranked by** `r1mo_pct` descending (most extended runner first).

---

## Setups page — 🎯 Tonight's candidates

A viewer for the nightly state file: [`src/daily_state.py:255`](../src/daily_state.py)
re-runs the scan functions at EOD with its own (sometimes stricter) parameters, attaches
entry/stop/flags, and the page renders the result verbatim
([`webapp/frontend/src/pages/Setups.jsx`](../webapp/frontend/src/pages/Setups.jsx)).
Where a scan also appears on the Scans page, the *conditions are the same functions* —
only the parameters and the freeze-at-EOD differ. State-only setups:

| Setup | Code | One-liner |
|---|---|---|
| Breakout Setup | [`stockbee/breakout_setup.py`](../strategies/stockbee/breakout_setup.py) | 4% burst out of a 5–20 day tight, quiet consolidation |
| EP9M | [`stockbee/ep_family.py`](../strategies/stockbee/ep_family.py) | Episodic Pivot with ≥ 15M shares traded (India's "9M" equivalent) |
| DEP Watchlist | [`stockbee/ep_family.py`](../strategies/stockbee/ep_family.py) | Delayed EP — recent EP holding within 15% of its pivot |
| EP Checklist | [`stockbee/ep_family.py`](../strategies/stockbee/ep_family.py) | Catalyst-tagged gap candidates for manual review |
| Episodic Pivot | [`stockbee/episodic_pivot.py`](../strategies/stockbee/episodic_pivot.py) | gap ≥ 8% + volume ≥ 3× + not already parabolic (`r1mo_pct ≤ 100`), catalyst tag left-joined from cached NSE announcements |

Full definitions: [`strategies/stockbee/SCAN_RULES.md`](../strategies/stockbee/SCAN_RULES.md).
The Daily Brief page is a renderer over the same state file (regime, exposure, journal).

---

## Offline — Qullamaggie Setups (not in the webapp)

The Qullamaggie scanner is a standalone CSV pipeline: running
[`strategies/qullamaggie/scanner.py`](../strategies/qullamaggie/scanner.py) writes
`output/qullamaggie_<setup>_<date>.csv` (defaults: `min_turnover_cr=1.0`, `min_rs_pct=60`).
It is not surfaced in the webapp — inspect the CSVs directly.

> ⚠️ **Code vs the written rules.** [`SETUP_RULES.md`](../strategies/qullamaggie/SETUP_RULES.md)
> lists "surfing the MA / higher lows / tightening range" as prerequisites. In the *scanner code*
> these are **conviction points (⭐), not hard filters** — a stock can appear with few of them.
> Only the gates listed under "Required" below actually exclude a stock.

### Setup 1 — Breakout from Consolidation
Blog: https://qullamaggie.com/my-3-timeless-setups-that-have-made-me-tens-of-millions/ · Code: [`strategies/qullamaggie/breakout.py`](../strategies/qullamaggie/breakout.py)

**Universe gates (all required):**
- Not on ASM/GSM list; ≥ 130 bars of history — `breakout.py:142`
- `avg_turnover_cr ≥ 1.0` ₹Cr/day — `breakout.py:148`
- Composite `rs_rank ≥ 60` (top ~40%) — `breakout.py:156`

**Required filters (`REQUIRED_FILTERS`, all must pass — `breakout.py:91`):**
| Filter | Exact condition |
|---|---|
| `f_adr_gt4` | ADR% (20d) ≥ 4 |
| `f_above_ma50` | close > SMA(50) |
| `f_breakout_return` | 21-day return in **30–200%** OR 63-day return in **30–300%** (`momentum.py:57`) |
| `f_near_high` | close within **10%** of the highest high of the last 20 bars (`consolidation.py:75`) |

**Conviction score ⭐ (each +1, not required — `breakout.py:99`):**
- `f_surfing_ma10` / `f_surfing_ma20` — for the last 10 bars, close stayed `≥ MA` and within **3% above** the 10- / 20-day MA (`moving_averages.py:55`)
- `f_rising_ma20` — 20-day MA today > 20-day MA 5 bars ago
- `f_tightening` — ADR% of last 20 bars < ADR% of the 60 bars before that (`consolidation.py:19`)
- `f_higher_lows` — ≥ 3 of the last 20 lows are above the trailing 5-bar minimum (`consolidation.py:52`)
- `f_consol_duration` — highest close sits 10–40 bars back (2 wks–2 mo) (`consolidation.py:95`)

**Ranked by** conviction ⭐ desc, then `r3mo_pct` desc.

### Setup 2 — Episodic Pivot (EP)
Blog: https://qullamaggie.com/how-to-master-a-setup-episodic-pivots/ · Code: [`strategies/qullamaggie/episodic_pivot.py`](../strategies/qullamaggie/episodic_pivot.py)

**Hard gates:** gap up `≥ 10%` (today_open vs prev_close, from bhavcopy — `episodic_pivot.py:44`),
not on ASM/GSM, `avg_turnover_cr ≥ 1.0`, ≥ 25 bars.

**Conviction score ⭐ (scored, not required — `episodic_pivot.py:135`):**
- `f_vol_2x` — volume ≥ 2× 20-day average
- `f_has_catalyst` — a same-day NSE filing tagged `results / guidance / order_win / regulatory / acquisition`
- `f_adr_gt4` — ADR% (20d) ≥ 4
- `f_not_parabolic` — 30-day return ≤ 100% (still "neglected")

> Note: the scanner's `min_vol_ratio` argument is **not** applied as a filter — the 2× volume
> rule only contributes to the ⭐ score. **Ranked by** ⭐ desc, then `gap_pct` desc.
>
> This differs from the Stockbee EP in the nightly state (Setups page): stricter gap
> (10% vs 8%), volume 2× **scored** vs 3× **enforced**, and runs on bhavcopy instead of
> the universe summary.

### Setup 3 — Parabolic Short / Long Bounce
Blog: https://qullamaggie.com/my-3-timeless-setups-that-have-made-me-tens-of-millions/ · Code: [`strategies/qullamaggie/parabolic.py`](../strategies/qullamaggie/parabolic.py)

Universe gate for both: not ASM/GSM, `avg_turnover_cr ≥ 1.0`, ≥ 80 bars. Two sub-scans, each
kept only if its conviction `≥ 2`.

**Parabolic SHORT** — hard gate `30-day return ≥ 100%`, then count exhaustion signals (`parabolic.py:87`):
30d ≥ 100 · peak-bar range ≥ 85th percentile of last 60 ranges · peak volume ≥ 2× 20-day avg ·
upper-wick ≥ 40% of the peak candle · latest close < peak bar's open (price fading) ·
last 2 bars' volume < peak volume (volume fading).

**Parabolic LONG bounce** — hard gate `drop from 20-bar peak ≥ 50%`, then signals (`parabolic.py:122`):
drop ≥ 50 · drop ≤ 80 (not fully destroyed) · last bar green (close > open).

**Ranked by** conviction desc, then `r30d_pct` desc.

---

## Offline — Zanger breakout (not in the webapp)

Dan Zanger's core breakout setup lives in
[`strategies/zanger/scans.py`](../strategies/zanger/scans.py) with its rules in
[`strategies/zanger/SCAN_RULES.md`](../strategies/zanger/SCAN_RULES.md); full method:
[`docs/dan_zanger_trading_setup.md`](dan_zanger_trading_setup.md). Like Qullamaggie, it
is not wired into the webapp — run it directly if needed.

**Base filters** (same shape as Stockbee, `scans.py:12`): min turnover ₹1 Cr, min price
(default 0 — pass **≥ ₹100** in the Zanger spirit of high-priced leaders), ASM/GSM
exclusion and F&O-only via the `excluded` / `fo_only` arguments.

### Breakout from a Well-Formed Base (`scans.breakout`)
Blog: https://chartpattern.com/ · the strongest leader breaking out near its highs on
a volume explosion, closing strong, not extended:
- `pct_from_52w_high ≥ −5` (default 5) — near the high *and* Zanger's "never pay >5%
  above the breakout" chase limit
- `chg_pct ≥ 3` (default 3) — breakout-day range expansion
- `volume_ratio ≥ 1.5` (default 1.5) — the confirming volume explosion
- `range_pos ≥ 0.5` — closed in the upper half (default on)
- `rs_rank ≥ 70` (default 70) — leaders only

**Ranked by** `rs_rank` desc, then `volume_ratio` desc. The scan flags the breakout *day* —
confirm the base pattern (cup & handle, flat base, ascending triangle…) by eye on the chart.
