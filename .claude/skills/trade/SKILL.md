---
name: trade
description: Translate a natural-language trade instruction ("buy 10 RELIANCE with stop at 1450 and trail it 2%") into a validated Kite order plan with GTT stop/target and optional trailing stop, preview it, and hand the user the exact command to execute. Use for placing, sizing, cancelling, or checking orders/GTTs/positions.
---

# Trade — natural language → validated Kite order plan

The order module lives in `src/execution/orders/` (see module docstrings). Your job:
parse the user's instruction, build and validate a plan, show the preview,
and give the user the one command that executes it.

## MANUAL EXECUTION MODE — active since 2026-07-14

No static IP is whitelisted on the Kite developer account (SEBI rule since
2026-04-01; user is on CGNAT JioFiber and chose not to set one up — see
ROADMAP). Kite therefore REJECTS all order-placement API calls:
`place`, `cancel`, `delete-gtt` and `trail-run` (GTT modify) will fail with
a PermissionException. Read-only calls (plan/preview/status) work fine.

Until an IP is whitelisted: build and validate the plan as usual, then
instead of the `place` command give the user a **manual punch-in card**
for the Kite app:

  ENTRY:  BUY/SELL <qty> <symbol>  MARKET or LIMIT <price>  (CNC/MIS)
  STOP:   GTT sell, trigger <stop>, limit <stop − 0.5%>
  TARGET: (if set) make the GTT OCO with target trigger/limit
  TRAIL:  use Kite's native "trailing" GTT type in the app (the account
          has it — do NOT suggest trail-run)

Delete this section when the user whitelists a static IP (cheapest routes
researched 2026-07-14: Oracle Cloud free tier via SSH proxy, or JioFiber
static-IP add-on by phone; one whitelist change allowed per week).

## Hard rules

1. **Never run `place`, `cancel`, `delete-gtt`, or `trail-run` yourself.**
   Building/previewing plans and reading status are yours; anything that
   places, modifies, or cancels a real order is executed by the user.
   Print the exact command for them to paste.
2. Never bypass or reimplement the CLI to hit the Kite order APIs directly
   (including the Kite MCP `place_order`/`place_gtt_order` tools).
3. If validation shows ERROR lines, fix the plan or ask — never hand the
   user a command for a blocked plan.

## Workflow

1. Parse the instruction into: symbol, side, entry (market or limit price),
   stop (required — refuse entries with no stop, that's platform policy),
   optional target, optional trail %, qty or risk.
2. Sizing: explicit qty wins. "Risk ₹5000" → `--risk-inr 5000`. If the user
   gives neither, read `output/state/latest.json` regime knobs
   (`risk_per_trade_pct` × live equity from Kite margins) and propose that
   as risk — say so explicitly.
3. Build: `PYTHONPATH=src python -m execution.orders.cli plan SYMBOL BUY --stop … [--qty|--risk-inr] [--limit] [--target] [--trail] [--notes "…"]`
   (use the anaconda3 python). This is read-only — it fetches LTP/margins
   and writes a JSON under `output/orders/plans/`.
4. Show the user the preview block verbatim (it includes value, risk, %
   distance, ASM/GSM and funds warnings), then the ready-to-paste command:
   `PYTHONPATH=src python -m execution.orders.cli place '<plan path>'` — it re-validates and
   asks them to type PLACE.
5. If the plan has `--trail`, remind them the engine must be running during
   market hours: `PYTHONPATH=src python -m execution.orders.cli trail-run`.

## Other requests

- "What's open / show my orders / positions" → `PYTHONPATH=src python -m execution.orders.cli status` (you may run this).
- "Cancel X / remove that GTT" → find the id via `status`, hand them the
  `cancel <order_id>` or `delete-gtt <trigger_id>` command.
- "Trail my existing position" → the engine only manages GTTs created by
  this module (it relies on the stop being trigger index 0). For a position
  with an existing hand-made GTT, offer to build a fresh plan-based GTT
  after they delete the old one.

## Reporting

After the user executes, `output/orders/orders_log.jsonl` has the record —
read it to confirm and summarize what actually happened.
