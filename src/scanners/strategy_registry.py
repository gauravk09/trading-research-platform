"""strategy_registry.py — single source of truth for validated strategies.

Every strategy that survived the research machine + red-team lives here with
its status, entry rules, regime gates, headline stats, caveats and the link
to its Google-Doc playbook. Consumed by:
  dashboard/tabs/strategy_book.py  (Strategies tab: cards + gate lights)
  src/scanners/live_scanner.py              (per-row TAKE/SKIP signal in the live scanner)

Gate thresholds mirror the backtests exactly (see each doc's provenance).
The exact numbers are soft (±10-20% tested in red-team); the directions are not.
"""

import json
import os

from data_collection.paths import ROOT_DIR

import pandas as pd

_MM_HISTORY = os.path.join(ROOT_DIR, "data", "processed", "mm_history.parquet")

_DOC_LINKS_PATH = os.path.join(ROOT_DIR, "data", "doc_links.json")
_DOC_LINKS = (json.load(open(_DOC_LINKS_PATH))
              if os.path.exists(_DOC_LINKS_PATH) else {})

STRATEGIES = [
    {
        "id": "lone_loser_short",
        "name": "F&O Lone-Loser Short",
        "direction": "SHORT",
        "status": "PRODUCTION_CANDIDATE",
        "lifecycle": "production_candidate",
        "tradeable": False,
        "action_policy": "paper_until_forward_record_clears",
        "universe": "Top-150 by mcap (F&O)",
        "rule": ("SHORT a large-cap 4%-down day when the tape is GREEN "
                 "(net4 >= 18) and Nifty is not extended (ti65 < 1.04). "
                 "Entry D+1 open, stop min(signal high, entry*1.06), exit D+5."),
        "stats": ("Backtest: ret/DD 0.59, ~10% CAGR, maxDD -13.7%, ~92 trades/yr. "
                  "Same-date selection lift stayed positive in every era; live S7 record is still accruing."),
        "caveats": [
            "Squeeze gap-throughs drive the DD — never skip the ti65 stand-down",
            "Top ~26 winners = 80% of net R; expect long flat stretches",
            "Trade it SOLO — pairing with any long dilutes ret/DD",
        ],
        "doc_url": _DOC_LINKS.get("lone_loser_short"),
        "gates": [
            ("net4 >= 18 (green tape)", "net4", ">=", 18),
            ("nifty ti65 < 1.04 (index not hot)", "ti65_nifty", "<", 1.04),
        ],
    },
    {
        "id": "qullamaggie_gated",
        "name": "Tape-Gated Qullamaggie Breakout",
        "direction": "LONG",
        "status": "CONDITIONAL_RESEARCH",
        "lifecycle": "conditional_research",
        "tradeable": False,
        "action_policy": "research_only_breadth_habitat",
        "universe": "F&O large caps",
        "rule": ("3-month move >= 30% + near 52wk high + tight 20d flag (<=25%) "
                 "+ breakout over prior 10d high on volume. Research habitat only: "
                 "55 <= pct40ma < 70. Stop = breakout-day low (cap 15%); "
                 "half off at +1R, trail rest on MA20."),
        "stats": ("Same-date entry-selection lift: +0.59%/trade full history; "
                  "+0.63% in the 55-69 breadth habitat in 2024-26. "
                  "Hot-tape 70-100 lift fell to -0.04%."),
        "caveats": [
            "The 55-69 habitat was discovered after results and needs forward confirmation",
            "2025-26 evidence is negative but thin (n=73)",
            "MA10 trail fails; any future retest must preserve the native MA20 exit",
        ],
        "doc_url": _DOC_LINKS.get("qullamaggie_gated"),
        "gates": [
            ("pct40ma >= 55 (moderate breadth floor)", "pct40ma", ">=", 55),
            ("pct40ma < 70 (hot-tape exclusion)", "pct40ma", "<", 70),
        ],
    },
    {
        "id": "darvas_gated",
        "name": "Gated Darvas-Box Breakout",
        "direction": "LONG",
        "status": "REJECTED",
        "lifecycle": "rejected",
        "tradeable": False,
        "action_policy": "do_not_trade",
        "universe": "Large caps (>= Rs 50k-cr ok)",
        "rule": ("Darvas-box breakout when pct40ma >= 60 AND stock ti65 >= 1.0. "
                 "60-day time exit, 0.5% risk (edge degrades at 0.75%)."),
        "stats": ("Rejected after matched-control audit: no full-period selection lift "
                  "over random entries in either risk or capital books."),
        "caveats": [
            "Full-period risk book was +7.4% versus +7.6% for random entries",
            "Era A and 2023-26 both lost to their matched controls",
            "Do not revive from the attractive absolute CAGR; it was market exposure, not selection",
        ],
        "doc_url": _DOC_LINKS.get("darvas_gated"),
        "gates": [
            ("pct40ma >= 60 (healthy breadth)", "pct40ma", ">=", 60),
        ],
    },
    {
        "id": "ryan_minervini",
        "name": "Ryan/Minervini Breakout Book",
        "direction": "LONG",
        "status": "INCUBATING",
        "lifecycle": "incubating",
        "tradeable": False,
        "action_policy": "paper_until_forward_record_clears",
        "universe": "Small/mid caps — NOT large caps",
        "rule": ("Classic leader breakout: strong RS + proper base + breakout, "
                 "trailed exit. Passed S5 on all 3 pre-registered variants. "
                 "S7 paper signals in the state file's incubation block from 2026-09-03."),
        "stats": ("knobs +8.3%/yr DD -10.5% | risk1 +24.7%/yr DD -16.7% | "
                  "attribution 2026-09-03: selection +1.60%/trade (t 2.4) vs control 0.00, "
                  "positive in every era"),
        "caveats": [
            "Large-cap version is COVID-only (2023-26 flat) — verified dead",
            "Top-5 trades = half the profit; never cut the runner",
            "D+1-open slippage is the bleed — execution quality matters",
        ],
        "doc_url": _DOC_LINKS.get("ryan_minervini"),
        "gates": [],
    },
]


def market_snapshot():
    """Read the latest breadth/tape values the gates need from mm_history.
    Returns {} if the file is missing so callers degrade gracefully."""
    try:
        mm = pd.read_parquet(_MM_HISTORY)
    except (OSError, ValueError):
        return {}
    last = mm.iloc[-1]
    snap = {"date": str(mm.index[-1].date()) if hasattr(mm.index[-1], "date")
            else str(mm.index[-1]),
            "net4": int(last["up4"] - last["dn4"]),
            "pct40ma": float(last["pct40ma"]),
            "ratio10": float(last["ratio10"])}
    if "ti65_nifty50" in mm.columns:
        snap["ti65_nifty"] = float(last["ti65_nifty50"])
    return snap


_OPS = {">=": lambda v, t: v >= t, "<": lambda v, t: v < t,
        "<=": lambda v, t: v <= t, ">": lambda v, t: v > t}


def evaluate_gates(strategy, market):
    """[{label, key, value, ok}] for one strategy against a market snapshot.
    ok=None when the market value is unavailable."""
    out = []
    for label, key, op, threshold in strategy["gates"]:
        v = market.get(key)
        ok = None if v is None else bool(_OPS[op](v, threshold))
        out.append({"label": label, "key": key,
                    "value": None if v is None else round(float(v), 3),
                    "ok": ok})
    return out


def gates_pass(strategy, market):
    """True / False / None (None = market data unavailable)."""
    checks = [g["ok"] for g in evaluate_gates(strategy, market)]
    if any(c is None for c in checks):
        return None
    return all(checks)
