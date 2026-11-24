# Zanger Scans — Rules & Indian Adaptation

Source of truth for the Dan Zanger scan in this repo. Runs on
`data/processed/universe_summary.parquet` (one row per NSE EQ stock), so the
dashboard stays instant. Columns used here are produced by `src/preprocessing/precompute.py`.
Full plain-English method: [`docs/dan_zanger_trading_setup.md`](../../docs/dan_zanger_trading_setup.md).

## Universe & global filters (applied to every scan)
- **Liquidity:** `avg_turnover_cr` ≥ slider (default ₹1 Cr).
- **Price floor:** `close` ≥ slider (default **₹100**). Zanger deliberately buys
  high-priced quality leaders, not cheap stocks — so this scan defaults to a real
  floor rather than ₹0.
- **ASM/GSM excluded** by default. Toggle off to include them.
- **F&O flag + toggle.**

## Scan — Breakout from a Well-Formed Base  (`scans.breakout`)
Zanger's core, continuously-traded setup: the strongest leader breaking out near
its highs on a volume explosion, closing strong, and not extended.

- `pct_from_52w_high` ≥ **−5%** (slider 0–25) — within 5% of the 52-week high. This
  doubles as Zanger's *"never pay more than 5% above the breakout point"* chase rule.
- `chg_pct` ≥ **3%** (slider 0–15) — a breakout-day range expansion.
- `volume_ratio` ≥ **1.5×** (slider 1–5) — the volume explosion that confirms the
  breakout (Zanger: *"it takes volume to move stocks"*).
- `range_pos` ≥ **0.5** — closed in the upper half of the day's range (toggle).
- `rs_rank` ≥ **70** (slider 0–100) — only leading stocks.
- Ranked by RS rank, then volume ratio (strongest leaders, biggest volume first).

### What is intentionally NOT modelled
Zanger's full method needs data we don't carry per stock:
- **Earnings/sales surprise, low float, leading group** — fundamental/sector inputs.
  We approximate "leader" with RS rank and "near highs" with `pct_from_52w_high`.
- **Specific chart patterns** (cup-&-handle, flat base, ascending triangle, etc.) —
  the scan finds the *breakout day*; eyeball the base on the chart to confirm.
- **Pyramiding (Setup 2)** and **short/cash (Setup 3)** are position-management and
  market-regime tactics, not screens, so they are not scanned.

## Precomputed columns this scan relies on
`pct_from_52w_high`, `volume_ratio`, `chg_pct`, `range_pos`, `rs_rank` (plus the
existing close / turnover / returns / ADR / F&O columns).

## Sources
- 10 Golden Rules & 11 Chart Patterns — https://chartpattern.com/
- See `docs/dan_zanger_trading_setup.md` for the full referenced write-up.
