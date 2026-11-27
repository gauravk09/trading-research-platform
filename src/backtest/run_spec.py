"""run_spec.py — run one strategy spec through the shared engine into output/trades.duckdb.

    PYTHONPATH=src python -m backtest.run_spec strategies/zanger

Steps: compile strategies/<name>/spec.json (validates first), load the study
price cache (backtest/studies/common.py) and the feature store columns the
strategy names, simulate the spec's entry clock with the shared exit rules,
and write one `runs` row plus its `trades` (contract:
.claude/skills/trades-db/SKILL.md), followed by the same-date random-entry
control run "<name>__control" (backtest/control.py) with the same spec_hash.

One run = one entry clock: the FIRST of the spec's entry_clocks_tested
(next_open when a condition is only known at the next open). The runs table
has no clock column, so a run's clock is always recoverable from its spec_json.

Inputs, built locally from the data snapshot:
  price cache    PYTHONPATH=src python src/backtest/studies/common.py
  feature store  PYTHONPATH=src python src/backtest/features.py
The run stops if the cache is older than data/parquet/daily, or if a feature
the strategy needs is missing or older than the cache. data_snapshot is then
the latest bar date the run used.
"""

import argparse
import glob
import importlib.util
import os
import subprocess

import duckdb
import pandas as pd

from backtest import control, simulator, spec_compiler, trades_db
from backtest.features import FEATURES_DIR
from data_collection.paths import ROOT_DIR

DAILY_GLOB = os.path.join(ROOT_DIR, "data", "parquet", "daily", "*.parquet")


class Columns:
    """col(name): a date x symbol frame from the price cache or the feature store."""

    def __init__(self, cache, features_dir, names):
        self.cache = cache
        self.features_dir = features_dir
        self.frames = {}
        for name in names:
            self(name)                    # load and check everything up front

    def __call__(self, name):
        if name not in self.frames:
            self.frames[name] = self._load(name)
        return self.frames[name]

    def _load(self, name):
        close = self.cache["close"]
        if name in spec_compiler.BAR_FIELDS:
            return self.cache[name].astype(float)
        path = os.path.join(self.features_dir, f"{name}.parquet")
        if not os.path.exists(path):
            raise SystemExit(f"feature {name!r} is not built: run PYTHONPATH=src python src/backtest/features.py")
        frame = pd.read_parquet(path)
        if frame.index.max() < close.index.max():
            raise SystemExit(f"feature {name!r} ends {frame.index.max().date()} but the price cache ends "
                             f"{close.index.max().date()}: rebuild the feature store")
        return frame.reindex(index=close.index, columns=close.columns).astype(float)


def entry_clock(module):
    return "next_open" if module.NEXT_OPEN_ONLY else module.ENTRY_CLOCKS[0]


def data_snapshot(cache, daily_glob=DAILY_GLOB):
    """The cache's last bar date; stops if data/parquet/daily already has newer bars."""
    last = simulator.calendar_dates(cache["close"].index[-1:])[0]
    if glob.glob(daily_glob):
        con = duckdb.connect()
        con.execute("SET TimeZone='Asia/Kolkata'")      # stored dates are midnight IST
        newest = con.execute(f"SELECT max(CAST(date AS DATE)) FROM read_parquet('{daily_glob}')").fetchone()[0]
        con.close()
        if newest is not None and newest > last:
            raise SystemExit(f"the price cache ends {last} but data/parquet/daily has bars to {newest}: "
                             f"rebuild the cache (PYTHONPATH=src python src/backtest/studies/common.py)")
    return last


def git_sha():
    try:
        return subprocess.check_output(["git", "-C", ROOT_DIR, "rev-parse", "--short", "HEAD"],
                                       text=True, stderr=subprocess.DEVNULL).strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def load_strategy(py_path):
    spec = importlib.util.spec_from_file_location("generated_strategy", py_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def run(strategy_dir, db_path=trades_db.DEFAULT_PATH, cache=None, features_dir=FEATURES_DIR,
        daily_glob=DAILY_GLOB):
    """Compile, simulate and store one strategy. Returns the new run_ids."""
    py_path = spec_compiler.write_strategy(strategy_dir)
    spec, _ = spec_compiler.load_spec(strategy_dir)
    module = load_strategy(py_path)
    if cache is None:
        from backtest.studies import common
        cache = common.load_cache()
    snapshot = data_snapshot(cache, daily_glob)
    col = Columns(cache, features_dir, set(module.COLUMNS) | {"open", "high", "low", "close"})
    clock = entry_clock(module)

    trades = simulator.simulate(module, col, clock)
    con = trades_db.connect(db_path)
    sha = git_sha()
    random_entries = control.control_trades(module, col, clock, trades, control.seed_from(trades_db.spec_hash(spec)))
    run_ids = [trades_db.write_run(con, module.SPEC_ID, spec, sha, snapshot, trades),
               trades_db.write_run(con, f"{module.SPEC_ID}__control", spec, sha, snapshot, random_entries)]
    print(f"entry clock: {clock}")
    print(trades_db.summary(con, run_ids).to_string(index=False))
    for note in module.NOT_APPLIED:
        print("  not applied:", note)
    con.close()
    return run_ids


def main(argv=None):
    ap = argparse.ArgumentParser(description="Run strategies/<name> through the shared engine")
    ap.add_argument("strategy", help="strategies/<name>")
    ap.add_argument("--db", default=trades_db.DEFAULT_PATH)
    a = ap.parse_args(argv)
    try:
        run(a.strategy, db_path=a.db)
    except spec_compiler.SpecError as exc:
        raise SystemExit(f"cannot compile: {exc}")


if __name__ == "__main__":
    main()
