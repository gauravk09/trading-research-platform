import pandas as pd
import pytest

from research.regime import data, splits


def test_folds_cover_2018_through_2024():
    dates = pd.bdate_range("2015-01-01", "2024-12-31")
    folds = splits.get_walkforward_folds(dates, embargo=20)
    years = [f["year"] for f in folds]
    assert years == list(range(2018, 2025))


def test_train_is_expanding():
    dates = pd.bdate_range("2015-01-01", "2024-12-31")
    folds = splits.get_walkforward_folds(dates, embargo=20)
    sizes = [len(f["train"]) for f in folds]
    assert sizes == sorted(sizes)
    assert all(s2 > s1 for s1, s2 in zip(sizes, sizes[1:]))


def test_embargo_drops_rows_immediately_before_test_start():
    dates = pd.bdate_range("2015-01-01", "2019-12-31")
    embargo = 20
    folds = splits.get_walkforward_folds(dates, embargo=embargo)
    fold_2019 = [f for f in folds if f["year"] == 2019][0]
    test_start_pos = dates.get_loc(fold_2019["test"][0])
    train_positions = [dates.get_loc(d) for d in fold_2019["train"]]
    # no train row within `embargo` rows of the test start
    assert max(train_positions) + embargo < test_start_pos
    # and the row right at the boundary (embargo-1 before cutoff) IS excluded
    assert (test_start_pos - embargo) not in train_positions


def test_purge_removes_rows_whose_target_window_reaches_test():
    dates = pd.bdate_range("2015-01-01", "2019-12-31")
    embargo = 60
    folds = splits.get_walkforward_folds(dates, embargo=embargo)
    fold_2019 = [f for f in folds if f["year"] == 2019][0]
    test_start_pos = dates.get_loc(fold_2019["test"][0])
    for d in fold_2019["train"]:
        pos = dates.get_loc(d)
        # this row's target window [pos+1, pos+embargo] must not reach test_start_pos
        assert pos + embargo < test_start_pos


def test_no_train_rows_before_dev_start():
    dates = pd.bdate_range("2013-01-01", "2019-12-31")  # includes warm-up years
    folds = splits.get_walkforward_folds(dates, embargo=20)
    fold_2018 = [f for f in folds if f["year"] == 2018][0]
    assert all(d >= splits.DEV_START for d in fold_2018["train"])


def test_test_windows_are_disjoint_and_annual():
    dates = pd.bdate_range("2015-01-01", "2024-12-31")
    folds = splits.get_walkforward_folds(dates, embargo=20)
    all_test = pd.DatetimeIndex([])
    for f in folds:
        assert f["test"].min().year == f["year"]
        assert f["test"].max().year == f["year"]
        assert len(all_test.intersection(f["test"])) == 0
        all_test = all_test.union(f["test"])


def test_larger_embargo_shrinks_train_set():
    dates = pd.bdate_range("2015-01-01", "2019-12-31")
    folds_small = splits.get_walkforward_folds(dates, embargo=5)
    folds_big = splits.get_walkforward_folds(dates, embargo=60)
    f_small = [f for f in folds_small if f["year"] == 2019][0]
    f_big = [f for f in folds_big if f["year"] == 2019][0]
    assert len(f_big["train"]) < len(f_small["train"])


def test_long_config_folds_cover_2000_through_2024():
    dates = pd.bdate_range("1995-01-01", "2024-12-31")
    folds = splits.get_walkforward_folds(dates, embargo=60, config="long")
    years = [f["year"] for f in folds]
    assert years == list(range(2000, 2025))


def test_long_config_train_never_precedes_its_dev_start():
    dates = pd.bdate_range("1995-01-01", "2024-12-31")
    cfg = data.get_window_config("long")
    folds = splits.get_walkforward_folds(dates, embargo=60, config="long")
    fold_2000 = [f for f in folds if f["year"] == 2000][0]
    assert all(d >= cfg["dev_start"] for d in fold_2000["train"])
    # the pre-1996 rows are warm-up only, never used as train rows
    assert all(d >= pd.Timestamp("1996-01-01") for d in fold_2000["train"])


def test_long_config_accepts_config_dict_directly():
    dates = pd.bdate_range("1995-01-01", "2024-12-31")
    cfg = data.get_window_config("long")
    folds_by_name = splits.get_walkforward_folds(dates, embargo=60, config="long")
    folds_by_dict = splits.get_walkforward_folds(dates, embargo=60, config=cfg)
    assert [f["year"] for f in folds_by_name] == [f["year"] for f in folds_by_dict]
