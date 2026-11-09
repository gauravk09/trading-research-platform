# Magic Formula + Technicals Pipeline

The pipeline treats Screener.in as a dated fundamental snapshot and the local
daily parquet store as the technical source. It does not scrape Screener.

## Screener export

Required columns:

- `NSE Code`
- `Market Capitalization`
- `Enterprise Value to EBIT`
- `Return on capital employed`

Recommended columns:

- `Company`
- `Industry`
- `Average return on capital employed 3Years`
- `Debt to equity`

A broad Screener query is preferable because the local pipeline performs the
cross-sectional ranking:

```text
Market Capitalization > 1000
AND Enterprise Value to EBIT > 0
AND Return on capital employed > 0
```

## Run

```bash
python src/magic_formula.py --input /path/to/screener-export.csv
```

Refresh the technical overlay later without changing the saved fundamentals:

```bash
python src/magic_formula.py --refresh
```

Or let the importer locate the newest matching export automatically:

```bash
python src/magic_formula.py --auto-import
```

By default it scans `~/Downloads`. To use a dedicated folder:

```bash
SCREENER_EXPORT_DIR="$HOME/Finance/Screener Exports" \
  python src/magic_formula.py --auto-import
```

The importer identifies the file from its column headers rather than its file
name. It stores a SHA-256 fingerprint and imports only changed content.

The normal `src/pipeline/run_daily.py` workflow runs auto-import after rebuilding the
local EOD price summary. A newly downloaded Screener CSV is archived and
imported; if nothing changed, the saved fundamentals are reused and only the
technical overlay advances.

Optional controls:

```bash
python src/magic_formula.py --refresh --as-of 2026-10-23 \
  --min-market-cap 1000 --min-turnover 1
```

Raw imports are retained under `data/raw/magic_formula/`. Ranked boards and
their metadata are written under `data/processed/magic_formula/`.

## Scoring

- Value score: percentile rank of EV/EBIT, lower is better.
- Quality score: percentile rank of ROCE, higher is better.
- Magic score: equal-weighted mean of value and quality.
- Momentum score: 12-month return excluding the latest month, percentile ranked.
- Blend score: 60% Magic score + 40% momentum score.
- Technical confirmation: close above 200 DMA and 50 DMA above 200 DMA.

Financials and utility industries are excluded. A candidate must pass technical
confirmation and the local liquidity floor. Current Screener exports must not be
used as historical fundamentals; use the retained dated snapshots for forward
testing.
