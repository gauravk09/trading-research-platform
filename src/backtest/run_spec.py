"""run_spec.py — run one strategy spec through the shared engine into output/trades.duckdb.

    PYTHONPATH=src python -m backtest.run_spec strategies/zanger

Steps: compile strategies/<name>/spec.json (validates first), load the study
price cache (backtest/studies/common.py) and the feature store columns the
strategy names, simulate each entry clock with the shared exit rules, and
write one `runs` row plus its `trades` per clock.

Inputs, built locally from the data snapshot:
  price cache    PYTHONPATH=src python src/backtest/studies/common.py
  feature store  PYTHONPATH=src python src/backtest/features.py
The run stops if a feature the strategy needs is missing or older than the cache.
"""

import argparse
import hashlib
import importlib.util
import os
import subprocess

import numpy as np
import pandas as pd

from backtest import simulator, spec_compiler, trades_db
from backtest.features import FEATURES_DIR
from data_collection.paths import ROOT_DIR


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

    def fingerprint(self):
        """sha256 over every frame this run read, so two runs can tell if their inputs matched."""
        digest = hashlib.sha256()
        for name in sorted(self.frames):
            frame = self.frames[name]
            digest.update(name.encode())
            digest.update("|".join(map(str, frame.columns)).encode())
            digest.update(np.ascontiguousarray(frame.to_numpy(dtype=float)).tobytes())
        return digest.hexdigest()[:16]


def data_snapshot(col):
    close = col("close")
    first, last = (simulator._calendar_dates(close.index[[0, -1]]))
    return f"cache {first}..{last}, {close.shape[1]} symbols, inputs sha256:{col.fingerprint()}"


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


def run(strategy_dir, db_path=trades_db.DEFAULT_PATH, cache=None, features_dir=FEATURES_DIR, clocks=None):
    """Compile, simulate and store one strategy. Returns the new run_ids."""
    py_path = spec_compiler.write_strategy(strategy_dir)
    spec, _ = spec_compiler.load_spec(strategy_dir)
    module = load_strategy(py_path)
    clocks = clocks or list(module.ENTRY_CLOCKS)
    if module.NEXT_OPEN_ONLY:
        clocks = [c for c in clocks if c == "next_open"]
    if cache is None:
        from backtest.studies import common
        cache = common.load_cache()
    col = Columns(cache, features_dir, set(module.COLUMNS) | {"open", "high", "low", "close"})
    snapshot, sha = data_snapshot(col), git_sha()

    con = trades_db.connect(db_path)
    run_ids = []
    for clock in clocks:
        trades = simulator.simulate(module, col, clock)
        run_ids.append(trades_db.write_run(con, module.SPEC_ID, clock, spec, sha, snapshot, trades))
    print(trades_db.summary(con, run_ids).to_string(index=False))
    for note in module.NOT_APPLIED:
        print("  not applied:", note)
    con.close()
    return run_ids


def main(argv=None):
    ap = argparse.ArgumentParser(description="Run strategies/<name> through the shared engine")
    ap.add_argument("strategy", help="strategies/<name>")
    ap.add_argument("--db", default=trades_db.DEFAULT_PATH)
    ap.add_argument("--clock", action="append", help="run only this entry clock (repeatable)")
    a = ap.parse_args(argv)
    try:
        run(a.strategy, db_path=a.db, clocks=a.clock)
    except spec_compiler.SpecError as exc:
        raise SystemExit(f"cannot compile: {exc}")


if __name__ == "__main__":
    main()
