# STYLE.md — the user's trading style profile (factory stage S6)

Drafted 2026-07-29; all open items confirmed by the user same day
(win-rate tolerance, screen windows, hold horizon, drawdown, account size).
This file is the single source the S6 gate reads.

## Hard constraints (fail any → strategy rejected for style)

- **Execution**: manual punching in the Kite app. No order API (SEBI static-IP
  rule, CGNAT — ROADMAP 2026-07-14). Strategies needing sub-minute reaction or
  many simultaneous fills are infeasible. Alert → ~1-2 minutes to punch is OK.
- **Screen windows**: open window 09:15-09:40 and last ~45 minutes are
  usually available; middle of day is not. (confirmed)
- **Instruments**: NSE cash equities, long side. Shorts only via F&O (cash
  shorting is intraday-only in India), and the F&O book is discretionary —
  factory strategies are long cash for now.
- **One risk bucket**: F&O notional counts against the same gross-exposure
  cap (decision 2026-07-18). A factory strategy must live inside the regime
  knobs (`src/risk/regime.py` TIER_KNOBS), not beside them.
- **Liquidity floor**: ₹5cr/day turnover minimum, ₹10cr for EP/gap types
  (house convention in `candidate_flags` and the EP studies).

## Soft preferences (each mismatch = size one tier down, or pass)

- **Hold horizon**: prefers 2-10 sessions (the whole tooling — scale-out at
  3-5d, daily brief cadence — is built around it). Will run 20-60-day
  trail-exit tail strategies at reduced size if the edge demands it. (confirmed)
- **Win-rate tolerance**: confirmed — comfortable running 25-35% win-rate
  books with 8-14-trade losing streaks at full size. The S8 monitor should
  still watch for behavior diverging from this claim under a real streak
  (skipped signals, early exits show up in the grader as plan-vs-done gaps).
- **Max drawdown on trading capital**: 20% (confirmed — also the Monte Carlo
  tolerance in ROADMAP item-5 knob calibration).
- **Account size**: stated by the owner 2026-07-29 (not recorded here). S5 bar:
  a strategy must project **≥ 3%/yr of account** to earn a slot.
  Zerodha delivery brokerage is zero; the 0.4% round-trip cost model (STT,
  stamp, GST, slippage) stands; fixed costs are negligible at this size.
- **Risk per trade / max positions**: taken from the regime tier knobs, not
  set per strategy.
- **Temperament notes**: prefers deterministic rules + one judgment pass
  (rejected the agent-debate architecture); wants to understand every rule
  (comprehension mode) — black-box signals will not be trusted, so any ML
  layer must ship with its odds table.
