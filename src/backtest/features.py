"""
features.py — per-stock daily feature store (date x symbol matrices).

Every feature is computed once over the full history cache and stored as its
own float32 parquet in data/processed/features/, in the same wide layout as
close_matrix — so every study joins them by (date, symbol) with zero recompute.
All features are causal: day t uses only data <= t's close.

Feature list (v1, 2026-07-25 — user + habitat-study driven):
  rs                composite RS rank (from the study cache)
  ti65              stock 7-DMA / 65-DMA (trend intensity)
  ret7 ret21 ret30  trailing returns %
  bounce_low21      % above the 21d low (how far it has bounced)
  pct_52wh pct_52wl % from 52-week high / low
  days_since_52wh   sessions since the last 252d closing high
  eff_ratio         efficiency ratio over 60d (|net move| / sum |daily moves|)
                    ~1 = clean linear mover, ~0 = chop ("linearity")
  adr20             average daily range % (20d)
  tightness         5d range as pct-rank of its own trailing year (low = tight)
  rvol50            volume / 50d mean volume
  volc5_50          5d mean vol / 50d mean vol (dry-up < 1)
  turn_decile       cross-sectional decile of 20d avg turnover (size/liquidity
                    proxy — true historical mcap unavailable)
  dist_50dma        % above the 50-DMA (extension)
  trend_age         sessions since close was last below the 200-DMA
  consol_days       consecutive sessions the 5d range has stayed <= 8% (base
                    length as of that day; use .shift(1) for pre-trigger length)
  days_since_burst  sessions since the previous +/-4% day, as of the PRIOR
                    close (shifted 1 bar so it is defined and causal on a
                    trigger day itself: 0 = burst was yesterday; NaN until
                    the stock's first-ever burst)
  burst_success     trailing-1yr share of the stock's 4% up-bursts that closed
                    higher 5 sessions later (personality; shifted 5d = causal)
  deliv_x20         delivery % / own 20d mean (2020-10+, NaN before).
                    Day t's value uses day t's DELIV_PER, which NSE publishes
                    in the EVENING — causal for anything entered at the D+1
                    open, but NOT knowable at a 15:20 same-day entry. It is the
                    only post-close-published input in this store; the research
                    engine tags it in NEXT_OPEN_FEATURES and refuses to grade a
                    close-entry verdict on it (research/machine/engine.py).
  sector_rs         sector's cross-sectional 21d-return rank (needs sector_map)

Feature list (v2, 2026-07-31 — trader-playbook genes for the GA):
  trend_template    Minervini stage-2 template, 0/1: close > 50DMA > 150DMA
                    > 200DMA and the 200DMA rising vs 21 sessions ago
  updown_vol50      O'Neil accumulation ratio: 50d up-day volume sum /
                    50d down-day volume sum
  pocket_pivot      Morales/Kacher, 0/1: up day whose volume exceeds the
                    max down-day volume of the prior 10 sessions
  rsline_pct52wh    IBD RS-line (close / equal-weight universe index) as
                    % below its own 252d high (0 = RS line at new high)

Build/refresh:  ~/anaconda3/bin/python src/backtest/features.py
Load:           from backtest.features import load_features
"""

import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "studies"))

_ROOT = os.path.join(os.path.dirname(__file__), "..", "..")
FEATURES_DIR = os.path.join(_ROOT, "data", "processed", "features")
DELIVERY = os.path.join(_ROOT, "data", "processed", "delivery_matrix.parquet")
SECTOR_MAP = os.path.join(_ROOT, "data", "processed", "sector_map.csv")


def _days_since(mask: pd.DataFrame) -> pd.DataFrame:
    """Sessions since `mask` was last True, per column. NaN before first True."""
    pos = pd.DataFrame(np.broadcast_to(np.arange(len(mask))[:, None], mask.shape),
                       index=mask.index, columns=mask.columns, dtype=float)
    return pos - pos.where(mask).ffill()


def build_all(m: dict) -> None:
    close, high, low, volume = m["close"], m["high"], m["low"], m["volume"]
    out = {}

    out["rs"] = m["rs"]
    out["ti65"] = close.rolling(7).mean() / close.rolling(65).mean()
    for n, name in ((7, "ret7"), (21, "ret21"), (30, "ret30")):
        out[name] = close.pct_change(n, fill_method=None) * 100
    out["bounce_low21"] = (close / low.rolling(21).min() - 1) * 100
    hi252, lo252 = close.rolling(252).max(), close.rolling(252).min()
    out["pct_52wh"] = (close / hi252 - 1) * 100
    out["pct_52wl"] = (close / lo252 - 1) * 100
    out["days_since_52wh"] = _days_since(close >= hi252)
    out["eff_ratio"] = ((close - close.shift(60)).abs()
                        / close.diff().abs().rolling(60).sum())
    out["adr20"] = ((high / low) - 1).rolling(20).mean() * 100
    rng5 = (high.rolling(5).max() - low.rolling(5).min()) / close
    out["tightness"] = rng5.rolling(252).rank(pct=True)
    vol50 = volume.rolling(50).mean()
    out["rvol50"] = volume / vol50
    out["volc5_50"] = volume.rolling(5).mean() / vol50
    turn20 = (close * volume).rolling(20).mean()
    out["turn_decile"] = turn20.rank(axis=1, pct=True)
    out["dist_50dma"] = (close / close.rolling(50).mean() - 1) * 100
    out["trend_age"] = _days_since(close < close.rolling(200).mean())

    rng5c = (high.rolling(5).max() - low.rolling(5).min()) / close
    tight5 = (rng5c <= 0.08).fillna(False)
    cs = tight5.cumsum()
    out["consol_days"] = (cs - cs.where(~tight5).ffill().fillna(0)).astype(float)

    chg = close.pct_change(fill_method=None)
    out["days_since_burst"] = _days_since(chg.abs() >= 0.04).shift(1)
    up_burst = chg >= 0.04
    fwd5_ok = (close.shift(-5) / close - 1) > 0
    out["burst_success"] = (fwd5_ok.where(up_burst).shift(5)
                            .rolling(252, min_periods=3).mean())

    sma50 = close.rolling(50).mean()
    sma150 = close.rolling(150).mean()
    sma200 = close.rolling(200).mean()
    out["trend_template"] = ((close > sma50) & (sma50 > sma150)
                             & (sma150 > sma200)
                             & (sma200 > sma200.shift(21))
                             ).astype(float).where(sma200.shift(21).notna())

    up = chg > 0
    upv = volume.where(up).rolling(50, min_periods=10).sum()
    dnv = volume.where(chg < 0).rolling(50, min_periods=10).sum()
    out["updown_vol50"] = upv / dnv

    max_dn_vol10 = volume.where(chg < 0).rolling(10, min_periods=1).max().shift(1)
    out["pocket_pivot"] = ((up & (volume > max_dn_vol10))
                           .astype(float).where(max_dn_vol10.notna()
                                                & chg.notna()))

    ew_index = (1 + chg.mean(axis=1)).cumprod()
    rs_line = close.div(ew_index, axis=0)
    out["rsline_pct52wh"] = (rs_line / rs_line.rolling(252).max() - 1) * 100

    if os.path.exists(DELIVERY):
        dm = pd.read_parquet(DELIVERY).reindex(index=close.index,
                                               columns=close.columns)
        out["deliv_x20"] = dm / dm.rolling(20, min_periods=10).mean()

    if os.path.exists(SECTOR_MAP):
        sm = pd.read_csv(SECTOR_MAP)
        sym_col = next(c for c in sm.columns if "symbol" in c.lower())
        sec_col = next(c for c in sm.columns
                       if c.lower() in ("sector", "industry"))
        groups = sm.groupby(sec_col)[sym_col].apply(list).to_dict()
        r21 = close.pct_change(21, fill_method=None)
        sec_med = pd.DataFrame({
            sec: r21[[s for s in syms if s in r21.columns]].median(axis=1)
            for sec, syms in groups.items()})
        sec_rank = sec_med.rank(axis=1, pct=True)
        srs = pd.DataFrame(np.nan, index=close.index, columns=close.columns)
        for sec, syms in groups.items():
            cols = [s for s in syms if s in srs.columns]
            srs[cols] = np.broadcast_to(sec_rank[sec].to_numpy()[:, None],
                                        (len(srs), len(cols)))
        out["sector_rs"] = srs

    os.makedirs(FEATURES_DIR, exist_ok=True)
    for name, df in out.items():
        df.astype("float32").to_parquet(
            os.path.join(FEATURES_DIR, f"{name}.parquet"), compression="snappy")
        print(f"  {name:<18} {df.shape}  non-null {df.notna().mean().mean() * 100:4.1f}%")


def list_features() -> list:
    if not os.path.isdir(FEATURES_DIR):
        return []
    return sorted(f[:-8] for f in os.listdir(FEATURES_DIR) if f.endswith(".parquet"))


def load_features(names: list = None) -> dict:
    names = names or list_features()
    return {n: pd.read_parquet(os.path.join(FEATURES_DIR, f"{n}.parquet"))
            for n in names}


if __name__ == "__main__":
    import common
    build_all(common.load_cache())
    print(f"\nFeature store -> {os.path.abspath(FEATURES_DIR)}")
