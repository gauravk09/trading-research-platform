"""Tier-1 (price-only, Nifty 500) features. Every value at t must use only
rows <= t (causal) — see tests/test_features.py::test_causality, which
recomputes on a series truncated at t and asserts equality with the
full-series value at t.

The ladder (n values) is a constructor argument so stability.py can swap a
rung for its neighbour (20->15/25, 250->200/300) without editing this file.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

DEFAULT_LADDER = (5, 10, 20, 60, 120, 250)
DEFAULT_ER_NS = (10, 20, 60, 120)
DEFAULT_DD_WINDOWS = (250, 500)


def _log_returns(close: pd.Series) -> pd.Series:
    return np.log(close / close.shift(1))


def _efficiency_ratio(close: pd.Series, n: int) -> pd.Series:
    """|net move over n rows| / sum of |daily diffs| over the same n rows."""
    net = (close - close.shift(n)).abs()
    diffs = close.diff().abs()
    denom = diffs.rolling(n, min_periods=n).sum()
    return net / denom


def build_features(
    close: pd.Series,
    ladder=DEFAULT_LADDER,
    er_ns=DEFAULT_ER_NS,
    dd_windows=DEFAULT_DD_WINDOWS,
) -> pd.DataFrame:
    ladder = tuple(sorted(set(ladder)))
    lr = _log_returns(close)
    out: dict[str, pd.Series] = {}

    smas = {n: close.rolling(n, min_periods=n).mean() for n in ladder}
    rvols = {}

    for n in ladder:
        out[f"ret_{n}"] = close / close.shift(n) - 1.0
        if n >= 10:
            out[f"dist_ma_{n}"] = close / smas[n] - 1.0
            rvols[n] = lr.rolling(n, min_periods=n).std() * np.sqrt(252)
            out[f"rvol_{n}"] = rvols[n]
        if n >= 20:
            k = min(n, 20)
            out[f"ma_slope_{n}"] = smas[n] / smas[n].shift(k) - 1.0

    rvol_ns = sorted(rvols)
    if len(rvol_ns) >= 2:
        short_n, long_n = rvol_ns[0], rvol_ns[-1]
        out["vol_ratio"] = rvols[short_n] / rvols[long_n]

    for n in er_ns:
        out[f"er_{n}"] = _efficiency_ratio(close, n)

    for n in dd_windows:
        out[f"dd_high_{n}"] = close / close.rolling(n, min_periods=n).max() - 1.0

    return pd.DataFrame(out, index=close.index)
