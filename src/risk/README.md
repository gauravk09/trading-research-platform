# risk

How much to risk, and whether the market allows it today. Reads prepared data; never fetches from outside.

| Module | What it does |
|---|---|
| `regime.py` | The validated HMM crash-risk dial: forecasts the chance Nifty 500 falls 5% or more within 20 sessions and sets the sizing tier (CALM = full knobs, ELEVATED = half). Refit once a year. Uses the models in `research/regime/`. |
| `sizing.py` | One side-aware position-size and portfolio-risk calculation, used by the order pad, the order plans and the Qullamaggie position sizer. |
| `plan_contract.py` | The typed daily plan and its deterministic gates (what passes, what is rejected and why). |
| `tests/` | Tests for the three modules above. |

The market-breadth counts that feed the Market Monitor tab are not here. They are display data and live in `preprocessing/breadth.py`.

Run the tests from `src/`: `python -m pytest risk/tests`.
