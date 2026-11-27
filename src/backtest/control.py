"""control.py — the same-date random-entry control run, stored as "<name>__control".

Without a control, a strategy's average R mixes its stock selection with the
market's move on those dates (beta). The control holds everything but the
selection fixed:

  dates     for every strategy trade, one random stock that was eligible on
            the SAME signal date (bookrunner.same_date_control, the house
            control; eligible = the spec's universe conditions)
  clock     the same entry clock
  geometry  the matched strategy trade's stop distance and frozen exit levels,
            as a ratio of entry. A random stock is rarely at its own breakout
            pivot, so its own pivot-based stop would usually sit above the
            entry and the trade would be skipped; scaling the strategy trade's
            geometry keeps every control trade valid and comparable
  exits     the same rules through the same shared exit code; live exits
            (e.g. close < sma20) read the control stock's own data
  costs     the same

The draw is seeded from the spec_hash, so the same spec on the same data gives
the same control. Compare a strategy with its control, not with zero.
"""

import numpy as np
import pandas as pd

from backtest import bookrunner, simulator


def control_trades(module, col, clock, strategy_trades, seed):
    """One control trade per strategy trade, as a DataFrame in the simulator's columns."""
    if strategy_trades.empty:
        return strategy_trades.iloc[0:0]
    close = col("close")
    dates = simulator.calendar_dates(close.index)
    date_pos = {d: i for i, d in enumerate(dates)}
    sym_pos = {s: j for j, s in enumerate(close.columns)}
    fill = col("open").shift(-1) if clock == "next_open" else close
    stop_frame = module.stop_level(col, fill)
    rules = module.exit_rules(col, fill)
    bars = {k: col(k).to_numpy(dtype=float) for k in ("open", "high", "low", "close")}

    matched = strategy_trades.assign(d0=strategy_trades["signal_date"].map(date_pos),
                                     js=strategy_trades["symbol"].map(sym_pos))
    matched = matched.sort_values("d0", kind="stable").reset_index(drop=True)
    picks = bookrunner.same_date_control({"close": close}, _eligible(module, col), matched["d0"].to_numpy(),
                                         k=1, seed=seed)
    rows = []
    for strategy, pick in zip(matched.itertuples(), picks.itertuples()):
        trade = _control_trade(module, clock, strategy, pick, bars, stop_frame, rules, dates)
        if trade is not None:
            rows.append(trade)
    return pd.DataFrame(rows, columns=strategy_trades.columns)


def seed_from(spec_hash):
    return int(spec_hash[:8], 16)


def _eligible(module, col):
    frames = list(module.universe_conditions(col).values())
    eligible = col("close").notna()
    for frame in frames:
        eligible = eligible & frame.fillna(False).astype(bool)
    return eligible


def _control_trade(module, clock, strategy, pick, bars, stop_frame, rules, dates):
    d0, js, jc = int(strategy.d0), int(strategy.js), int(pick.si)
    assert int(pick.di) == d0, "control pick is not on the strategy trade's date"
    entered = simulator.entry_at(clock, jc, d0, bars)
    if entered is None:
        return None
    entry_bar, entry = entered
    scale = entry / strategy.entry_px
    stop_s = stop_frame.iat[d0, js] if stop_frame is not None else np.nan
    stop = simulator.capped(module, strategy.entry_px, stop_s) * scale
    frozen = {k: v * scale for k, v in simulator.frozen_levels(rules, js, d0).items()}
    walked = simulator.walk_trade(module, jc, d0, entry, stop, rules, frozen, bars)
    if walked is None:
        return None
    risk, out = walked
    trade, _ = simulator.row(module, rules, pick.symbol, dates, d0, entry_bar, entry, risk, out, bars["close"][:, jc])
    return trade
