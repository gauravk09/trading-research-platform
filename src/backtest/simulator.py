"""simulator.py — a generated strategy + the shared exit rules -> trades.

One position per stock at a time; a new signal on the same stock is ignored
until the open trade has closed and `DEDUP_BARS` have passed since the last
taken signal. Every trade is walked by backtest.exits.walk, the same exit code
the event store uses.

Entry clocks:
  next_open            signal on day t's close, fill at day t+1's open
  signal_close         fill at day t's close
  signal_close_strong  as signal_close, only if range_pos >= 0.75 (FACTORY lever 1)

For next_open the fill-price frame is tomorrow's open aligned to the signal
bar. It is only used to set the stop and target prices at fill time, never
inside a signal.

r is net of costs: costs_pct_per_side on the way in and on the way out,
converted to R (r = gross R - 2 x cost x entry / risk). A trade with no stop
has no R. A trade still open when the data ends is kept with exit_reason
"open" and no exit fields.
"""

import numpy as np
import pandas as pd

from backtest import exits

STRONG_CLOSE = 0.75


def signals(module, col, clock):
    """Signal frame: every universe and entry condition, plus the strong-close gate."""
    frames = list(module.universe_conditions(col).values()) + list(module.entry_conditions(col).values())
    signal = frames[0].fillna(False).astype(bool)
    for frame in frames[1:]:
        signal = signal & frame.fillna(False).astype(bool)
    if clock == "signal_close_strong":
        signal = signal & (col("range_pos") >= STRONG_CLOSE)
    return signal


def simulate(module, col, clock, signal=None):
    """All trades of one strategy at one entry clock, as a DataFrame."""
    signal = signals(module, col, clock) if signal is None else signal
    fill = col("open").shift(-1) if clock == "next_open" else col("close")
    stop = module.stop_level(col, fill)
    rules = module.exit_rules(col, fill)
    bars = {k: col(k).to_numpy(dtype=float) for k in ("open", "high", "low", "close")}
    dates = _calendar_dates(col("close").index)
    rows = []
    for j, symbol in enumerate(col("close").columns):
        rows += _trades_for_stock(module, clock, j, symbol, dates, bars, signal.iloc[:, j].to_numpy(),
                                  None if stop is None else stop.iloc[:, j].to_numpy(dtype=float), rules)
    return pd.DataFrame(rows, columns=["symbol", "signal_date", "entry_date", "entry_px", "exit_date",
                                       "exit_px", "exit_reason", "r"])


def trade(module, clock, j, d0, bars, stop_px, rules):
    """Walk one trade from signal bar d0 on stock column j. None if it can't be entered."""
    o, h, l, c = (bars[k][:, j] for k in ("open", "high", "low", "close"))
    entry_bar = d0 + 1 if clock == "next_open" else d0
    if entry_bar >= len(c):
        return None
    entry = o[entry_bar] if clock == "next_open" else c[d0]
    stop = _capped(module, entry, stop_px)
    if not np.isfinite(entry) or _through_entry(module.DIRECTION, entry, stop):
        return None
    risk = abs(entry - stop) if np.isfinite(stop) else np.nan
    plan = build_plan(module.DIRECTION, rules, j, d0, entry, stop, risk)
    return entry_bar, entry, risk, exits.walk(o, h, l, c, d0, entry, plan)


def build_plan(side, rules, j, d0, entry, stop, risk):
    """Spec exit rules -> an exits.ExitPlan. Levels are read once, on the signal bar."""
    sign = 1 if side == "long" else -1
    touches, close_exits, time_cap = [], [], None
    for rule in rules:
        kind = rule["kind"]
        if kind == "close_exit":
            close_exits.append(exits.CloseExit(rule["id"], rule["op"], float(rule["level"].iat[d0, j])))
        elif kind == "signal":
            close_exits.append(exits.CloseExit(rule["id"], when=rule["when"].iloc[:, j].fillna(False).to_numpy()))
        elif kind == "touch":
            touches.append(exits.Touch(rule["id"], float(rule["level"].iat[d0, j]), rule["fraction"]))
        elif kind == "target_pct":
            touches.append(exits.Touch(rule["id"], entry * (1 + sign * rule["value"] / 100), rule["fraction"]))
        elif kind == "target_r":
            if not np.isfinite(risk):
                raise ValueError(f"{rule['id']}: target_r needs a stop")
            touches.append(exits.Touch(rule["id"], entry + sign * rule["value"] * risk, rule["fraction"]))
        elif kind == "time":
            time_cap = rule["value"] if time_cap is None else min(time_cap, rule["value"])
    return exits.ExitPlan(side=side, stop=stop, touches=tuple(touches),
                          close_exits=tuple(close_exits), time_cap=time_cap)


def _trades_for_stock(module, clock, j, symbol, dates, bars, signal_col, stop_col, rules):
    rows, free_from, last_taken = [], 0, -10**9
    for d0 in np.flatnonzero(signal_col):
        if d0 < free_from or d0 - last_taken < module.DEDUP_BARS:
            continue
        stop_px = stop_col[d0] if stop_col is not None else np.nan
        walked = trade(module, clock, j, d0, bars, stop_px, rules)
        if walked is None:
            continue
        entry_bar, entry, risk, out = walked
        last_taken = d0
        free_from = out.legs[-1][3] + 1 if out.resolved else len(dates)
        rows.append(_row(module, symbol, dates, d0, entry_bar, entry, risk, out))
    return rows


def _row(module, symbol, dates, d0, entry_bar, entry, risk, out):
    row = {"symbol": symbol, "signal_date": dates[d0], "entry_date": dates[entry_bar],
           "entry_px": float(entry), "exit_date": None, "exit_px": None, "exit_reason": "open", "r": None}
    if out.resolved:
        size = sum(f for f, _, _, _ in out.legs)
        gross = out.r_multiple(entry, risk, module.DIRECTION) if np.isfinite(risk) else np.nan
        cost = 2 * module.COSTS_PCT_PER_SIDE / 100 * entry / risk if np.isfinite(risk) else np.nan
        row.update(exit_date=dates[out.legs[-1][3]],
                   exit_px=float(sum(f * p for f, p, _, _ in out.legs) / size),
                   exit_reason="+".join(reason for _, _, reason, _ in out.legs),
                   r=None if not np.isfinite(gross) else float(gross - cost))
    return row


def _capped(module, entry, stop):
    """Apply the spec's max_pct cap to the stop, using the shared exits.capped_stop."""
    if module.MAX_STOP_PCT is None or not np.isfinite(stop):
        return stop
    sign = 1 if module.DIRECTION == "long" else -1
    return exits.capped_stop(module.DIRECTION, entry, stop, 1 - sign * module.MAX_STOP_PCT / 100)


def _through_entry(side, entry, stop):
    if not np.isfinite(stop):
        return False
    return stop >= entry if side == "long" else stop <= entry


def _calendar_dates(index):
    """Trading dates as plain dates (the cache is midnight IST)."""
    index = pd.DatetimeIndex(index)
    if index.tz is not None:
        index = index.tz_convert("Asia/Kolkata").tz_localize(None)
    return np.array(index.date)
