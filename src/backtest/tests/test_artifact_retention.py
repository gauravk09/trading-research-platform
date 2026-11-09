import os
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path

from backtest.artifact_retention import scan
from backtest.artifact_retention import git_tracked_paths


NOW = 1_800_000_000
POLICY = {"policy": "inventory_only_no_deletion", "areas": [
    {"path": "logs", "glob": "**/*.log", "category": "generated_reports", "action": "compress_candidate",
     "min_age_days": 30, "reason": "old logs"},
    {"path": "data/parquet", "category": "canonical_keep", "action": "keep", "reason": "canonical"},
]}


class ArtifactRetentionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        (root / "logs").mkdir()
        (root / "data" / "parquet").mkdir(parents=True)
        self.tracked = root / "logs" / "tracked.log"
        self.old = root / "logs" / "old.log"
        self.canonical = root / "data" / "parquet" / "input.parquet"
        self.tracked.write_bytes(b"t" * 100)
        self.old.write_bytes(b"o" * 300)
        self.canonical.write_bytes(b"c" * 500)
        for path in (self.tracked, self.old):
            os.utime(path, (NOW - 40 * 86400, NOW - 40 * 86400))

    def tearDown(self):
        self.temp.cleanup()

    def test_tracked_files_are_never_candidates(self):
        report = scan(POLICY, self.temp.name, tracked_paths={Path("logs/tracked.log")}, now=NOW)
        paths = [item["path"] for item in report["top_candidates"]]
        self.assertEqual(paths, ["logs/old.log"])
        self.assertEqual(report["areas"][0]["tracked_files"], 1)

    def test_age_size_and_action_aggregate(self):
        report = scan(POLICY, self.temp.name, tracked_paths=set(), now=NOW)
        logs = report["areas"][0]
        self.assertEqual((logs["files"], logs["bytes"], logs["potential_reclaim_bytes"]), (2, 400, 400))
        self.assertEqual(report["top_candidates"][0]["action"], "compress_candidate")
        self.assertEqual(report["areas"][1]["action"], "keep")

    def test_scan_is_deterministic_and_does_not_write(self):
        before = sorted(path.relative_to(self.temp.name) for path in Path(self.temp.name).rglob("*"))
        one = scan(POLICY, self.temp.name, tracked_paths=set(), now=NOW)
        two = scan(POLICY, self.temp.name, tracked_paths=set(), now=NOW)
        after = sorted(path.relative_to(self.temp.name) for path in Path(self.temp.name).rglob("*"))
        self.assertEqual(one, two)
        self.assertEqual(before, after)

    def test_git_failure_refuses_to_build_candidates(self):
        with patch("backtest.artifact_retention.subprocess.check_output", side_effect=OSError("git unavailable")):
            with self.assertRaisesRegex(RuntimeError, "refusing"):
                git_tracked_paths(self.temp.name)


if __name__ == "__main__":
    unittest.main()
