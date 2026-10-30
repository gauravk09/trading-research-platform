import os
import sys
import tempfile
import unittest
from pathlib import Path

from backtest.canonical_runner import replay, run_spec, validate_spec


class CanonicalRunnerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.factory_spec = root / "SPEC.md"
        self.dataset = root / "data.csv"
        self.factory_spec.write_text("pre-registered\n", encoding="utf-8")
        self.dataset.write_text("date,close\n2025-01-01,100\n", encoding="utf-8")
        self.spec = {"id": "fixture_s4", "stage": "S4", "strategy": "fixture", "family": "test",
                     "module": "src.backtest.studies.canonical_test_fixture", "spec_path": str(self.factory_spec),
                     "dataset_paths": [str(self.dataset)], "parameters": {"costs": "10bps",
                     "entry_clock": "D+1 open", "eras": "A,B", "control_type": "same-date",
                     "survivorship": "fixture"},
                     "success_bars": {"lift": ">0"}, "artifact_paths": []}

    def tearDown(self):
        self.temp.cleanup()

    def test_validation_does_not_import_fixture(self):
        sys.modules.pop("src.backtest.studies.canonical_test_fixture", None)
        validate_spec(self.spec)
        self.assertNotIn("src.backtest.studies.canonical_test_fixture", sys.modules)

    def test_boundary_guard_rejects_noncanonical_s4_examples(self):
        outside = {**self.spec, "module": "research.machine.evolve"}
        with self.assertRaisesRegex(ValueError, "src.backtest.studies"):
            validate_spec(outside)
        with self.assertRaisesRegex(ValueError, "S4"):
            validate_spec({**self.spec, "stage": "S3"})

    def test_incomplete_result_is_not_persisted_or_logged(self):
        bad = {**self.spec, "id": "bad", "fixture_incomplete": True}
        out = Path(self.temp.name) / "output"
        with self.assertRaisesRegex(ValueError, "incomplete"):
            run_spec(bad, out, Path(self.temp.name) / "mlflow")
        self.assertFalse((out / "bad").exists())

    def test_spec_without_survivorship_header_is_rejected(self):
        params = {k: v for k, v in self.spec["parameters"].items() if k != "survivorship"}
        with self.assertRaisesRegex(ValueError, "survivorship"):
            validate_spec({**self.spec, "parameters": params})

    def test_pass_requires_attribution_or_explicit_na(self):
        import src.backtest.studies.canonical_test_fixture as fixture
        original = fixture.run
        try:
            def with_attribution(value):
                def run(spec):
                    result = original(spec)
                    result["checks"]["attribution"] = value
                    return result
                return run
            fixture.run = with_attribution("failed")
            with self.assertRaisesRegex(ValueError, "attribution"):
                run_spec(self.spec, Path(self.temp.name) / "out_attr",
                         Path(self.temp.name) / "mlflow_attr")
            fixture.run = with_attribution("N/A (no cross-section)")
            run_spec(self.spec, Path(self.temp.name) / "out_attr_na",
                     Path(self.temp.name) / "mlflow_attr_na")
        finally:
            fixture.run = original

    def test_replay_reproduces_persisted_metrics(self):
        out = Path(self.temp.name) / "out_replay"
        first = run_spec(self.spec, out, Path(self.temp.name) / "mlflow_replay")
        check = replay(first["result_path"], out, Path(self.temp.name) / "mlflow_replay2")
        self.assertEqual(check["r2"], "PASS", check)
        self.assertEqual(check["diffs"], {})

    def test_pass_cannot_override_failed_control(self):
        import src.backtest.studies.canonical_test_fixture as fixture
        original = fixture.run
        try:
            def failed(spec):
                result = original(spec)
                result["checks"]["same_date_control"] = "failed"
                return result
            fixture.run = failed
            with self.assertRaisesRegex(ValueError, "passed same-date"):
                run_spec(self.spec, Path(self.temp.name) / "out",
                         Path(self.temp.name) / "mlflow_failed")
        finally:
            fixture.run = original

    def test_complete_run_persists_and_indexes(self):
        out, store = Path(self.temp.name) / "output", Path(self.temp.name) / "mlflow"
        result = run_spec(self.spec, out, store)
        self.assertTrue(Path(result["result_path"]).is_file())
        self.assertRegex(Path(result["result_path"]).name, r"^[0-9a-f]{16}\.json$")
        from mlflow.tracking import MlflowClient
        client = MlflowClient(tracking_uri=result["tracking"]["tracking_uri"])
        runs = client.search_runs([result["tracking"]["experiment_id"]], filter_string="tags.strategy = 'fixture'")
        self.assertEqual(len(runs), 1)
        self.assertEqual(runs[0].data.tags["stage"], "S4")


if __name__ == "__main__":
    unittest.main()
