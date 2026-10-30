---
name: chart-bank
description: Build a flip-through PDF deck of annotated "winner" charts for a study — every event that gained >=20% in the month after entry, with ~2 years of prior daily context and ~3 months after, the setup zone shaded, entry marked, SMAs/TI65/market-context overlaid. Use when the user says /chart-bank, "chart bank", "training charts", "show me winners for <study>", or wants to eyeball what a setup looks like before it runs.
---

# Chart Bank — visual pattern-training decks

Turn a study's event log into a deck you page through (next / next / next) to
train your eye on what a working setup looks like *before* it runs. Each page is
one event that went on to gain **>= 20% in the month after entry**, drawn with
~2 years of daily context before the signal and ~3 months after.

The point is repetition on winners: setup zone shaded, entry marked, the market
regime at the time spelled out — so you internalise the pattern, not the story.

## What each page shows

- **Daily candlesticks**, ~504 bars before the signal → ~63 bars after entry.
- **SMAs 10 / 20 / 50 / 200** (dashboard colours).
- **Volume** with its 50-day average.
- **TI65** panel (Bonde 7-day / 65-day close ratio; the 1.05 trend-on line is
  drawn and the >1.05 zone shaded) — same indicator as the dashboard stock chart.
- **Entry marker** at the D+1 open, a dashed vertical across all panels, and a
  dotted **+20% (1-month target)** line off the entry.
- **Setup zone** shaded per study (Darvas box, HTF flag, base, signal low, …).
- **Side box** with the entry criteria in plain English **plus** a
  "Market context at signal" block: stock composite **RS**, market **regime**
  (breadth score), and **T2108** (% of market above its 40 DMA) — so you can see
  what the broad market was doing when the setup fired.

Winners are curated, not dumped: capped per study (default 40), spread across
calendar years so the deck spans bull *and* bear regimes, and limited to
`PER_SYMBOL_CAP` events per symbol so no single name dominates.

## How to run

Uses the anaconda3 python and the study cache (built by `common.py`).

```bash
# one study
~/anaconda3/bin/python src/backtest/studies/chart_bank.py darvas_box

# several, more charts each
~/anaconda3/bin/python src/backtest/studies/chart_bank.py high_tight_flag ryan_52wk_high --n 60

# every study with a *_events.csv
~/anaconda3/bin/python src/backtest/studies/chart_bank.py
```

Output: `output/chart_bank/<slug>_chart_bank.pdf` — one event per page. Open the
PDF and arrow through it. Studies with no `ret_o20` column (e.g. `overnight_news`,
an intraday ORB study) are skipped automatically.

## Prerequisites

- The study cache must exist (`output/studies/cache/*.parquet`). If missing, the
  run errors — rebuild it once with
  `~/anaconda3/bin/python src/backtest/studies/common.py` (needed after EOD
  updates so the matrices include recent bars).
- The study's `output/studies/<slug>_events.csv` must exist (produced by running
  that study's script, e.g. `python src/backtest/studies/darvas_box.py`).

## Adding a new study's annotations

Setup-zone shading and the criteria bullets live in
`src/backtest/studies/annotators.py`, one function per study registered in
`ANNOTATORS`. A study with no annotator still renders via the generic fallback
(entry + market context, no setup-specific zone). To add one: write
`def <slug>(ax, row, win, sig_pos, entry_x) -> list[str]`, draw any zone with the
`_zone` / `_mark_low` helpers using that study's event-csv columns, return the
plain-English bullet lines, and add it to `ANNOTATORS`.

## Knobs (top of `chart_bank.py`)

- `BARS_BEFORE` (504) / `BARS_AFTER` (63) — context window either side of entry.
- `WIN_RET` (20.0) — the "winner" threshold: `ret_o20 >= WIN_RET`.
- `DEFAULT_N` (40) / `--n` — charts per study.
- `PER_SYMBOL_CAP` (2) — max events per symbol in one deck.
