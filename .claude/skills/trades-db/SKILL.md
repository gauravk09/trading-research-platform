---
name: trades-db
description: Create, write to, change or query the local trades database (output/trades.duckdb). Use when building or changing the code that writes runs/trades, when adding a column, when the DB is missing or broken, or when the user asks to query trades across strategies.
---

# Trades Database (output/trades.duckdb)

A local, rebuildable cache of every backtest run's entries and exits. It's never committed or shared.
Each person rebuilds it from the specs (see `.claude/skills/rebuild-trades/SKILL.md`).
Because it can always be rebuilt, **deleting it is safe**, and schema changes need no migration code.

## Tables (the contract)

Once the writer module exists, its `CREATE TABLE` statements are the source of truth, and this section must match them.

```sql
CREATE TABLE IF NOT EXISTS runs (
    run_id          VARCHAR PRIMARY KEY,   -- uuid4, new for every run, never reused
    strategy        VARCHAR NOT NULL,      -- spec slug; control runs are '<slug>__control'
    schema_version  VARCHAR NOT NULL,      -- from spec.json
    spec_hash       VARCHAR NOT NULL,      -- sha256 of the canonical spec JSON
    spec_json       JSON    NOT NULL,      -- the full spec used, verbatim
    git_sha         VARCHAR NOT NULL,      -- code version that ran
    data_snapshot   DATE    NOT NULL,      -- latest bar date in data/parquet/daily at run time
    db_version      INTEGER NOT NULL,      -- version of this table layout (see "Changing the tables")
    run_at          TIMESTAMPTZ NOT NULL
);

CREATE TABLE IF NOT EXISTS trades (
    run_id       VARCHAR NOT NULL REFERENCES runs(run_id),
    strategy     VARCHAR NOT NULL,
    symbol       VARCHAR NOT NULL,
    side         VARCHAR NOT NULL,         -- 'long' | 'short'
    entry_date   DATE    NOT NULL,         -- IST trading date
    entry_px     DOUBLE  NOT NULL,
    exit_date    DATE,                     -- NULL = still open at data_snapshot
    exit_px      DOUBLE,
    exit_reason  VARCHAR,                  -- stop | target | trail | time | delist | open
    r            DOUBLE                    -- result in R after costs; NULL while open
);
```

## Writing rules

1. **Only the shared engine writes.** Never insert rows by hand or from a notebook.
2. **One transaction per run.** Write the `runs` row and all its `trades` rows in a single `BEGIN … COMMIT`,
   so a crashed run leaves nothing half-written.
3. **Append-only.** Never `UPDATE` or `DELETE` rows. Re-running a spec creates a new `run_id`.
4. **Timezone.** On connect, run `SET TimeZone='Asia/Kolkata'`. Otherwise DuckDB shifts stored IST
   midnights back one day on a UTC machine.
5. **One writer at a time.** DuckDB allows a single writing process. Run strategies one after another,
   or have the worker processes return their trades so the parent process does the write.

## Changing the tables

1. Edit the `CREATE TABLE` statements in the writer module and bump `db_version`.
2. Update the "Tables" section above to match. The README rule says the System architecture section
   is updated in the same PR.
3. Each person deletes their local `output/trades.duckdb` and rebuilds with the rebuild-trades skill.
   Don't write `ALTER TABLE` migrations: the DB is a cache.

## Useful queries

```sql
-- latest run per strategy
SELECT * FROM runs QUALIFY row_number() OVER (PARTITION BY strategy ORDER BY run_at DESC) = 1;

-- strategy vs its same-date control (latest runs)
WITH latest AS (
  SELECT * FROM runs QUALIFY row_number() OVER (PARTITION BY strategy ORDER BY run_at DESC) = 1)
SELECT t.strategy, count(*) AS n, avg(t.r) AS avg_r
FROM trades t JOIN latest l USING (run_id)
WHERE t.strategy IN ('zanger_breakout', 'zanger_breakout__control') AND t.r IS NOT NULL
GROUP BY t.strategy;
```

Open it read-only for queries, so the engine can still write:
`duckdb.connect("output/trades.duckdb", read_only=True)`.

## Status

The writer module and the engine are being built (PR #2). Until they're merged there's no DB to
write to. Report that, and don't create the file or invent rows. `duckdb` is installed, but it's
missing from `requirements.txt`; PR #2 adds it.
