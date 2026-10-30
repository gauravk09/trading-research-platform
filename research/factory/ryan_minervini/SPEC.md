# SPEC — ryan_minervini_book        status: S5 | 2026-07-29

Sources: `ryan_52wk_high.py` + `minervini_trend_template.py` (S2 DONE, MIXED —
only champions with tail edge), `close_entry_rescore.py` (S3 lever 1 measured
at D+5: Ryan PF 0.70/0.97 → 1.59/1.46 with close+strong-close entry).
This run answers S5: **does the combined book pay in rupees on a ₹10,00,000
account at the live regime knobs?**

Claimed edge: tail-riding 52wk-high / trend-template breakouts; pays via rare
large winners held 20-120 days; concentrated in RS ≥ 80; ~30-37% win rate.

## Fixed choices (no sweeping)

- Events: the two studies' dedup'd event CSVs as-is; no re-mining.
- Entry: **signal-day close**, gated on range_pos ≥ 0.75 (skip if high==low).
  Known optimism: backtest uses the final bar's range; the live check at
  ~15:15 uses range-so-far (dashboard_setups_entry approximation, accepted).
- Same symbol, both strategies, same day → Ryan takes it. One position per
  symbol. When slots are short, higher rs_rank wins.
- Exits exactly as published per study:
  Ryan — 7% hard stop; once a close ≥ +20%, exit on close < 50DMA (hard stop
  off, per the study); 120-bar time stop.
  Minervini — stop = 5-bar low capped −8%; 1/3 off at +2R then stop to
  breakeven; exit on close < 20DMA; 60-bar time stop.
- Tier gate: **previous session's** 5-signal breadth score (house prev-close
  rule) → tier; breakout entries allowed only in AGGRESSIVE/NORMAL
  (live `allowed_entries`).
- Costs 0.2%/side. Start ₹10,00,000. Fractional shares (house sim style).
  No leverage modeled even where leverage_ok. Delisting: 20 straight NaN
  sessions → force-exit at last mark.

## Variants (exactly these 3, pre-registered)

| variant | tier gate | risk/trade | max pos | gross cap |
|---|---|---|---|---|
| V1 knobs | yes (live TIER_KNOBS) | 0.50% AGG / 0.35% NORMAL | 6 / 4 | 100 / 75% |
| V2 normal_fixed | no | 0.35% always | 4 | 75% |
| V3 risk1 | yes | 1.00% both tiers | 6 | 100% |

V2 isolates what the tier gate adds; V3 asks whether the knob, not the edge,
is the binding constraint.

## Success bars (written before running)

- **S5 PASS**: ≥ +3%/yr (₹30,000/yr) average on the full period AND positive
  in era A (≤2019) and era B (2023-26) for at least one variant, with that
  variant's realized max drawdown ≤ 20%. 2024-26 sub-era shown.
- S6 expectation check: win rate lands in the confirmed-tolerable 25-40%,
  holds 20-60d+ (soft mismatch with 2-10d preference → size-tier note).
- Report signals → gated → taken funnel so capital-starvation is visible
  (the DEP lesson).
