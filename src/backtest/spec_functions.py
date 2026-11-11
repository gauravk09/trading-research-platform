"""spec_functions.py — the expression vocabulary of strategies/_spec, as pandas code.

Generated strategy files (strategies/<id>/strategy.py) call only these
functions. Every input and output is a wide DataFrame (rows = dates,
columns = symbols). Every function is causal: the value on day t uses data
up to day t's close and nothing later. Warm-up bars come out as NaN, and a
comparison against NaN is False, so a condition never fires on too little
history.

`d` is the data dict built by spec_backtest.load_batch():
    d["open"], d["high"], d["low"], d["close"], d["volume"]   wide frames
    d["features_dir"]   folder of the feature store (data/processed/features)
    d["market"]         mm_history DataFrame indexed by date, or None
"""

import os

import numpy as np
import pandas as pd

MARKET_COLUMNS = {"pct40ma", "pct20ma", "net4", "ratio10", "net25q",
                  "ti65_nifty50", "ti65_nifty500"}
CALENDAR_FIELDS = {"month", "dow", "dom"}


def lag(x, n):
    return x.shift(n)


def sma(x, n):
    return x.rolling(n).mean()


def ema(x, n):
    return x.ewm(span=n, adjust=False, min_periods=n).mean()


def rolling_max(x, n):
    return x.rolling(n).max()


def rolling_min(x, n):
    return x.rolling(n).min()


def rolling_mean(x, n):
    return x.rolling(n).mean()


def ret(x, n):
    """% change over n bars."""
    return (x / x.shift(n) - 1) * 100


def atr(d, n):
    """Average true range in price units (EWM, as src/indicators/volatility.py)."""
    prev_close = d["close"].shift(1)
    true_range = np.maximum(d["high"] - d["low"],
                            np.maximum((d["high"] - prev_close).abs(), (d["low"] - prev_close).abs()))
    return true_range.ewm(span=n, adjust=False, min_periods=n).mean()


def adr(d, n):
    """Average daily range in % (as src/indicators/volatility.py and the feature store)."""
    return ((d["high"] - d["low"]) / d["low"] * 100).rolling(n).mean()


def range_pos(d):
    """Where the close sits in the day's range: 0 = at the low, 1 = at the high."""
    day_range = (d["high"] - d["low"]).where(d["high"] > d["low"])
    return (d["close"] - d["low"]) / day_range


def gap_pct(d):
    prev_close = d["close"].shift(1)
    return (d["open"] - prev_close) / prev_close * 100


def turnover_cr(d, n):
    """Average daily traded value over n bars, in ₹ crore."""
    return (d["close"] * d["volume"]).rolling(n).mean() / 1e7


def bars_since(cond):
    """Bars since `cond` was last True (0 on a True bar, NaN before the first True)."""
    cond = cond.fillna(False).astype(bool)
    bar_number = np.arange(len(cond), dtype=float)[:, None]
    last_true = pd.DataFrame(np.where(cond.values, bar_number, np.nan),
                             index=cond.index, columns=cond.columns).ffill()
    return bar_number - last_true


def feature(d, name):
    """One matrix from the repo feature store, aligned to this batch."""
    path = os.path.join(d["features_dir"], f"{name}.parquet")
    if not os.path.exists(path):
        raise FileNotFoundError(f"feature '{name}' not found at {path} "
                                f"(build it with: PYTHONPATH=src python -m backtest.features)")
    matrix = pd.read_parquet(path)
    matrix.index = _naive_dates(matrix.index)
    return matrix.reindex(index=d["close"].index, columns=d["close"].columns).astype(float)


def market(d, name):
    """A market-breadth series from mm_history, broadcast to every symbol.

    House previous-close rule: a signal on day t sees day t-1's breadth value,
    because the breadth of day t is only known after day t's close.
    """
    if name not in MARKET_COLUMNS:
        raise KeyError(f"market.{name} is not in the vocabulary: {sorted(MARKET_COLUMNS)}")
    if d.get("market") is None:
        raise FileNotFoundError("market.* needs data/processed/mm_history.parquet")
    history = d["market"]
    series = pd.Series(history[name].values, index=_naive_dates(history.index))
    series = series[~series.index.duplicated(keep="last")].sort_index().shift(1)
    return _broadcast(series.reindex(d["close"].index), d["close"])


def calendar(d, name):
    dates = d["close"].index
    values = {"month": dates.month, "dow": dates.dayofweek, "dom": dates.day}[name]
    return _broadcast(pd.Series(values, index=dates, dtype=float), d["close"])


def _broadcast(series, like):
    return pd.DataFrame(np.repeat(series.values[:, None], like.shape[1], axis=1),
                        index=like.index, columns=like.columns)


def _naive_dates(index):
    index = pd.to_datetime(index)
    if index.tz is not None:
        index = index.tz_convert("Asia/Kolkata").tz_localize(None)
    return index.normalize()
