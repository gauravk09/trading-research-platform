import json
import os
import tempfile
import unittest
from pathlib import Path

from experiment_tracking import fingerprint, log_run, main, normalize_manifest


class ExperimentTrackingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.spec = root / "SPEC.md"
        self.data = root / "dataset.csv"
        self.spec.write_text("fixed spec\n", encoding="utf-8")
        self.data.write_text("date,close\n2025-01-01,100\n", encoding="utf-8")
        self.manifest = {"run_name": "golden", "stage": "S4", "strategy": "demo",
                         "family": "demo_family", "code_entrypoint": "src/demo.py",
                         "spec_path": str(self.spec), "dataset_paths": [str(self.data)],
                         "parameters": {"costs": "10bps", "entry_clock": "D+1 open",
                                        "eras": "A,B", "control_type": "same-date", "seed": 7},
                         "metrics": {"return": 0.12, "trades": 10}, "status": "completed",
                         "verdict": "PASS", "artifact_paths": ["research/demo/report.md"]}

    def tearDown(self):
        self.temp.cleanup()

    def test_fingerprint_is_deterministic(self):
        self.assertEqual(fingerprint(self.data, root=self.temp.name), fingerprint(self.data, root=self.temp.name))

    def test_required_metadata_is_validated(self):
        broken = dict(self.manifest)
        broken["parameters"] = {"costs": "10bps"}
        with self.assertRaisesRegex(ValueError, "entry_clock"):
            normalize_manifest(broken)

    def test_dry_run_creates_no_database(self):
        manifest_path = Path(self.temp.name) / "manifest.json"
        manifest_path.write_text(json.dumps(self.manifest), encoding="utf-8")
        store = Path(self.temp.name) / "mlflow"
        main([str(manifest_path), "--store-dir", str(store), "--dry-run"])
        self.assertFalse(store.exists())

    def test_temp_sqlite_run_is_searchable_with_metadata_and_manifest(self):
        store = Path(self.temp.name) / "mlflow"
        result = log_run(self.manifest, store, "tests")
        from mlflow.tracking import MlflowClient
        client = MlflowClient(tracking_uri=result["tracking_uri"])
        runs = client.search_runs([result["experiment_id"]], filter_string="tags.strategy = 'demo'")
        self.assertEqual(len(runs), 1)
        run = runs[0]
        self.assertEqual(run.data.params["entry_clock"], "D+1 open")
        self.assertEqual(run.data.metrics["return"], 0.12)
        self.assertEqual(run.data.tags["verdict"], "PASS")
        self.assertEqual(client.list_artifacts(run.info.run_id)[0].path, "artifact_manifest.json")


if __name__ == "__main__":
    unittest.main()
