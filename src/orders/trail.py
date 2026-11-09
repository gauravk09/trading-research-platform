"""
trail.py — trailing-stoploss engine.

Kite has no native trailing stop for CNC, so this loop polls LTP during
market hours and ratchets the stop trigger of each registered GTT upward
(never downward) to trail_pct below the latest price. State lives in the
GTT itself — restarting the engine just resumes from the current trigger.

Run: python src/orders/cli.py trail-run [--interval 60] [--once]
"""

import math
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from data_collection.kite.auth import get_kite_client
from orders.execute import (load_trailing, log_action, save_trailing,
                            stop_leg_price)
from orders.plans import get_ltp, now_ist

LOG = os.path.join(os.path.dirname(__file__), "..", "..", "logs", "trailing.log")


def say(msg):
    line = f"{now_ist():%Y-%m-%d %H:%M:%S}  {msg}"
    print(line)
    os.makedirs(os.path.dirname(LOG), exist_ok=True)
    with open(LOG, "a") as f:
        f.write(line + "\n")


def market_open():
    now = now_ist()
    return now.weekday() < 5 and "09:15" <= now.strftime("%H:%M") <= "15:30"


def floor_to_tick(price, tick):
    return round(math.floor(price / tick) * tick, 2)


def ratchet(kite, cfg):
    """Raise one GTT's stop if price has moved up. Returns cfg, or None to drop it."""
    gtt = kite.get_gtt(cfg["trigger_id"])
    if gtt["status"] != "active":
        say(f"{cfg['symbol']}: GTT {cfg['trigger_id']} is {gtt['status']} — removing from trailing")
        log_action("trailing_removed", trigger_id=cfg["trigger_id"],
                   symbol=cfg["symbol"], gtt_status=gtt["status"])
        return None

    ltp = get_ltp(kite, cfg["symbol"])
    tick = cfg["tick_size"]
    new_stop = floor_to_tick(ltp * (1 - cfg["trail_pct"] / 100), tick)
    leg = cfg["stop_leg"]
    current = gtt["condition"]["trigger_values"][leg]
    if new_stop <= current:
        return cfg

    triggers = list(gtt["condition"]["trigger_values"])
    triggers[leg] = new_stop
    orders = []
    for i, o in enumerate(gtt["orders"]):
        price = stop_leg_price(new_stop, "BUY", tick) if i == leg else o["price"]
        orders.append({"transaction_type": o["transaction_type"],
                       "quantity": o["quantity"], "order_type": o["order_type"],
                       "product": o["product"], "price": price})

    kite.modify_gtt(trigger_id=cfg["trigger_id"], trigger_type=gtt["type"],
                    tradingsymbol=cfg["symbol"], exchange="NSE",
                    trigger_values=triggers, last_price=ltp, orders=orders)
    say(f"{cfg['symbol']}: stop {current} → {new_stop} (LTP {ltp})")
    log_action("stop_trailed", trigger_id=cfg["trigger_id"], symbol=cfg["symbol"],
               old_stop=current, new_stop=new_stop, ltp=ltp)
    cfg["stop"] = new_stop
    return cfg


def run(interval=60, once=False):
    kite = get_kite_client()
    while True:
        configs = load_trailing()
        if not configs:
            say("no trailing configs registered — nothing to do")
            return
        if market_open():
            kept = []
            for cfg in configs:
                try:
                    updated = ratchet(kite, cfg)
                except Exception as e:
                    say(f"{cfg['symbol']}: error, will retry next cycle — {e}")
                    updated = cfg
                if updated is not None:
                    kept.append(updated)
            save_trailing(kept)
        else:
            say("market closed — idle")
        if once:
            return
        time.sleep(interval)
