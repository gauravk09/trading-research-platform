"""simulator + trades_db + run_spec: spec -> shared engine -> output/trades.duckdb."""

import datetime
import json
import os
import shutil
import tempfile
import types
import unittest
from unittest.mock import patch

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from backtest import features, run_spec, simulator, trades_db
from data_collection.paths import ROOT_DIR

ZANGER_SPEC = os.path.join(ROOT_DIR, "strategies", "zanger", "spec.json")
NO_DAILY = "/nonexistent/*.parquet"

# The contract in .claude/skills/trades-db/SKILL.md, column by column.
CONTRACT = {
    "runs": [("run_id", "VARCHAR"), ("strategy", "VARCHAR"), ("schema_version", "VARCHAR"),
             ("spec_hash", "VARCHAR"), ("spec_json", "JSON"), ("git_sha", "VARCHAR"), ("data_snapshot", "DATE"),
             ("db_version", "INTEGER"), ("run_at", "TIMESTAMP WITH TIME ZONE")],
    "trades": [("run_id", "VARCHAR"), ("strategy", "VARCHAR"), ("symbol", "VARCHAR"), ("side", "VARCHAR"),
               ("entry_date", "DATE"), ("entry_px", "DOUBLE"), ("exit_date", "DATE"), ("exit_px", "DOUBLE"),
               ("exit_reason", "VARCHAR"), ("r", "DOUBLE")],
}


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
        self.assertEqual((t.side, t.entry_px, t.exit_px, t.exit_reason), ("long", 100.0, 103.0, "time"))
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

    def test_stock_that_stops_trading_exits_as_delist_at_its_last_close(self):
        rows = self.rows[:3] + [(np.nan,) * 4] * 3
        module, col, signal = tiny(rows, [0], time_bars=10)
        t = simulator.simulate(module, col, "next_open", signal=signal).iloc[0]
        self.assertEqual((t.exit_reason, t.exit_px), ("delist", 102.0))
        self.assertAlmostEqual(t.r, (102 - 100) / 10)

    def test_signal_close_enters_at_the_signal_close(self):
        module, col, signal = tiny(self.rows, [1], time_bars=1)
        t = simulator.simulate(module, col, "signal_close", signal=signal).iloc[0]
        self.assertEqual((t.entry_px, t.exit_px, t.entry_date), (101.0, 102.0, t.signal_date))


# ── the trades-db contract ───────────────────────────────────────────────────

class TradesDbTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.db = os.path.join(self.tmp, "trades.duckdb")

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def test_tables_match_the_contract(self):
        con = trades_db.connect(self.db)
        for table, columns in CONTRACT.items():
            got = [(r[0], r[1]) for r in con.execute(f"DESCRIBE {table}").fetchall()]
            self.assertEqual(got, columns, table)

    def test_a_failed_write_leaves_nothing(self):
        con = trades_db.connect(self.db)
        spec = {"schema_version": "1.0"}
        bad = pd.DataFrame([{"symbol": "X", "side": "long", "entry_date": datetime.date(2020, 1, 1),
                             "entry_px": None, "exit_date": None, "exit_px": None, "exit_reason": "open", "r": None}])
        with self.assertRaises(Exception):                       # entry_px NOT NULL
            trades_db.write_run(con, "x", spec, "sha", datetime.date(2020, 1, 1), bad)
        self.assertEqual(con.execute("SELECT count(*) FROM runs").fetchone()[0], 0)

    def test_unknown_exit_reason_is_rejected(self):
        con = trades_db.connect(self.db)
        bad = pd.DataFrame([{"symbol": "X", "side": "long", "entry_date": datetime.date(2020, 1, 1),
                             "entry_px": 1.0, "exit_date": None, "exit_px": None, "exit_reason": "magic", "r": None}])
        with self.assertRaisesRegex(ValueError, "exit_reason"):
            trades_db.write_run(con, "x", {"schema_version": "1.0"}, "sha", datetime.date(2020, 1, 1), bad)


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
        cls.run_ids = cls.run_once(cls.db)
        con = trades_db.connect(cls.db, read_only=True)
        cls.runs = con.execute("SELECT * FROM runs").df()
        cls.trades = con.execute("SELECT * FROM trades").df()
        con.close()

    @classmethod
    def run_once(cls, db, cache=None, daily_glob=NO_DAILY):
        return run_spec.run(cls.strategy, db_path=db, cache=cache if cache is not None else cls.cache,
                            features_dir=cls.features_dir, daily_glob=daily_glob)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp)

    def test_run_row_carries_the_identity_fields(self):
        with open(ZANGER_SPEC) as f:
            spec = json.load(f)
        strategy_runs = self.runs[self.runs.strategy == "zanger"]
        self.assertEqual(len(strategy_runs), 1)
        row = strategy_runs.iloc[0]
        self.assertEqual(row.schema_version, "1.0")
        self.assertEqual(row.spec_hash, trades_db.spec_hash(spec))
        self.assertEqual(json.loads(row.spec_json), spec)
        self.assertEqual(row.db_version, trades_db.DB_VERSION)
        self.assertTrue(row.git_sha)
        self.assertEqual(pd.Timestamp(row.data_snapshot).date(), datetime.date(2021, 9, 30))

    def test_the_strategy_run_has_a_same_date_control_run(self):
        self.assertEqual(sorted(self.runs.strategy), ["zanger", "zanger__control"])
        self.assertEqual(self.runs.spec_hash.nunique(), 1)
        ids = self.runs.set_index("strategy").run_id
        real = self.trades[self.trades.run_id == ids["zanger"]]
        ctrl = self.trades[self.trades.run_id == ids["zanger__control"]]
        self.assertGreater(len(ctrl), 0)
        self.assertLessEqual(len(ctrl), len(real))
        self.assertTrue(set(ctrl.entry_date) <= set(real.entry_date))

    def test_trades_follow_the_contract(self):
        mine = self.trades[self.trades.strategy == "zanger"]
        self.assertGreater(len(mine), 0)
        self.assertTrue((mine.side == "long").all())
        self.assertTrue(set(mine.exit_reason) <= set(trades_db.EXIT_REASONS))
        closed = mine.dropna(subset=["exit_date"])
        self.assertTrue((closed.exit_date >= closed.entry_date).all())

    def test_rerun_gives_identical_trades(self):
        db2 = os.path.join(self.tmp, "again.duckdb")
        self.run_once(db2)
        con = trades_db.connect(db2, read_only=True)
        again = con.execute("SELECT * FROM trades").df()
        con.close()
        key = ["strategy", "symbol", "entry_date"]
        pd.testing.assert_frame_equal(self.trades.drop(columns="run_id").sort_values(key).reset_index(drop=True),
                                      again.drop(columns="run_id").sort_values(key).reset_index(drop=True))

    def test_stale_feature_store_stops_the_run(self):
        longer = {k: pd.concat([v, v.iloc[-1:].set_axis([v.index[-1] + pd.offsets.BDay()])])
                  for k, v in self.cache.items()}
        with self.assertRaisesRegex(SystemExit, "rebuild the feature store"):
            self.run_once(os.path.join(self.tmp, "stale.duckdb"), cache=longer)

    def test_cache_older_than_daily_parquet_stops_the_run(self):
        daily = os.path.join(self.tmp, "daily")
        os.makedirs(daily)
        newer = pd.DataFrame({"date": pd.to_datetime(["2021-10-04"]).tz_localize("Asia/Kolkata"),
                              "close": [1.0], "symbol": ["STK00"]})
        pq.write_table(pa.Table.from_pandas(newer, preserve_index=False), os.path.join(daily, "STK00.parquet"))
        with self.assertRaisesRegex(SystemExit, "rebuild the cache"):
            self.run_once(os.path.join(self.tmp, "old_cache.duckdb"), daily_glob=os.path.join(daily, "*.parquet"))


if __name__ == "__main__":
    unittest.main()
