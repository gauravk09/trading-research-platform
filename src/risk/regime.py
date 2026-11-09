"""Market risk regime: the validated HMM crash-risk dial and the sizing it sets.

The model is H1 (3-state Gaussian HMM on Nifty 500 ret_20 + rvol_20) from
research/regime/, selected under rule 1A (risk skill) and confirmed on the
sealed 2025-26 lockbox (research/regime/CHANGELOG.md). It forecasts RISK, not
direction: P(Nifty 500 falls >=5% below today's close within 20 sessions).

Refit once a year, exactly as validated: train from 1996-01-01 through the
last Dec 31, minus a 60-row embargo so no training label peeks past that date.
Predictions are filtered (real-time) probabilities using closes up to today.

Sizing (untested mapping, the simplest rule the validation supports): the
dial is compared with the historical-average drop rate over the same training
window. At or below average -> CALM (full knobs); above -> ELEVATED (half).
"""
import os
import pickle
import sys

import pandas as pd

from data_collection.paths import ROOT_DIR

ROOT = ROOT_DIR
sys.path.insert(0, ROOT)
from research.regime import features, targets  # noqa: E402
from research.regime.models.base import Climatology  # noqa: E402
from research.regime.models.hmm_gaussian import GaussianHMM3State  # noqa: E402

LONG_CSV = os.path.join(ROOT, "data", "raw", "index_history_long", "nifty500_daily.csv")
LIVE_PARQUET = os.path.join(ROOT, "data", "parquet", "indices", "nifty500.parquet")
PROCESSED = os.path.join(ROOT, "data", "processed")
TRAIN_START = pd.Timestamp("1996-01-01")
EMBARGO_ROWS = 60

TIER_KNOBS = {
    "CALM":     {"risk_per_trade_pct": 0.35, "max_open_positions": 4,
                 "max_gross_exposure_pct": 75, "leverage_ok": False,
                 "allowed_entries": ["breakout", "episodic_pivot", "anticipation"]},
    "ELEVATED": {"risk_per_trade_pct": 0.175, "max_open_positions": 2,
                 "max_gross_exposure_pct": 40, "leverage_ok": False,
                 "allowed_entries": ["breakout", "episodic_pivot", "anticipation"]},
}
STATE_NAMES = {"regime_p_up": "calm-trend", "regime_p_chop": "choppy", "regime_p_down": "rough"}


def load_nifty500_close() -> pd.Series:
    """1995+ official history, extended with the live pipeline's newer closes."""
    hist = pd.read_csv(LONG_CSV, usecols=["date", "close"], parse_dates=["date"]).dropna()
    hist = hist.set_index("date")["close"]
    live = pd.read_parquet(LIVE_PARQUET)
    live["date"] = pd.to_datetime(live["date"]).dt.tz_localize(None).dt.normalize()
    live = live.set_index("date")["close"]
    close = pd.concat([hist, live[live.index > hist.index.max()]]).sort_index()
    close = close[~close.index.duplicated(keep="last")]
    close.name = "close"
    return close


def _fit(close: pd.Series, year: int):
    """Fit H1 + the climatology baseline on data through the end of year-1."""
    X = features.build_features(close)
    Y = targets.build_targets(close, open_lockbox=True)
    train = X.index[(X.index >= TRAIN_START) & (X.index < pd.Timestamp(f"{year}-01-01"))]
    train = train[:-EMBARGO_ROWS]
    model = GaussianHMM3State(knobs={}).fit(X.loc[train], Y.loc[train])
    baseline = Climatology().fit(X.loc[train], Y.loc[train])
    return {"model": model, "baseline": baseline, "trained_through": str(train[-1].date())}


def _fitted_for(close: pd.Series, year: int) -> dict:
    path = os.path.join(PROCESSED, f"risk_regime_hmm_{year}.pkl")
    if os.path.exists(path):
        with open(path, "rb") as f:
            return pickle.load(f)
    fitted = _fit(close, year)
    with open(path, "wb") as f:
        pickle.dump(fitted, f)
    return fitted


def walkforward_history(start_year: int = 2000, close: pd.Series = None) -> pd.DataFrame:
    """The dial as it would have read in real time: each year's rows come from
    the model fitted through the prior Dec 31 (no hindsight in past shading)."""
    close = load_nifty500_close() if close is None else close
    years = range(start_year, close.index[-1].year + 1)
    parts = [predict_history(close, year)
             for year in years]
    return pd.concat([p[p.index.year == y] for p, y in zip(parts, years)])


def predict_history(close: pd.Series = None, year: int = None) -> pd.DataFrame:
    """Filtered dial over all rows using the model for `year` (default: current)."""
    close = load_nifty500_close() if close is None else close
    fitted = _fitted_for(close, year or close.index[-1].year)
    X = features.build_features(close)
    pred = fitted["model"].predict(X)
    base = fitted["baseline"].predict(X)
    out = pd.DataFrame({
        "close": close,
        "p_drop_20d": pred["p_dd_20"],
        "baseline_p_drop_20d": base["p_dd_20"],
        "p_vol_high_20d": pred["p_vol_high_20"],
        "baseline_p_vol_high_20d": base["p_vol_high_20"],
        "state": pred[list(STATE_NAMES)].idxmax(axis=1).map(STATE_NAMES),
    })
    out["tier"] = (out["p_drop_20d"] > out["baseline_p_drop_20d"]).map({True: "ELEVATED", False: "CALM"})
    out.attrs["trained_through"] = fitted["trained_through"]
    return out.dropna(subset=["p_drop_20d"])


def evaluate(close: pd.Series = None) -> dict:
    """Today's regime block for the daily state file."""
    hist = predict_history(close)
    last = hist.iloc[-1]
    tier = last["tier"]
    return {
        "model": "H1_gaussian_hmm",
        "as_of": str(hist.index[-1].date()),
        "trained_through": hist.attrs["trained_through"],
        "tier": tier,
        "state": last["state"],
        "p_drop_20d": round(float(last["p_drop_20d"]), 4),
        "baseline_p_drop_20d": round(float(last["baseline_p_drop_20d"]), 4),
        "p_vol_high_20d": round(float(last["p_vol_high_20d"]), 4),
        "baseline_p_vol_high_20d": round(float(last["baseline_p_vol_high_20d"]), 4),
        "knobs": dict(TIER_KNOBS[tier]),
        "rule": "ELEVATED (half size) when P(>=5% drop in 20d) > its historical average; else CALM",
    }


if __name__ == "__main__":
    r = evaluate()
    print(f"{r['as_of']}: {r['tier']} | P(drop>=5% in 20d) {r['p_drop_20d']:.1%} "
          f"vs avg {r['baseline_p_drop_20d']:.1%} | state {r['state']} | trained through {r['trained_through']}")
