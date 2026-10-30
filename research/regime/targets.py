"""Forward-looking labels (targets). Every function here uses FUTURE prices by
definition — that is what makes them useful as targets and dangerous as
features. None of these may ever be fed into a model as an input feature
(features.py is strictly causal and separate).

Lockbox safety: by default (open_lockbox=False), any target value at a dev
date t whose forward window reaches a date >= LOCKBOX_START is set to NaN, so
scoring on dev data can never quietly read a lockbox price. Pass
open_lockbox=True only when deliberately computing targets inside the sealed
lockbox period.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .data import LOCKBOX_START

HORIZONS = (5, 20, 60)

FIXED_BAND_PCT = {5: 0.015, 20: 0.03, 60: 0.06}
DD_THRESHOLD = {5: 0.03, 20: 0.05, 60: 0.10}

DOWN, FLAT_CHOP, UP = 0, 1, 2
VOL_LOW, VOL_MID, VOL_HIGH = 0, 1, 2
TRUTH_DOWN, TRUTH_CHOPPY, TRUTH_UP = 0, 1, 2


def log_returns(close: pd.Series) -> pd.Series:
    return np.log(close / close.shift(1))


def sigma_h(close: pd.Series, h: int) -> pd.Series:
    """Trailing 1-yr (250-row) daily log-return vol at t, scaled to h days.

    No look-ahead: uses only rows <= t (rolling window ending at t inclusive).
    """
    lr = log_returns(close)
    daily_sigma = lr.rolling(250, min_periods=250).std()
    return daily_sigma * np.sqrt(h)


def fwd_ret(close: pd.Series, h: int) -> pd.Series:
    return close.shift(-h) / close - 1.0


def _end_date(close: pd.Series, h: int) -> pd.Series:
    """Date of the row h positions ahead of t (NaT if it doesn't exist)."""
    dates = pd.Series(close.index, index=close.index)
    return dates.shift(-h)


def _lockbox_mask(close: pd.Series, h: int, open_lockbox: bool) -> pd.Series:
    """True where the target's forward window would leak a lockbox price."""
    if open_lockbox:
        return pd.Series(False, index=close.index)
    end = _end_date(close, h)
    return end.isna() | (end >= LOCKBOX_START)


def _apply_lockbox(series: pd.Series, close: pd.Series, h: int, open_lockbox: bool) -> pd.Series:
    mask = _lockbox_mask(close, h, open_lockbox)
    out = series.astype(float).copy()
    out[mask] = np.nan
    return out


def _forward_window_apply(series: pd.Series, h: int, agg: str) -> pd.Series:
    """Apply `agg` (min/sum/std) over the forward window [t+1 .. t+h].

    Implemented by reversing the series, shifting by 1, taking a trailing
    rolling window of size h, then reversing back — this maps a backward
    rolling op onto the forward window without re-deriving alignment by hand.
    """
    rev = series.iloc[::-1]
    shifted = rev.shift(1)
    roll = shifted.rolling(window=h, min_periods=h)
    if agg == "min":
        r = roll.min()
    elif agg == "sum":
        r = roll.sum()
    elif agg == "std":
        r = roll.std()
    else:
        raise ValueError(agg)
    return r.iloc[::-1]


def fwd_ret_h(close: pd.Series, h: int, open_lockbox: bool = False) -> pd.Series:
    return _apply_lockbox(fwd_ret(close, h), close, h, open_lockbox)


def band_h(close: pd.Series, h: int, open_lockbox: bool = False) -> pd.Series:
    """Vol-scaled 3-band label: 0 Down, 1 Flat, 2 Up (spec Section 1.3)."""
    r = fwd_ret(close, h)
    sig = sigma_h(close, h)
    lab = pd.Series(FLAT_CHOP, index=close.index, dtype=float)
    lab[r < -0.5 * sig] = DOWN
    lab[r > 0.5 * sig] = UP
    lab[sig.isna() | r.isna()] = np.nan
    return _apply_lockbox(lab, close, h, open_lockbox)


def fixed_band_h(close: pd.Series, h: int, open_lockbox: bool = False) -> pd.Series:
    """Fixed-percentage band, reported alongside the vol-scaled one."""
    r = fwd_ret(close, h)
    pct = FIXED_BAND_PCT[h]
    lab = pd.Series(FLAT_CHOP, index=close.index, dtype=float)
    lab[r < -pct] = DOWN
    lab[r > pct] = UP
    lab[r.isna()] = np.nan
    return _apply_lockbox(lab, close, h, open_lockbox)


def dd_h(close: pd.Series, h: int, open_lockbox: bool = False) -> pd.Series:
    """1 if the index draws down >= X% from close[t] at any point in t+1..t+h."""
    x = DD_THRESHOLD[h]
    min_ratio = _forward_window_apply(close, h, "min") / close - 1.0
    lab = pd.Series(np.nan, index=close.index)
    valid = min_ratio.notna()
    lab[valid] = (min_ratio[valid] <= -x).astype(float)
    return _apply_lockbox(lab, close, h, open_lockbox)


def _rv20_backward(close: pd.Series) -> pd.Series:
    """Causal 20-row realized vol, known at t (uses rows <= t only)."""
    lr = log_returns(close)
    return lr.rolling(20, min_periods=20).std()


def _rv20_forward(close: pd.Series) -> pd.Series:
    """Realized vol of the next 20 daily log returns after t (the target)."""
    lr = log_returns(close)
    return _forward_window_apply(lr, 20, "std")


def fwd_vol_tercile(close: pd.Series, open_lockbox: bool = False) -> pd.Series:
    """20d forward realized-vol tercile, classed against CAUSAL thresholds.

    Thresholds at t = 33rd/67th percentile of the trailing 750 rows of the
    *backward* (known-at-t) 20d realized-vol series ending at or before t.
    Only the classification target (forward realized vol) looks into the
    future; the thresholds it is compared against do not.
    """
    rv_back = _rv20_backward(close)
    rv_fwd = _rv20_forward(close)

    vals = rv_back.to_numpy()
    n = len(vals)
    low_thr = np.full(n, np.nan)
    high_thr = np.full(n, np.nan)
    for i in range(n):
        window = vals[max(0, i - 749) : i + 1]
        window = window[~np.isnan(window)]
        if len(window) < 750:
            continue
        low_thr[i] = np.quantile(window, 1.0 / 3.0)
        high_thr[i] = np.quantile(window, 2.0 / 3.0)
    low_thr = pd.Series(low_thr, index=close.index)
    high_thr = pd.Series(high_thr, index=close.index)

    valid = rv_fwd.notna() & low_thr.notna() & high_thr.notna()
    lab = pd.Series(VOL_MID, index=close.index, dtype=float)
    lab[rv_fwd <= low_thr] = VOL_LOW
    lab[(rv_fwd >= high_thr) & (rv_fwd > low_thr)] = VOL_HIGH
    lab[~valid] = np.nan
    return _apply_lockbox(lab, close, 20, open_lockbox)


def truth_regime(close: pd.Series, open_lockbox: bool = False) -> pd.Series:
    """Hindsight-only evaluation label (spec Section 1.4). Never a feature.

    Up:     fwd_ret_60 > +0.5*sigma_60  and  ER > 0.3
    Down:   fwd_ret_60 < -0.5*sigma_60  and  ER > 0.3
    Choppy: otherwise
    ER = |close[t+60]-close[t]| / sum_{i=t+1..t+60} |close[i]-close[i-1]|
    """
    h = 60
    r = fwd_ret(close, h)
    sig = sigma_h(close, h)
    abs_diffs = close.diff().abs()
    fwd_sum_abs_diffs = _forward_window_apply(abs_diffs, h, "sum")
    net_move = (close.shift(-h) - close).abs()
    er = net_move / fwd_sum_abs_diffs

    lab = pd.Series(TRUTH_CHOPPY, index=close.index, dtype=float)
    up_mask = (r > 0.5 * sig) & (er > 0.3)
    down_mask = (r < -0.5 * sig) & (er > 0.3)
    lab[up_mask] = TRUTH_UP
    lab[down_mask] = TRUTH_DOWN
    invalid = r.isna() | sig.isna() | er.isna()
    lab[invalid] = np.nan
    return _apply_lockbox(lab, close, h, open_lockbox)


def build_targets(close: pd.Series, open_lockbox: bool = False) -> pd.DataFrame:
    """All targets in one frame, indexed by date. Convenience for runner.py."""
    out = {}
    for h in HORIZONS:
        out[f"fwd_ret_{h}"] = fwd_ret_h(close, h, open_lockbox)
        out[f"sigma_{h}"] = _apply_lockbox(sigma_h(close, h), close, h, open_lockbox)
        out[f"band_{h}"] = band_h(close, h, open_lockbox)
        out[f"fixed_band_{h}"] = fixed_band_h(close, h, open_lockbox)
        out[f"dd_{h}"] = dd_h(close, h, open_lockbox)
    out["vol_tercile_20"] = fwd_vol_tercile(close, open_lockbox)
    out["truth_regime"] = truth_regime(close, open_lockbox)
    return pd.DataFrame(out, index=close.index)
