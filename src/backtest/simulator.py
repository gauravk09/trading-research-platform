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

exit_reason uses the trades-db vocabulary (.claude/skills/trades-db/SKILL.md):
  stop    the stop
  target  a resting target (touch, target_pct, target_r)
  trail   a close-based exit (close beyond a level, or a signal like close < sma20)
  time    the time cap
  delist  the stock stopped trading mid-trade: closed at its last close
  open    still open when the data ends: no exit fields, no r
A trade that took a partial first is labelled by its final exit.

r is net of costs: costs_pct_per_side on the way in and on the way out,
converted to R (r = gross R - 2 x cost x entry / risk). A trade with no stop
has no R.
"""

import numpy as np
import pandas as pd

from backtest import exits

STRONG_CLOSE = 0.75
COLUMNS = ["symbol", "side", "signal_date", "entry_date", "entry_px", "exit_date", "exit_px", "exit_reason", "r"]
REASON_BY_KIND = {"touch": "target", "target_pct": "target", "target_r": "target",
                  "close_exit": "trail", "signal": "trail"}


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
    """All trades of one strategy at one entry clock (signal_date is kept for the control run)."""
    signal = signals(module, col, clock) if signal is None else signal
    fill = col("open").shift(-1) if clock == "next_open" else col("close")
    stop = module.stop_level(col, fill)
    rules = module.exit_rules(col, fill)
    bars = {k: col(k).to_numpy(dtype=float) for k in ("open", "high", "low", "close")}
    dates = calendar_dates(col("close").index)
    rows = []
    for j, symbol in enumerate(col("close").columns):
        rows += _trades_for_stock(module, clock, j, symbol, dates, bars, signal.iloc[:, j].to_numpy(),
                                  None if stop is None else stop.iloc[:, j].to_numpy(dtype=float), rules)
    return pd.DataFrame(rows, columns=COLUMNS)


def entry_at(clock, j, d0, bars):
    """(entry_bar, entry price) for a signal on bar d0 of stock column j, or None."""
    entry_bar = d0 + 1 if clock == "next_open" else d0
    if entry_bar >= len(bars["close"]):
        return None
    entry = bars["open"][entry_bar, j] if clock == "next_open" else bars["close"][d0, j]
    return (entry_bar, entry) if np.isfinite(entry) else None


def frozen_levels(rules, j, d0):
    """Every level an exit rule fixes at entry, read on the signal bar."""
    return {r["id"]: float(r["level"].iat[d0, j]) for r in rules if r["kind"] in ("close_exit", "touch")}


def walk_trade(module, j, d0, entry, stop, rules, frozen, bars):
    """(risk, exits.Outcome) for one trade, or None if the stop is already through the entry."""
    if _through_entry(module.DIRECTION, entry, stop):
        return None
    risk = abs(entry - stop) if np.isfinite(stop) else np.nan
    plan = build_plan(module.DIRECTION, rules, j, entry, stop, risk, frozen)
    o, h, l, c = (bars[k][:, j] for k in ("open", "high", "low", "close"))
    return risk, exits.walk(o, h, l, c, d0, entry, plan)


def build_plan(side, rules, j, entry, stop, risk, frozen):
    """Spec exit rules -> an exits.ExitPlan. `frozen` holds the levels fixed at entry."""
    sign = 1 if side == "long" else -1
    touches, close_exits, time_cap = [], [], None
    for rule in rules:
        kind = rule["kind"]
        if kind == "close_exit":
            close_exits.append(exits.CloseExit(rule["id"], rule["op"], frozen[rule["id"]]))
        elif kind == "signal":
            close_exits.append(exits.CloseExit(rule["id"], when=rule["when"].iloc[:, j].fillna(False).to_numpy()))
        elif kind == "touch":
            touches.append(exits.Touch(rule["id"], frozen[rule["id"]], rule["fraction"]))
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


def capped(module, entry, stop):
    """Apply the spec's max_pct cap to the stop, using the shared exits.capped_stop."""
    if module.MAX_STOP_PCT is None or not np.isfinite(stop):
        return stop
    sign = 1 if module.DIRECTION == "long" else -1
    return exits.capped_stop(module.DIRECTION, entry, stop, 1 - sign * module.MAX_STOP_PCT / 100)


def row(module, rules, symbol, dates, d0, entry_bar, entry, risk, out, closes):
    """(trades-table row, exit bar or None). `closes` is the stock's close array, for a delisting exit."""
    legs = list(out.legs)
    if not out.resolved:
        last = _last_close_before_gap(closes, d0, entry_bar)
        if last is None:
            return _open_row(module, symbol, dates, d0, entry_bar, entry), None
        legs.append((1.0 - sum(f for f, _, _, _ in legs), closes[last], "delist", last))
    kinds = {r["id"]: r["kind"] for r in rules}
    final = legs[-1][2]
    gross = exits.Outcome(legs, True).r_multiple(entry, risk, module.DIRECTION) if np.isfinite(risk) else np.nan
    cost = 2 * module.COSTS_PCT_PER_SIDE / 100 * entry / risk if np.isfinite(risk) else np.nan
    exit_bar = legs[-1][3]
    return {"symbol": symbol, "side": module.DIRECTION, "signal_date": dates[d0], "entry_date": dates[entry_bar],
            "entry_px": float(entry), "exit_date": dates[exit_bar],
            "exit_px": float(sum(f * p for f, p, _, _ in legs) / sum(f for f, _, _, _ in legs)),
            "exit_reason": final if final in ("stop", "time", "delist") else REASON_BY_KIND[kinds[final]],
            "r": None if not np.isfinite(gross) else float(gross - cost)}, exit_bar


def calendar_dates(index):
    """Trading dates as plain dates (the cache is midnight IST)."""
    index = pd.DatetimeIndex(index)
    if index.tz is not None:
        index = index.tz_convert("Asia/Kolkata").tz_localize(None)
    return np.array(index.date)


def _trades_for_stock(module, clock, j, symbol, dates, bars, signal_col, stop_col, rules):
    rows, free_from, last_taken = [], 0, -10**9
    for d0 in np.flatnonzero(signal_col):
        if d0 < free_from or d0 - last_taken < module.DEDUP_BARS:
            continue
        entered = entry_at(clock, j, d0, bars)
        if entered is None:
            continue
        entry_bar, entry = entered
        stop = capped(module, entry, stop_col[d0] if stop_col is not None else np.nan)
        walked = walk_trade(module, j, d0, entry, stop, rules, frozen_levels(rules, j, d0), bars)
        if walked is None:
            continue
        risk, out = walked
        last_taken = d0
        trade, exit_bar = row(module, rules, symbol, dates, d0, entry_bar, entry, risk, out, bars["close"][:, j])
        rows.append(trade)
        free_from = len(dates) if exit_bar is None else exit_bar + 1
    return rows


def _last_close_before_gap(closes, d0, entry_bar):
    """The bar before the first missing close after d0, if the stock stopped trading mid-trade.
    None when the data simply ended (the trade is still open)."""
    gaps = np.flatnonzero(np.isnan(closes[d0 + 1:]))
    if not len(gaps):
        return None
    last = d0 + int(gaps[0])
    return last if last >= entry_bar else None


def _open_row(module, symbol, dates, d0, entry_bar, entry):
    return {"symbol": symbol, "side": module.DIRECTION, "signal_date": dates[d0], "entry_date": dates[entry_bar],
            "entry_px": float(entry), "exit_date": None, "exit_px": None, "exit_reason": "open", "r": None}


def _through_entry(side, entry, stop):
    if not np.isfinite(stop):
        return False
    return stop >= entry if side == "long" else stop <= entry
