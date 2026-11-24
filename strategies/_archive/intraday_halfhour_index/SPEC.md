# SPEC — intraday_halfhour_index

Status: superseded timing record for v1/v2 (2026-09-02). Those runs entered
09:45 and measured an all-day strategy, not the paper-derived half-hour claim.
Their specs/results remain audit history; `SPEC_V3.md` is the exact replication.

Universe: existing Kite 5-minute parquet series for NIFTY 50 and NIFTY BANK.
Observed history is 2024-08-29 through the latest local update. A valid session
must contain the 09:40, 09:45, and 15:25 IST bars; anomalous out-of-session
timestamps are excluded.

Timing (fixed): the 09:40 timestamped 5-minute candle ends at 09:45, so its
close is the latest predictor observation. Predictor = previous valid session's
15:25 close to that 09:40 close return. Enter at the **09:45 bar open**, after
the predictor is observable, and exit at the 15:25 bar close (the 15:25-15:30
bar). No same-bar predictor/entry fill is assumed.

Predeclared variants, no selection between them:

- primary momentum: direction = sign of the morning predictor;
- secondary reversal: direction = negative sign of the same predictor.

Costs: 5 bps per side (10 bps round trip) for each daily in/out position.
Report the break-even one-way bps = gross mean return / 2. The price proxy has
no futures bid/ask, impact, margin, taxes, or true executable index fill, so
the cost model is optimistic for small/illiquid execution and incomplete for
options/futures implementation.

No tuning/OOS choice: fixed descriptive development period = 2024; fixed OOS
period = 2025-26. Report every calendar year separately. Controls are 500
fixed-seed random-sign paths on the same date/instrument rows and 500 fixed-seed
five-session day-block bootstrap paths, all with identical costs and entry/exit.

Primary momentum success bars:

- OOS (2025-26) net mean return is positive;
- OOS momentum Sharpe is above the random-sign-control 95th percentile;
- net mean return is positive in at least two reported calendar years.

Caveat: this short local history is insufficient to infer a durable intraday
effect; the second variant is a symmetric diagnostic, not a licence to choose
the winner after seeing results.
