"""Tests for the spec pipeline: JSON -> strategy.py -> backtest -> Excel."""

import copy
import json
import os
import tempfile
import types
import unittest

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from backtest import spec_backtest, spec_compiler
from backtest.spec_simulator import simulate_stock
from data_collection.paths import ROOT_DIR

EXAMPLE = os.path.join(ROOT_DIR, "strategies", "_spec", "examples", "dan_zanger_breakout.json")
DAILY_SCHEMA = pa.schema([("date", pa.timestamp("ns", tz="Asia/Kolkata")), ("open", pa.float32()),
                          ("high", pa.float32()), ("low", pa.float32()), ("close", pa.float32()),
                          ("volume", pa.int64()), ("symbol", pa.string())])


def example_spec():
    with open(EXAMPLE) as f:
        return json.load(f)


def write_spec(spec, folder):
    path = os.path.join(folder, "spec.json")
    with open(path, "w") as f:
        json.dump(spec, f)
    return path


def write_fake_market(folder, n_stocks=12, start="2016-01-01", end="2019-12-31", seed=0):
    """Random-walk stocks in the repo's exact parquet schema (IST midnight timestamps)."""
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range(start, end, tz="Asia/Kolkata")
    daily_dir = os.path.join(folder, "daily")
    os.makedirs(daily_dir)
    for i in range(n_stocks):
        close = 200 * np.exp(np.cumsum(rng.normal(0.0008, 0.02, len(dates))))
        open_ = close * (1 + rng.normal(0, 0.005, len(dates)))
        high = np.maximum(open_, close) * (1 + np.abs(rng.normal(0, 0.01, len(dates))))
        low = np.minimum(open_, close) * (1 - np.abs(rng.normal(0, 0.01, len(dates))))
        volume = rng.lognormal(14, 0.6, len(dates)).astype("int64")
        df = pd.DataFrame({"date": dates, "open": open_, "high": high, "low": low, "close": close,
                           "volume": volume, "symbol": f"STK{i:02d}"})
        pq.write_table(pa.Table.from_pandas(df, schema=DAILY_SCHEMA, preserve_index=False),
                       os.path.join(daily_dir, f"STK{i:02d}.parquet"))
    features_dir = os.path.join(folder, "features")
    os.makedirs(features_dir)
    naive = dates.tz_localize(None)
    pd.DataFrame(80.0, index=naive, columns=[f"STK{i:02d}" for i in range(n_stocks)]).to_parquet(
        os.path.join(features_dir, "rs.parquet"))
    return os.path.join(daily_dir, "*.parquet"), features_dir


def simple_breakout_spec():
    """The example, loosened so random data produces trades."""
    spec = example_spec()
    source = spec["must_have"]["from_source"]
    source["entry"]["setup_conditions"] = [{
        "id": "above_50dma", "text": "Above the 50-DMA", "expr": "close > sma(close,50)",
        "origin": "proxy", "known_at": "close"}]
    spec["must_have"]["from_house"]["universe"]["min_turnover_cr"] = 0
    return spec


class CompilerTests(unittest.TestCase):
    def compile_with(self, mutate):
        spec = example_spec()
        mutate(spec)
        return spec_compiler.compile_spec(spec, EXAMPLE)

    def test_example_compiles_to_an_importable_module(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = spec_compiler.write_strategy(EXAMPLE, out_dir=tmp)
            module = spec_backtest.load_strategy(path)
        self.assertEqual(module.SPEC_ID, "dan_zanger_breakout")
        self.assertEqual(module.ENTRY_CLOCKS, ["signal_close_strong", "next_open"])
        self.assertEqual(module.FEATURES_USED, ["rs"])

    def test_unknown_identifier_is_rejected(self):
        def mutate(spec):
            spec["must_have"]["from_source"]["entry"]["trigger"]["expr"] = "magic_line > 1"
        with self.assertRaisesRegex(spec_compiler.SpecError, "unknown identifier 'magic_line'"):
            self.compile_with(mutate)

    def test_negative_lag_is_rejected(self):
        def mutate(spec):
            spec["must_have"]["from_source"]["entry"]["trigger"]["expr"] = "close[-1] > close"
        with self.assertRaisesRegex(spec_compiler.SpecError, "future"):
            self.compile_with(mutate)

    def test_delivery_needs_next_open(self):
        def mutate(spec):
            spec["must_have"]["from_source"]["entry"]["trigger"]["expr"] = "deliv_x20 > 2"
        with self.assertRaisesRegex(spec_compiler.SpecError, "next_open"):
            self.compile_with(mutate)

    def test_level_exit_must_be_one_comparison(self):
        def mutate(spec):
            spec["must_have"]["from_source"]["exits"][0]["expr"] = "close < pivot and close < 5"
        with self.assertRaisesRegex(spec_compiler.SpecError, "ONE comparison"):
            self.compile_with(mutate)

    def test_fundamentals_are_reserved(self):
        def mutate(spec):
            spec["must_have"]["from_source"]["entry"]["trigger"]["expr"] = "fin.pat_cr > 0"
        with self.assertRaisesRegex(spec_compiler.SpecError, "reserved"):
            self.compile_with(mutate)

    def test_invalid_json_is_rejected_before_compiling(self):
        spec = example_spec()
        del spec["must_have"]["from_source"]["exits"]
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(spec_compiler.SpecError, "exits"):
                spec_compiler.load_spec(write_spec(spec, tmp))


def bars(rows):
    """rows of (open, high, low, close) -> dict of arrays."""
    a = np.array(rows, dtype=float)
    return {"open": a[:, 0], "high": a[:, 1], "low": a[:, 2], "close": a[:, 3]}


def run_one(rows, signal_bars, stop, rules, clock="next_open", direction="long", cost=0.0):
    b = bars(rows)
    n = len(b["close"])
    signal = np.zeros(n, dtype=bool)
    signal[signal_bars] = True
    dates = pd.bdate_range("2020-01-01", periods=n)
    stop_arr = np.full(n, stop) if stop is not None else None
    return simulate_stock("X", dates, b, signal, stop_arr, rules, clock, direction, cost, dedup_bars=0)


class SimulatorTests(unittest.TestCase):
    def test_stop_gap_fills_at_the_open(self):
        rows = [(100, 101, 99, 100), (100, 102, 99, 101), (90, 92, 88, 91)]
        trades, _ = run_one(rows, [0], stop=95, rules=[])
        self.assertEqual(trades[0]["exit_price"], 90)          # gapped below 95 -> open
        self.assertEqual(trades[0]["exit_reason"], "stop")

    def test_stop_inside_the_bar_fills_at_the_stop(self):
        rows = [(100, 101, 99, 100), (100, 102, 99, 101), (98, 99, 94, 96)]
        trades, _ = run_one(rows, [0], stop=95, rules=[])
        self.assertEqual(trades[0]["exit_price"], 95)

    def test_partial_then_close_exit_fills_next_open(self):
        n = 5
        level = np.full(n, 110.0)
        exit_level = np.full(n, 100.0)
        rules = [
            {"id": "exit_1", "kind": "close_level", "live": np.array([100, 101, 112, 99, 98.0]),
             "op": "<", "level": exit_level, "fraction": 1.0},
            {"id": "partial_1", "kind": "touch_level", "live": None, "op": ">=", "level": level, "fraction": 0.25},
        ]
        rows = [(100, 101, 99, 100), (100, 102, 99, 101), (105, 113, 104, 112), (105, 106, 98, 99), (97, 98, 96, 98)]
        trades, _ = run_one(rows, [0], stop=None, rules=rules)
        t = trades[0]
        self.assertEqual(t["exit_reason"], "partial_1+exit_1")
        # entry 100 (bar 1 open); 25% at 110, 75% at bar 4 open (97) after bar 3 closed below 100
        self.assertAlmostEqual(t["raw_ret"], 0.25 * 0.10 + 0.75 * (97 / 100 - 1))

    def test_time_exit_at_close(self):
        rows = [(100, 101, 99, 100)] + [(100, 101, 99, 100 + i) for i in range(1, 6)]
        rules = [{"id": "time", "kind": "time", "value": 3, "fraction": 1.0}]
        trades, _ = run_one(rows, [0], stop=None, rules=rules)
        self.assertEqual(trades[0]["days"], 3)
        self.assertEqual(trades[0]["exit_price"], 104)

    def test_signal_close_entry_uses_signal_close(self):
        rows = [(100, 101, 99, 100), (100, 102, 99, 101), (101, 103, 100, 102)]
        rules = [{"id": "time", "kind": "time", "value": 1, "fraction": 1.0}]
        trades, _ = run_one(rows, [0], stop=None, rules=rules, clock="signal_close")
        self.assertEqual(trades[0]["entry_price"], 100)
        self.assertEqual(trades[0]["exit_price"], 101)

    def test_short_stop_is_above(self):
        rows = [(100, 101, 99, 100), (100, 101, 98, 99), (103, 107, 102, 106)]
        trades, _ = run_one(rows, [0], stop=105, rules=[], direction="short")
        self.assertEqual(trades[0]["exit_price"], 105)
        self.assertAlmostEqual(trades[0]["raw_ret"], -(105 / 100 - 1))

    def test_stop_through_entry_is_skipped(self):
        rows = [(100, 101, 99, 100), (90, 92, 88, 91)]
        trades, skipped = run_one(rows, [0], stop=95, rules=[])
        self.assertEqual((trades, skipped), ([], 1))

    def test_costs_are_charged_both_sides(self):
        rows = [(100, 101, 99, 100)] * 4
        rules = [{"id": "time", "kind": "time", "value": 1, "fraction": 1.0}]
        trades, _ = run_one(rows, [0], stop=None, rules=rules, cost=0.2)
        self.assertAlmostEqual(trades[0]["raw_ret"], -0.004)


class LookAheadTests(unittest.TestCase):
    def test_leaky_strategy_is_caught(self):
        leaky = types.SimpleNamespace(entry_conditions=lambda d: {"peek": d["close"].shift(-1) > d["close"]})
        with tempfile.TemporaryDirectory() as tmp:
            data, features = write_fake_market(tmp, n_stocks=3)
            con = spec_backtest.connect()
            src = spec_backtest.reader(data)
            d = spec_backtest.load_batch(con, src, ["STK00", "STK01"], "2016-01-01", "2019-12-31", features, None)
        with self.assertRaises(spec_backtest.LookAheadError):
            spec_backtest.check_lookahead(leaky, d)

    def test_connection_pins_ist_so_dates_do_not_shift(self):
        # Stored timestamps are midnight IST; on a UTC session they would cast to the previous day.
        with tempfile.TemporaryDirectory() as tmp:
            data, features = write_fake_market(tmp, n_stocks=1, start="2016-01-04", end="2016-01-08")
            con = spec_backtest.connect()
            timezone = con.execute("SELECT current_setting('TimeZone')").fetchone()[0]
            d = spec_backtest.load_batch(con, spec_backtest.reader(data), ["STK00"],
                                         "2016-01-01", "2016-01-31", features, None)
        self.assertEqual(timezone, "Asia/Kolkata")
        self.assertEqual(d["close"].index[0], pd.Timestamp("2016-01-04"))


class EndToEndTests(unittest.TestCase):
    def test_spec_to_excel(self):
        with tempfile.TemporaryDirectory() as tmp:
            data, features = write_fake_market(tmp)
            strategy_dir = os.path.join(tmp, "strategy")
            os.makedirs(strategy_dir)
            py = spec_compiler.write_strategy(write_spec(simple_breakout_spec(), strategy_dir), out_dir=strategy_dir)
            path, trades = spec_backtest.run(py, data=data, features_dir=features,
                                             market_path=os.path.join(tmp, "none.parquet"),
                                             start="2016-01-01", end="2019-12-31", batch=5,
                                             min_rows=100, out_root=os.path.join(tmp, "out"))
            sheets = pd.read_excel(path, sheet_name=None)
        self.assertGreater(len(trades), 0)
        self.assertEqual(set(sheets), {"Summary", "Eras", "Trades", "Per_stock", "Conditions", "Run", "Spec"})
        self.assertEqual(list(sheets["Trades"].columns[:8]),
                         ["asset", "side", "entry", "exit", "days", "raw_ret", "mkt_ret", "pnl"])
        self.assertEqual(set(sheets["Summary"]["clock"]), {"signal_close_strong", "next_open"})
        run = dict(zip(sheets["Run"]["item"], sheets["Run"]["value"]))
        self.assertTrue(run["lookahead_check"].startswith("passed"))
        self.assertTrue((trades["entry"] >= trades["signal"]).all())
        self.assertTrue((trades["exit"] >= trades["entry"]).all())


if __name__ == "__main__":
    unittest.main()
