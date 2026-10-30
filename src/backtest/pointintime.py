"""
pointintime.py — Run the breakout scanner as of any historical date

The live scanner evaluates every filter at the LAST bar of a series, so
"what would the scan have shown on date D?" is answered by truncating each
stock's history to D and calling the exact same scoring function. One code
path for live scans and backtests — they cannot drift apart.

Speed: calling score_breakout_candidate() for ~2100 symbols × every
backtest date is too slow, so a vectorized pre-screen replicates the
REQUIRED_FILTERS formulas with slightly LOOSER thresholds and marks, per
bar, whether a symbol could possibly pass. The real scoring function makes
the final call only for pre-screen survivors — the pre-screen can only
prune, never decide.

Known bias vs the live scanner: the ASM/GSM surveillance filter is skipped
(no historical surveillance lists exist), so backtests are slightly
optimistic — some names you would have excluded live are included here.
"""

import os
import sys
import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "strategies", "qullamaggie"))

from storage import read_daily, list_stored_symbols
from filters.momentum import rs_rank_filter
from breakout import score_breakout_candidate, REQUIRED_FILTERS, CONVICTION_FILTERS

MIN_BARS = 130  # same minimum history requirement as the live scanner


def load_universe(symbols: list = None) -> dict:
    """
    Load full daily history for every symbol into memory, once.
    Returns {symbol: DataFrame} — the working set for a whole backtest.
    """
    symbols = symbols or list_stored_symbols()
    data = {}
    for i, symbol in enumerate(symbols, start=1):
        if i % 500 == 0:
            print(f"  Loading [{i}/{len(symbols)}]...")
        df = read_daily(symbol)
        if len(df) >= MIN_BARS:
            data[symbol] = df.reset_index(drop=True)
    return data


def build_close_matrix(data: dict) -> pd.DataFrame:
    """Wide close-price matrix (index=date, columns=symbol) from loaded data."""
    frames = {s: df.set_index("date")["close"] for s, df in data.items()}
    return pd.DataFrame(frames).sort_index()


def composite_rs_matrix(close_wide: pd.DataFrame) -> pd.DataFrame:
    """
    Composite RS rank for EVERY date at once (index=date, columns=symbol).

    Same formula as indicators.relative_strength.composite_rs_rank —
    40% × 21-day rank + 30% × 63-day rank + 30% × 126-day rank, each rank a
    cross-sectional percentile 0–100 — but computed for all dates in one
    vectorized pass instead of only the latest bar.
    """
    composite = None
    for n, weight in [(21, 0.40), (63, 0.30), (126, 0.30)]:
        returns = close_wide.pct_change(n)
        rank = returns.rank(axis=1, pct=True) * 100 * weight
        composite = rank if composite is None else composite + rank
    return composite


def prescreen_mask(df: pd.DataFrame, min_turnover_cr: float) -> pd.Series:
    """
    Per-bar boolean: could this symbol possibly pass the required breakout
    filters on this date? Thresholds are slightly LOOSER than the real
    filters so this is a strict superset — float32 storage and rolling-edge
    quirks can't cause a candidate the real scanner would accept to be
    pruned here.
    """
    close, high, low, volume = df["close"], df["high"], df["low"], df["volume"]

    adr20 = ((high - low) / low * 100).rolling(20).mean()
    ma50 = close.rolling(50).mean()
    r21 = close.pct_change(21) * 100
    r63 = close.pct_change(63) * 100
    dist_from_high = (high.rolling(20).max() - close) / high.rolling(20).max() * 100
    turnover = (close * volume / 1e7).rolling(20).mean().shift(1)

    return (
        (adr20 > 3.9)
        & (close > ma50 * 0.995)
        & (((r21 >= 29) & (r21 <= 201)) | ((r63 >= 29) & (r63 <= 301)))
        & (dist_from_high <= 10.5)
        & (turnover >= min_turnover_cr * 0.9)
    )


def build_prescreens(data: dict, min_turnover_cr: float) -> dict:
    """Precompute the pre-screen mask for every symbol, indexed by date."""
    return {
        symbol: prescreen_mask(df, min_turnover_cr).set_axis(df["date"])
        for symbol, df in data.items()
    }


def scan_asof(
    data:            dict,
    as_of:           pd.Timestamp,
    prescreens:      dict,
    rs_matrix:       pd.DataFrame = None,
    min_turnover_cr: float = 1.0,
    min_rs_pct:      float = 60.0,
) -> pd.DataFrame:
    """
    Run the breakout scan as of a historical date.

    Truncates each symbol's history to `as_of` and applies the SAME scoring,
    required-filter, liquidity, RS and conviction logic as the live scanner
    (strategies/qullamaggie/breakout.py + scanner.py), minus the
    surveillance filter (no historical ASM/GSM data).
    """
    rs_ranks = None
    if rs_matrix is not None and as_of in rs_matrix.index:
        rs_ranks = rs_matrix.loc[as_of].dropna()

    results = []
    for symbol, df in data.items():
        mask = prescreens[symbol]
        if as_of not in mask.index or not mask.loc[as_of]:
            continue

        cutoff = df["date"].searchsorted(as_of, side="right")
        if cutoff < MIN_BARS:
            continue
        truncated = df.iloc[:cutoff]
        if truncated["date"].iloc[-1] != as_of:
            continue  # symbol didn't trade on as_of (suspension/halt)

        scores = score_breakout_candidate(truncated)

        if scores["avg_turnover_cr"] is None or scores["avg_turnover_cr"] < min_turnover_cr:
            continue
        if not all(scores[f] for f in REQUIRED_FILTERS):
            continue
        if rs_ranks is not None and not rs_rank_filter(symbol, rs_ranks, min_rs_pct):
            continue

        scores["symbol"] = symbol
        scores["conviction"] = sum(1 for f in CONVICTION_FILTERS if scores[f])
        scores["date"] = as_of
        results.append(scores)

    if not results:
        return pd.DataFrame()

    return (
        pd.DataFrame(results)
        .sort_values(["conviction", "r3mo_pct"], ascending=[False, False])
        .reset_index(drop=True)
    )
