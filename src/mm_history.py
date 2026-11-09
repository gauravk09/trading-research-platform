"""mm_history.py — full-history Stockbee Market Monitor, for the
dashboard's 10-year "compare today to previous markets" view.

The fast-path close_matrix.parquet keeps only the last 252 rows per stock
(precompute.CLOSE_MATRIX_DAYS), so on-screen breadth is effectively ~1 year.
This module reads the complete per-stock history (2015 → today) into a full
close+volume matrix, computes the Market Monitor via regime.compute_market_monitor
(single source of truth), and adds an equal-weight forward-return proxy —
then caches it to data/processed/mm_history.parquet, a small ~2800-row artifact
the dashboard reads instantly.

Two caveats baked into every number here:
  - Survivorship: the stored files are today's surviving symbols, so pre-2018
    breadth and forward returns are measured over survivors only and skew
    slightly optimistic (delisted names are absent).
  - Warm-up: the 40-DMA / rolling windows need ~40 bars, so the first ~2 months
    of 2015 are unreliable — WARMUP_ROWS trims them from percentiles/analogs.

Rebuild the artifact standalone:
    python src/mm_history.py
"""

import os

import numpy as np
import pandas as pd

import data_collection.kite.index_history as index_history
import regime
from data_collection.storage import list_stored_symbols, read_daily

_PROCESSED = os.path.join(os.path.dirname(__file__), "..", "data", "processed")
HISTORY_PATH = os.path.join(_PROCESSED, "mm_history.parquet")

WARMUP_ROWS = 72            # index TI65 needs 65+7 bars; covers the 40-DMA too
FWD_HORIZONS = (5, 10, 20)  # forward-return horizons (trading days)

# Analog-finder features, grouped into themes. Distance = mean percentile-point
# gap per theme (Manhattan on ranks, each theme's vote split among its members):
#   - Rank space, NOT z-space: count features are violently fat-tailed (max |z|
#     ~16 on net20_5d vs ~2 on pct40ma) — z-scores let one crash-day spike
#     hijack the whole distance. Fractional nets (÷ active universe) keep 2015
#     and 2026 comparable despite the universe roughly doubling.
#   - Theme weights, NOT flat: correlated gauges double-count (the four TI65s
#     correlate 0.83-0.98 = one trend measured four times; pct40ma/pct20ma
#     0.74). One vote per theme fixes that without Mahalanobis' unstable,
#     unexplainable covariance estimate.
ANALOG_THEMES = {
    "participation": ["pct40ma", "pct20ma"],
    "burst_momentum": ["ratio10", "net4_pct", "net20_5d_pct"],
    "quarterly_breadth": ["net25q_pct"],
    "index_trend": ["ti65_nifty50", "ti65_nifty500",
                    "ti65_midcap150", "ti65_smallcap250"],
    "cycle_position": ["dd2y_nifty500", "dd2y_smallcap250"],
}


def _full_matrices() -> tuple[pd.DataFrame, pd.DataFrame]:
    """Every stored symbol's full close+volume history as wide date×symbol frames."""
    closes, volumes = {}, {}
    for sym in list_stored_symbols():
        df = read_daily(sym, columns=["date", "close", "volume"])
        if df.empty:
            continue
        df = df.set_index("date")
        closes[sym] = df["close"]
        volumes[sym] = df["volume"]
    return pd.DataFrame(closes).sort_index(), pd.DataFrame(volumes).sort_index()


def _pct20ma(cm: pd.DataFrame) -> pd.Series:
    """% of stocks above their 20-DMA ('both close and MA present' denominator)."""
    ma20 = cm.rolling(20).mean()
    active = cm.notna() & ma20.notna()
    return ((cm > ma20) & active).sum(axis=1) / active.sum(axis=1) * 100


def _forward_returns(cm: pd.DataFrame) -> pd.DataFrame:
    """Equal-weight median-stock forward return (%) at each horizon — the
    cross-sectional 'what the average stock did next', shown alongside the
    index returns. The last N rows are NaN by construction (no future yet)."""
    return pd.DataFrame(
        {f"fwd_{n}d": ((cm.shift(-n) / cm - 1).median(axis=1) * 100).round(2)
         for n in FWD_HORIZONS},
        index=cm.index)


def _index_columns(dates: pd.DatetimeIndex) -> pd.DataFrame:
    """Per-index TI65 (7-DMA / 65-DMA, Bonde's trend intensity) and forward
    returns, aligned to the monitor's dates. Empty frame (with a warning) when
    no index data is stored, so a fresh checkout still builds."""
    closes = index_history.load_closes()
    if closes.empty:
        print("  WARNING: no index data (run `PYTHONPATH=src python -m data_collection.kite.index_history`) — "
              "skipping TI65 features and index forward returns")
        return pd.DataFrame(index=dates)
    closes = closes.reindex(dates)
    out = {}
    for slug in closes.columns:
        c = closes[slug]
        out[f"ti65_{slug}"] = (c.rolling(7).mean() / c.rolling(65).mean()).round(4)
        out[f"ma1020_{slug}"] = (c.rolling(10).mean() / c.rolling(20).mean()).round(4)
        for n in FWD_HORIZONS:
            out[f"fwd_{slug}_{n}d"] = ((c.shift(-n) / c - 1) * 100).round(2)
    for slug in ("nifty500", "smallcap250"):
        # Cycle position: % below the 2-year high (0 = at highs, -40 = deep
        # bear). min_periods lets early 2015 use its partial lookback instead
        # of pushing the analog pool's warm-up out to ~2 years.
        if slug in closes.columns:
            c = closes[slug]
            out[f"dd2y_{slug}"] = ((c / c.rolling(504, min_periods=63).max()
                                    - 1) * 100).round(2)
    return pd.DataFrame(out, index=dates)


def build_history(write: bool = True, matrices: tuple = None) -> pd.DataFrame:
    """Full-history monitor + forward returns.
    Writes data/processed/mm_history.parquet when write=True.
    `matrices` = pre-loaded (close, volume) frames to skip the parquet read."""
    cm, vm = matrices if matrices is not None else _full_matrices()
    mm = regime.compute_market_monitor(cm, vm)
    mm["pct20ma"] = _pct20ma(cm)
    mm["active"] = cm.notna().sum(axis=1)
    for name, up, dn in [("net4", "up4", "dn4"), ("net25q", "up25q", "dn25q"),
                         ("net50m", "up50m", "dn50m"),
                         ("net20_5d", "up20_5d", "dn20_5d")]:
        mm[name] = mm[up] - mm[dn]
        mm[f"{name}_pct"] = (mm[name] / mm["active"] * 100).round(2)
    mm = mm.join(_forward_returns(cm))
    mm = mm.join(_index_columns(mm.index))
    if write:
        os.makedirs(_PROCESSED, exist_ok=True)
        mm.to_parquet(HISTORY_PATH, compression="snappy")
    return mm


# ── Analytics the dashboard renders (pure — no Streamlit) ──────────────────────

def year_summary(hist: pd.DataFrame) -> pd.DataFrame:
    """One row per calendar year, newest first: participation, extremes, and how
    the average day that year resolved."""
    rows = []
    for year, g in hist.groupby(hist.index.year):
        rows.append({
            "Year": int(year),
            "Days": len(g),
            "Median T2108": round(g["pct40ma"].median()),
            "Washout <20": int((g["pct40ma"] < 20).sum()),
            "Overheated >80": int((g["pct40ma"] > 80).sum()),
            "% green days": round((g["up4"] > g["dn4"]).mean() * 100),
            "Median 10d ratio": round(g["ratio10"].median(), 2),
            "Median fwd-20d %": round(g["fwd_20d"].median(), 1),
        })
    return pd.DataFrame(rows).sort_values("Year", ascending=False).reset_index(drop=True)


def today_percentiles(hist: pd.DataFrame) -> list[dict]:
    """Each headline signal's latest value, its percentile within the full
    history, and the distribution stats (p2/q1/median/q3/p98) the dashboard's
    boxplot strip renders. Skips MA warm-up rows. Uses the fractional net
    columns so old and new eras are comparable."""
    valid = hist.iloc[WARMUP_ROWS:]
    latest = hist.iloc[-1]
    # Grouped by the same themes the analog distance votes with (ANALOG_THEMES).
    # Index trend shows two of the four TI65s: they correlate 0.83-0.98, so the
    # large-cap/small-cap pair carries all the visual information.
    specs = [
        ("pct40ma", "T2108 (% > 40-DMA)", "Participation"),
        ("pct20ma", "% above 20-DMA", "Participation"),
        ("ratio10", "10-day 4% ratio", "Burst momentum"),
        ("net4_pct", "4%-movers net (% of mkt)", "Burst momentum"),
        ("net20_5d_pct", "20%-in-5-day net (% of mkt)", "Burst momentum"),
        ("net25q_pct", "25%-in-quarter net (% of mkt)", "Quarterly breadth"),
        ("ti65_nifty50", "Nifty 50 TI65", "Index trend"),
        ("ti65_smallcap250", "Smallcap 250 TI65", "Index trend"),
        ("dd2y_nifty500", "Nifty 500 off 2-yr high %", "Cycle position"),
        ("dd2y_smallcap250", "Smallcap off 2-yr high %", "Cycle position"),
    ]
    out = []
    for col, label, theme in specs:
        if col not in valid.columns:
            continue
        series = valid[col].dropna()
        val = latest.get(col)
        if not len(series) or pd.isna(val):
            continue
        p2, q1, med, q3, p98 = np.percentile(series, [2, 25, 50, 75, 98])
        out.append({"col": col, "label": label, "theme": theme,
                    "value": float(val),
                    "pct": round((series <= val).mean() * 100),
                    "p2": p2, "q1": q1, "med": med, "q3": q3, "p98": p98})
    return out


def find_analogs(hist: pd.DataFrame, n: int = 8, min_gap: int = 15) -> pd.DataFrame:
    """The historical days whose tape most resembles the latest day.

    Distance = mean percentile-point gap per theme: Manhattan distance on
    percentile ranks, with each feature weighted 1/themesize so every theme in
    ANALOG_THEMES casts exactly one vote (see the comment there for why ranks
    beat z-scores and why themes beat flat weights). A distance of 6 reads as
    "the two days' themes differ by ~6 percentile points on average".
    Tradeoff: ranks compress truly unprecedented extremes — the raw values in
    the table keep that visible. The pool skips TI65 warm-up and the last 21
    rows (incomplete forward returns), and picks are de-clustered so each
    analog is a distinct episode (>min_gap trading days apart).
    """
    themes = {t: [f for f in fs if f in hist.columns]
              for t, fs in ANALOG_THEMES.items()}
    themes = {t: fs for t, fs in themes.items() if fs}
    feats = [f for fs in themes.values() for f in fs]
    weights = pd.Series({f: 1 / len(fs) for fs in themes.values() for f in fs})
    ranks = hist[feats].rank(pct=True)
    gaps = (ranks - ranks.iloc[-1]).abs()
    dist = ((gaps * weights).sum(axis=1) / len(themes) * 100).to_numpy()

    lo, hi = WARMUP_ROWS, len(hist) - 21
    order = [i for i in np.argsort(dist)
             if lo <= i < hi and not np.isnan(dist[i])]

    picked: list[int] = []
    for i in order:
        if all(abs(i - p) > min_gap for p in picked):
            picked.append(i)
        if len(picked) >= n:
            break

    has_idx = "fwd_nifty50_20d" in hist.columns
    rows = []
    for i in picked:
        r = hist.iloc[i]
        row = {
            "Date": hist.index[i].strftime("%d %b %Y"),
            "T2108": round(r["pct40ma"]),
            "10d ratio": round(r["ratio10"], 2),
            "Distance": round(float(dist[i]), 2),
            "Stock 2w %": r["fwd_10d"],
            "Stock 4w %": r["fwd_20d"],
        }
        if has_idx:
            row.update({
                "N50 1w %": r["fwd_nifty50_5d"],
                "N50 2w %": r["fwd_nifty50_10d"],
                "N50 4w %": r["fwd_nifty50_20d"],
                "Smallcap 4w %": r["fwd_smallcap250_20d"],
            })
        rows.append(row)
    return pd.DataFrame(rows)


if __name__ == "__main__":
    hist = build_history()
    print(f"mm_history {hist.shape}  "
          f"{hist.index.min().date()} → {hist.index.max().date()}")
    print(f"  columns: {list(hist.columns)}")
    print(f"  written: {os.path.abspath(HISTORY_PATH)}")
