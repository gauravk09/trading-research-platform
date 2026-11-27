"""Self-tests for schema.json, the changelog, strategy ids, and that every spec compiles."""

import copy
import glob
import json
import os
import re
import sys
import unittest

import jsonschema

HERE = os.path.dirname(os.path.abspath(__file__))
STRATEGIES = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(STRATEGIES, "..", "src"))

from backtest import spec_compiler  # noqa: E402

SCHEMA = json.load(open(os.path.join(HERE, "schema.json")))
EXAMPLE = json.load(open(os.path.join(STRATEGIES, "zanger", "spec.json")))
VALIDATOR = jsonschema.Draft202012Validator(SCHEMA)


def errors(spec):
    return [e.message for e in VALIDATOR.iter_errors(spec)]


def spec_paths():
    """Every live strategy spec: strategies/<id>/spec.json, excluding _spec and _archive."""
    return sorted(p for p in glob.glob(os.path.join(STRATEGIES, "*", "spec.json"))
                  if not os.path.basename(os.path.dirname(p)).startswith("_"))


class StrategySchemaTests(unittest.TestCase):
    def setUp(self):
        self.spec = copy.deepcopy(EXAMPLE)
        self.source = self.spec["must_have"]["from_source"]
        self.house = self.spec["must_have"]["from_house"]
        self.external = self.spec["good_to_have"]["external_evaluations"]

    def test_schema_is_valid_json_schema(self):
        jsonschema.Draft202012Validator.check_schema(SCHEMA)

    def test_example_is_valid(self):
        self.assertEqual(errors(self.spec), [])

    def test_missing_entry_is_rejected(self):
        del self.source["entry"]
        self.assertTrue(errors(self.spec))

    def test_empty_exits_or_sources_are_rejected(self):
        self.source["exits"] = []
        self.assertTrue(errors(self.spec))
        self.spec = copy.deepcopy(EXAMPLE)
        self.spec["must_have"]["from_source"]["sources"] = []
        self.assertTrue(errors(self.spec))

    def test_source_rule_needs_a_quote(self):
        del self.source["stop_loss"]["quote"]
        self.assertTrue(errors(self.spec))

    def test_proxy_rule_does_not_need_a_quote(self):
        self.source["stop_loss"]["origin"] = "proxy"
        del self.source["stop_loss"]["quote"]
        self.assertEqual(errors(self.spec), [])

    def test_more_than_three_variants_is_rejected(self):
        variants = self.spec["good_to_have"]["variants"]
        variants.append(variants[0])
        self.assertTrue(errors(self.spec))

    def test_unknown_key_is_rejected(self):
        self.source["vibes"] = "strong"
        self.assertTrue(errors(self.spec))

    def test_prior_work_check_is_required(self):
        del self.house["prior_work_check"]
        self.assertTrue(errors(self.spec))

    def test_external_found_any_must_match_results(self):
        self.external["found_any"] = False
        self.assertTrue(errors(self.spec))
        self.external["results"] = []
        self.assertEqual(errors(self.spec), [])
        self.external["found_any"] = True
        self.assertTrue(errors(self.spec))

    def test_external_search_needs_queries(self):
        self.external["search_log"]["queries"] = []
        self.assertTrue(errors(self.spec))

    def test_free_text_id_is_rejected(self):
        self.house["id"] = "Zanger Breakout v2"
        self.assertTrue(errors(self.spec))


class VersionTests(unittest.TestCase):
    def test_schema_version_matches_newest_changelog_line(self):
        with open(os.path.join(HERE, "CHANGELOG.md")) as f:
            versions = re.findall(r"^\| (\d+\.\d+) \|", f.read(), flags=re.M)
        self.assertTrue(versions, "CHANGELOG.md has no version rows")
        self.assertEqual(SCHEMA["properties"]["schema_version"]["const"], versions[0])


class StrategyFolderTests(unittest.TestCase):
    def test_every_spec_is_valid(self):
        for path in spec_paths():
            with self.subTest(path=path), open(path) as f:
                self.assertEqual(errors(json.load(f)), [])

    def test_id_equals_folder_name_and_is_unique(self):
        ids = []
        for path in spec_paths():
            with open(path) as f:
                spec_id = json.load(f)["must_have"]["from_house"]["id"]
            self.assertEqual(spec_id, os.path.basename(os.path.dirname(path)), path)
            ids.append(spec_id)
        self.assertEqual(len(ids), len(set(ids)))
        self.assertIn("zanger", ids)

    def test_every_spec_compiles(self):
        """The compiler is the one vocabulary check: feature-store names only, no functions."""
        for path in spec_paths():
            with self.subTest(path=path):
                spec, spec_path = spec_compiler.load_spec(path)
                spec_compiler.compile_spec(spec, spec_path)


if __name__ == "__main__":
    unittest.main()
