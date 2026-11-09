# evaluation

Answers "did the decisions and strategies actually work?" using only what was recorded at the time.

| Module | What it does | Writes to |
|---|---|---|
| `grade_decisions.py` | +1/+3/+5/+20 day forward returns for every scan candidate, brief recommendation and triage verdict, on two bases: decision-day close and next-day open (the one you can actually get). | `output/grader/forward_returns.parquet` |
| `incubation.py` | Generates the S7 paper signals for the factory strategies (called by `daily_state`). | signals in the daily state |
| `s7_verdict.py` | Reads the forward record nightly and flags tracks that are negative or decaying. | `output/grader/s7_verdict.md` |
| `tests/` | Tests for the incubation signals. | |

Both graders run as steps 8 and 9 of the nightly job. Run one by hand from the repo root, for example:

```bash
PYTHONPATH=src python -m evaluation.s7_verdict
```

Research-run tracking (`backtest/experiment_tracking.py`) and artifact cleanup reports (`backtest/artifact_retention.py`) are in `backtest/`, not here, because the backtest runner uses them.
