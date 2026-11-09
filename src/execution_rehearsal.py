"""Zero-money execution rehearsal for lone-loser-short paper signals.

This module never imports execution code and never emits an executable plan or
placement command.  Its optional Kite check is deliberately limited to read-only
orders, positions, and GTT queries.
"""
import argparse
import hashlib
import json
import os
import sys

import pandas as pd

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import scanners.order_pad as order_pad
from paper_broker import replay
from scanners.strategy_registry import STRATEGIES
from webapp.server.freshness import freshness

STATE_DIR = os.path.join(ROOT, "output", "state")
BARS_DIR = os.path.join(ROOT, "data", "parquet", "daily")
REHEARSAL_DIR = os.path.join(ROOT, "output", "rehearsals")


def _load_state(states_dir, chosen):
    path = os.path.join(states_dir, "latest.json" if chosen == "latest" else f"{chosen}.json")
    with open(path, encoding="utf-8") as handle:
        return json.load(handle), path


def _state_hash(state):
    return hashlib.sha256(json.dumps(state, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _registry_policy():
    strategy = next(item for item in STRATEGIES if item["id"] == "lone_loser_short")
    lifecycle = strategy["lifecycle"]
    label = ("PRODUCTION_CANDIDATE — PAPER ONLY"
             if lifecycle == "production_candidate" and not strategy.get("tradeable")
             else f"{lifecycle.upper()} — PAPER ONLY")
    return {"id": strategy["id"], "lifecycle": lifecycle, "tradeable": strategy.get("tradeable", False),
            "action_policy": strategy.get("action_policy"), "label": label}


def _check(name, passed, detail):
    return {"name": name, "passed": bool(passed), "detail": detail}


def _broker_readonly(symbol):
    """Optional inspection only. Credential failures remain report data, not crashes."""
    try:
        from data_collection.kite.auth import get_kite_client
        kite = get_kite_client()
        orders = kite.orders()
        positions = kite.positions().get("net", [])
        gtts = kite.get_gtts()
        found = {
            "orders": any(item.get("tradingsymbol") == symbol for item in orders),
            "positions": any(item.get("tradingsymbol") == symbol for item in positions),
            "gtts": any((item.get("condition") or {}).get("tradingsymbol") == symbol for item in gtts),
        }
        return {"checked": True, "symbol_present": any(found.values()), "matches": found, "error": None}
    except Exception as exc:  # expired tokens are a checklist failure, not a crash
        return {"checked": True, "symbol_present": False, "matches": {}, "error": str(exc)}


def _candidate_evidence(state, symbol, bars_dir):
    path = os.path.join(bars_dir, f"{symbol}.parquet")
    if not os.path.exists(path):
        return [], None
    frame = pd.read_parquet(path)
    return replay([state], {symbol: frame}), frame


def run_rehearsal(*, states_dir=STATE_DIR, bars_dir=BARS_DIR, state_choice="latest",
                  historical_state=False, equity=1_000_000, risk_pct=None,
                  symbol=None, check_broker_readonly=False, today=None):
    """Build a deterministic, entirely non-actionable rehearsal report."""
    state, state_path = _load_state(states_dir, state_choice)
    data_date = state.get("meta", {}).get("data_date")
    fresh = freshness(data_date, today=today)
    state_digest = _state_hash(state)
    policy = _registry_policy()
    checklist = [_check("registry_lifecycle", policy["lifecycle"] == "production_candidate", policy["label"]),
                 _check("paper_only", not policy["tradeable"], policy["action_policy"])]
    if fresh["stale"] and not historical_state:
        checklist.append(_check("freshness", False, "State is stale; pass --historical-state only for retrospective rehearsal."))
        return {"mode": "PAPER REHEARSAL / DO NOT PUNCH", "state_path": state_path,
                "state_hash": state_digest, "data_date": data_date, "freshness": fresh,
                "registry_policy": policy, "checklist": checklist, "rehearsals": []}
    checklist.append(_check("freshness", True, "Historical replay explicitly allowed." if historical_state else "State is current."))
    block = (state.get("incubation", {}).get("strategies", {}) or {}).get("b5_short_green_tape", {})
    candidates = block.get("candidates", []) if block.get("gates_pass") else []
    if symbol:
        candidates = [candidate for candidate in candidates if str(candidate.get("symbol", "")).upper() == symbol.upper()]
    if not candidates:
        checklist.append(_check("candidate_selection", False, "No gated lone_loser_short candidate in chosen state."))
    else:
        checklist.append(_check("candidate_selection", True, f"{len(candidates)} gated candidate(s)."))
    knobs = state.get("regime", {}).get("knobs", {})
    effective_risk = float(risk_pct if risk_pct is not None else knobs.get("risk_per_trade_pct", 0.0))
    portfolio = {"existing_gross_exposure": 0.0, "existing_heat": 0.0, "open_positions": 0,
                 "max_positions": int(knobs.get("max_open_positions", 1)),
                 "max_gross_exposure_pct": float(knobs.get("max_gross_exposure_pct", 100)),
                 "max_heat_pct": effective_risk * max(1, int(knobs.get("max_open_positions", 1))),
                 "leverage": 1.0}
    rehearsals = []
    for candidate in candidates:
        ticker = str(candidate["symbol"]).upper()
        events, _ = _candidate_evidence(state, ticker, bars_dir)
        entry_event = next((event for event in events if event["event"] == "d1_open_fill"), None)
        terminal = next((event for event in events if event["event"] in {"stop_fill", "d5_time_exit", "unresolved"}), None)
        # Historical D+1 evidence gives an exact fill/stop. Without it we still
        # report the candidate reference, but sizing fail-closes via the checklist.
        entry = entry_event["price"] if entry_event else candidate.get("close")
        stop = entry_event["stop"] if entry_event else candidate.get("stop_ref")
        ticket = order_pad.ticket(ticker, "lone_loser_short", entry, stop, equity, effective_risk, **portfolio)
        ticket["actionable"] = False
        ticket["note"] = "PAPER REHEARSAL ONLY — simulated historical outcome; do not punch."
        manual_card = "PAPER REHEARSAL / DO NOT PUNCH — NO ORDER WILL BE SENT\n" + order_pad.punch_card(ticket)
        item_checks = [
            _check("simulated_d1_fill", entry_event is not None, "D+1 open evidence found." if entry_event else "No D+1 open fill evidence."),
            _check("sizing", ticket["accepted"], "Central risk engine accepted." if ticket["accepted"] else "; ".join(r["message"] for r in ticket["rejection_reasons"])),
            _check("protective_stop", entry_event is not None and entry_event.get("stop") is not None,
                   "Stop derives from signal high and D+1 entry." if entry_event else "Stop cannot be verified without entry evidence."),
        ]
        if check_broker_readonly:
            broker = _broker_readonly(ticker)
            item_checks.append(_check("broker_readonly", broker["error"] is None,
                                      broker["error"] or f"symbol present: {broker['symbol_present']}"))
        else:
            broker = {"checked": False}
        rehearsals.append({"symbol": ticker, "candidate": candidate, "sizing": ticket,
                           "manual_card": manual_card, "simulation_events": events,
                           "fill_stop_exit_evidence": {"entry": entry_event, "terminal": terminal},
                           "broker_readonly": broker, "checklist": item_checks})
    return {"mode": "PAPER REHEARSAL / DO NOT PUNCH", "state_path": state_path,
            "state_hash": state_digest, "data_date": data_date, "freshness": fresh,
            "registry_policy": policy, "equity": equity, "risk_pct": effective_risk,
            "regime_caps": portfolio, "checklist": checklist, "rehearsals": rehearsals}


def write_rehearsal(report, out_dir=REHEARSAL_DIR):
    """Write a stable, idempotent artifact; no journal/order data is touched."""
    os.makedirs(out_dir, exist_ok=True)
    suffix = report["state_hash"][:12]
    path = os.path.join(out_dir, f"{report['data_date'] or 'unknown'}_{suffix}.json")
    payload = json.dumps(report, sort_keys=True, indent=2) + "\n"
    existing = None
    if os.path.exists(path):
        with open(path, encoding="utf-8") as handle:
            existing = handle.read()
    if existing != payload:
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(payload)
    return path


def main(argv=None):
    parser = argparse.ArgumentParser(description="Zero-money lone-loser execution rehearsal (never places orders).")
    parser.add_argument("--states-dir", default=STATE_DIR)
    parser.add_argument("--bars-dir", default=BARS_DIR)
    parser.add_argument("--state", default="latest", help="latest (default) or YYYY-MM-DD")
    parser.add_argument("--historical-state", action="store_true", help="allow stale state only for retrospective rehearsal")
    parser.add_argument("--symbol")
    parser.add_argument("--equity", type=float, default=1_000_000)
    parser.add_argument("--risk-pct", type=float)
    parser.add_argument("--check-broker-readonly", action="store_true")
    parser.add_argument("--write-rehearsal", action="store_true")
    parser.add_argument("--out-dir", default=REHEARSAL_DIR)
    args = parser.parse_args(argv)
    report = run_rehearsal(states_dir=args.states_dir, bars_dir=args.bars_dir, state_choice=args.state,
                           historical_state=args.historical_state, equity=args.equity, risk_pct=args.risk_pct,
                           symbol=args.symbol, check_broker_readonly=args.check_broker_readonly)
    if args.write_rehearsal:
        report["artifact"] = write_rehearsal(report, args.out_dir)
    print(json.dumps(report, sort_keys=True, indent=2))
    return report


if __name__ == "__main__":
    main()
