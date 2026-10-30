# SPEC — commodity_tsmom baseline

Status: S4 pre-registered 2026-09-02. This is a replication baseline, not a
commodity strategy promotion claim.

Universe: daily offshore continuous Yahoo futures `GC=F` (gold), `SI=F`
(silver), and `HG=F` (copper). Exclude crude oil and natural gas: their
contract rolls and pronounced term structure/storage economics make a naive
continuous-price trend result especially vulnerable to roll-yield artefacts.

Signal: on each weekly Friday (or final available session of a week), take the
mean of the signs of own trailing 21/63/126/252-trading-day close returns.
The sign of that ensemble is the position direction. A signal may only become
active after at least one full subsequent daily bar.

Variants (fixed; no tuning):

1. unscaled TSMOM, equal absolute exposure across available instruments;
2. TSMOM scaled by each instrument's trailing 63-day annualized volatility to
   a 10% annual target, cap 2x, equal risk across available instruments;
3. identically vol-scaled always-long control.

Costs: 5 bps per unit one-way turnover, charged whenever a held position
changes. Eras: 2001-12, 2013-19, 2020-26. Random control: fixed-seed 200-path
random signs, the same weekly refresh, one-bar lag, volatility scale, and costs.

Success bars:

- positive net full-sample CAGR;
- positive net CAGR in at least two of the three eras;
- scaled TSMOM Sharpe exceeds scaled always-long Sharpe;
- scaled TSMOM Sharpe exceeds the random-sign control 95th percentile.

Caveat: Yahoo continuous futures are not investable contracts and their roll
construction/term structure is not independently verified here. Results cannot
be promoted without a tradable-contract and roll-cost replication.
