# SPEC V3 — exact first-half-hour to last-half-hour index replication

Status: S4 pre-registered 2026-09-02. This corrects the entry clock of v1/v2,
which are preserved as superseded all-day audit records. It is a paper-derived
replication baseline, not an executable index strategy or promotion claim.

Universe: existing 5-minute NIFTY 50 and NIFTY BANK index parquet data. A
session must have 09:40, 15:00 and 15:25 IST bars; anomalous timestamps are
excluded. The completed 09:40 timestamped candle ends at 09:45. Predictor =
previous valid session's 15:25 close through the 09:40 close (the first
half-hour return), observable at 09:45. No information after that close enters
the predictor.

Outcome: enter **at the 15:00 bar open** and exit at the 15:25 bar close (the
last 30 minutes, through 15:30). This ensures the predictor is known for over
five hours before entry and makes no same-bar fill assumption.

Predeclared variants, no winner selection: primary momentum follows the
first-half-hour sign; secondary reversal takes the opposite sign. Cost is 5 bps
per side (10 bps round trip), charged on every daily in/out position. Report
break-even one-way bps = daily equal-weight gross mean / 2.

Fixed development/OOS split: 2024 development, 2025-26 OOS; report every
calendar year. Controls are 500 fixed-seed random-sign paths on the same
date/instrument rows and 500 fixed-seed five-session day-block bootstrap paths,
with identical entry, exit, and costs.

Primary momentum success bars: positive 2025-26 OOS net mean; OOS Sharpe above
the random-sign p95; positive net mean in at least two reported calendar years.

Caveat: local history is short; index prices are not executable futures/options
fills and omit spread, impact, margin, taxes, and implementation frictions.
