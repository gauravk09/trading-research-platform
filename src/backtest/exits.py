"""exits.py — the one copy of every stop and exit rule (the fixed menu).

Used by event_store.py (its stop_r / trail rulers) and by simulator.py (spec
strategies), so a stop or a trail means the same thing everywhere.

A trade is walked bar by bar on daily data. Bars are counted from the SIGNAL
bar: bar 1 is the first bar after the signal (for a next-open entry, that is
the entry bar itself). Each bar is resolved in this order, the cautious one
first, because a daily bar cannot say which price came first:

  1. stop        long: low <= stop / short: high >= stop. Fills at the stop, or
                 at the open when the bar gaps through it.
  2. touches     resting orders at fixed prices (partial or full targets).
                 long: high >= level / short: low <= level. Fills at the level,
                 or at the open when the bar gaps past it.
  3. breakeven   once a bar touches `breakeven_at`, the stop moves to the entry
                 price, effective from the NEXT bar (step 1 already ran).
  4. close exits a close beyond a level (fixed at entry, read per bar, or
                 ratcheting in the trade's favour), or a True signal at the
                 close. Fills at the NEXT bar's open; at this bar's close if
                 there is no next bar.
  5. time cap    `time_cap` bars after the signal bar: fills at that close.

A missing bar (NaN close) or the end of the data before the trade closes
leaves it UNRESOLVED (the house convention: no partial marks). Everything here
is cost-blind; callers add costs.
"""

import operator
from dataclasses import dataclass, field

import numpy as np

COMPARE = {"<": operator.lt, "<=": operator.le, ">": operator.gt, ">=": operator.ge}


@dataclass(frozen=True)
class Touch:
    """A resting order at a fixed price; `fraction` of the ORIGINAL position."""
    reason: str
    level: float
    fraction: float = 1.0


@dataclass(frozen=True)
class CloseExit:
    """Exit at the next open when the close is `op` the level (or `when` is True).

    level    a float fixed at entry, or a 1-D per-bar array
    ratchet  per-bar level that only moves in the trade's favour
             (up for "<" / "<=", down for ">" / ">=")
    when     a 1-D per-bar boolean array, used instead of a level
    """
    reason: str
    op: str = "<"
    level: object = None
    ratchet: bool = False
    when: object = None


@dataclass(frozen=True)
class ExitPlan:
    side: str                       # "long" | "short"
    stop: float = np.nan            # NaN = no stop
    touches: tuple = ()
    breakeven_at: float = np.nan    # NaN = never move the stop
    close_exits: tuple = ()
    time_cap: int = None            # None = no time cap


@dataclass
class Outcome:
    legs: list = field(default_factory=list)   # (fraction, price, reason, bar)
    resolved: bool = False

    def r_multiple(self, entry, risk, side):
        """Return in R (cost-blind); NaN while unresolved."""
        if not self.resolved:
            return np.nan
        total = None
        for fraction, price, _, _ in self.legs:
            move = (price - entry) if side == "long" else (entry - price)
            term = fraction * move / risk
            total = term if total is None else total + term
        return total


def capped_stop(side, entry, extreme, cap_multiple):
    """Stop at the signal bar's extreme, but no further than entry x cap_multiple.

    long:  max(extreme, entry * cap_multiple), e.g. cap_multiple 0.94 = at most 6% below
    short: min(extreme, entry * cap_multiple), e.g. cap_multiple 1.06 = at most 6% above
    A NaN extreme gives a NaN stop (builtin max/min keep the first argument).
    """
    if side == "long":
        return max(extreme, entry * cap_multiple)
    return min(extreme, entry * cap_multiple)


def walk(o, h, l, c, signal_bar, entry, plan):
    """Walk one trade forward from `signal_bar`. o/h/l/c are one stock's 1-D arrays."""
    long = plan.side == "long"
    n = len(c)
    stop = plan.stop
    remaining = 1.0
    out = Outcome()
    taken = set()
    trail = {i: _ratchet_start(x.op) for i, x in enumerate(plan.close_exits) if x.ratchet}
    last_k = plan.time_cap if plan.time_cap is not None else n

    for k in range(1, last_k + 1):
        bar = signal_bar + k
        if bar >= n or np.isnan(c[bar]):
            return out                                          # unresolved

        if np.isfinite(stop) and (l[bar] <= stop if long else h[bar] >= stop):
            fill = min(o[bar], stop) if long else max(o[bar], stop)
            return _close(out, remaining, fill, "stop", bar)

        for i, touch in enumerate(plan.touches):
            if i in taken or not (h[bar] >= touch.level if long else l[bar] <= touch.level):
                continue
            fill = max(o[bar], touch.level) if long else min(o[bar], touch.level)
            size = min(touch.fraction, remaining)
            out.legs.append((size, fill, touch.reason, bar))
            remaining -= size
            taken.add(i)
            if remaining <= 1e-12:
                out.resolved = True
                return out

        if np.isfinite(plan.breakeven_at):
            if long and stop < entry and h[bar] >= plan.breakeven_at:
                stop = entry
            elif not long and stop > entry and l[bar] <= plan.breakeven_at:
                stop = entry

        for i, rule in enumerate(plan.close_exits):
            if _close_exit_hit(rule, i, bar, c[bar], trail):
                nxt = bar + 1
                if nxt < n and not np.isnan(o[nxt]):
                    return _close(out, remaining, o[nxt], rule.reason, nxt)
                return _close(out, remaining, c[bar], rule.reason, bar)

        if plan.time_cap is not None and k == plan.time_cap:
            return _close(out, remaining, c[bar], "time", bar)
    return out


def _close(out, remaining, price, reason, bar):
    out.legs.append((remaining, price, reason, bar))
    out.resolved = True
    return out


def _ratchet_start(op):
    return -np.inf if op in ("<", "<=") else np.inf


def _close_exit_hit(rule, i, bar, close, trail):
    if rule.when is not None:
        return bool(rule.when[bar])
    if rule.ratchet:
        level = rule.level[bar]
        rising = rule.op in ("<", "<=")
        if (level > trail[i]) if rising else (level < trail[i]):   # NaN never moves it
            trail[i] = level
        level = trail[i]
    elif np.ndim(rule.level):
        level = rule.level[bar]
    else:
        level = rule.level
    return bool(COMPARE[rule.op](close, level))
