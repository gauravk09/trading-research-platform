"""trades_db.py — the local trades database, output/trades.duckdb (never committed).

Two tables. Every run stores the full spec it used, so every trade traces back
to the exact rules, schema version, code version and data that produced it.

  runs    run_id, strategy, entry_clock, schema_version, spec_json, spec_hash,
          git_sha, data_snapshot, run_at
  trades  run_id, strategy, symbol, signal_date, entry_date, entry_px,
          exit_date, exit_px, exit_reason, r

A strategy's control run is stored as strategy "<name>__control" with the
same spec_hash. Trades still open at the end of the data have exit_reason
"open" and NULL exit fields and r.
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
TRADE_COLUMNS = ["run_id", "strategy", "symbol", "signal_date", "entry_date", "entry_px",
                 "exit_date", "exit_px", "exit_reason", "r"]

RUNS_DDL = """CREATE TABLE IF NOT EXISTS runs (
    run_id VARCHAR PRIMARY KEY, strategy VARCHAR NOT NULL, entry_clock VARCHAR NOT NULL,
    schema_version VARCHAR NOT NULL, spec_json VARCHAR NOT NULL, spec_hash VARCHAR NOT NULL,
    git_sha VARCHAR NOT NULL, data_snapshot VARCHAR NOT NULL, run_at TIMESTAMP NOT NULL)"""
TRADES_DDL = """CREATE TABLE IF NOT EXISTS trades (
    run_id VARCHAR NOT NULL, strategy VARCHAR NOT NULL, symbol VARCHAR NOT NULL,
    signal_date DATE NOT NULL, entry_date DATE NOT NULL, entry_px DOUBLE NOT NULL,
    exit_date DATE, exit_px DOUBLE, exit_reason VARCHAR NOT NULL, r DOUBLE)"""


def connect(path=DEFAULT_PATH):
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    con = duckdb.connect(path)
    # Market dates are IST; pin the session so no timestamp is re-read in another zone.
    con.execute("SET TimeZone='Asia/Kolkata'")
    con.execute(RUNS_DDL)
    con.execute(TRADES_DDL)
    return con


def spec_hash(spec):
    """sha256 of the spec's canonical JSON: same rules -> same hash, whatever the formatting."""
    canonical = json.dumps(spec, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode()).hexdigest()


def write_run(con, strategy, entry_clock, spec, git_sha, data_snapshot, trades):
    """Store one run and its trades; return the new run_id."""
    run_id = uuid.uuid4().hex
    run_at = datetime.now(ZoneInfo("Asia/Kolkata")).replace(tzinfo=None, microsecond=0)
    con.execute("INSERT INTO runs VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                [run_id, strategy, entry_clock, spec["schema_version"],
                 json.dumps(spec, ensure_ascii=False), spec_hash(spec), git_sha, data_snapshot, run_at])
    rows = trades.assign(run_id=run_id, strategy=strategy)[TRADE_COLUMNS]
    if len(rows):
        con.register("new_trades", rows)
        con.execute(f"INSERT INTO trades SELECT {', '.join(TRADE_COLUMNS)} FROM new_trades")
        con.unregister("new_trades")
    return run_id


def summary(con, run_ids):
    """One line per run: the identifying fields first, then counts and R."""
    marks = ", ".join("?" for _ in run_ids)
    return con.execute(f"""
        SELECT r.strategy, r.entry_clock, r.spec_hash, r.schema_version, r.git_sha, r.data_snapshot,
               count(t.run_id)                                   AS trades,
               count(t.r)                                        AS closed_with_r,
               round(avg(CASE WHEN t.r > 0 THEN 1.0 ELSE 0.0 END) FILTER (WHERE t.r IS NOT NULL) * 100, 1)
                                                                 AS win_rate_pct,
               round(avg(t.r), 3)                                AS avg_r
        FROM runs r LEFT JOIN trades t USING (run_id)
        WHERE r.run_id IN ({marks})
        GROUP BY ALL ORDER BY r.entry_clock, r.strategy""", list(run_ids)).df()
