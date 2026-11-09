# pipeline

The only layer that calls all the others. It runs them in order and decides nothing itself.

| Module | What it does |
|---|---|
| `run_daily.py` | The nightly 9-step update. Cron runs it at 8 PM through `src/eod_update_cron.sh`. |
| `collect_all.py` | One-off: full history for a new IPO or any stock with no data yet, then rebuild the summary. |
| `daily_state.py` | Writes the machine-readable daily snapshot (`output/state/<date>.json`, `latest.json`): scans, regime, trades. |

## The nightly order

1. `data_collection/kite/updater` — new daily candles from Kite, checked against NSE bhavcopy
2. NSE side feeds (FII/DII, bulk deals, delivery, stock OI, insider trading, shareholding, earnings calendar, bonus) and MF holdings
3. Corporate announcements
4. Quarterly financials
5. Company master and index closes, then `preprocessing/precompute`
6. Split/bonus repair, then point-in-time market cap
7. `daily_state` (scans, regime, incubation signals)
8. `evaluation/grade_decisions`
9. `evaluation/s7_verdict`

If step 1 cannot log in to Kite, the run stops there: data stays stale and nothing downstream refreshes.

```bash
PYTHONPATH=src python -m pipeline.run_daily     # the nightly job, by hand
PYTHONPATH=src python -m pipeline.collect_all   # after a new IPO lists
PYTHONPATH=src python -m pipeline.daily_state   # rebuild only the state file
```
