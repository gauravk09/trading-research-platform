"""Synthetic validation (spec Step 1 of the validation loop): a 3-state Markov
regime price generator with a KNOWN planted answer, plus an Oracle model
(knows the true generating state at t — legitimate, that's information
available at t, not the future) and a Random model (pure noise). If the
harness can't show Oracle >> Climatology >> Random on this data, it's broken.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .models.base import RegimeModel, StateToOdds, HORIZONS

STATE_DOWN, STATE_CHOP, STATE_UP = 0, 1, 2
STATE_NAMES = {STATE_DOWN: "regime_p_down", STATE_CHOP: "regime_p_chop", STATE_UP: "regime_p_up"}

STATE_PARAMS = {
    STATE_UP: {"drift": 0.0025, "vol": 0.007},
    STATE_CHOP: {"drift": 0.0, "vol": 0.009},
    STATE_DOWN: {"drift": -0.0030, "vol": 0.014},
}
STAY_PROB = 0.99

_OTHER_STATES = {
    STATE_UP: (STATE_CHOP, STATE_DOWN),
    STATE_CHOP: (STATE_UP, STATE_DOWN),
    STATE_DOWN: (STATE_CHOP, STATE_UP),
}


def generate_synthetic(n_rows: int = 3000, seed: int = 0, start: str = "2000-01-03",
                        state_params: dict | None = None) -> pd.DataFrame:
    """Returns a DataFrame indexed by business-day dates with columns
    'close' (price path) and 'state' (the TRUE generating state, 0/1/2 =
    down/chop/up — matches targets.TRUTH_DOWN/CHOPPY/UP encoding).

    `state_params` overrides the module-level STATE_PARAMS (used by
    power_curve() to scale regime separation without duplicating this
    function).
    """
    params = state_params if state_params is not None else STATE_PARAMS
    rng = np.random.default_rng(seed)
    states = np.empty(n_rows, dtype=int)
    states[0] = STATE_CHOP
    for i in range(1, n_rows):
        if rng.random() < STAY_PROB:
            states[i] = states[i - 1]
        else:
            states[i] = rng.choice(_OTHER_STATES[states[i - 1]])

    log_rets = np.empty(n_rows)
    prev = 0.0
    for i in range(n_rows):
        p = params[states[i]]
        r = rng.normal(p["drift"], p["vol"])
        if states[i] == STATE_CHOP and i > 0:
            r -= 0.15 * prev  # mild mean reversion inside chop
        log_rets[i] = r
        prev = r

    close = 100.0 * np.exp(np.cumsum(log_rets))
    dates = pd.bdate_range(start=start, periods=n_rows)
    df = pd.DataFrame({"close": close, "state": states}, index=dates)
    df.index.name = "date"
    return df


def _state_probs_onehot(state_series: pd.Series, index) -> pd.DataFrame:
    states = state_series.loc[index]
    probs = pd.DataFrame(0.0, index=index, columns=list(STATE_NAMES.values()))
    for code, col in STATE_NAMES.items():
        probs.loc[states == code, col] = 1.0
    return probs


class OracleModel(RegimeModel):
    name = "oracle"
    is_stochastic = False

    def __init__(self, state_series: pd.Series):
        super().__init__(knobs={})
        self.state_series = state_series
        self.s2o = StateToOdds()

    @property
    def n_fitted_knobs(self) -> int:
        return 0

    def fit(self, X_train: pd.DataFrame, Y_train: pd.DataFrame) -> "OracleModel":
        state_probs = _state_probs_onehot(self.state_series, X_train.index)
        levels = {f"band_{h}": [0, 1, 2] for h in HORIZONS}
        levels.update({f"dd_{h}": [0, 1] for h in HORIZONS})
        levels["vol_tercile_20"] = [0, 1, 2]
        self.s2o.fit(state_probs, Y_train, levels)
        return self

    def predict(self, X: pd.DataFrame) -> pd.DataFrame:
        state_probs = _state_probs_onehot(self.state_series, X.index)
        out = self._empty_predictions(X.index)
        for col in STATE_NAMES.values():
            out[col] = state_probs[col]
        for h in HORIZONS:
            odds = self.s2o.predict(state_probs, f"band_{h}")
            out[f"p_down_{h}"] = odds[0]
            out[f"p_flat_{h}"] = odds[1]
            out[f"p_up_{h}"] = odds[2]
            odds_dd = self.s2o.predict(state_probs, f"dd_{h}")
            out[f"p_dd_{h}"] = odds_dd[1]
        odds_vol = self.s2o.predict(state_probs, "vol_tercile_20")
        out["p_vol_low_20"] = odds_vol[0]
        out["p_vol_mid_20"] = odds_vol[1]
        out["p_vol_high_20"] = odds_vol[2]
        return out


class RandomModel(RegimeModel):
    """Random Dirichlet probabilities, independent of any information. Should
    score approximately zero or negative skill vs climatology.
    """

    name = "random"
    is_stochastic = True

    def __init__(self, seed: int = 0):
        super().__init__(knobs={"seed": seed})
        self.seed = seed

    @property
    def n_fitted_knobs(self) -> int:
        return 0

    def fit(self, X_train: pd.DataFrame, Y_train: pd.DataFrame) -> "RandomModel":
        return self

    def predict(self, X: pd.DataFrame) -> pd.DataFrame:
        rng = np.random.default_rng(self.seed)
        n = len(X)
        out = self._empty_predictions(X.index)
        out[list(STATE_NAMES.values())] = rng.dirichlet([1, 1, 1], size=n)
        for h in HORIZONS:
            probs3 = rng.dirichlet([1, 1, 1], size=n)
            out[f"p_down_{h}"] = probs3[:, 0]
            out[f"p_flat_{h}"] = probs3[:, 1]
            out[f"p_up_{h}"] = probs3[:, 2]
            out[f"p_dd_{h}"] = rng.random(n)
        vol3 = rng.dirichlet([1, 1, 1], size=n)
        out["p_vol_low_20"] = vol3[:, 0]
        out["p_vol_mid_20"] = vol3[:, 1]
        out["p_vol_high_20"] = vol3[:, 2]
        return out


def power_curve(scales=(0.1, 0.25, 0.5, 1.0), seeds=range(10), n_rows: int | None = None,
                 window_config="default") -> pd.DataFrame:
    """Statistical power of the harness at varying synthetic regime
    separation (spec-review item F5). STATE_PARAMS at scale=1.0 was widened
    during Stage A build until the Oracle validation test passed, so the
    harness's power at REALISTIC separations was previously unknown.

    For each scale, both the drift GAP and the vol GAP of up/down relative
    to chop are multiplied by `scale` (chop itself never moves), the Oracle
    model is run through the real walk-forward pipeline for every seed, and
    this reports the share of seeds where the 20d skill's 95% CI lower
    bound clears zero, plus the median 20d skill and median 20d-up ECE.

    `window_config` (data.WINDOW_CONFIGS name or dict, spec-review item G2)
    controls both which walk-forward folds run_walkforward uses AND the
    synthetic series' start date (its own warmup_start), so a "long" run
    actually tests 2000-2024 on 1995+ data instead of silently falling back
    to the 2018-2024 default folds.

    Nothing here is tuned to make any particular scale look good -- it is a
    report, run once and written verbatim into README.md's "Statistical
    power" section, not a pass/fail test.

    `n_rows` defaults to None: when not given, it is derived from
    `window_config` so the generated series actually covers every test fold
    (warmup_start through the end of last_test_year, business days). A fixed
    default of 3000 rows from warmup_start silently produced too SHORT a
    series for the "long" config (warmup_start 1995 + 3000 business days ends
    around 2006), leaving test folds 2007-2024 empty -- the bug this
    parameter change fixes.
    """
    from . import data as _data, features as _features, runner as _runner, targets as _targets

    cfg = _data.get_window_config(window_config)
    start = cfg["warmup_start"]
    if n_rows is None:
        end = pd.Timestamp(f"{cfg['last_test_year']}-12-31")
        n_rows = len(pd.bdate_range(start=start, end=end))

    chop = STATE_PARAMS[STATE_CHOP]
    seeds = list(seeds)
    rows = []
    for scale in scales:
        scaled_params = {
            STATE_CHOP: dict(chop),
            STATE_UP: {
                "drift": chop["drift"] + scale * (STATE_PARAMS[STATE_UP]["drift"] - chop["drift"]),
                "vol": chop["vol"] + scale * (STATE_PARAMS[STATE_UP]["vol"] - chop["vol"]),
            },
            STATE_DOWN: {
                "drift": chop["drift"] + scale * (STATE_PARAMS[STATE_DOWN]["drift"] - chop["drift"]),
                "vol": chop["vol"] + scale * (STATE_PARAMS[STATE_DOWN]["vol"] - chop["vol"]),
            },
        }
        skills, eces, n_pass = [], [], 0
        for seed in seeds:
            df = generate_synthetic(n_rows=n_rows, seed=seed, start=start, state_params=scaled_params)
            close = df["close"]
            X = _features.build_features(close)
            Y = _targets.build_targets(close, open_lockbox=False)
            state = df["state"]
            oracle_pred, clim_pred, _ = _runner.run_walkforward(
                lambda k, s=state: OracleModel(s), {}, X, Y, window_config=cfg
            )
            metrics = _runner.score_predictions(oracle_pred, clim_pred, Y, eras=cfg["eras"])
            skill = metrics["rps_skill_20"]
            ci_lo = metrics["rps_skill_20_ci_lo"]
            ece_up = metrics.get("ece_20d_up", np.nan)
            skills.append(skill)
            eces.append(ece_up)
            if not np.isnan(ci_lo) and ci_lo > 0:
                n_pass += 1
        rows.append({
            "scale": scale,
            "up_drift_annualized": scaled_params[STATE_UP]["drift"] * 252,
            "down_drift_annualized": scaled_params[STATE_DOWN]["drift"] * 252,
            "share_ci_lower_positive": n_pass / len(seeds),
            "median_skill_20d": float(np.median(skills)),
            "median_ece_20d_up": float(np.nanmedian(eces)),
            "n_seeds": len(seeds),
        })
    return pd.DataFrame(rows)


def real_nifty500_annualized_drift_vol() -> dict:
    """Nifty 500's actual annualized drift and volatility over the dev
    window (2015-01-01 .. 2024-12-31), computed OVERALL (not per-regime),
    for comparison against the synthetic generator's separation. This never
    touches lockbox dates.
    """
    from . import data as _data

    close = _data.load_close()
    dev = close[(close.index >= _data.DEV_START) & (close.index <= _data.DEV_END)]
    log_rets = np.log(dev / dev.shift(1)).dropna()
    return {
        "annualized_drift": float(log_rets.mean() * 252),
        "annualized_vol": float(log_rets.std() * np.sqrt(252)),
        "n_days": int(len(log_rets)),
    }
