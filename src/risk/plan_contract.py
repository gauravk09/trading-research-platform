"""
plan_contract.py — the typed daily plan and its deterministic gates.

/brief used to compute its PASS/BLOCK gates in prose. A gate that lives in
prose is a gate a model can talk itself past (AgenticAITA, arXiv:2605.12532:
run the hard gates BEFORE any narrative so no reasoning can override them).
This module owns the gates:

    PYTHONPATH=src python -m risk.plan_contract output/brief/plan_draft.json

reads a draft journal entry, evaluates every recommendation against the
state file the plan claims to be built from, attaches `gates` to each
recommendation, moves any that fail a hard gate to `rejected` with a
`reject_reason`, writes output/brief/plan_gated.json and prints the table.
Exit code 1 if anything was rejected, so the caller cannot miss it.

The gate layer may pass or fail a recommendation. It never edits one.

Rejected recommendations are kept, not dropped: grade_decisions.py grades
them too, and the share of rejected names that went on to gain is the
FalseBlock rate — the only number that can tell an over-tight gate from a
good one.
"""

import json
import os
import sys

from data_collection.paths import ROOT_DIR

ROOT = ROOT_DIR
STATE_DIR = os.path.join(ROOT, "output", "state")
GATED_PATH = os.path.join(ROOT, "output", "brief", "plan_gated.json")

REQUIRED = ("symbol", "scan", "entry", "stop", "qty", "risk_inr")
PARTICIPATION_FLOOR = 0.7     # brief rule 9: turnover < 0.7x 20d avg = no-chase
CIRCUIT_BREAKER_STOPS = 3     # brief rule 10: 3 stop-outs = stand down
ENTRY_DRIFT_PCT = 5.0         # entry must sit near the state-file close
EARNINGS_WINDOW_DAYS = 5      # soft: results due inside the hold window
HARD = ("schema", "fresh_state", "in_scans", "stop_side", "leakage_checked",
        "circuit_breaker_ok", "participation_ok", "risk_ok", "positions_ok",
        "exposure_ok")
SOFT = ("earnings_ok",)


def _candidates(state):
    out = {}
    for scan, block in state.get("scans", {}).items():
        for c in block.get("candidates", []):
            out.setdefault(c["symbol"], (scan, c))
    for name, strat in state.get("incubation", {}).get("strategies", {}).items():
        for c in strat.get("candidates", []):
            out.setdefault(c["symbol"], (name, c))
    return out


def _open_notional(state):
    return sum(float(t.get("notional") or (t.get("qty", 0) * t.get("entry", 0)))
               for t in state.get("open_trades", []))


def gate_entry(entry, state):
    """Return (gated_entry, report_rows). Pure: no I/O."""
    knobs = state["regime"]["knobs"]
    equity = float(entry.get("equity") or 0)
    cands = _candidates(state)
    open_trades = state.get("open_trades", [])
    stopped = sum(1 for t in open_trades if t.get("status") == "stopped")
    ratio = state.get("participation", {}).get("ratio_20d")
    fresh = entry.get("date") == state["meta"]["data_date"]
    exposure_cap = equity * float(knobs["max_gross_exposure_pct"]) / 100.0
    risk_cap = equity * float(knobs["risk_per_trade_pct"]) / 100.0
    notional_used = _open_notional(state)
    taken = len(open_trades)

    kept, rejected, rows = [], [], []
    for reco in entry.get("recommendations", []):
        g = {}
        missing = [k for k in REQUIRED if reco.get(k) in (None, "")]
        g["schema"] = (not missing, "missing " + ",".join(missing) if missing else "ok")
        g["fresh_state"] = (fresh, f"plan {entry.get('date')} vs state {state['meta']['data_date']}")
        sym = reco.get("symbol")
        cand = cands.get(sym)
        g["in_scans"] = (cand is not None, cand[0] if cand else "not in any scan")
        if not missing:
            entry_px, stop, qty, risk = (float(reco["entry"]), float(reco["stop"]),
                                         int(reco["qty"]), float(reco["risk_inr"]))
            short = str(reco.get("side", "BUY")).upper() in ("SELL", "SHORT")
            g["stop_side"] = ((stop > entry_px) if short else (stop < entry_px),
                              f"stop {stop} vs entry {entry_px}")
            close = float(cand[1].get("close") or 0) if cand else 0.0
            drift = abs(entry_px - close) / close * 100 if close else float("inf")
            g["leakage_checked"] = (drift <= ENTRY_DRIFT_PCT,
                                    f"entry {drift:.1f}% from state close {close}")
            g["circuit_breaker_ok"] = (stopped < CIRCUIT_BREAKER_STOPS, f"{stopped} stop-outs")
            g["participation_ok"] = (ratio is not None and ratio >= PARTICIPATION_FLOOR,
                                     f"ratio_20d {ratio}")
            g["risk_ok"] = (risk <= risk_cap * 1.05, f"risk {risk:,.0f} vs cap {risk_cap:,.0f}")
            g["positions_ok"] = (taken + 1 <= int(knobs["max_open_positions"]),
                                 f"{taken} open + 1 vs max {knobs['max_open_positions']}")
            notional = qty * entry_px
            g["exposure_ok"] = (notional_used + notional <= exposure_cap,
                                f"{notional_used + notional:,.0f} vs cap {exposure_cap:,.0f}")
            due = cand[1].get("results_due_days") if cand else None
            g["earnings_ok"] = (due is None or due > EARNINGS_WINDOW_DAYS,
                                f"results due in {due}d" if due is not None else "none scheduled")
        failed = [k for k in HARD if k in g and not g[k][0]]
        warned = [k for k in SOFT if k in g and not g[k][0]]
        reco = dict(reco, gates={k: {"ok": v[0], "value": v[1]} for k, v in g.items()},
                    gate_warnings=warned)
        if failed:
            reco["reject_reason"] = "; ".join(f"{k}: {g[k][1]}" for k in failed)
            rejected.append(reco)
        else:
            kept.append(reco)
            taken += 1
            notional_used += qty * entry_px
        rows.append((sym, "BLOCK" if failed else "PASS",
                     reco.get("reject_reason") or ("warn " + ",".join(warned) if warned else "all gates pass")))
    out = dict(entry, recommendations=kept, rejected=rejected + list(entry.get("rejected", [])))
    return out, rows


def gate_file(draft_path, state_path=None, out_path=GATED_PATH):
    entry = json.load(open(draft_path))
    state_path = state_path or os.path.join(STATE_DIR, f"{entry['date']}.json")
    state = json.load(open(state_path))
    gated, rows = gate_entry(entry, state)
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w") as f:
        json.dump(gated, f, indent=1)
    return gated, rows


def main(argv=None):
    argv = argv if argv is not None else sys.argv[1:]
    if not argv:
        print(__doc__)
        return 2
    gated, rows = gate_file(argv[0], argv[1] if len(argv) > 1 else None)
    for sym, verdict, why in rows:
        print(f"  {verdict:<5} {sym:<14} {why}")
    n_rej = len([r for r in rows if r[1] == "BLOCK"])
    print(f"{len(rows) - n_rej} pass, {n_rej} rejected -> {os.path.relpath(GATED_PATH, ROOT)}")
    return 1 if n_rej else 0


if __name__ == "__main__":
    sys.exit(main())
