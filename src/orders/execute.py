"""
execute.py — place the orders described by a plan file (the only module
with side effects on the broker account).

Flow per plan: entry order (regular MARKET/LIMIT) → protective GTT
(single stop, or OCO stop+target) → optional trailing registration for
trail.py. Every broker action is appended to output/orders/orders_log.jsonl.
"""

import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from auth import get_kite_client
from orders.plans import (ORDERS_DIR, STOP_LIMIT_BUFFER_PCT, format_preview,
                          get_ltp, load_plan, now_ist, round_to_tick,
                          validate_plan)

LOG_FILE = os.path.join(ORDERS_DIR, "orders_log.jsonl")
TRAIL_FILE = os.path.join(ORDERS_DIR, "trailing.json")


def log_action(action, **fields):
    os.makedirs(ORDERS_DIR, exist_ok=True)
    record = {"ts": now_ist().isoformat(timespec="seconds"), "action": action, **fields}
    with open(LOG_FILE, "a") as f:
        f.write(json.dumps(record) + "\n")
    return record


def stop_leg_price(trigger, side_of_position, tick):
    """LIMIT price for a GTT stop leg: past the trigger so it actually fills."""
    sign = -1 if side_of_position == "BUY" else 1  # long exits sell below trigger
    return round_to_tick(trigger * (1 + sign * STOP_LIMIT_BUFFER_PCT / 100), tick)


def place_entry(kite, plan):
    kwargs = dict(
        variety=kite.VARIETY_REGULAR,
        exchange=plan["exchange"],
        tradingsymbol=plan["symbol"],
        transaction_type=plan["side"],
        quantity=plan["qty"],
        product=plan["product"],
        order_type=plan["entry"]["type"],
    )
    if plan["entry"]["type"] == "LIMIT":
        kwargs["price"] = plan["entry"]["price"]
    order_id = kite.place_order(**kwargs)
    log_action("entry_placed", order_id=order_id, symbol=plan["symbol"],
               side=plan["side"], qty=plan["qty"], entry=plan["entry"])
    return order_id


def place_protection(kite, plan):
    """GTT that exits the position: OCO if a target is set, else single stop."""
    exit_side = "SELL" if plan["side"] == "BUY" else "BUY"
    tick = plan["tick_size"]
    ltp = get_ltp(kite, plan["symbol"])

    def leg(price):
        return {"transaction_type": exit_side, "quantity": plan["qty"],
                "order_type": "LIMIT", "product": plan["product"], "price": price}

    stop_order = leg(stop_leg_price(plan["stop"], plan["side"], tick))
    if plan["target"] is not None:
        trigger_type = kite.GTT_TYPE_OCO
        triggers = [plan["stop"], plan["target"]]  # stop leg first, always index 0
        orders = [stop_order, leg(plan["target"])]
    else:
        trigger_type = kite.GTT_TYPE_SINGLE
        triggers = [plan["stop"]]
        orders = [stop_order]

    resp = kite.place_gtt(trigger_type=trigger_type, tradingsymbol=plan["symbol"],
                          exchange=plan["exchange"], trigger_values=triggers,
                          last_price=ltp, orders=orders)
    trigger_id = resp["trigger_id"]
    log_action("gtt_placed", trigger_id=trigger_id, symbol=plan["symbol"],
               triggers=triggers, oco=plan["target"] is not None)
    return trigger_id


def register_trailing(plan, trigger_id):
    configs = load_trailing()
    configs.append({
        "symbol": plan["symbol"],
        "trigger_id": trigger_id,
        "trail_pct": plan["trail_pct"],
        "tick_size": plan["tick_size"],
        "stop_leg": 0,
        "stop": plan["stop"],
        "registered": now_ist().isoformat(timespec="seconds"),
    })
    save_trailing(configs)
    log_action("trailing_registered", trigger_id=trigger_id,
               symbol=plan["symbol"], trail_pct=plan["trail_pct"])


def load_trailing():
    if not os.path.exists(TRAIL_FILE):
        return []
    with open(TRAIL_FILE) as f:
        return json.load(f)


def save_trailing(configs):
    os.makedirs(ORDERS_DIR, exist_ok=True)
    with open(TRAIL_FILE, "w") as f:
        json.dump(configs, f, indent=2)


def execute_plan(path):
    """Validate, show the preview, require a typed confirmation, then place."""
    plan = load_plan(path)
    kite = get_kite_client()
    errors, warnings = validate_plan(plan, kite)
    print(format_preview(plan, errors, warnings))
    if errors:
        return False

    answer = input("\nType PLACE to send these orders: ").strip().upper()
    if answer != "PLACE":
        print(f"Aborted — nothing was placed (you typed {answer!r}, PLACE was needed).")
        return False

    try:
        order_id = place_entry(kite, plan)
    except Exception as e:
        print(f"Entry order REJECTED, nothing placed: {e}")
        if "IP" in str(e):
            print("Static-IP allowlist error → add your current public IP "
                  "(curl -4 ifconfig.me) to the app at developers.kite.trade, "
                  "wait a minute, and retry.")
        log_action("entry_rejected", symbol=plan["symbol"], error=str(e))
        return False
    print(f"Entry order placed: {order_id}")

    try:
        trigger_id = place_protection(kite, plan)
    except Exception as e:
        log_action("gtt_rejected", symbol=plan["symbol"], error=str(e))
        print(f"\n*** ENTRY IS LIVE BUT THE STOP GTT FAILED: {e}")
        print(f"*** You hold {plan['qty']} {plan['symbol']} with NO protective stop.")
        print(f"*** Place the stop manually on Kite (GTT sell, trigger {plan['stop']}) "
              f"or exit the position.")
        return False
    print(f"Protective GTT placed: {trigger_id}"
          + (" (OCO stop + target)" if plan["target"] else " (stop only)"))
    if plan["trail_pct"]:
        register_trailing(plan, trigger_id)
        print(f"Trailing registered at {plan['trail_pct']}% — start the engine with: "
              f"python src/orders/cli.py trail-run")
    return True
