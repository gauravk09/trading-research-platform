"""factor_model.py — the "5 hidden forces" engine: PCA crowding gauge + residual momentum.

Two things a quant desk pulls out of a universe's return matrix, both useful to a
momentum trader (not the stat-arb mean-reversion at the end of the article — that's
the opposite style):

  1. Absorption ratio — the share of total variance the single largest eigenvector
     (PC1, "the market itself") soaks up. High = every stock moving as one animal,
     correlations snapping toward 1, breakouts failing as a group. A fragility gauge
     your breadth model does not directly capture: breadth says "how many are up",
     this says "how independent are they". See absorption_series().

  2. Residual (idiosyncratic) momentum — each stock's return AFTER regressing out the
     market factor and its sector factor. What's left is the part that is genuinely
     about that company, not the market tide or a sector ripping. A rigorous upgrade
     of a plain return-vs-universe RS rank. See residual_momentum().

Random matrix theory (Marchenko-Pastur) draws the line between eigenvalues that carry
real structure and the cloud that is pure sampling noise — marchenko_pastur_max() /
n_significant_factors() report how many forces are actually real on a given day.

Pure numpy/pandas, no IO. Math only; the zoning
and presentation of #1 live in market_signals.py, and #2 slots into
indicators/relative_strength.py as residual_rs_rank().

Plain-text read of both: PYTHONPATH=src python -m preprocessing.factor_report
"""

import numpy as np
import pandas as pd


# ─────────────────────────────────────────────────────────────────────────────
# #1  Absorption ratio (PC1 crowding gauge) + Marchenko-Pastur noise band
# ─────────────────────────────────────────────────────────────────────────────

def absorption_ratio(returns: pd.DataFrame, k: int = 1) -> float:
    """Share of total variance absorbed by the top `k` principal components.

    Standardizes each stock's returns first, so we eigen-decompose the CORRELATION
    matrix, not the raw covariance — otherwise a few high-vol names mechanically own
    PC1 and the number stops meaning "co-movement". For a correlation matrix the
    eigenvalues sum to N (the number of stocks), so PC1 share = largest eigenvalue / N,
    bounded in [1/N, 1]. k=1 is the classic crowding gauge; k>1 is the multi-factor
    absorption ratio (Kritzman-Li-Page-Rigobon).

    Returns NaN if fewer than 2 usable stocks remain after dropping incomplete columns.
    """
    z = _standardize(returns)
    if z.shape[1] < 2:
        return float("nan")
    corr = np.corrcoef(z.values, rowvar=False)
    eig = np.linalg.eigvalsh(corr)            # ascending, length N
    eig = np.clip(eig[::-1], 0, None)         # descending, guard tiny negatives
    total = eig.sum()
    return float(eig[:k].sum() / total) if total > 0 else float("nan")


def marchenko_pastur_max(n_obs: int, n_vars: int) -> float:
    """Upper edge of the Marchenko-Pastur noise band for a correlation matrix.

    With T observations and N variables of pure noise, sample eigenvalues still
    spread up to λ+ = (1 + sqrt(N/T))^2 purely by accident. Any real eigenvalue must
    poke ABOVE this to carry information — everything inside the band is statistically
    indistinguishable from random junk.
    """
    q = n_vars / n_obs
    return (1 + q ** 0.5) ** 2


def n_significant_factors(returns: pd.DataFrame) -> int:
    """How many eigenvalues clear the Marchenko-Pastur band = count of real forces.

    On a normal day this is a small single-digit number: the market, then a handful
    of sector/style contrasts, then hundreds of noise eigenvalues inside the band.
    """
    z = _standardize(returns)
    n_obs, n_vars = z.shape
    if n_vars < 2:
        return 0
    corr = np.corrcoef(z.values, rowvar=False)
    eig = np.linalg.eigvalsh(corr)
    return int((eig > marchenko_pastur_max(n_obs, n_vars)).sum())


def absorption_series(close_wide: pd.DataFrame, window: int = 63, max_names: int = 250,
                      stride: int = 5, history: int = 260) -> pd.Series:
    """Trailing series of the PC1 absorption ratio, one point every `stride` sessions.

    Runs on a FIXED liquid basket — the `max_names` most consistently-traded names over
    the recent slice — so day-to-day changes reflect co-movement, not basket churn.
    A `window`-day return block feeds each eigen-decomposition; `history` is how far
    back the series reaches (enough to percentile-rank today's reading). Sampled every
    `stride` days because a 250x250 eigen-decomposition per day is wasteful and the
    ratio moves slowly.

    Survivorship note: the basket is intentionally the names alive throughout the slice.
    This is a market-STATE gauge; a stable basket is the right choice, the same reason
    market_rhythm.py freezes its leader basket.
    """
    px = _liquid_basket(close_wide, max_names, window + history)
    if px.shape[1] < 2 or len(px) < window + 2:
        return pd.Series(dtype=float)

    rets = px.pct_change(fill_method=None)
    ends = range(len(px) - 1, window, -stride)
    out = {}
    for end in sorted(ends):
        block = rets.iloc[end - window + 1:end + 1].dropna(axis=1)
        if block.shape[1] >= 2:
            out[px.index[end]] = absorption_ratio(block, k=1)
    return pd.Series(out).sort_index()


# ─────────────────────────────────────────────────────────────────────────────
# #2  Residual (idiosyncratic) momentum
# ─────────────────────────────────────────────────────────────────────────────

def residual_momentum(close_wide: pd.DataFrame, sector_map: pd.DataFrame,
                      n: int = 63, min_sector: int = 5) -> pd.Series:
    """Each stock's cumulative return after removing the market and sector factors.

    For every stock, regress its daily returns over the last `n` sessions on
    [intercept, equal-weight market return, its sector's equal-weight return] and keep
    the INTERCEPT (alpha) times n — the cumulative daily drift the market and sector
    together do not explain. (Note: with an intercept in the regression the residuals
    sum to exactly zero by construction, so summing residuals would be a bug; the
    idiosyncratic slice of the cumulative return is alpha*n, since
    sum(r) = alpha*n + beta.market*sum(market) + beta.sector*sum(sector) + 0.)
    Stocks in sectors with < `min_sector` members (or with no sector label) are
    regressed on the market factor alone, so a thin sector can't manufacture a spurious
    factor. Solved once per sector (shared design matrix), not per stock.

    Look-ahead: purely descriptive of realized returns in the window — the factor on
    day t is that day's cross-section only. No future bars, no shift needed.
    Self-inclusion: a stock sits inside its own sector mean; the min_sector floor keeps
    that bias negligible (>=5 names) rather than leave-one-out, which is not worth the cost.

    Returns a Series indexed by symbol (higher = stronger idiosyncratic momentum),
    NaN-free, only for stocks that traded every session in the window.
    """
    block = close_wide.iloc[-(n + 1):]
    rets = block.pct_change(fill_method=None).iloc[1:]        # n rows
    rets = rets.dropna(axis=1)                                # fully-traded names only
    if rets.shape[1] < 2:
        return pd.Series(dtype=float)

    market = rets.mean(axis=1).values                        # equal-weight universe factor
    ones = np.ones(len(rets))
    sectors = sector_map.set_index("symbol")["industry"] if not sector_map.empty \
        else pd.Series(dtype=object)

    # Group tradable symbols by sector label (missing label -> its own market-only bucket).
    labels = pd.Series(rets.columns, index=rets.columns).map(sectors)
    resid_cum = {}
    for label, group in labels.groupby(labels, dropna=False):
        cols = list(group.index)
        Y = rets[cols].values                                # n × members
        if pd.notna(label) and len(cols) >= min_sector:
            sector_ret = rets[cols].mean(axis=1).values
            X = np.column_stack([ones, market, sector_ret])
        else:
            X = np.column_stack([ones, market])
        beta, *_ = np.linalg.lstsq(X, Y, rcond=None)         # rows: [alpha, betas...]
        alpha = beta[0]                                      # per-day idiosyncratic drift
        for c, a in zip(cols, alpha):
            resid_cum[c] = a * n                             # cumulative idiosyncratic return
    return pd.Series(resid_cum).dropna()


# ─────────────────────────────────────────────────────────────────────────────
# helpers
# ─────────────────────────────────────────────────────────────────────────────

def _standardize(returns: pd.DataFrame) -> pd.DataFrame:
    """Drop incomplete columns and zero-variance columns, then z-score each stock."""
    r = returns.dropna(axis=1)
    sd = r.std(ddof=0)
    r = r.loc[:, sd > 0]
    return (r - r.mean()) / r.std(ddof=0)


def _liquid_basket(close_wide: pd.DataFrame, max_names: int, lookback: int) -> pd.DataFrame:
    """The `max_names` most consistently-traded columns over the last `lookback` rows.

    Fewest NaNs = a liquidity proxy without needing the volume matrix here. Ties are
    broken by higher average price so we lean toward real, investable names over
    perpetually-halted penny stocks.
    """
    tail = close_wide.tail(lookback)
    traded = tail.notna().sum()
    rank = pd.DataFrame({"traded": traded, "px": tail.mean()})
    keep = rank.sort_values(["traded", "px"], ascending=False).head(max_names).index
    return tail[keep]
