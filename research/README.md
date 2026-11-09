# research/ — Bonde-style mover studies

"Every day I study 20% plus... all my learnings, all setup ideas, entries,
exits, everything comes from that study." — the TraderLion 2026 talk.

Quickstart:

```bash
python research/run.py research/studies/up20_in_5d.py
open research/output/up20_in_5d/summary.md
```

- `framework.py` — fixed engine: episodes → features → baseline → summary
- `features.py` — feature library (pre-pivot + during-move registries)
- `studies/` — one tiny spec file per idea (X% in Y days, filters, dates)
- `output/<study>/` — episodes.csv, movers.csv, baseline.csv, summary.md
- `LOG.md` — every run, appended automatically
- `PROGRAM.md` — the contract for AI agents replicating these studies

The one methodological hill this folder dies on: **every mover stat is shown
against a same-date non-mover baseline.** Without that, "80% of movers were
above their 20 DMA" is astrology.

This directory is descriptive hypothesis discovery, not a promotion path. New
S4+ promotion-grade work uses `src/backtest/canonical_runner.py` plus
`src/backtest/bookrunner.py`; its explicit spec, result checks, and MLflow index
do not replace the append-only factory ledger. `research/alpha_forge/` is frozen archived
exploration and cannot make new promotion claims. See `PROMOTION_POLICY.json`.
