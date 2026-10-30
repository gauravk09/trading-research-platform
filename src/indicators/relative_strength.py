"""
indicators/relative_strength.py — Relative strength ranking across the universe

Qullamaggie's rule: only trade stocks in the top 1-2% by RS rank.
We compute this by comparing each stock's return to all other stocks
over 1mo, 3mo, and 6mo periods, then rank them.

This is a UNIVERSE-level calculation — it needs data for all stocks.
"""

import pandas as pd
import numpy as np
from indicators.returns import n_day_return


def rs_rank(close_wide: pd.DataFrame, n: int = 63) -> pd.Series:
    """
    Compute percentile rank for each stock based on n-day return.

    Args:
        close_wide: Wide DataFrame with symbols as columns and date as index.
                    Use storage.read_universe_close() to build this.
        n:          Return period in trading days (21=1mo, 63=3mo, 126=6mo)

    Returns:
        Series indexed by symbol with percentile rank 0–100.
        100 = strongest stock in universe.
    """
    if close_wide.empty:
        return pd.Series(dtype=float)

    returns = close_wide.iloc[-1] / close_wide.iloc[-1 - n] - 1
    returns = returns.dropna()
    ranked = returns.rank(pct=True) * 100
    return ranked.sort_values(ascending=False)


def composite_rs_rank(close_wide: pd.DataFrame) -> pd.Series:
    """
    Composite RS rank using weighted average of 1mo, 3mo, and 6mo returns.
    Weights: 40% for 1mo (recent momentum matters most), 30% for 3mo, 30% for 6mo.

    Returns:
        Series indexed by symbol with composite percentile rank 0–100.
    """
    r1  = rs_rank(close_wide, n=21)
    r3  = rs_rank(close_wide, n=63)
    r6  = rs_rank(close_wide, n=126)

    all_symbols = r1.index.union(r3.index).union(r6.index)
    r1  = r1.reindex(all_symbols)
    r3  = r3.reindex(all_symbols)
    r6  = r6.reindex(all_symbols)

    composite = (r1 * 0.40 + r3 * 0.30 + r6 * 0.30)
    return composite.dropna().sort_values(ascending=False)


def residual_rs_rank(close_wide: pd.DataFrame, sector_map: pd.DataFrame = None,
                     n: int = 63) -> pd.Series:
    """RS rank on IDIOSYNCRATIC return — momentum left after removing market + sector.

    Plain rs_rank ranks raw n-day return, so a stock that only rose because its whole
    sector ripped scores as highly as one that broke away on its own. This ranks the
    residual from factor_model.residual_momentum instead: the part of the move neither
    the equal-weight market nor the stock's sector explains. A cleaner "this company
    specifically is strong" signal for gating breakout/EP candidates.

    Args:
        close_wide: wide close DataFrame (symbols as columns, date index).
        sector_map: symbol→industry frame; loaded from the processed map if None.
        n:          lookback in trading days (63 = one quarter).

    Returns:
        Series indexed by symbol, percentile rank 0–100 (100 = strongest residual),
        sorted descending. Empty if the window has too few fully-traded stocks.
    """
    import factor_model
    if sector_map is None:
        sector_map = factor_model.load_sector_map()
    resid = factor_model.residual_momentum(close_wide, sector_map, n=n)
    if resid.empty:
        return pd.Series(dtype=float)
    return (resid.rank(pct=True) * 100).sort_values(ascending=False)


def top_n_by_rs(close_wide: pd.DataFrame, top_pct: float = 2.0) -> list:
    """
    Return the list of symbols in the top X% by composite RS rank.
    Default top_pct=2.0 matches Qullamaggie's top 1-2% rule.

    Args:
        close_wide: Wide close price DataFrame
        top_pct:    Percentile cutoff (2.0 = top 2%)
    """
    ranked = composite_rs_rank(close_wide)
    if ranked.empty:
        return []
    cutoff = ranked.quantile(1 - top_pct / 100)
    return ranked[ranked >= cutoff].index.tolist()
