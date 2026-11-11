"""Self-tests for strategy.schema.json: the example passes, incomplete specs fail."""

import copy
import json
import os
import unittest

import jsonschema

HERE = os.path.dirname(os.path.abspath(__file__))
SCHEMA = json.load(open(os.path.join(HERE, "strategy.schema.json")))
EXAMPLE = json.load(open(os.path.join(HERE, "examples", "dan_zanger_breakout.json")))
VALIDATOR = jsonschema.Draft202012Validator(SCHEMA)


def errors(spec):
    return [e.message for e in VALIDATOR.iter_errors(spec)]


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


if __name__ == "__main__":
    unittest.main()
