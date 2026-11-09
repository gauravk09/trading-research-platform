import ast
import unittest
from pathlib import Path

SRC = Path(__file__).resolve().parents[2]
PRODUCTION = ["data_collection", "preprocessing", "indicators", "filters", "risk",
              "scanners", "execution", "evaluation", "pipeline"]


def imports_experimentation(path):
    for node in ast.walk(ast.parse(path.read_text())):
        names = []
        if isinstance(node, ast.ImportFrom) and node.module:
            names = [node.module]
        elif isinstance(node, ast.Import):
            names = [alias.name for alias in node.names]
        if any(name.split(".")[0] == "experimentation" for name in names):
            return True
    return False


class ExperimentationIsolationTests(unittest.TestCase):
    def test_no_production_layer_imports_experimentation(self):
        offenders = [str(p.relative_to(SRC)) for layer in PRODUCTION
                     for p in (SRC / layer).rglob("*.py") if imports_experimentation(p)]
        self.assertEqual(offenders, [])


if __name__ == "__main__":
    unittest.main()
