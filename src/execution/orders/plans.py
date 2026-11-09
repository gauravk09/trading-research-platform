"""
plans.py — build, validate and preview order plans (no side effects).

A plan is one JSON file in output/orders/plans/ describing a complete trade:
entry order, protective GTT stop, optional GTT target (OCO) and optional
trailing-stop config. Only execute.py ever places anything; everything here
is read-only against the Kite API (LTP, margins, instrument master).
"""

import json
import os
from datetime import datetime
from zoneinfo import ZoneInfo


from data_collection.kite.auth import get_kite_client
from data_collection.paths import ROOT_DIR
from data_collection.kite.instruments import download_instruments
from risk.sizing import size_position

IST = ZoneInfo("Asia/Kolkata")
ORDERS_DIR = os.path.join(ROOT_DIR, "output", "orders")
PLANS_DIR = os.path.join(ORDERS_DIR, "plans")
JOURNAL_PATH = os.path.join(ORDERS_DIR, "..", "brief", "journal.jsonl")

GTT_MIN_GAP_PCT = 0.25    # Kite rejects GTT triggers closer than 0.25% to LTP
STOP_LIMIT_BUFFER_PCT = 0.5  # stop leg is a LIMIT order: price this far past trigger so it fills
MIN_TRAIL_PCT = 0.5       # trailing tighter than this would violate the trigger gap


def now_ist():
    return datetime.now(IST)


def instrument_row(symbol):
    df = download_instruments("NSE")
    rows = df[(df["tradingsymbol"] == symbol) & (df["instrument_type"] == "EQ")]
    if rows.empty:
        raise ValueError(f"{symbol} is not an NSE EQ instrument")
    return rows.iloc[0]


def round_to_tick(price, tick):
    return round(round(price / tick) * tick, 2)


def get_ltp(kite, symbol):
    key = f"NSE:{symbol}"
    return kite.ltp(key)[key]["last_price"]


def build_plan(symbol, side, stop, qty=None, risk_inr=None, limit_price=None,
               target=None, trail_pct=None, product="CNC", notes=""):
    """Resolve prices/quantity against live data and write the plan JSON."""
    if side not in ("BUY", "SELL"):
        raise ValueError("side must be BUY or SELL")
    if (qty is None) == (risk_inr is None):
        raise ValueError("give exactly one of qty or risk_inr")

    kite = get_kite_client()
    inst = instrument_row(symbol)
    tick = float(inst["tick_size"])
    ltp = get_ltp(kite, symbol)
    entry_price = round_to_tick(limit_price, tick) if limit_price else ltp

    stop = round_to_tick(stop, tick)
    if target is not None:
        target = round_to_tick(target, tick)
    if qty is None:
        # The CLI's --risk-inr is an absolute risk budget.  This adapter keeps
        # its public contract while delegating geometry and floor sizing to the
        # one shared risk engine (100% of synthetic equity = the budget).
        sizing = size_position(equity=float(risk_inr), risk_pct=100.0,
                               entry=entry_price, stop=stop, side=side,
                               max_positions=1, max_gross_exposure_pct=1e12,
                               max_heat_pct=100.0, leverage=1e12)
        if not sizing["accepted"]:
            detail = "; ".join(reason["message"] for reason in sizing["rejection_reasons"])
            raise ValueError(f"cannot size --risk-inr plan: {detail}")
        qty = sizing["qty"]

    plan = {
        "created": now_ist().isoformat(timespec="seconds"),
        "symbol": symbol,
        "exchange": "NSE",
        "side": side,
        "product": product,
        "entry": {"type": "LIMIT" if limit_price else "MARKET",
                  "price": entry_price if limit_price else None},
        "qty": qty,
        "stop": stop,
        "target": target,
        "trail_pct": trail_pct,
        "tick_size": tick,
        "ltp_at_build": ltp,
        "notes": notes,
    }

    os.makedirs(PLANS_DIR, exist_ok=True)
    fname = f"{now_ist():%Y-%m-%d_%H%M%S}_{side}_{symbol}.json"
    path = os.path.join(PLANS_DIR, fname)
    with open(path, "w") as f:
        json.dump(plan, f, indent=2)
    return path, plan


def load_plan(path):
    with open(path) as f:
        return json.load(f)


def validate_plan(plan, kite=None):
    """Return (errors, warnings). Errors block execution; warnings don't."""
    errors, warnings = [], []
    kite = kite or get_kite_client()
    ltp = get_ltp(kite, plan["symbol"])
    ref = plan["entry"]["price"] or ltp
    long = plan["side"] == "BUY"

    if plan["qty"] <= 0:
        errors.append("quantity is 0 — risk amount too small for this stop distance")
    if long and not plan["stop"] < ref:
        errors.append(f"stop {plan['stop']} must be below entry {ref} for a BUY")
    if not long and not plan["stop"] > ref:
        errors.append(f"stop {plan['stop']} must be above entry {ref} for a SELL")
    if plan["target"] is not None:
        if long and not plan["target"] > ref:
            errors.append(f"target {plan['target']} must be above entry {ref} for a BUY")
        if not long and not plan["target"] < ref:
            errors.append(f"target {plan['target']} must be below entry {ref} for a SELL")

    for name in ("stop", "target"):
        level = plan[name]
        if level is not None and abs(level - ltp) / ltp * 100 < GTT_MIN_GAP_PCT:
            errors.append(f"{name} {level} is within {GTT_MIN_GAP_PCT}% of LTP {ltp} — Kite will reject the GTT")

    if plan["trail_pct"] is not None:
        if not long:
            errors.append("trailing stop is only supported for BUY plans (long positions)")
        elif plan["trail_pct"] < MIN_TRAIL_PCT:
            errors.append(f"trail_pct must be >= {MIN_TRAIL_PCT} (GTT trigger gap rule)")

    if plan["side"] == "BUY":
        cost = plan["qty"] * ref
        try:
            avail = kite.margins("equity")["available"]["live_balance"]
            if cost > avail:
                errors.append(f"cost ₹{cost:,.0f} exceeds available balance ₹{avail:,.0f}")
        except Exception as e:
            warnings.append(f"could not check funds: {e}")

    try:
        from data_collection.nse.surveillance import get_excluded_symbols
        if plan["symbol"] in get_excluded_symbols():
            warnings.append(f"{plan['symbol']} is on the ASM/GSM surveillance list")
    except Exception as e:
        warnings.append(f"could not check ASM/GSM list: {e}")

    drift = abs(ltp - plan["ltp_at_build"]) / plan["ltp_at_build"] * 100
    if drift > 1:
        warnings.append(f"price moved {drift:.1f}% since the plan was built (LTP now {ltp})")

    now = now_ist()
    if now.weekday() >= 5 or not ("09:15" <= now.strftime("%H:%M") <= "15:30"):
        warnings.append("market is closed — a MARKET entry would sit as AMO-invalid; GTTs are fine anytime")

    contract_errors, contract_warnings = plan_contract_check(plan["symbol"])
    errors += contract_errors
    warnings += contract_warnings
    return errors, warnings


def plan_contract_check(symbol, journal_path=JOURNAL_PATH):
    """The gate layer (src/risk/plan_contract.py) decides in the brief; /trade only
    honours it. A symbol the latest journal entry REJECTED is an error — the
    reason travels with it. A symbol not in the plan at all is a warning
    (discretionary trades are allowed, but say so)."""
    try:
        with open(journal_path) as f:
            lines = [ln for ln in f.read().splitlines() if ln.strip()]
        entry = json.loads(lines[-1])
    except (OSError, IndexError, json.JSONDecodeError) as e:
        return [], [f"no plan contract to check against: {e}"]
    for rej in entry.get("rejected", []):
        if rej.get("symbol") == symbol:
            return [f"rejected by the {entry.get('date')} plan contract — {rej.get('reject_reason')}"], []
    if any(r.get("symbol") == symbol for r in entry.get("recommendations", [])):
        return [], []
    return [], [f"{symbol} is not in the {entry.get('date')} validated plan — discretionary trade"]


def format_preview(plan, errors, warnings):
    e = plan["entry"]
    entry_txt = f"LIMIT @ {e['price']}" if e["type"] == "LIMIT" else f"MARKET (~{plan['ltp_at_build']})"
    ref = e["price"] or plan["ltp_at_build"]
    risk = plan["qty"] * abs(ref - plan["stop"])
    lines = [
        f"{plan['side']} {plan['qty']} × {plan['symbol']} ({plan['product']})  —  {entry_txt}",
        f"  value  ₹{plan['qty'] * ref:,.0f}",
        f"  stop   {plan['stop']}  (risk ₹{risk:,.0f}, {abs(ref - plan['stop']) / ref * 100:.1f}% away)"
        + ("  + target " + str(plan["target"]) + " [GTT OCO]" if plan["target"] else "  [GTT single]"),
    ]
    if plan["trail_pct"]:
        lines.append(f"  trail  stop ratchets to {plan['trail_pct']}% below LTP (engine must be running)")
    for w in warnings:
        lines.append(f"  WARN   {w}")
    for err in errors:
        lines.append(f"  ERROR  {err}")
    lines.append("  → " + ("BLOCKED — fix errors above" if errors else "valid, ready to place"))
    return "\n".join(lines)
