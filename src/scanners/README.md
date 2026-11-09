# scanners

Finds candidates and turns them into tickets. Reads prepared data and calls `indicators/`, `filters/` and `risk/`.
It never places an order: tickets are for you to punch in by hand.

| Module | What it does |
|---|---|
| `live_anticipation.py` | The live intraday scanner server (port 8602) and its page, `live_anticipation.html`. Needs today's Kite token. |
| `live_scanner.py` | Turns live quotes plus EOD history into the scan tables the live page shows. |
| `order_pad.py` | Builds the order ticket (side, size, entry timing, stop) and the manual punch-in card from a ranked candidate. |
| `strategy_registry.py` | The validated strategies: status, entry rules, regime gates, playbook links (links come from `data/doc_links.json`, not the repo). |
| `conviction.py` | Ranks a scan hit-list into a research queue. |
| `trade_metrics.py` | Empirical chance of profit and expectancy for a live candidate. |
| `overnight_news.py` | Ranks material after-close filings for next-day trades. |
| `tracker.py` | "Started watching here" stamps for the live dashboard. |

Start the live scanner from the repo root:

```bash
PYTHONPATH=src python -m scanners.live_anticipation
```
