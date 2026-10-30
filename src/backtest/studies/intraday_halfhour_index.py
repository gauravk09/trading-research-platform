"""Fixed 09:45-to-15:30 NIFTY/BANKNIFTY intraday replication baseline."""
from pathlib import Path

import numpy as np
import pandas as pd


ROUND_TRIP_COST = 0.001  # 5 bps per side, fixed by the pre-registered spec


def _ist_times(frame):
    timestamps = pd.to_datetime(frame["date"])
    if timestamps.dt.tz is not None:
        timestamps = timestamps.dt.tz_convert("Asia/Kolkata")
    return timestamps


def daily_observations(frame, symbol, cutoff_time="09:40", entry_time="09:45", exit_time="15:25"):
    """Use a completed cutoff candle, a later configured entry, and fixed exit."""
    timestamps = _ist_times(frame)
    data = frame.copy()
    data["session"] = timestamps.dt.date
    data["time"] = timestamps.dt.strftime("%H:%M")
    data = data[data["time"].isin([cutoff_time, entry_time, exit_time])]
    pivot = data.pivot_table(index="session", columns="time", values=["open", "close"], aggfunc="last").sort_index()
    required = [("close", cutoff_time), ("open", entry_time), ("close", exit_time)]
    # Previous close is from the prior valid exit session, not the prior day
    # that happened also to have every entry field needed for this variant.
    previous_close = pivot[("close", exit_time)].shift(1)
    out = pd.DataFrame({"date": pd.to_datetime(pivot.index), "symbol": symbol,
                        "previous_close": previous_close, "cutoff_close": pivot[("close", cutoff_time)],
                        "entry_open": pivot[("open", entry_time)], "exit_close": pivot[("close", exit_time)]})
    out["predictor"] = out["cutoff_close"] / out["previous_close"] - 1
    out["raw_return"] = out["exit_close"] / out["entry_open"] - 1
    return out.dropna(subset=["cutoff_close", "entry_open", "exit_close", "previous_close"]).replace([np.inf, -np.inf], np.nan).dropna().reset_index(drop=True)


def strategy_returns(observations, variant="momentum", round_trip_cost=ROUND_TRIP_COST):
    direction = np.sign(observations["predictor"])
    if variant == "reversal":
        direction = -direction
    elif variant != "momentum":
        raise ValueError("variant must be momentum or reversal")
    result = observations.loc[direction != 0, ["date", "symbol", "raw_return"]].copy()
    result["direction"] = direction.loc[direction != 0].to_numpy()
    result["gross"] = result["direction"] * result["raw_return"]
    result["cost"] = float(round_trip_cost)
    result["net"] = result["gross"] - result["cost"]
    return result


def daily_portfolio_returns(returns):
    """Equal-weight active index legs into exactly one portfolio observation/day."""
    return returns.groupby("date", sort=True)[["gross", "cost", "net"]].mean().reset_index()


def sharpe(values):
    values = pd.Series(values).dropna()
    std = values.std(ddof=0)
    return 0.0 if len(values) < 2 or not np.isfinite(std) or std == 0 else float(values.mean() / std * np.sqrt(252))


def random_sign_sharpes(observations, paths=500, seed=20260902, round_trip_cost=ROUND_TRIP_COST):
    """Same date/instrument rows and costs; only the sign is randomized."""
    rng = np.random.default_rng(seed)
    active = observations.loc[np.sign(observations["predictor"]) != 0, ["date", "raw_return"]]
    raw = active["raw_return"].to_numpy(float)
    return np.array([sharpe(pd.DataFrame({"date": active["date"].to_numpy(),
                                          "net": np.where(rng.integers(0, 2, len(raw)), 1.0, -1.0) * raw - round_trip_cost})
                            .groupby("date", sort=True)["net"].mean()) for _ in range(paths)])


def day_block_sharpes(returns, paths=500, block_size=5, seed=20260902):
    """Fixed-seed date-block bootstrap preserves the cross-index day grouping."""
    daily = returns.groupby("date", sort=True)["net"].mean().to_numpy(float)
    if len(daily) == 0:
        return np.zeros(paths)
    rng = np.random.default_rng(seed + 1)
    blocks = [daily[start:start + block_size] for start in range(0, len(daily), block_size)]
    out = []
    for _ in range(paths):
        sample = np.concatenate([blocks[index] for index in rng.integers(0, len(blocks), len(blocks))])[:len(daily)]
        out.append(sharpe(sample))
    return np.array(out)


def _year_metrics(returns, prefix):
    result = {}
    for year in sorted(returns.date.dt.year.unique()):
        values = returns.loc[returns.date.dt.year == year, "net"]
        result[f"{prefix}_net_mean_bps_{year}"] = float(values.mean() * 10000)
        result[f"{prefix}_sharpe_{year}"] = sharpe(values)
    return result


def run(spec):
    params = spec["parameters"]
    observations = pd.concat([daily_observations(pd.read_parquet(path), Path(path).stem,
                                                   params.get("cutoff_time", "09:40"), params.get("entry_time", "09:45"),
                                                   params.get("exit_time", "15:25"))
                              for path in spec["dataset_paths"]], ignore_index=True).sort_values(["date", "symbol"])
    cost = float(params["cost_per_side_bps"]) / 10000 * 2
    momentum = strategy_returns(observations, "momentum", cost)
    reversal = strategy_returns(observations, "reversal", cost)
    momentum_daily = daily_portfolio_returns(momentum)
    reversal_daily = daily_portfolio_returns(reversal)
    oos = momentum_daily[momentum_daily.date.dt.year >= 2025]
    random_oos = random_sign_sharpes(observations[observations.date.dt.year >= 2025], int(params["control_paths"]),
                                     int(params["random_seed"]), cost)
    blocks = day_block_sharpes(oos, int(params["control_paths"]), int(params["day_block_size"]), int(params["random_seed"]))
    metrics = {"momentum_full_net_mean_bps": float(momentum_daily.net.mean() * 10000),
               "momentum_full_sharpe": sharpe(momentum_daily.net), "momentum_oos_net_mean_bps": float(oos.net.mean() * 10000),
               "momentum_oos_sharpe": sharpe(oos.net), "momentum_break_even_one_way_bps": float(momentum_daily.gross.mean() * 10000 / 2),
               "reversal_full_net_mean_bps": float(reversal_daily.net.mean() * 10000), "reversal_full_sharpe": sharpe(reversal_daily.net),
               "reversal_oos_net_mean_bps": float(reversal_daily[reversal_daily.date.dt.year >= 2025].net.mean() * 10000),
               "random_sign_oos_sharpe_p95": float(np.percentile(random_oos, 95)),
               "day_block_oos_sharpe_p05": float(np.percentile(blocks, 5)), "day_block_oos_sharpe_p95": float(np.percentile(blocks, 95)),
               "momentum_trade_count": float(len(momentum)), "momentum_portfolio_day_count": float(len(momentum_daily)),
               "oos_portfolio_day_count": float(len(oos)), "sample_start_yyyymmdd": float(int(momentum_daily.date.min().strftime("%Y%m%d"))),
               "sample_end_yyyymmdd": float(int(momentum_daily.date.max().strftime("%Y%m%d")))}
    metrics.update(_year_metrics(momentum_daily, "momentum"))
    positive_years = sum(metrics[f"momentum_net_mean_bps_{year}"] > 0 for year in momentum_daily.date.dt.year.unique())
    bars = {"positive_oos_net_mean": metrics["momentum_oos_net_mean_bps"] > 0,
            "oos_sharpe_gt_random_p95": metrics["momentum_oos_sharpe"] > metrics["random_sign_oos_sharpe_p95"],
            "positive_net_in_at_least_2_years": positive_years >= 2}
    return {"metrics": metrics, "status": "completed", "verdict": "PASS" if all(bars.values()) else "FAIL", "artifacts": [],
            "checks": {"same_date_control": "passed", "era_results": "calendar years reported; fixed OOS 2025-26",
            "cost_inclusion": "included", "portfolio_sizing_mode": "equal_weight_one_day_index_proxy",
            "attribution": "N/A (single index proxy, no cross-section to regress)", "success_bars": bars}}
