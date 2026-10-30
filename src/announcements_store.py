"""
announcements_store.py — yearly parquet archive of NSE corporate announcements

One file per year: data/raw/announcements/announcements_YYYY.parquet.
Replaces the old one-CSV-per-day layout (4000+ files). Every row carries a
`date` column (ISO string) — the archive day it was filed under, which used
to live only in the CSV filename. All other columns are stored as strings.
"""

import os
import glob
from datetime import date

import pandas as pd

DIR = os.path.join(os.path.dirname(__file__), "..", "data", "raw", "announcements")
os.makedirs(DIR, exist_ok=True)


def _year_path(year: int) -> str:
    return os.path.join(DIR, f"announcements_{year}.parquet")


def year_paths() -> list:
    return sorted(glob.glob(os.path.join(DIR, "announcements_[0-9][0-9][0-9][0-9].parquet")))


def latest_path() -> str:
    """Newest year file — its mtime bumps when a new day lands (dashboard cache key)."""
    paths = year_paths()
    return paths[-1] if paths else ""


def _path_year(path: str) -> int:
    return int(os.path.basename(path)[len("announcements_"):-len(".parquet")])


def load_range(start: date = None, end: date = None) -> pd.DataFrame:
    """All archived rows with `date` in [start, end], both bounds optional/inclusive."""
    paths = year_paths()
    if start:
        paths = [p for p in paths if _path_year(p) >= start.year]
    if end:
        paths = [p for p in paths if _path_year(p) <= end.year]
    if not paths:
        return pd.DataFrame(columns=["date"])
    df = pd.concat([pd.read_parquet(p) for p in paths], ignore_index=True)
    if start:
        df = df[df["date"] >= start.isoformat()]
    if end:
        df = df[df["date"] <= end.isoformat()]
    return df.reset_index(drop=True)


def load_day(d: date) -> pd.DataFrame:
    path = _year_path(d.year)
    if not os.path.exists(path):
        return pd.DataFrame(columns=["date"])
    df = pd.read_parquet(path)
    return df[df["date"] == d.isoformat()].reset_index(drop=True)


def load_latest_day() -> pd.DataFrame:
    """Rows for the most recent archived day."""
    for path in reversed(year_paths()):
        df = pd.read_parquet(path)
        if not df.empty:
            return df[df["date"] == df["date"].max()].reset_index(drop=True)
    return pd.DataFrame(columns=["date"])


def archived_dates() -> set:
    """ISO date strings that have at least one archived row."""
    dates = set()
    for path in year_paths():
        dates.update(pd.read_parquet(path, columns=["date"])["date"].unique())
    return dates


def save_day(df: pd.DataFrame, d: date) -> None:
    """Upsert one day's rows into its year file, replacing any existing rows for that day."""
    df = df.copy()
    for col in df.columns:
        df[col] = df[col].astype("string")
    df["date"] = d.isoformat()

    path = _year_path(d.year)
    if os.path.exists(path):
        year_df = pd.read_parquet(path)
        df = pd.concat([year_df[year_df["date"] != d.isoformat()], df], ignore_index=True)
    df.to_parquet(path, index=False)
