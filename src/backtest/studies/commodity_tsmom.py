"""Pre-registered GC/SI/HG weekly time-series-momentum baseline.

Continuous Yahoo futures are a price proxy only: their roll methodology and
term-structure effects are not tradable-contract evidence.
"""
from pathlib import Path

import numpy as np
import pandas as pd


TRADING_DAYS = 252
ERAS = {"2001_2012": ("2001-01-01", "2012-12-31"),
        "2013_2019": ("2013-01-01", "2019-12-31"),
        "2020_2026": ("2020-01-01", "2026-12-31")}


def load_prices(paths):
    series = []
    for path in paths:
        frame = pd.read_parquet(path)
        symbol = Path(path).stem
        close = frame.assign(date=pd.to_datetime(frame["date"]))[["date", "close"]].dropna().drop_duplicates("date", keep="last")
        series.append(close.set_index("date")["close"].rename(symbol))
    return pd.concat(series, axis=1).sort_index()


def rebalance_dates(index):
    """Friday when present, otherwise the final available session of the week."""
    frame = pd.DataFrame(index=pd.DatetimeIndex(index))
    return frame.groupby(frame.index.to_period("W-FRI"), sort=True).apply(lambda group: group.index[-1]).tolist()


def signal_frames(prices, lookbacks=(21, 63, 126, 252), vol_lookback=63):
    returns = prices.pct_change(fill_method=None)
    signs = sum(np.sign(prices.pct_change(days, fill_method=None)) for days in lookbacks) / len(lookbacks)
    ensemble = np.sign(signs)
    sparse_signal = pd.DataFrame(np.nan, index=prices.index, columns=prices.columns)
    sparse_vol = sparse_signal.copy()
    vol = returns.rolling(vol_lookback, min_periods=vol_lookback).std() * np.sqrt(TRADING_DAYS)
    dates = rebalance_dates(prices.index)
    sparse_signal.loc[dates] = ensemble.loc[dates]
    sparse_vol.loc[dates] = vol.loc[dates]
    return returns, sparse_signal, sparse_vol


def weights_from_signals(sparse_signals, sparse_vol, target_vol=0.10, vol_cap=2.0, scaled=True):
    """Equal-risk weights; shift one complete daily row to prevent look-ahead."""
    signs = sparse_signals.ffill().shift(1)
    vols = sparse_vol.ffill().shift(1)
    available = signs.notna() & (signs != 0)
    if scaled:
        scale = (target_vol / vols).clip(upper=vol_cap)
        scale = scale.where(np.isfinite(scale) & (scale > 0))
        raw = signs * scale
    else:
        raw = signs
    count = raw.where(available).notna().sum(axis=1).replace(0, np.nan)
    return raw.div(count, axis=0).fillna(0.0)


def portfolio_returns(returns, weights, cost_per_turnover=0.0005):
    """Cost is 5 bps per one-way unit of aggregate notional turnover."""
    weights = weights.reindex_like(returns).fillna(0.0)
    turnover = weights.diff().abs().sum(axis=1)
    turnover.iloc[0] = weights.iloc[0].abs().sum()
    gross = (weights * returns.fillna(0.0)).sum(axis=1)
    costs = turnover * cost_per_turnover
    return pd.DataFrame({"gross": gross, "turnover": turnover, "cost": costs, "net": gross - costs})


def annualized_sharpe(returns):
    std = returns.std(ddof=0)
    return 0.0 if not np.isfinite(std) or std == 0 else float(returns.mean() / std * np.sqrt(TRADING_DAYS))


def cagr(returns):
    returns = returns.dropna()
    if len(returns) < 2:
        return 0.0
    wealth = float((1 + returns).prod())
    return float(wealth ** (TRADING_DAYS / len(returns)) - 1) if wealth > 0 else -1.0


def random_sign_control(sparse_signals, sparse_vol, paths=200, seed=20260902,
                        preserve_neutral=False, **weight_kwargs):
    """Randomize weekly directions; audit mode can preserve neutral cells."""
    rng = np.random.default_rng(seed)
    out = []
    valid = sparse_signals.notna()
    for _ in range(paths):
        random_signs = pd.DataFrame(np.where(rng.integers(0, 2, sparse_signals.shape) == 0, -1.0, 1.0),
                                    index=sparse_signals.index, columns=sparse_signals.columns).where(valid)
        if preserve_neutral:
            random_signs = random_signs.mask(sparse_signals.eq(0), 0.0)
        out.append(weights_from_signals(random_signs, sparse_vol, **weight_kwargs))
    return out


def _metrics(frame):
    result = {"net_cagr": cagr(frame["net"]), "net_sharpe": annualized_sharpe(frame["net"]),
              "gross_cagr": cagr(frame["gross"]), "total_cost": float(frame["cost"].sum())}
    for name, (start, end) in ERAS.items():
        result[f"net_cagr_{name}"] = cagr(frame.loc[start:end, "net"])
    return result


def run(spec):
    params = spec["parameters"]
    cost_per_turnover = float(params["cost_per_turnover"])
    prices = load_prices(spec["dataset_paths"])
    returns, signals, sparse_vol = signal_frames(prices, tuple(params["lookbacks"]), int(params["vol_lookback"]))
    unscaled = portfolio_returns(returns, weights_from_signals(signals, sparse_vol, scaled=False), cost_per_turnover)
    scaled_weights = weights_from_signals(signals, sparse_vol, float(params["target_annual_vol"]), float(params["vol_cap"]), True)
    scaled = portfolio_returns(returns, scaled_weights, cost_per_turnover)
    long_signals = pd.DataFrame(1.0, index=signals.index, columns=signals.columns).where(signals.notna())
    long_only = portfolio_returns(returns, weights_from_signals(long_signals, sparse_vol,
                                                                 float(params["target_annual_vol"]), float(params["vol_cap"]), True), cost_per_turnover)
    random_frames = [portfolio_returns(returns, weights, cost_per_turnover)
                     for weights in random_sign_control(signals, sparse_vol, int(params["random_paths"]), int(params["random_seed"]),
                                                        preserve_neutral=bool(params.get("preserve_neutral_control", False)),
                                                        target_vol=float(params["target_annual_vol"]), vol_cap=float(params["vol_cap"]), scaled=True)]
    random_sharpes = np.array([annualized_sharpe(frame["net"]) for frame in random_frames])
    metrics = {"unscaled_net_cagr": cagr(unscaled["net"]), **{f"scaled_{key}": value for key, value in _metrics(scaled).items()},
               "scaled_long_only_net_cagr": cagr(long_only["net"]), "scaled_long_only_sharpe": annualized_sharpe(long_only["net"]),
               "random_sharpe_p95": float(np.percentile(random_sharpes, 95)), "random_paths": float(len(random_sharpes))}
    positive_eras = sum(metrics[f"scaled_net_cagr_{name}"] > 0 for name in ERAS)
    bars = {"positive_net_full_cagr": metrics["scaled_net_cagr"] > 0,
            "positive_net_cagr_at_least_2_of_3_eras": positive_eras >= 2,
            "scaled_sharpe_gt_scaled_long_only": metrics["scaled_net_sharpe"] > metrics["scaled_long_only_sharpe"],
            "scaled_sharpe_gt_random_p95": metrics["scaled_net_sharpe"] > metrics["random_sharpe_p95"]}
    verdict = "PASS" if all(bars.values()) else "FAIL"
    return {"metrics": {key: float(value) for key, value in metrics.items()}, "status": "completed", "verdict": verdict,
            "artifacts": [], "checks": {"same_date_control": "passed", "era_results": "reported",
            "cost_inclusion": "included", "portfolio_sizing_mode": "equal_risk_vol_scaled",
            "attribution": "N/A (three futures, no equity cross-section to regress)",
            "success_bars": bars}}
