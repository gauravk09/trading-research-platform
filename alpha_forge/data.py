"""data.py — the substrate the whole miner scores against.

Reads the parent repo's per-symbol OHLCV parquet files READ-ONLY and turns
them into aligned cross-sectional panels (dates x symbols), a point-in-time
liquid universe, and forward-return labels.

Isolated by design: this package imports nothing from src/ or research/. The
only shared thing is the raw price data on disk, which is data, not logic.
"""

import glob
import os

import numpy as np
import pandas as pd

# Read-only pointer into the parent repo's price store. We never write here.
# Overridable via ALPHA_FORGE_DAILY_DIR so parallel scoring can run from any cwd
# (e.g. a subagent whose working directory isn't the repo root).
_DEFAULT_DAILY = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "data", "parquet", "daily"))
DAILY_DIR = os.environ.get("ALPHA_FORGE_DAILY_DIR", _DEFAULT_DAILY)

# Read-only pointer into the parent repo's PRE-COMPUTED feature matrices
# (data/processed/features/<name>.parquet, each already a date x symbol matrix)
# plus a few standalone matrices in data/processed/. Data, not logic — same D1
# contract as DAILY_DIR. These carry information OHLCV alone cannot express
# (delivery %, point-in-time market cap, relative strength, ...).
_DEFAULT_PROCESSED = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "data", "processed"))
PROCESSED_DIR = os.environ.get("ALPHA_FORGE_PROCESSED_DIR", _DEFAULT_PROCESSED)


def load_panels(min_history=400):
    """Load every symbol into two aligned panels: close and volume.

    Returns (close, volume) DataFrames indexed by naive daily date, columns
    are symbols. Symbols with fewer than min_history bars are dropped so the
    cross-section on any given day is not polluted by brand-new listings that
    have no rank-able history.
    """
    closes, volumes = {}, {}
    for path in sorted(glob.glob(os.path.join(DAILY_DIR, "*.parquet"))):
        sym = os.path.basename(path).replace(".parquet", "")
        df = pd.read_parquet(path, columns=["date", "close", "volume"])
        if len(df) < min_history:
            continue
        # Kite timestamps are IST-aware; normalise to a naive calendar date so
        # every symbol shares one index and nothing mixes tz-aware/naive.
        d = pd.to_datetime(df["date"]).dt.tz_localize(None).dt.normalize()
        closes[sym] = pd.Series(df["close"].values, index=d)
        volumes[sym] = pd.Series(df["volume"].values, index=d)

    close = pd.DataFrame(closes).sort_index()
    volume = pd.DataFrame(volumes).sort_index()
    # Align both panels on the union of trading days. A missing day for a
    # symbol stays NaN — it is NOT forward-filled, because a fabricated price
    # would create a fake return and a fake factor value on a day the stock
    # did not actually trade.
    volume = volume.reindex(close.index)
    return close, volume


def load_ohlcv(min_history=400):
    """Like load_panels but returns all five aligned panels: open, high, low,
    close, volume. Used by the OHLC mining round (gaps, intraday ranges).
    """
    cols = {"open": {}, "high": {}, "low": {}, "close": {}, "volume": {}}
    for path in sorted(glob.glob(os.path.join(DAILY_DIR, "*.parquet"))):
        sym = os.path.basename(path).replace(".parquet", "")
        df = pd.read_parquet(path, columns=["date", "open", "high", "low", "close", "volume"])
        if len(df) < min_history:
            continue
        d = pd.to_datetime(df["date"]).dt.tz_localize(None).dt.normalize()
        for c in cols:
            cols[c][sym] = pd.Series(df[c].values, index=d)
    panels = {c: pd.DataFrame(v).sort_index() for c, v in cols.items()}
    idx = panels["close"].index
    return tuple(panels[c].reindex(idx) for c in ["open", "high", "low", "close", "volume"])


def _feature_path(name):
    """Resolve a feature name to a parquet path. Plain names live under
    features/; a name with a '/' (e.g. 'delivery_matrix') is a standalone
    matrix directly under data/processed/."""
    if "/" in name:
        return os.path.join(PROCESSED_DIR, name.replace("/", os.sep) + ".parquet")
    return os.path.join(PROCESSED_DIR, "features", name + ".parquet")


def load_features(names, index, columns):
    """Load pre-computed date x symbol feature matrices, aligned onto the
    master price panel so every field shares one index and one column order.

    `index`/`columns` are the master panel's (close.index, close.columns). Each
    matrix is reindexed onto them: a symbol/day the feature never covered stays
    NaN (never fabricated), and symbols outside the price universe are dropped.
    The feature index is tz-normalised to naive calendar dates the SAME way
    load_panels does — without this the tz-aware IST stamps miss every naive
    date on reindex and the field silently comes back all-NaN.

    Returns {name: DataFrame}. These matrices were computed point-in-time in the
    parent project (trailing windows, filing-date-aware); we do not re-derive
    them here, we only align them.
    """
    out = {}
    for name in names:
        df = pd.read_parquet(_feature_path(name))
        idx = pd.DatetimeIndex(pd.to_datetime(df.index))
        if idx.tz is not None:  # tz-aware IST -> naive; naive matrices pass through
            idx = idx.tz_localize(None)
        idx = idx.normalize()
        df = pd.DataFrame(df.values, index=idx, columns=df.columns)
        out[name] = df.reindex(index=index, columns=columns)
    return out


def forward_return(close, horizon=5):
    """h-day forward simple return per symbol: (close[t+h] / close[t]) - 1.

    This is the LABEL. shift(-horizon) pulls the future price back to day t so
    that row t holds "what happens over the next h days". A factor value on
    day t is later correlated against this. The look-ahead is intentional and
    lives only in the label; features never get to see it.
    """
    return close.shift(-horizon) / close - 1.0


def liquid_universe(close, volume, top=500, lookback=60):
    """Point-in-time top-N liquid universe as a boolean panel (date x symbol).

    Turnover = close * volume (rupees traded). For each day we rank symbols by
    their trailing-`lookback`-day average turnover and mark the top `top` as
    tradable ON THAT DAY. Using only trailing data means the universe we would
    actually have known at day t — no future leakage, and names that later
    delist simply fall out of the top set as their turnover dies, instead of
    being silently excluded from history.
    """
    turnover = close * volume
    avg_turnover = turnover.rolling(lookback, min_periods=lookback // 2).mean()
    # Rank across symbols within each day; rank 1 = most liquid. Keep <= top.
    ranks = avg_turnover.rank(axis=1, ascending=False, method="first")
    return ranks <= top


if __name__ == "__main__":
    close, volume = load_panels()
    fwd = forward_return(close, horizon=5)
    uni = liquid_universe(close, volume, top=500, lookback=60)

    print(f"symbols loaded      : {close.shape[1]}")
    print(f"trading days        : {close.shape[0]}")
    print(f"date range          : {close.index.min().date()} -> {close.index.max().date()}")
    print(f"fwd-return panel     : {fwd.shape}")
    # Universe size should hover at ~top on mature days (fewer early on when
    # not enough symbols have lookback history yet).
    daily_uni = uni.sum(axis=1)
    recent = daily_uni.iloc[-1]
    print(f"universe on last day: {int(recent)} names (target {500})")
    print(f"universe size (median over full history): {int(daily_uni.median())}")
