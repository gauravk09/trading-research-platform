# SPEC — dan_zanger_breakout        status: S1 | 2026-07-29

Source: docs/dan_zanger_trading_setup.md (S0 done). Zanger's edge claim:
buy the volume-confirmed breakout of a well-formed base in a leading,
high-priced growth stock; never chase >5% past the pivot; exit instantly if
the pivot is lost; sell 20-30% into the first +15-20% pop; hold the rest
until the pattern breaks. Record era: dot-com, heavy margin, concentration.

## Honesty preamble — what is NOT codable (from the S0 extraction)

The doc defines NO breakout-point geometry, NO volume multiple, NO liquidity
floors, and dollar stops ($1-2) that don't translate. All 11 chart patterns
are named, none specified. The spec below is therefore a CODABLE PROXY of
Zanger, and results speak about the proxy, not the man. Biggest overlap
risk: the codable core is close to ryan_52wk_high (S2/S5 done) — the S2
question is really "do Zanger's DISTINCTIVE elements (tight pivot stop,
pivot-loss hard exit, fast scale-out, extreme growth screen, volume
explosion) add anything beyond Ryan's already-measured shape?"

## Fixed proxy definitions (pre-registered)

- Pivot: prior 20-day closing high.
- Base: >= 20 bars since the previous 20d-closing-high cross, base floor
  >= 0.80 x base top (depth <= 20%).
- Quality/leader proxy: close >= 0.85 x 252d closing high; close >= Rs 100;
  20d turnover >= Rs 5cr; composite RS >= 70.
- Chase cap: signal close <= pivot x 1.05.
- Volume: signal-day volume >= 2.0 x 30d average (his "explosion", number is
  OURS — the doc gives none; 1.5x/2.5x reported as neighborhood only).
- Entry: signal-day close with range_pos >= 0.75 (house lever 1); D+1 open
  reported as control.
- Stop: pivot x 0.95 (his acknowledged 5% alternative; $-stops rejected).
- Hard exit: any CLOSE back below the pivot ("no questions asked").
- Scale-out: 25% of position at +17.5% above pivot (midpoint of his 20-30%
  at +15-20%).
- Remainder exit: close < 20DMA (OUR proxy — he "sells strength" and redraws
  trendlines, uncodable) or 50-bar time cap (his 10-week max).
- Dedup 10 bars/symbol; costs 0.2%/side; eras A 2015-19 / COVID / B 2023-26.

## Variants (exactly 3)

  V1 core           all rules above
  V2 no-volume-leg  V1 minus the 2x volume requirement
  V3 growth         V1 + (PAT or revenue YoY >= +100% from financials.parquet,
                    joined on filing_date; Nifty-500 2016+ coverage only —
                    report coverage % and treat as a subset study)

Written-now expectation (so results can't be spun): NSE precedent says
volume-confirmation legs measure neutral-to-harmful (>3x gate, dry-up,
breakout-volume buckets) — V2 beating V1 would CONFIRM the house pattern,
not surprise it. V3 is the genuinely new information (nobody has tested the
extreme-growth screen here).

## Success bars

- S2 verdict: any variant with close-entry PF >= 1.2 in BOTH eras, n >= 150
  → proceed to S3/S5 (book sim vs ryan_minervini_book as the incumbent —
  it must BEAT the incumbent or add uncorrelated trades, not merely pass).
- Else: record FAILS/MIXED with the Ryan-overlap explanation and stop.
