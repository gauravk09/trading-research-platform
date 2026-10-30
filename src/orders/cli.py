"""
cli.py — single command-line entry point for the order module.

  plan       build + preview a plan JSON (no orders placed)
  preview    re-validate an existing plan against live prices
  place      preview, then place after a typed PLACE confirmation
  status     open orders, GTTs, positions, holdings, funds
  cancel     cancel a pending regular order (typed confirmation)
  delete-gtt delete a GTT (typed confirmation)
  trail-run  start the trailing-stop engine
  trail-list show registered trailing configs

Examples:
  python src/orders/cli.py plan RELIANCE BUY --qty 10 --stop 1450 --target 1580 --trail 2
  python src/orders/cli.py plan TATAPOWER BUY --risk-inr 5000 --stop 405 --limit 416.5
  python src/orders/cli.py place output/orders/plans/2026-07-14_101500_BUY_RELIANCE.json
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from auth import get_kite_client


def cmd_plan(args):
    from orders.plans import build_plan, format_preview, validate_plan
    path, plan = build_plan(
        symbol=args.symbol.upper(), side=args.side.upper(), stop=args.stop,
        qty=args.qty, risk_inr=args.risk_inr, limit_price=args.limit,
        target=args.target, trail_pct=args.trail, product=args.product,
        notes=args.notes)
    errors, warnings = validate_plan(plan)
    print(format_preview(plan, errors, warnings))
    print(f"\nPlan saved: {os.path.relpath(path)}")
    if not errors:
        print(f"To execute:  python src/orders/cli.py place '{os.path.relpath(path)}'")


def cmd_preview(args):
    from orders.plans import format_preview, load_plan, validate_plan
    plan = load_plan(args.plan)
    errors, warnings = validate_plan(plan)
    print(format_preview(plan, errors, warnings))


def cmd_place(args):
    from orders.execute import execute_plan
    ok = execute_plan(args.plan)
    sys.exit(0 if ok else 1)


def cmd_status(args):
    kite = get_kite_client()
    pending = [o for o in kite.orders()
               if o["status"] in ("OPEN", "TRIGGER PENDING", "AMO REQ RECEIVED")]
    print(f"Pending orders ({len(pending)}):")
    for o in pending:
        px = o["price"] or o["trigger_price"] or "MKT"
        print(f"  {o['order_id']}  {o['transaction_type']} {o['quantity']} "
              f"{o['tradingsymbol']} @ {px}  [{o['status']}]")

    gtts = [g for g in kite.get_gtts() if g["status"] == "active"]
    print(f"\nActive GTTs ({len(gtts)}):")
    for g in gtts:
        print(f"  {g['id']}  {g['condition']['tradingsymbol']}  "
              f"triggers {g['condition']['trigger_values']}  [{g['type']}]")

    positions = [p for p in kite.positions()["net"] if p["quantity"] != 0]
    print(f"\nOpen positions ({len(positions)}):")
    for p in positions:
        print(f"  {p['tradingsymbol']}  {p['quantity']} @ {p['average_price']}  "
              f"P&L {p['pnl']:,.0f}")

    holdings = [h for h in kite.holdings() if h["quantity"] > 0]
    print(f"\nHoldings ({len(holdings)}):")
    for h in holdings:
        print(f"  {h['tradingsymbol']}  {h['quantity']} @ {h['average_price']}  "
              f"LTP {h['last_price']}  P&L {h['pnl']:,.0f}")

    avail = kite.margins("equity")["available"]["live_balance"]
    print(f"\nAvailable balance: ₹{avail:,.0f}")


def confirm_or_abort(prompt):
    if input(f"Type YES to {prompt}: ").strip().upper() != "YES":
        print("Aborted.")
        sys.exit(1)


def cmd_cancel(args):
    from orders.execute import log_action
    kite = get_kite_client()
    confirm_or_abort(f"cancel order {args.order_id}")
    kite.cancel_order(variety=kite.VARIETY_REGULAR, order_id=args.order_id)
    log_action("order_cancelled", order_id=args.order_id)
    print("Cancelled.")


def cmd_delete_gtt(args):
    from orders.execute import load_trailing, log_action, save_trailing
    kite = get_kite_client()
    confirm_or_abort(f"delete GTT {args.trigger_id}")
    kite.delete_gtt(args.trigger_id)
    save_trailing([c for c in load_trailing() if c["trigger_id"] != args.trigger_id])
    log_action("gtt_deleted", trigger_id=args.trigger_id)
    print("Deleted (and unregistered from trailing if present).")


def cmd_trail_run(args):
    from orders.trail import run
    run(interval=args.interval, once=args.once)


def cmd_trail_list(args):
    from orders.execute import load_trailing
    configs = load_trailing()
    if not configs:
        print("No trailing configs registered.")
        return
    for c in configs:
        print(f"  GTT {c['trigger_id']}  {c['symbol']}  trail {c['trail_pct']}%  "
              f"last stop {c['stop']}  since {c['registered']}")


def main():
    p = argparse.ArgumentParser(description="Kite order placement with GTT and trailing stops")
    sub = p.add_subparsers(dest="cmd", required=True)

    sp = sub.add_parser("plan", help="build and preview an order plan")
    sp.add_argument("symbol")
    sp.add_argument("side", choices=["BUY", "SELL", "buy", "sell"])
    sp.add_argument("--stop", type=float, required=True, help="protective stop price (GTT)")
    sp.add_argument("--qty", type=int)
    sp.add_argument("--risk-inr", type=float, help="size so entry→stop loses this many rupees")
    sp.add_argument("--limit", type=float, help="limit entry price (default: market)")
    sp.add_argument("--target", type=float, help="profit target (makes the GTT an OCO)")
    sp.add_argument("--trail", type=float, help="trailing stop %% below LTP")
    sp.add_argument("--product", default="CNC", choices=["CNC", "MIS"])
    sp.add_argument("--notes", default="")
    sp.set_defaults(func=cmd_plan)

    sp = sub.add_parser("preview", help="re-validate an existing plan")
    sp.add_argument("plan")
    sp.set_defaults(func=cmd_preview)

    sp = sub.add_parser("place", help="place the orders in a plan (asks for confirmation)")
    sp.add_argument("plan")
    sp.set_defaults(func=cmd_place)

    sp = sub.add_parser("status", help="orders, GTTs, positions, holdings, funds")
    sp.set_defaults(func=cmd_status)

    sp = sub.add_parser("cancel", help="cancel a pending order")
    sp.add_argument("order_id")
    sp.set_defaults(func=cmd_cancel)

    sp = sub.add_parser("delete-gtt", help="delete a GTT trigger")
    sp.add_argument("trigger_id", type=int)
    sp.set_defaults(func=cmd_delete_gtt)

    sp = sub.add_parser("trail-run", help="start the trailing-stop engine")
    sp.add_argument("--interval", type=int, default=60, help="poll seconds (default 60)")
    sp.add_argument("--once", action="store_true", help="one pass then exit (for cron)")
    sp.set_defaults(func=cmd_trail_run)

    sp = sub.add_parser("trail-list", help="show registered trailing configs")
    sp.set_defaults(func=cmd_trail_list)

    args = p.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
