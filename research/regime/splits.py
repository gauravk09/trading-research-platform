"""Walk-forward, expanding-window splitter with embargo + purge.

Test years come from a window config (see data.WINDOW_CONFIGS; "default" is
2018-2024, matching the module-level DEV_START/TEST_YEARS constants kept
below for backward compatibility). Train = all rows from the config's
dev_start up to the test-year start, expanding fold to fold, refit every fold.

Embargo/purge: a row's target uses future prices out to `embargo` rows ahead.
If that row is within `embargo` rows of the test-year start, its target
window overlaps or reaches into the test period, so it is dropped from
train. For a simple h-row-ahead target this single rule implements BOTH the
"leave a gap of the horizon length" embargo and the "purge any train row
whose target window reaches into the test period" purge — they coincide here
because both are governed by the same window length. Callers that fit on a
target with a longer window than their scoring horizon (e.g. B0 fits on the
60-row truth_regime label even when horizon h=5) must pass embargo=max(h, 60)
to stay safe for that target too.
"""
from __future__ import annotations

import pandas as pd

from . import data as _data

DEV_START = _data.WINDOW_CONFIGS["default"]["dev_start"]
TEST_YEARS = tuple(range(
    _data.WINDOW_CONFIGS["default"]["first_test_year"],
    _data.WINDOW_CONFIGS["default"]["last_test_year"] + 1,
))


def get_walkforward_folds(dates, embargo: int, config=None):
    """`config` is a window-config name or dict (see data.get_window_config);
    defaults to "default" (2015 dev_start, 2018-2024 test years).
    """
    cfg = _data.get_window_config(config or "default")
    dev_start = cfg["dev_start"]
    test_years = range(cfg["first_test_year"], cfg["last_test_year"] + 1)

    dates = pd.DatetimeIndex(dates).sort_values()
    pos = pd.Series(range(len(dates)), index=dates)

    folds = []
    for year in test_years:
        test_start = pd.Timestamp(f"{year}-01-01")
        test_end = pd.Timestamp(f"{year}-12-31")
        test_idx = dates[(dates >= test_start) & (dates <= test_end)]
        if len(test_idx) == 0:
            continue
        first_test_pos = pos[test_idx[0]]

        train_idx = dates[(dates >= dev_start) & (dates < test_start)]
        train_pos = pos[train_idx]
        keep = (train_pos + embargo) < first_test_pos
        train_idx = train_idx[keep.to_numpy()]

        folds.append({"year": year, "train": train_idx, "test": test_idx})
    return folds
