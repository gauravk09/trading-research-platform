import sys
from pathlib import Path

import pytest

# Allow `from research.regime import ...` regardless of the cwd pytest is
# invoked from, without modifying anything outside research/regime/.
_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))


def pytest_addoption(parser):
    parser.addoption("--runslow", action="store_true", default=False,
                      help="also run tests marked @pytest.mark.slow (e.g. the power-curve report)")


def pytest_configure(config):
    config.addinivalue_line("markers", "slow: slow test, skipped by default (use --runslow)")


def pytest_collection_modifyitems(config, items):
    if config.getoption("--runslow"):
        return
    skip_slow = pytest.mark.skip(reason="slow; pass --runslow to run")
    for item in items:
        if "slow" in item.keywords:
            item.add_marker(skip_slow)
