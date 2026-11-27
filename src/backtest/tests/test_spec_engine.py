"""simulator + trades_db + run_spec: spec -> shared engine -> output/trades.duckdb."""

import json
import os
import shutil
import tempfile
import types
import unittest
from unittest.mock import patch

import numpy as np
import pandas as pd

from backtest import features, run_spec, simulator, spec_compiler, trades_db
from data_collection.paths import ROOT_DIR

ZANGER_SPEC = os.path.join(ROOT_DIR, "strategies", "zanger", "spec.json")


def synthetic_cache(n_dates=1500, n_stocks=30, seed=1):
    """Random-walk OHLCV on a midnight-IST calendar, like the real study cache."""
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range("2016-01-01", periods=n_dates, tz="Asia/Kolkata")
    cols = [f"STK{i:02d}" for i in range(n_stocks)]
    close = 200 * np.exp(np.cumsum(rng.normal(0.0008, 0.02, (n_dates, n_stocks)), axis=0))
    open_ = close * (1 + rng.normal(0, 0.005, close.shape))
    high = np.maximum(open_, close) * (1 + np.abs(rng.normal(0, 0.01, close.shape)))
    low = np.minimum(open_, close) * (1 - np.abs(rng.normal(0, 0.01, close.shape)))
    volume = rng.lognormal(14, 0.6, close.shape)
    frame = lambda a: pd.DataFrame(a, index=dates, columns=cols)
    return {"open": frame(open_), "high": frame(high), "low": frame(low), "close": frame(close),
            "volume": frame(volume), "rs": frame(np.full(close.shape, 80.0))}


def build_features(cache, out_dir):
    with patch.object(features, "DELIVERY", "/nonexistent"), \
         patch.object(features, "SECTOR_MAP", "/nonexistent"):
        features.build_all(cache, out_dir=out_dir)


def copy_zanger(tmp):
    folder = os.path.join(tmp, "zanger")
    os.makedirs(folder)
    shutil.copyfile(ZANGER_SPEC, os.path.join(folder, "spec.json"))
    return folder


# ── a hand-built strategy, so every trade can be checked by hand ─────────────

def tiny(rows, signal_bars, time_bars=3, dedup=0, cost=0.0, stop_frac=0.9):
    a = np.array(rows, dtype=float)
    dates = pd.bdate_range("2020-01-01", periods=len(a))
    frames = {k: pd.DataFrame({"X": a[:, i]}, index=dates) for i, k in enumerate(("open", "high", "low", "close"))}
    signal = pd.DataFrame({"X": np.isin(np.arange(len(a)), signal_bars)}, index=dates)
    module = types.SimpleNamespace(
        DIRECTION="long", DEDUP_BARS=dedup, COSTS_PCT_PER_SIDE=cost, MAX_STOP_PCT=None,
        universe_conditions=lambda col: {}, entry_conditions=lambda col: {"s": signal},
        stop_level=lambda col, entry: entry * stop_frac,
        exit_rules=lambda col, entry: [{"id": "time", "kind": "time", "value": time_bars, "fraction": 1.0}])
    return module, frames.__getitem__, signal


class SimulatorTests(unittest.TestCase):
    rows = [(100, 101, 99, 100), (100, 102, 99, 101), (101, 103, 100, 102),
            (102, 104, 101, 103), (103, 105, 102, 104), (104, 106, 103, 105)]

    def test_one_position_per_stock(self):
        module, col, signal = tiny(self.rows, [0, 1])
        trades = simulator.simulate(module, col, "next_open", signal=signal)
        self.assertEqual(len(trades), 1)                       # bar-1 signal arrives while bar-0 trade is open
        t = trades.iloc[0]
        self.assertEqual((t.entry_px, t.exit_px, t.exit_reason), (100.0, 103.0, "time"))
        self.assertAlmostEqual(t.r, (103 - 100) / 10)          # stop 90 -> risk 10

    def test_costs_are_charged_in_r(self):
        module, col, signal = tiny(self.rows, [0], cost=0.2)
        t = simulator.simulate(module, col, "next_open", signal=signal).iloc[0]
        self.assertAlmostEqual(t.r, 0.3 - 2 * 0.002 * 100 / 10)

    def test_trade_open_at_data_end_is_kept_without_exit(self):
        module, col, signal = tiny(self.rows, [4], time_bars=10)
        t = simulator.simulate(module, col, "signal_close", signal=signal).iloc[0]
        self.assertEqual(t.exit_reason, "open")
        self.assertIsNone(t.exit_date)
        self.assertTrue(pd.isna(t.r))

    def test_signal_close_enters_at_the_signal_close(self):
        module, col, signal = tiny(self.rows, [1], time_bars=1)
        t = simulator.simulate(module, col, "signal_close", signal=signal).iloc[0]
        self.assertEqual((t.entry_px, t.exit_px, t.entry_date), (101.0, 102.0, t.signal_date))


# ── the real Zanger spec end to end ──────────────────────────────────────────

class EngineEndToEndTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        cls.cache = synthetic_cache()
        cls.features_dir = os.path.join(cls.tmp, "features")
        build_features(cls.cache, cls.features_dir)
        cls.strategy = copy_zanger(cls.tmp)
        cls.db = os.path.join(cls.tmp, "trades.duckdb")
        cls.run_ids = run_spec.run(cls.strategy, db_path=cls.db, cache=cls.cache, features_dir=cls.features_dir)
        con = trades_db.connect(cls.db)
        cls.runs = con.execute("SELECT * FROM runs").df()
        cls.trades = con.execute("SELECT * FROM trades").df()
        con.close()

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp)

    def test_one_run_per_entry_clock_with_identity_fields(self):
        self.assertEqual(sorted(self.runs.entry_clock), ["next_open", "signal_close_strong"])
        with open(ZANGER_SPEC) as f:
            spec = json.load(f)
        row = self.runs.iloc[0]
        self.assertEqual(row.strategy, "zanger")
        self.assertEqual(row.schema_version, "1.0")
        self.assertEqual(row.spec_hash, trades_db.spec_hash(spec))
        self.assertEqual(json.loads(row.spec_json), spec)
        self.assertTrue(row.git_sha)
        self.assertIn("symbols, inputs sha256:", row.data_snapshot)

    def test_trades_are_written_and_dated_in_order(self):
        self.assertGreater(len(self.trades), 20)
        self.assertTrue((self.trades.entry_date >= self.trades.signal_date).all())
        closed = self.trades.dropna(subset=["exit_date"])
        self.assertTrue((closed.exit_date >= closed.entry_date).all())
        reasons = set("+".join(self.trades.exit_reason).split("+"))
        self.assertTrue(reasons <= {"exit_1:close_below_level", "exit_2:trail_ma", "partial_1", "time", "stop", "open"},
                        reasons)

    def test_rerun_gives_identical_trades(self):
        db2 = os.path.join(self.tmp, "again.duckdb")
        run_spec.run(self.strategy, db_path=db2, cache=self.cache, features_dir=self.features_dir)
        con = trades_db.connect(db2)
        again = con.execute("SELECT * FROM trades").df()
        snapshot = con.execute("SELECT data_snapshot FROM runs").fetchone()[0]
        con.close()
        key = ["strategy", "symbol", "signal_date", "entry_date"]
        pd.testing.assert_frame_equal(self.trades.drop(columns="run_id").sort_values(key).reset_index(drop=True),
                                      again.drop(columns="run_id").sort_values(key).reset_index(drop=True))
        self.assertEqual(snapshot, self.runs.data_snapshot.iloc[0])

    def test_stale_feature_store_stops_the_run(self):
        longer = {k: pd.concat([v, v.iloc[-1:].set_axis([v.index[-1] + pd.offsets.BDay()])])
                  for k, v in self.cache.items()}
        with self.assertRaisesRegex(SystemExit, "rebuild the feature store"):
            run_spec.run(self.strategy, db_path=os.path.join(self.tmp, "stale.duckdb"),
                         cache=longer, features_dir=self.features_dir)


if __name__ == "__main__":
    unittest.main()
