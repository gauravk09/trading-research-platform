"""Load the Nifty 500 close series and enforce the lockbox boundary.

Lockbox rule (spec Section 5.2 / user prompt): no date >= LOCKBOX_START may be
used for fitting or scoring unless the caller explicitly passes
open_lockbox=True to `assert_no_lockbox`. Every other module that touches
dates for fitting/scoring routes through this gate.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

INDEX_CSV = str(Path(__file__).resolve().parents[2] / "data/raw/index_history_long/nifty500_daily.csv")

# Pre-2015 rows exist only to warm up rolling windows (e.g. the 250-row
# volatility lookback needs history before 2015-01-01 to be non-NaN on day 1).
WARMUP_START = pd.Timestamp("2013-01-01")
DEV_START = pd.Timestamp("2015-01-01")
DEV_END = pd.Timestamp("2024-12-31")
LOCKBOX_START = pd.Timestamp("2025-01-01")  # fixed in every window config -- see WINDOW_CONFIGS

# Walk-forward window configs (spec-review item G2): everything that
# controls which years get fit vs scored lives here, in one dict per named
# config, so switching to the long history is a config change, not a code
# change. `default` is the config every existing call uses implicitly.
# `long` extends into the 1995+ history now available in INDEX_CSV; its
# warmup_start is the earliest real row in the file (1995-01-01 itself is a
# base value with no OHL and is dropped by load_close's own filtering).
MIN_TRAIN_YEARS = 3  # minimum span required between dev_start and first_test_year

WINDOW_CONFIGS = {
    "default": {
        "warmup_start": WARMUP_START,
        "dev_start": DEV_START,
        "first_test_year": 2018,
        "last_test_year": 2024,
        "eras": {
            "2018_19": (2018, 2019),
            "2020_22": (2020, 2021, 2022),
            "2023_24": (2023, 2024),
        },
    },
    "long": {
        "warmup_start": pd.Timestamp("1995-01-01"),
        "dev_start": pd.Timestamp("1996-01-01"),
        "first_test_year": 2000,
        "last_test_year": 2024,
        "eras": {
            "2000_02": (2000, 2001, 2002),
            "2003_07": (2003, 2004, 2005, 2006, 2007),
            "2008_09": (2008, 2009),
            "2010_14": (2010, 2011, 2012, 2013, 2014),
            "2015_19": (2015, 2016, 2017, 2018, 2019),
            "2020_22": (2020, 2021, 2022),
            "2023_24": (2023, 2024),
        },
    },
}


def get_window_config(name: str = "default") -> dict:
    """A named WINDOW_CONFIGS entry, validated. `name` may also be a dict
    (an already-resolved config), returned as-is, so callers can accept
    either a config name or a config dict interchangeably.
    """
    cfg = WINDOW_CONFIGS[name] if isinstance(name, str) else name
    span_years = cfg["first_test_year"] - cfg["dev_start"].year
    if span_years < MIN_TRAIN_YEARS:
        raise ValueError(
            f"window config spans only {span_years}y between dev_start and "
            f"first_test_year, need >= {MIN_TRAIN_YEARS}y"
        )
    return cfg


class LockboxError(RuntimeError):
    """Raised when code tries to fit/score on lockbox dates without permission."""


def load_close(path: str = INDEX_CSV, start: pd.Timestamp = WARMUP_START) -> pd.Series:
    """Load close prices from `start` onward (default: warm-up start, 2013-01-01).

    Returns a tz-naive, sorted, unique Series indexed by date, name='close'.
    Only the close column is used anywhere in this package (open/high/low are
    not needed by any T1 feature or target), which also sidesteps the fact
    that ~240 early rows of the raw file have NaN OHL.
    """
    df = pd.read_csv(path, usecols=["date", "close"])
    df["date"] = pd.to_datetime(df["date"])
    df = df.dropna(subset=["close"])
    df = df.sort_values("date")
    df = df.drop_duplicates(subset="date", keep="last")
    s = df.set_index("date")["close"].astype(float)
    s = s[s.index >= start]
    s.index.name = "date"
    s.name = "close"
    return s


def assert_no_lockbox(dates, open_lockbox: bool = False) -> None:
    """Raise LockboxError if any date in `dates` is >= LOCKBOX_START.

    Pass open_lockbox=True only when deliberately scoring the sealed lockbox
    period (Step 7 of the validation loop, for the one selected model).
    """
    if open_lockbox:
        return
    dates = pd.DatetimeIndex(dates)
    if len(dates) and dates.max() >= LOCKBOX_START:
        bad = dates[dates >= LOCKBOX_START]
        raise LockboxError(
            f"{len(bad)} date(s) >= {LOCKBOX_START.date()} (lockbox) touched "
            f"without open_lockbox=True. First bad date: {bad.min().date()}."
        )
