"""spec_simulator.py — walk each stock bar by bar and turn signals into trades.

One position per stock at a time. Daily bars only, so fills follow these rules
(the same order is used on every bar, the cautious one first):

  1. an exit queued by yesterday's close fills at today's OPEN
  2. the stop: if the bar trades through it, fill at the stop, or at the open
     when the stock gaps past it
  3. touch levels (partial targets, target_pct, target_r, trail_pct, and
     `high >= level` / `low <= level` exits): fill at the level, or at the open
     on a gap past it
  4. close conditions (`close < level`, `close < sma(...)`, signal exits) are
     seen at the close and queue an exit for the NEXT open; time exits fill at
     the close of their last bar

Entry clocks:
  next_open            signal on day t's close, fill at day t+1's open
  signal_close         fill at day t's close
  signal_close_strong  as signal_close, only if range_pos >= 0.75 (applied by the caller)

Returns are net of costs: costs_pct_per_side is charged on the way in and out.
r_multiple = net return / (|entry - stop| / entry); NaN when there is no stop.
A trade whose stop is already through the fill price is skipped, not entered.
"""

import math

import numpy as np

MAX_MISSING_BARS = 20     # repo delisting convention: 20 straight missing bars -> exit at last price


def simulate_stock(symbol, dates, bars, signal, stop, rules, clock, direction, cost_pct, dedup_bars):
    """Trades for one stock. `bars` = dict of 1-D arrays open/high/low/close.
    `signal`, `stop` and every rule array are aligned to the same dates."""
    o, h, l, c = bars["open"], bars["high"], bars["low"], bars["close"]
    n = len(c)
    long = direction == "long"
    trades, skipped = [], 0
    next_free_bar, last_taken_signal = 0, -10**9

    for s in np.flatnonzero(signal):
        if s < next_free_bar or s - last_taken_signal < dedup_bars:
            continue
        entry_bar = s + 1 if clock == "next_open" else s
        if entry_bar >= n:
            continue
        entry = o[entry_bar] if clock == "next_open" else c[s]
        stop_level = stop[s] if stop is not None else math.nan
        if not np.isfinite(entry) or _stop_through_entry(long, entry, stop_level):
            skipped += 1
            continue
        last_taken_signal = s
        legs, exit_bar = _manage(s, entry_bar, entry, stop_level, rules, o, h, l, c, clock, long)
        next_free_bar = exit_bar + 1
        trades.append(_record(symbol, dates, s, entry_bar, exit_bar, entry, stop_level, legs, long, cost_pct, clock))
    return trades, skipped


def _stop_through_entry(long, entry, stop_level):
    if not np.isfinite(stop_level):
        return False
    return stop_level >= entry if long else stop_level <= entry


def _manage(s, entry_bar, entry, stop_level, rules, o, h, l, c, clock, long):
    """Walk forward from entry until the whole position is closed. Return (legs, exit_bar)."""
    n = len(c)
    remaining = 1.0
    legs = []                  # (fraction, price, reason)
    done = set()               # partial rules already taken
    best = entry               # best price since entry, for trail_pct
    queued = None              # reason of an exit queued for the next open
    missing, last_bar = 0, entry_bar
    first_bar = entry_bar if clock == "next_open" else entry_bar + 1

    def close_out(price, reason, fraction=None):
        nonlocal remaining
        take = remaining if fraction is None else min(fraction, remaining)
        legs.append((take, price, reason))
        remaining -= take

    for b in range(first_bar, n):
        if not np.isfinite(c[b]):
            missing += 1
            if missing >= MAX_MISSING_BARS:
                close_out(c[last_bar], "data_gap")
                return legs, last_bar
            continue
        missing, last_bar = 0, b

        if queued:                                                   # 1. queued exit at the open
            close_out(o[b], queued)
            return legs, b

        if np.isfinite(stop_level) and _crossed(long, h[b], l[b], stop_level, against=True):   # 2. stop
            close_out(_gap_fill(long, o[b], stop_level, against=True), "stop")
            return legs, b

        for rule in rules:                                           # 3. touch levels
            level = _touch_level(rule, s, b, entry, stop_level, best, long)
            if level is None or rule["id"] in done:
                continue
            against = rule["kind"] == "trail_pct" or _touch_is_against(rule, long)
            if _crossed(long, h[b], l[b], level, against):
                close_out(_gap_fill(long, o[b], level, against), rule["id"], rule["fraction"])
                done.add(rule["id"])
                if remaining <= 1e-9:
                    return legs, b
        best = max(best, h[b]) if long else min(best, l[b])

        for rule in rules:                                           # 4. close conditions
            kind = rule["kind"]
            if kind == "time" and b - entry_bar >= rule["value"]:
                close_out(c[b], rule["id"])
                return legs, b
            if kind == "close_bool" and bool(rule["when"][b]):
                queued = rule["id"]
            if kind == "close_level" and _compare(rule["live"][b], rule["op"], rule["level"][s]):
                queued = rule["id"]
            if queued:
                break

    close_out(c[last_bar], "end_of_data")
    return legs, last_bar


def _touch_level(rule, s, b, entry, stop_level, best, long):
    """The price level a touch-type rule exits at on bar b, or None if the rule is not a touch."""
    kind, sign = rule["kind"], 1 if long else -1
    if kind == "touch_level":
        return rule["level"][s] if np.isfinite(rule["level"][s]) else None
    if kind == "target_pct":
        return entry * (1 + sign * rule["value"] / 100)
    if kind == "target_r":
        return entry + rule["value"] * (entry - stop_level) if np.isfinite(stop_level) else None
    if kind == "trail_pct":
        return best * (1 - sign * rule["value"] / 100)
    return None


def _touch_is_against(rule, long):
    """A touch_level exit on the losing side (e.g. `low <= level` for a long) behaves like a stop."""
    if rule["kind"] != "touch_level":
        return False
    downward = rule["op"] in ("<", "<=")
    return downward if long else not downward


def _crossed(long, high, low, level, against):
    """Did the bar trade through `level`? `against` = in the losing direction (stop-like)."""
    goes_down = against if long else not against
    return low <= level if goes_down else high >= level


def _gap_fill(long, open_, level, against):
    """Fill at the level, or at the open if the bar opened past it."""
    goes_down = against if long else not against
    return min(open_, level) if goes_down else max(open_, level)


def _compare(a, op, b):
    if not (np.isfinite(a) and np.isfinite(b)):
        return False
    return {">": a > b, ">=": a >= b, "<": a < b, "<=": a <= b, "==": a == b}[op]


def _record(symbol, dates, s, entry_bar, exit_bar, entry, stop_level, legs, long, cost_pct, clock):
    sign = 1 if long else -1
    gross = sum(f * sign * (price / entry - 1) for f, price, _ in legs)
    net = gross - 2 * cost_pct / 100
    risk = abs(entry - stop_level) / entry if np.isfinite(stop_level) else math.nan
    exit_price = sum(f * price for f, price, _ in legs) / sum(f for f, _, _ in legs)
    return {
        "asset": symbol,
        "side": "LONG" if long else "SHORT",
        "clock": clock,
        "signal": dates[s],
        "entry": dates[entry_bar],
        "exit": dates[exit_bar],
        "days": int(exit_bar - entry_bar),
        "entry_price": round(float(entry), 4),
        "exit_price": round(float(exit_price), 4),
        "stop_price": round(float(stop_level), 4) if np.isfinite(stop_level) else math.nan,
        "raw_ret": net,
        "r_multiple": net / risk if risk and np.isfinite(risk) else math.nan,
        "exit_reason": "+".join(reason for _, _, reason in legs),
    }
