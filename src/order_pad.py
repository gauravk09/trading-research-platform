"""order_pad.py — turn ranked candidates into EOD order tickets.

Read-only. Builds the ticket (side, qty, entry basis, stop, exit rule) and
the manual punch-in card for the Kite app. It never places, modifies or
cancels anything — placement is the user's, by platform policy (manual
execution mode: no static IP whitelisted, so Kite rejects order API calls)
and because executing trades is not the dashboard's job.

The thing this gets right that a plain scan list cannot: WHEN the order is
entered. The validated books enter at D+1 open, so their order is an AMO
punched tonight; Bonde's same-day setups are entered at 15:58 and are gone
once the bell rings. A ticket that ignores that is a different strategy
from the one that was backtested.
"""

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from risk_sizing import size_position

IST = ZoneInfo("Asia/Kolkata")

# family -> how this playbook is actually traded (from the validated books)
RULES = {
    "lone_loser_short": {
        "label": "F&O Lone-Loser Short",
        "side": "SELL",
        "when": "D+1 open",
        "window": "AMO tonight (or market order at tomorrow's 09:15 open)",
        "stop_rule": "min(signal-day high, entry × 1.06)",
        "exit_rule": "time exit at the close of D+5",
        "product": "MIS/NRML — F&O futures only, no overnight cash short",
    },
    "qullamaggie": {
        "label": "Tape-Gated Qullamaggie Breakout",
        "side": "BUY",
        "when": "D+1 open",
        "window": "AMO tonight (or market order at tomorrow's 09:15 open)",
        "stop_rule": "breakout-day low (capped 15% away)",
        "exit_rule": "half off at +1R, trail the rest on MA20 (max hold 120d)",
        "product": "CNC",
    },
    "reversal": {
        "label": "Dip-buy / reversal (tape rules)",
        "side": "BUY",
        "when": "today 15:58",
        "window": "SAME-DAY — enter just before the close, not tomorrow",
        "stop_rule": "today's low",
        "exit_rule": "no certified exit — treat as a swing, size small",
        "product": "CNC",
    },
    "breakout": {
        "label": "Breakout setup (Bonde)",
        "side": "BUY",
        "when": "today 15:58",
        "window": "SAME-DAY — enter just before the close, not tomorrow",
        "stop_rule": "breakout-day low",
        "exit_rule": "stop to breakeven day 3 if green; exit by day 5",
        "product": "CNC",
    },
}


def session_state(now=None):
    """Where we are in the trading day — decides which tickets are still
    actionable and whether an AMO is the right instrument."""
    now = now or datetime.now(IST)
    hm = now.strftime("%H:%M")
    if now.weekday() >= 5:
        return "weekend"
    if hm < "09:15":
        return "pre-open"
    if hm < "15:20":
        return "open"
    if hm <= "15:30":
        return "closing-window"
    return "after-close"


def next_session_date(now=None):
    """The next 09:15 open that has not happened yet. Once today's open is
    past (anything from 09:15 onward, including the closing window), a
    D+1-open entry belongs to TOMORROW — dating it today would send you to
    an open that already came and went."""
    now = now or datetime.now(IST)
    d = now.date()
    if now.strftime("%H:%M") >= "09:15" or now.weekday() >= 5:
        d += timedelta(days=1)
    while d.weekday() >= 5:
        d += timedelta(days=1)
    return d


def size(equity, risk_pct, entry, stop, side="BUY", **portfolio):
    """Compatibility facade; all quantity arithmetic lives in risk_sizing."""
    result = size_position(equity=equity, risk_pct=risk_pct, entry=entry,
                           stop=stop, side=side, **portfolio)
    return {**result, "value": result["notional"], "risk_inr": result["rupee_risk"]}


def ticket(symbol, family, entry, stop, equity, risk_pct, now=None, **portfolio):
    """One EOD order ticket. `entry` is the reference price (last close for an
    AMO — the real fill is tomorrow's open, which nobody knows tonight)."""
    rule = RULES[family]
    s = size(equity, risk_pct, entry, stop, side=rule["side"], **portfolio)
    state = session_state(now)
    same_day = rule["when"] == "today 15:58"

    # Mid-session the day's high/low is only the range SO FAR, so a stop taken
    # off it is too tight and the risk-based size therefore too big — often
    # several times too big early in the day. The backtests stop off the
    # COMPLETED day's extreme. Sizes are only firm once the range is done.
    provisional = state == "open"

    if same_day:
        actionable = state == "closing-window"
        note = ("enter NOW — closing window" if actionable else
                "MISSED for today — this setup is entered at 15:58; "
                "re-scan tomorrow" if state == "after-close" else
                f"not yet — wait for 15:20-15:30 (session: {state})")
    else:
        actionable = state in ("after-close", "closing-window", "pre-open",
                               "weekend")
        note = (f"punch AMO for {next_session_date(now)} open"
                if actionable else
                "wait for the close — this is a D+1-open entry, do not chase "
                "it intraday")

    if provisional:
        note = ("PROVISIONAL — the day's range is still forming, so this stop "
                "is too tight and this size too big. Re-read at 15:20. · "
                + note)

    return {"symbol": symbol, "playbook": rule["label"],
            "when": rule["when"], "window": rule["window"],
            "entry_ref": round(entry, 2), "stop": round(stop, 2),
            "stop_rule": rule["stop_rule"], "exit_rule": rule["exit_rule"],
            "product": rule["product"],
            "actionable": actionable and not provisional and s["accepted"],
            "provisional": provisional, "note": note, **s, "side": rule["side"]}


def punch_card(t):
    """The manual punch-in card for the Kite app — the primary output while
    order-placement APIs are blocked (no whitelisted static IP)."""
    if not t.get("qty"):
        reasons = "; ".join(reason["message"] for reason in t.get("rejection_reasons", []))
        return f"{t['symbol']}: cannot size — {reasons or 'stop distance unusable'}"
    amo = t["when"] == "D+1 open"
    lines = [
        (f"{t['symbol']} — {t['playbook']}" if not t.get("provisional") else
         f"{t['symbol']} — {t['playbook']}   *** PROVISIONAL — DO NOT PUNCH YET ***"),
        f"  WHEN   {t['window']}",
        f"  ENTRY  {t['side']} {t['qty']} {t['symbol']} "
        + ("MARKET (AMO)" if amo else "MARKET")
        + f"  [{t['product']}]   ref ₹{t['entry_ref']:,.2f} "
          f"≈ ₹{t['value']:,.0f}",
        f"  STOP   GTT {'BUY' if t['side'] == 'SELL' else 'SELL'} trigger "
        f"₹{t['stop']:,.2f}  ({t['stop_pct']}% away, risk ₹{t['risk_inr']:,.0f})",
        f"         limit {'above' if t['side'] == 'SELL' else 'below'} trigger "
        "by ~0.5% so it fills",
        f"  EXIT   {t['exit_rule']}",
        f"  ⚠ {t['note']}",
    ]
    if amo:
        lines.append("  NOTE   the backtested fill is tomorrow's OPEN — an AMO "
                     "market order reproduces it; a limit at today's close "
                     "does not.")
    return "\n".join(lines)


def plan_command(t):
    """Read-only CLI command that builds+validates a plan file. Placing it is
    a separate command the user runs themselves."""
    return (f"python src/orders/cli.py plan {t['symbol']} {t['side']} "
            f"--stop {t['stop']} --qty {t['qty']} --product "
            f"{t['product'].split('/')[0].split(' ')[0]} "
            f"--notes \"{t['playbook']} · {t['exit_rule']}\"")
