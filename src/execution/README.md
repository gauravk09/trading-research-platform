# execution

Everything that touches your trading account or simulates doing so. The riskiest layer: read before changing.

| Module | What it does |
|---|---|
| `kite_account.py` | Read-only snapshot of margins, positions and holdings from Kite. |
| `paper_broker.py` | Deterministic, append-only paper broker for the lone-loser short signal. |
| `rehearsal.py` | Zero-money execution rehearsal for paper signals. It must never import order-placing code; a test enforces that. |
| `orders/plans.py` | Build, validate and preview an order plan. No side effects. |
| `orders/execute.py` | Place the orders in a plan file. The only module that sends orders. |
| `orders/trail.py` | Trailing-stop-loss engine. |
| `orders/cli.py` | The single command-line entry point for the order module. |
| `tests/` | Tests for the paper broker and the rehearsal. |

Order placement is blocked on your setup (SEBI static-IP rule), so tickets are punched in by hand in the Kite app.
Plans and previews still come from here:

```bash
PYTHONPATH=src python -m execution.orders.cli plan RELIANCE BUY --qty 10 --stop 1450
```
