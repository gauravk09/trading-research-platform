# PROGRAM.md — instructions for agents running mover studies

This folder follows the karpathy/autoresearch pattern: **fixed engine, one
small file per idea, comparable reports, a log of every run.**

| autoresearch | here | edit? |
|---|---|---|
| `prepare.py` (fixed infra) | `framework.py` + `features.py` registries | engine semantics: NO. Adding features to the registries: yes |
| `train.py` (the experiment) | `studies/<idea>.py` — a `StudySpec` | **this is the file you write** |
| `val_bpb` (fixed metric) | `summary.md` lift table (movers vs baseline) | never change its shape |
| morning log | `LOG.md` | appended automatically |

## The loop

1. **State the idea as a spec.** Copy `studies/up20_in_5d.py`, change name,
   `move_pct`, `window_days`, filters, dates. One idea = one file = one output
   folder. Never overwrite an old study's name — comparability across runs is
   the asset.
2. **Run**: `python research/run.py research/studies/<idea>.py`
   (`--fetch-catalysts` to download missing pivot-date announcements,
   `--no-cache` after data updates).
3. **Read `output/<idea>/summary.md`.** The only numbers that matter are the
   **lift** columns: movers vs the same-date baseline. A 90% feature with 88%
   baseline is wallpaper.
4. **Iterate.** New windows, new filters (`min_turnover_cr=25` for
   institutional-only, `min_price=100` for high-priced), new features via
   `extra_pre_features` in the spec — promote a feature into `features.py`
   registries once it earns its keep.
5. **Never conclude — hand off.** A strong lift is a *hypothesis* for the
   point-in-time backtest (`src/backtest/`), not a tradeable finding. Write
   candidate rules into ROADMAP.md.

## Rules that keep studies honest (do not relax these)

- **Baseline is mandatory.** Studying only winners tells you what winners look
  like, not what distinguishes them. The engine samples non-mover controls on
  the *same dates* — this also cancels regime clustering.
- **Pre-pivot features see only rows `<= pivot`** — `features._pre()` enforces
  the slice. If you write an extra feature, take `(df, i)` and slice the same
  way. During-features may see the move (they describe it, they don't predict).
- **Pivots are hindsight.** The engine found them by conditioning on the
  outcome. All results are descriptive. Say so in anything you write.
- **Check `n_circuit_like` and turnover** before falling in love with a move —
  locked upper circuits were not buyable.
- **`catalyst_any = None` means no data**, not "no news" — check the coverage
  % in the summary before reading the catalyst section.
- **~40 features → a few lucky lifts.** Rank by lift, distrust singletons,
  prefer features that hold across BOTH the 5d and 63d studies.

## Data notes

- Matrices are built from per-symbol parquets (full history) and cached in
  `output/_cache/` per date-range. After an EOD update, use `--no-cache`.
- Announcements exist as full days only where fetched (the API returns 20-row
  stubs without a date range — fixed 2026-07-12); `--fetch-catalysts` fills
  pivot dates at ~1.2s per call, capped at 150 per run.
- Known artifacts: demergers are not price-adjusted (VEDL 2026-04-30 — see
  `data/processed/price_breaks_confirmed.json`); no historical ASM/GSM lists.
