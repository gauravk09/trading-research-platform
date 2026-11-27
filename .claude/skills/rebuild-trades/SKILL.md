---
name: rebuild-trades
description: Rebuild a strategy's trades locally from its spec.json into the local trades DuckDB. Use when the user says /rebuild-trades, "run/backtest <strategy>", "get the trades for <strategy>", when output/trades.duckdb is missing or stale, or when two team members' results for the same strategy differ.
---

# Rebuild Trades From Specs

Nobody shares trade results. Everyone rebuilds them locally from the specs.
`output/trades.duckdb` is a local cache and is never committed or sent to anyone.
The source of truth is:

```
strategies/<name>/spec.json   (in git)  +  the data snapshot in data/  (shared privately)
```

The same spec, code version and data snapshot always give the same trades.

## Steps

1. **Pick the specs.** Use one `strategies/<name>/spec.json`, or all of them if the user asks to rebuild
   everything. Never run anything from `strategies/_archive/`.
2. **Check the data snapshot.** Report the latest date in the daily price data under `data/parquet/daily/`.
   If it's older than the last trading day, say so before running. Don't refresh it yourself unless the user asks.
3. **Validate the spec** against `strategies/_spec/schema.json`. If it fails, report the exact field and stop.
   Don't change the spec to make it pass. Steps 3 and 4 are one command; it validates first and stops on
   the first problem:
   ```bash
   PYTHONPATH=src python -m backtest.spec_compiler strategies/<name>
   ```
4. **Compile** `spec.json` into `strategy.py` (the command above writes `strategies/<name>/strategy.py`).
   Never edit `strategy.py` by hand. If the generated code looks wrong, the fix goes in the spec or the
   compiler. A spec that needs a feature the store doesn't have fails here: add the feature to
   `src/backtest/features.py` (and `FEATURE_NAMES`) first, never inside the strategy.
5. **Run** the shared engine. It writes the `runs` and `trades` tables in `output/trades.duckdb`, plus the
   `<name>__control` run (random entries on the same dates). It needs the study price cache and the feature
   store built from the same data snapshot, and stops if a feature is missing or older than the cache:
   ```bash
   PYTHONPATH=src python src/backtest/studies/common.py   # price cache, after a data refresh
   PYTHONPATH=src python src/backtest/features.py         # feature store, after the cache
   PYTHONPATH=src python -m backtest.run_spec strategies/<name>
   ```
   A run uses the spec's first `entry_clocks_tested` clock (the `runs` table has no clock column).
   It also stops if the price cache is older than `data/parquet/daily`.
6. **Report** from DuckDB, with the identifying fields from the `runs` table first:
   `strategy, spec_hash, schema_version, git_sha, data_snapshot`, then the trade count and summary.
   Compare the strategy against its `__control` run, not against zero. `run_spec` prints this table at the
   end of a run; to read it again later:
   ```bash
   PYTHONPATH=src python -c "from backtest import trades_db as T; c=T.connect(); \
     ids=[r[0] for r in c.execute('SELECT run_id FROM runs WHERE strategy LIKE ? ORDER BY run_at DESC LIMIT 2', ['<name>%']).fetchall()]; \
     print(T.summary(c, ids).to_string(index=False))"
   ```

## When two people's results differ

Compare `spec_hash`, `git_sha` and `data_snapshot` from both `runs` tables before looking at any numbers:

- If any of the three differs, that difference explains the mismatch. Report which one.
- If all three match and the trades still differ, that's a bug in the pipeline. Report both run_ids and stop.

## Never

- Commit, upload or copy `output/trades.duckdb` anywhere (`output/` is gitignored).
- Add a feature inside a strategy. Add it to the central feature store first.
- Edit anything under `strategies/_archive/`.

## Status

The schema, compiler, shared exits, engine, trades database and control run exist; steps 3 to 6 have
their commands above. Evaluation and reports beyond the summary table are the next revamp: don't
improvise them here.
