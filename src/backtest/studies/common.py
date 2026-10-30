"""
common.py — Shared plumbing for champion-trader event studies.

Every study in this folder follows the washout_reversal.py pattern:
build wide OHLCV matrices, tag each event with the market breadth regime
and the stock's composite RS rank at signal time, measure forward returns
from the D+1 open, and report regime × RS segmented stats.

This module centralizes that plumbing plus a parquet cache in
output/studies/cache/ so ten studies don't each spend minutes re-reading
~2100 per-symbol parquets.

Build/refresh the cache once:
    ~/anaconda3/bin/python src/backtest/studies/common.py
"""

import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from storage import read_daily, list_stored_symbols
from regime import compute_market_monitor
from backtest.pointintime import composite_rs_matrix

OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "..", "output", "studies")
CACHE_DIR = os.path.join(OUTPUT_DIR, "cache")

MIN_BARS = 130
MIN_PRICE = 30.0
MIN_TURNOVER_CR = 1.0
HORIZONS = [1, 2, 3, 5, 10, 20]

MATRIX_COLS = ["open", "high", "low", "close", "volume"]


def build_matrices() -> dict:
    """Full-history wide matrices (index=date, columns=symbol) for OHLCV."""
    frames = {col: {} for col in MATRIX_COLS}
    symbols = list_stored_symbols()
    for i, symbol in enumerate(symbols, start=1):
        if i % 500 == 0:
            print(f"  Loading [{i}/{len(symbols)}]...")
        df = read_daily(symbol, columns=["date"] + MATRIX_COLS)
        # ~400 daily files carry stray intraday rows (2016-18); a real daily
        # bar is always midnight IST — non-midnight rows would poison the
        # union index and NaN out diffs market-wide.
        df = df[df["date"].dt.time == pd.Timestamp("00:00").time()]
        if len(df) < MIN_BARS:
            continue
        df = df.set_index("date")
        for col in MATRIX_COLS:
            frames[col][symbol] = df[col]
    return {col: pd.DataFrame(series).sort_index() for col, series in frames.items()}


def breadth_score_series(cm: pd.DataFrame, vm: pd.DataFrame) -> pd.Series:
    """
    The regime.py 5-signal score vectorized over every date: ratio5, ratio10,
    up25q-dn25q, pct40ma, pct20ma each contribute +1 / -1 / 0. Same thresholds
    as the live regime evaluation.
    """
    mm = compute_market_monitor(cm, vm)

    ma20 = cm.rolling(20).mean()
    pct20ma = (cm > ma20).sum(axis=1) / (cm.notna() & ma20.notna()).sum(axis=1) * 100

    def zone(series, bull, bear):
        return pd.Series(np.where(series > bull, 1, np.where(series < bear, -1, 0)),
                         index=series.index).where(series.notna(), 0)

    return (
        zone(mm["ratio5"], 2, 0.5)
        + zone(mm["ratio10"], 2, 0.5)
        + zone(mm["up25q"] - mm["dn25q"], 0, 0)
        + zone(mm["pct40ma"], 60, 40)
        + zone(pct20ma, 60, 40)
    )


def build_cache() -> None:
    """Build OHLCV matrices + breadth score + RS matrix and cache as parquet."""
    os.makedirs(CACHE_DIR, exist_ok=True)
    print("Building full-history matrices from per-symbol parquets...")
    m = build_matrices()
    for col, df in m.items():
        df.to_parquet(os.path.join(CACHE_DIR, f"{col}.parquet"))
    print(f"  {m['close'].shape[1]} symbols, "
          f"{m['close'].index.min().date()} → {m['close'].index.max().date()}")

    print("Computing breadth score and composite RS ranks...")
    score = breadth_score_series(m["close"], m["volume"])
    score.rename("score").to_frame().to_parquet(os.path.join(CACHE_DIR, "breadth_score.parquet"))
    composite_rs_matrix(m["close"]).to_parquet(os.path.join(CACHE_DIR, "rs_rank.parquet"))
    print(f"Cache written to {os.path.abspath(CACHE_DIR)}")


def load_cache() -> dict:
    """
    Load cached matrices. Returns dict with keys open/high/low/close/volume
    (DataFrames), score (Series), rs (DataFrame).
    """
    if not os.path.exists(os.path.join(CACHE_DIR, "close.parquet")):
        raise FileNotFoundError(
            "Study cache missing — run: python src/backtest/studies/common.py")
    out = {col: pd.read_parquet(os.path.join(CACHE_DIR, f"{col}.parquet"))
           for col in MATRIX_COLS}
    out["score"] = pd.read_parquet(os.path.join(CACHE_DIR, "breadth_score.parquet"))["score"]
    out["rs"] = pd.read_parquet(os.path.join(CACHE_DIR, "rs_rank.parquet"))
    return out


def tradeable_mask(close: pd.DataFrame, volume: pd.DataFrame) -> pd.DataFrame:
    """Same floor as washout_reversal: price, 20d turnover, enough history."""
    turnover_cr = (close * volume / 1e7).rolling(20).mean()
    enough_history = close.notna().cumsum() >= MIN_BARS
    return (close >= MIN_PRICE) & (turnover_cr >= MIN_TURNOVER_CR) & enough_history


def events_from_mask(mask: pd.DataFrame, m: dict) -> pd.DataFrame:
    """
    One row per True cell in `mask` (index=date, columns=symbol), tagged with
    close, breadth score, RS rank, D+1 open entry, and forward returns at
    HORIZONS from both the signal close (ret_cN) and the D+1 open (ret_oN).
    """
    close, open_ = m["close"], m["open"]
    dates, syms = np.where(mask.reindex_like(close).fillna(False))
    events = pd.DataFrame({
        "date": close.index[dates],
        "symbol": close.columns[syms],
        "close": close.values[dates, syms],
        "rs_rank": m["rs"].values[dates, syms],
        "breadth_score": m["score"].reindex(close.index).values[dates],
    })
    next_open = open_.shift(-1)
    events["entry_open"] = next_open.values[dates, syms]
    for n in HORIZONS:
        fwd_close = close.shift(-n).values[dates, syms]
        events[f"ret_c{n}"] = (fwd_close / events["close"] - 1) * 100
        events[f"ret_o{n}"] = (fwd_close / events["entry_open"] - 1) * 100
    return events


def add_regime_and_rs_buckets(events: pd.DataFrame) -> pd.DataFrame:
    events["regime"] = pd.cut(events["breadth_score"], [-np.inf, -2, 0, np.inf],
                              labels=["bad", "neutral", "good"])
    events["rs_bucket"] = pd.cut(events["rs_rank"], [0, 20, 40, 60, 80, 100],
                                 labels=["RS 0-20", "RS 20-40", "RS 40-60",
                                         "RS 60-80", "RS 80-100"])
    return events


def stat_line(returns: pd.Series) -> str:
    r = returns.dropna()
    if len(r) < 30:
        return f"n={len(r)} (too few)"
    return (f"med {r.median():+5.2f}%  mean {r.mean():+5.2f}%  "
            f"win {(r > 0).mean() * 100:4.1f}%")


def print_table(events: pd.DataFrame, group_col: str, ret_prefix: str = "ret_o",
                horizons: list = (1, 5, 20)) -> None:
    for label, grp in events.groupby(group_col, observed=True):
        cells = "  |  ".join(f"D+{n} {stat_line(grp[f'{ret_prefix}{n}'])}"
                             for n in horizons)
        print(f"  {str(label):<22} n={len(grp):<6} {cells}")


def print_standard_segments(events: pd.DataFrame, horizons: list = (1, 5, 20)) -> None:
    """The two mandatory cuts: breadth regime, and RS quintile in good markets."""
    print("\n[Regime] By market breadth at signal (score>=+1 good, <=-2 bad):")
    print_table(events, "regime", horizons=horizons)
    print("\n[RS] Good market only — by composite RS quintile at signal:")
    print_table(events[events["regime"] == "good"], "rs_bucket", horizons=horizons)


CAVEATS = """Notes:
  - Forward windows overlap across events of the same symbol; stats are
    per-event, not a portfolio equity curve.
  - Stocks suspended/delisted inside the window drop out of that horizon's
    stats (mild exit-survivorship).
  - No historical ASM/GSM exclusion; no costs/slippage modelled.
  - Bad-market events cluster in corrections; their forward windows overlap
    and ride the market's own rebound (beta, not alpha).
  - Split repair: run integrity.py --scan first if results look off."""


if __name__ == "__main__":
    build_cache()
