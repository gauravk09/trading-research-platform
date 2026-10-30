import pandas as pd
import pytest

from research.regime import data


def test_load_close_sorted_unique_tz_naive():
    s = data.load_close()
    assert s.index.is_monotonic_increasing
    assert s.index.is_unique
    assert s.index.tz is None
    assert s.index.min() >= data.WARMUP_START
    assert s.notna().all()


def test_load_close_drops_base_row():
    # base row (1995-01-01, close=1000, no OHL) is before WARMUP_START so it's
    # excluded by the default start filter regardless of NaN handling
    s = data.load_close()
    assert pd.Timestamp("1995-01-01") not in s.index


def test_assert_no_lockbox_passes_for_dev_dates():
    dates = pd.date_range("2020-01-01", "2024-12-31", freq="B")
    data.assert_no_lockbox(dates)  # must not raise


def test_assert_no_lockbox_refuses_lockbox_dates():
    dates = pd.date_range("2024-06-01", "2025-06-01", freq="B")
    with pytest.raises(data.LockboxError):
        data.assert_no_lockbox(dates)


def test_assert_no_lockbox_open_flag_allows_it():
    dates = pd.date_range("2024-06-01", "2025-06-01", freq="B")
    data.assert_no_lockbox(dates, open_lockbox=True)  # must not raise


def test_assert_no_lockbox_boundary_exact():
    # LOCKBOX_START itself must be refused (it is the first sealed date)
    with pytest.raises(data.LockboxError):
        data.assert_no_lockbox(pd.DatetimeIndex([data.LOCKBOX_START]))
    # the day before must be fine
    data.assert_no_lockbox(pd.DatetimeIndex([data.LOCKBOX_START - pd.Timedelta(days=1)]))


def test_default_window_config_matches_existing_constants():
    cfg = data.get_window_config("default")
    assert cfg["dev_start"] == data.DEV_START
    assert cfg["warmup_start"] == data.WARMUP_START
    assert cfg["first_test_year"] == 2018
    assert cfg["last_test_year"] == 2024
    assert cfg["eras"]["2018_19"] == (2018, 2019)
    assert cfg["eras"]["2020_22"] == (2020, 2021, 2022)
    assert cfg["eras"]["2023_24"] == (2023, 2024)


def test_long_window_config_spec():
    cfg = data.get_window_config("long")
    assert cfg["dev_start"] == pd.Timestamp("1996-01-01")
    assert cfg["warmup_start"] == pd.Timestamp("1995-01-01")
    assert cfg["first_test_year"] == 2000
    assert cfg["last_test_year"] == 2024
    assert cfg["eras"] == {
        "2000_02": (2000, 2001, 2002),
        "2003_07": (2003, 2004, 2005, 2006, 2007),
        "2008_09": (2008, 2009),
        "2010_14": (2010, 2011, 2012, 2013, 2014),
        "2015_19": (2015, 2016, 2017, 2018, 2019),
        "2020_22": (2020, 2021, 2022),
        "2023_24": (2023, 2024),
    }


def test_lockbox_start_is_the_same_for_every_config():
    # LOCKBOX_START is a module-level constant, not part of any config --
    # every config must be sealed at the same date.
    for name in data.WINDOW_CONFIGS:
        cfg = data.get_window_config(name)
        assert cfg["last_test_year"] < data.LOCKBOX_START.year


def test_get_window_config_accepts_a_dict_passthrough():
    custom = {"dev_start": pd.Timestamp("2010-01-01"), "warmup_start": pd.Timestamp("2008-01-01"),
              "first_test_year": 2014, "last_test_year": 2016, "eras": {}}
    assert data.get_window_config(custom) is custom


def test_get_window_config_rejects_too_short_a_training_span():
    bad = {"dev_start": pd.Timestamp("2018-01-01"), "warmup_start": pd.Timestamp("2017-01-01"),
           "first_test_year": 2019, "last_test_year": 2020, "eras": {}}
    with pytest.raises(ValueError):
        data.get_window_config(bad)
