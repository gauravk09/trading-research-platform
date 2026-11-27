"""spec_compiler: feature-store-only vocabulary, guards, determinism."""

import copy
import json
import os
import tempfile
import types
import unittest
from unittest.mock import patch

import numpy as np
import pandas as pd

from backtest import spec_compiler
from backtest.features import FEATURE_NAMES
from data_collection.paths import ROOT_DIR

ZANGER_DIR = os.path.join(ROOT_DIR, "strategies", "zanger")


def zanger_spec():
    with open(os.path.join(ZANGER_DIR, "spec.json")) as f:
        return json.load(f)


def compile_with(mutate):
    spec = zanger_spec()
    mutate(spec)
    return spec_compiler.compile_spec(spec, os.path.join(ZANGER_DIR, "spec.json"))


def set_trigger(expr):
    def mutate(spec):
        spec["must_have"]["from_source"]["entry"]["trigger"]["expr"] = expr
    return mutate


def load_module(code):
    module = types.ModuleType("generated")
    exec(code, module.__dict__)
    return module


class CompilerTests(unittest.TestCase):
    def test_committed_strategy_py_matches_its_spec(self):
        spec, path = spec_compiler.load_spec(ZANGER_DIR)
        with open(os.path.join(ZANGER_DIR, "strategy.py")) as f:
            committed = f.read()
        self.assertEqual(spec_compiler.compile_spec(spec, path), committed,
                         "strategy.py is stale or hand-edited: recompile from spec.json")

    def test_compiling_is_deterministic(self):
        spec, path = spec_compiler.load_spec(ZANGER_DIR)
        self.assertEqual(spec_compiler.compile_spec(spec, path),
                         spec_compiler.compile_spec(copy.deepcopy(spec), path))

    def test_generated_module_reads_only_cache_and_feature_store_columns(self):
        module = load_module(compile_with(lambda spec: None))
        allowed = set(spec_compiler.BAR_FIELDS) | set(FEATURE_NAMES)
        self.assertTrue(set(module.COLUMNS) <= allowed)
        self.assertNotIn("import", compile_with(lambda spec: None).split('"""', 2)[2])

    def test_functions_are_rejected(self):
        with self.assertRaisesRegex(spec_compiler.SpecError, "feature store"):
            compile_with(set_trigger("close > sma(close, 20)"))

    def test_unknown_name_is_rejected(self):
        with self.assertRaisesRegex(spec_compiler.SpecError, "unknown name 'magic_line'"):
            compile_with(set_trigger("magic_line > 1"))

    def test_vocabulary_comes_from_feature_names(self):
        with self.assertRaises(spec_compiler.SpecError):
            compile_with(set_trigger("brand_new_feature > 1"))
        with patch.object(spec_compiler, "FEATURE_NAMES", FEATURE_NAMES + ("brand_new_feature",)):
            self.assertIn('col("brand_new_feature")', compile_with(set_trigger("brand_new_feature > 1")))

    def test_negative_lag_is_rejected(self):
        with self.assertRaisesRegex(spec_compiler.SpecError, "future"):
            compile_with(set_trigger("close[-1] > close"))

    def test_delivery_needs_next_open(self):
        with self.assertRaisesRegex(spec_compiler.SpecError, "next_open"):
            compile_with(set_trigger("deliv_x20 > 2"))

    def test_level_exit_must_be_one_comparison(self):
        def mutate(spec):
            spec["must_have"]["from_source"]["exits"][0]["expr"] = "close < pivot and close < 5"
        with self.assertRaisesRegex(spec_compiler.SpecError, "ONE comparison"):
            compile_with(mutate)

    def test_exit_must_be_on_the_menu(self):
        def low_touch(spec):
            spec["must_have"]["from_source"]["exits"][0]["expr"] = "low <= pivot"
        def trail_pct(spec):
            spec["must_have"]["from_source"]["exits"][0] = {"type": "trail_pct", "text": "x", "value": 10,
                                                            "origin": "proxy"}
        with self.assertRaisesRegex(spec_compiler.SpecError, "not on the exit menu"):
            compile_with(low_touch)
        with self.assertRaisesRegex(spec_compiler.SpecError, "trail_pct"):
            compile_with(trail_pct)

    def test_id_must_equal_folder(self):
        spec = zanger_spec()
        with tempfile.TemporaryDirectory() as tmp:
            folder = os.path.join(tmp, "not_zanger")
            os.makedirs(folder)
            with open(os.path.join(folder, "spec.json"), "w") as f:
                json.dump(spec, f)
            with self.assertRaisesRegex(spec_compiler.SpecError, "folder name"):
                spec_compiler.load_spec(folder)


class GeneratedCodeTests(unittest.TestCase):
    """The generated code means what the spec says on real frames."""

    def setUp(self):
        dates = pd.bdate_range("2020-01-01", periods=6)
        close = pd.DataFrame({"A": [10.0, 11, 12, 11, 13, 9]}, index=dates)
        frames = {"close": close, "close_max20": close.cummax(), "sma20": close * 0 + 11.5}
        self.col = lambda name: frames[name]
        self.module = load_module(compile_with(lambda spec: None))

    def test_pivot_is_yesterdays_20d_closing_high(self):
        pivot = self.module.levels(self.col)["pivot"]["A"].tolist()
        self.assertTrue(np.isnan(pivot[0]))
        self.assertEqual(pivot[1:], [10.0, 11, 12, 12, 13])

    def test_exit_rules_freeze_levels_and_read_signals_live(self):
        rules = {r["id"]: r for r in self.module.exit_rules(self.col, entry=self.col("close"))}
        self.assertEqual(rules["exit_1:close_below_level"]["kind"], "close_exit")
        self.assertEqual(rules["partial_1"]["fraction"], 0.25)
        when = rules["exit_2:trail_ma"]["when"]["A"].tolist()
        self.assertEqual(when, [True, True, False, True, False, True])


if __name__ == "__main__":
    unittest.main()
