# Red-team — four_pct_down SHORT pocket (2026-07-31)

Champion: short on a stock's 4%-down day when
`market:ratio10 >= 0.65  AND  volc5_50 >= 0.93  AND  market:net25q >= -135`
("short the lone loser in a healthy tape, volume not drying up").

9/9 attacks PASS the pocket bars (era A & B mean > 0, era-B clustered t >= 2,
era-A t >= 1, beats >= 95% of 200 random same-size era-B naked-cohort subsets):

| variant | era-B mean R | t | trades/yr | vs-naked |
|---|---|---|---|---|
| baseline | +0.151 | 4.1 | 1756 | 100% |
| ratio10 0.55 / 0.75 | +0.152 / +0.138 | 4.2 / 4.5 | 1856 / 1714 | 100% |
| volc 0.80 / 1.10 | +0.139 / +0.168 | 4.0 / 3.7 | 2112 / 1403 | 100% |
| net25q -170 / -100 | +0.152 / +0.139 | 4.2 / 3.7 | 1821 / 1699 | 100% |
| LIQUID turn_decile>=0.8 | **+0.202** | 4.3 | 487 | 100% |
| LIQUID turn_decile>=0.9 | **+0.194** | 3.4 | 250 | 100% |

Edge CONCENTRATES in the liquid half — where shorting is actually feasible.
Independently converges with the large-cap F&O "short-the-lone-loser" finding.

Open before trading: stop_r_short is daily-bar accounting (no borrow/F&O
costs, approximate fills); India cash market has no overnight shorting →
real universe is F&O names; 20d-horizon grade not yet run. Next step:
factory-style cost-realistic backtest (src/backtest) on F&O universe.
