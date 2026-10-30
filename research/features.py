"""research/features.py — the feature library. Add features here; engine stays fixed.

Two registries:
  PRE_FEATURES[name]    = fn(df, i)     — context at the pivot bar i, computed
                                          ONLY from rows <= i (no look-ahead;
                                          the slice is enforced here, once)
  DURING_FEATURES[name] = fn(df, i, j)  — behaviour of the move, bars i..j
                                          (pivot..peak); hindsight is fine here,
                                          these describe the move itself.

A study spec can pass extra_pre_features / extra_during_features without
touching this file — but features that prove broadly useful should graduate
into these registries so every later study gets them.
"""

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import numpy as np
import pandas as pd

from indicators.trend_stage import base_count, trend_age


def safe(fn, *args):
    """NaN-tolerant feature call: any failure or short history -> None."""
    try:
        v = fn(*args)
        if v is None or (isinstance(v, float) and not np.isfinite(v)):
            return None
        return v
    except Exception:
        return None


def _pre(df, i):
    """Rows up to and including the pivot bar — the only data a pre-feature sees."""
    return df.iloc[:i + 1]


# ── pre-pivot: trend structure ─────────────────────────────────────────────────

def _above_ma(n):
    def fn(df, i):
        d = _pre(df, i)
        if len(d) < n:
            return None
        return bool(d["close"].iloc[-1] > d["close"].rolling(n).mean().iloc[-1])
    return fn


def _dist_ma_pct(n):
    def fn(df, i):
        d = _pre(df, i)
        if len(d) < n:
            return None
        ma = d["close"].rolling(n).mean().iloc[-1]
        return round((d["close"].iloc[-1] / ma - 1) * 100, 2)
    return fn


def pct_from_52w_high(df, i):
    d = _pre(df, i).tail(252)
    return round((d["close"].iloc[-1] / d["high"].max() - 1) * 100, 1)


def pct_from_52w_low(df, i):
    d = _pre(df, i).tail(252)
    return round((d["close"].iloc[-1] / d["low"].min() - 1) * 100, 1)


def ti65(df, i):
    d = _pre(df, i)
    if len(d) < 65:
        return None
    return round(float(d["close"].rolling(7).mean().iloc[-1]
                       / d["close"].rolling(65).mean().iloc[-1]), 3)


def trend_age_d(df, i):
    d = _pre(df, i)
    return trend_age(d["close"])


def base_count_n(df, i):
    d = _pre(df, i)
    return base_count(d["close"], d["high"], d["low"])


# ── pre-pivot: prior returns & linearity ───────────────────────────────────────

def _ret_pct(n):
    def fn(df, i):
        d = _pre(df, i)["close"]
        if len(d) < n + 1:
            return None
        return round((d.iloc[-1] / d.iloc[-n - 1] - 1) * 100, 1)
    return fn


def _efficiency_ratio(n):
    """|net move| / sum of |daily moves| over n bars: 1 = straight line,
    ~0 = drunken walk or flat base (Bonde's 'linear and orderly')."""
    def fn(df, i):
        c = _pre(df, i)["close"].iloc[-(n + 1):]
        if len(c) < n + 1:
            return None
        path = c.diff().abs().sum()
        return round(float(abs(c.iloc[-1] - c.iloc[0]) / path), 2) if path > 0 else None
    return fn


def _r2(n):
    def fn(df, i):
        c = _pre(df, i)["close"].iloc[-n:]
        if len(c) < n or (c <= 0).any():
            return None
        lg = np.log(c.values)
        return round(float(np.corrcoef(np.arange(n), lg)[0, 1] ** 2), 2)
    return fn


# ── pre-pivot: consolidation / tightness ───────────────────────────────────────

def _range_pct(n):
    def fn(df, i):
        d = _pre(df, i).tail(n)
        if len(d) < n:
            return None
        return round((d["high"].max() - d["low"].min()) / d["close"].iloc[-1] * 100, 1)
    return fn


def consol_days_adr(df, i):
    """Quiet days before the pivot at the stock's own scale — same vocabulary
    as the live scans (1x prior-50d ADR, clipped 2.5-8%)."""
    d = _pre(df, i)
    if len(d) < 55:
        return None
    chg = d["close"].pct_change() * 100
    adr = ((d["high"] / d["low"]).rolling(50).mean() - 1).shift(1) * 100
    thr = adr.clip(2.5, 8.0).fillna(4.0)
    big = chg.abs() >= thr
    n = 0
    for flag in reversed(big.tolist()):
        if flag:
            break
        n += 1
    return min(n, 60)


def nr7(df, i):
    d = _pre(df, i)
    if len(d) < 7:
        return None
    rng = d["high"] - d["low"]
    return bool(rng.iloc[-1] <= rng.iloc[-7:-1].min())


def vol_contraction(df, i):
    d = _pre(df, i)
    if len(d) < 20:
        return None
    v20 = d["volume"].iloc[-20:].mean()
    return round(float(d["volume"].iloc[-5:].mean() / v20), 2) if v20 > 0 else None


def adr20_pct(df, i):
    d = _pre(df, i)
    if len(d) < 21:
        return None
    return round(float(((d["high"] / d["low"]).iloc[-20:].mean() - 1) * 100), 2)


# ── pre-pivot: volume/liquidity ────────────────────────────────────────────────

def _avg_turnover_cr(n):
    def fn(df, i):
        d = _pre(df, i).tail(n)
        if len(d) < min(n, 10):
            return None
        return round(float((d["close"] * d["volume"]).mean() / 1e7), 1)
    return fn


def pivot_day_vol_ratio(df, i):
    d = _pre(df, i)
    if len(d) < 21:
        return None
    v20 = d["volume"].iloc[-21:-1].mean()
    return round(float(d["volume"].iloc[-1] / v20), 2) if v20 > 0 else None


def down_streak_at_pivot(df, i):
    """Consecutive down closes ending AT the pivot — was the pivot a capitulation?"""
    d = _pre(df, i)["close"]
    n = 0
    for flag in reversed((d.diff() < 0).tolist()):
        if flag:
            n += 1
        else:
            break
    return n


# ── during the move (pivot i .. peak j) ────────────────────────────────────────

def n_up4(df, i, j):
    chg = df["close"].pct_change() * 100
    return int((chg.iloc[i + 1:j + 1] >= 4).sum())


def max_consec_up(df, i, j):
    up = (df["close"].diff() > 0).iloc[i + 1:j + 1]
    best = run = 0
    for f in up:
        run = run + 1 if f else 0
        best = max(best, run)
    return best


def n_gapup2(df, i, j):
    gap = (df["open"] / df["close"].shift(1) - 1) * 100
    return int((gap.iloc[i + 1:j + 1] >= 2).sum())


def n_circuit_like(df, i, j):
    """Days moving >= 9.5% c2c — near NSE circuit bands; a proxy for
    'could you even have bought it?'"""
    chg = df["close"].pct_change() * 100
    return int((chg.iloc[i + 1:j + 1] >= 9.5).sum())


def max_dd_in_move_pct(df, i, j):
    c = df["close"].iloc[i:j + 1]
    return round(float(((c / c.cummax()) - 1).min() * 100), 1)


def vol_mult_during(df, i, j):
    pre = df["volume"].iloc[max(0, i - 60):i]
    dur = df["volume"].iloc[i + 1:j + 1]
    if len(pre) < 10 or not len(dur) or pre.mean() <= 0:
        return None
    return round(float(dur.mean() / pre.mean()), 2)


def day1_gap_pct(df, i, j):
    if i + 1 > j:
        return None
    return round(float((df["open"].iloc[i + 1] / df["close"].iloc[i] - 1) * 100), 2)


def day1_chg_pct(df, i, j):
    if i + 1 > j:
        return None
    return round(float((df["close"].iloc[i + 1] / df["close"].iloc[i] - 1) * 100), 2)


def day1_vol_ratio(df, i, j):
    v20 = df["volume"].iloc[max(0, i - 19):i + 1].mean()
    if i + 1 > j or v20 <= 0:
        return None
    return round(float(df["volume"].iloc[i + 1] / v20), 2)


# ── registries ─────────────────────────────────────────────────────────────────

PRE_FEATURES = {
    "above_ma10": _above_ma(10), "above_ma20": _above_ma(20),
    "above_ma50": _above_ma(50), "above_ma100": _above_ma(100),
    "above_ma200": _above_ma(200),
    "dist_ma20_pct": _dist_ma_pct(20), "dist_ma50_pct": _dist_ma_pct(50),
    "pct_from_52w_high": pct_from_52w_high, "pct_from_52w_low": pct_from_52w_low,
    "ti65": ti65, "trend_age_d": trend_age_d, "base_count": base_count_n,
    "ret_10d_pct": _ret_pct(10), "ret_30d_pct": _ret_pct(30), "ret_60d_pct": _ret_pct(60),
    "er_10": _efficiency_ratio(10), "er_30": _efficiency_ratio(30),
    "er_60": _efficiency_ratio(60),
    "r2_30": _r2(30), "r2_60": _r2(60),
    "range_pct_5d": _range_pct(5), "range_pct_20d": _range_pct(20),
    "consol_days_adr": consol_days_adr, "nr7": nr7,
    "vol_contraction": vol_contraction, "adr20_pct": adr20_pct,
    "avg_turnover_cr_10d": _avg_turnover_cr(10), "avg_turnover_cr_60d": _avg_turnover_cr(60),
    "pivot_day_vol_ratio": pivot_day_vol_ratio,
    "down_streak_at_pivot": down_streak_at_pivot,
}

DURING_FEATURES = {
    "n_up4": n_up4, "max_consec_up": max_consec_up, "n_gapup2": n_gapup2,
    "n_circuit_like": n_circuit_like, "max_dd_in_move_pct": max_dd_in_move_pct,
    "vol_mult_during": vol_mult_during,
    "day1_gap_pct": day1_gap_pct, "day1_chg_pct": day1_chg_pct,
    "day1_vol_ratio": day1_vol_ratio,
}
