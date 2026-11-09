# experimentation

Where new ideas get tested before they earn a place anywhere else. It sits on top of every other layer:
an experiment may import from any of them, but **nothing in production imports from here**, so an experiment
can never change the nightly run, the scans or an order. A test (`tests/test_isolation.py`) enforces this.

| Module | What it studies |
|---|---|
| `studies/fund_behavior.py` | Longitudinal study of the SBI Contra Fund (run with `run_fund_study.command`; the dashboard has a page for it). |
| `studies/investor_footprint.py` | Point-in-time investor holdings, accumulation and what a disclosure did to the price. |

Older experiments live in `backtest/studies/` (36 files) and the top-level `research/` folder (research machine,
regime lab, factory). They are not moved yet because their notes and specs refer to them by path.

## Adding an experiment

1. Create `studies/<name>.py` with a docstring saying the question, the data used, and what would count as a result.
2. Read prepared data (`data_collection.storage`, files in `data/processed/`); compute with `indicators/`.
3. Write results under `output/studies/<name>/`. Do not write into `data/processed/` or `data/parquet/`: the nightly job and dashboard read those.
4. Add `tests/test_<name>.py` for any non-trivial calculation.
5. If it survives, promote it: move the code into the layer it belongs to, and add a row to that layer's README.

Run one from the repo root:

```bash
PYTHONPATH=src python -m experimentation.studies.fund_behavior
```

## Checks before believing a result

- **Look-ahead:** does day *t* use anything not known at that day's close?
- **Survivors:** the stored universe has no delisted stocks, so older results flatter small caps.
- **Alignment:** off-by-one in `shift()`, rolling windows, or joining files on the wrong trading day.
- **Corporate actions:** splits and bonuses break price continuity unless adjusted.
- **Short series:** a window longer than the data should give NaN, not a number.
- **IST:** don't mix naive timestamps with IST-aware ones from Kite.

Note: the two existing studies write their results into `data/processed/` (`fund_study_sbi_contra.parquet`,
`named_*_holdings*.parquet`), which predates rule 3. New work should follow the rule.
