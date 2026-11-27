"""trades_db.py — the writer for the local trades database, output/trades.duckdb.

The table layout and write rules are the contract in .claude/skills/trades-db/SKILL.md;
these CREATE TABLE statements are its source of truth, and the skill must match them.

  - only the shared engine writes, one transaction per run (runs row + all its trades)
  - append-only: re-running a spec makes a new run_id; nothing is updated or deleted
  - the session is pinned to Asia/Kolkata (IST midnights must not shift on a UTC machine)
  - one writer process at a time
  - changing a table: bump DB_VERSION, delete the local DB and rebuild (it is a cache)

A strategy's control run is stored as strategy "<slug>__control" with the same spec_hash.
"""

import hashlib
import json
import os
import uuid
from datetime import datetime
from zoneinfo import ZoneInfo

import duckdb

from data_collection.paths import ROOT_DIR

DEFAULT_PATH = os.path.join(ROOT_DIR, "output", "trades.duckdb")
DB_VERSION = 1
EXIT_REASONS = ("stop", "target", "trail", "time", "delist", "open")
TRADE_COLUMNS = ["run_id", "strategy", "symbol", "side", "entry_date", "entry_px",
                 "exit_date", "exit_px", "exit_reason", "r"]

RUNS_DDL = """CREATE TABLE IF NOT EXISTS runs (
    run_id          VARCHAR PRIMARY KEY,
    strategy        VARCHAR NOT NULL,
    schema_version  VARCHAR NOT NULL,
    spec_hash       VARCHAR NOT NULL,
    spec_json       JSON    NOT NULL,
    git_sha         VARCHAR NOT NULL,
    data_snapshot   DATE    NOT NULL,
    db_version      INTEGER NOT NULL,
    run_at          TIMESTAMPTZ NOT NULL
)"""
TRADES_DDL = """CREATE TABLE IF NOT EXISTS trades (
    run_id       VARCHAR NOT NULL REFERENCES runs(run_id),
    strategy     VARCHAR NOT NULL,
    symbol       VARCHAR NOT NULL,
    side         VARCHAR NOT NULL,
    entry_date   DATE    NOT NULL,
    entry_px     DOUBLE  NOT NULL,
    exit_date    DATE,
    exit_px      DOUBLE,
    exit_reason  VARCHAR,
    r            DOUBLE
)"""


def connect(path=DEFAULT_PATH, read_only=False):
    if not read_only:
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    con = duckdb.connect(path, read_only=read_only)
    con.execute("SET TimeZone='Asia/Kolkata'")
    if not read_only:
        con.execute(RUNS_DDL)
        con.execute(TRADES_DDL)
        _check_version(con)
    return con


def spec_hash(spec):
    """sha256 of the spec's canonical JSON: same rules -> same hash, whatever the formatting."""
    canonical = json.dumps(spec, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode()).hexdigest()


def write_run(con, strategy, spec, git_sha, data_snapshot, trades):
    """Store one run and all its trades in one transaction; return the new run_id."""
    bad = set(trades["exit_reason"]) - set(EXIT_REASONS)
    if bad:
        raise ValueError(f"exit_reason must be one of {EXIT_REASONS}, got {sorted(bad)}")
    run_id = uuid.uuid4().hex
    rows = trades.assign(run_id=run_id, strategy=strategy)[TRADE_COLUMNS]
    con.execute("BEGIN TRANSACTION")
    try:
        con.execute("INSERT INTO runs VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    [run_id, strategy, spec["schema_version"], spec_hash(spec),
                     json.dumps(spec, ensure_ascii=False), git_sha, data_snapshot, DB_VERSION,
                     datetime.now(ZoneInfo("Asia/Kolkata"))])
        if len(rows):
            con.register("new_trades", rows)
            con.execute(f"INSERT INTO trades SELECT {', '.join(TRADE_COLUMNS)} FROM new_trades")
            con.unregister("new_trades")
        con.execute("COMMIT")
    except Exception:
        con.execute("ROLLBACK")
        raise
    return run_id


def summary(con, run_ids):
    """One line per run: the identifying fields first, then counts and R."""
    marks = ", ".join("?" for _ in run_ids)
    return con.execute(f"""
        SELECT r.strategy, r.spec_hash, r.schema_version, r.git_sha, r.data_snapshot,
               count(t.run_id)                                   AS trades,
               count(t.r)                                        AS closed_with_r,
               round(avg(CASE WHEN t.r > 0 THEN 1.0 ELSE 0.0 END) FILTER (WHERE t.r IS NOT NULL) * 100, 1)
                                                                 AS win_rate_pct,
               round(avg(t.r), 3)                                AS avg_r
        FROM runs r LEFT JOIN trades t USING (run_id)
        WHERE r.run_id IN ({marks})
        GROUP BY ALL ORDER BY r.strategy""", list(run_ids)).df()


def _check_version(con):
    stored = con.execute("SELECT DISTINCT db_version FROM runs").fetchall()
    if stored and stored != [(DB_VERSION,)]:
        raise SystemExit(f"{DEFAULT_PATH} has db_version {sorted(v for (v,) in stored)}, this code writes "
                         f"{DB_VERSION}: delete the local DB and rebuild (see .claude/skills/trades-db/SKILL.md)")
