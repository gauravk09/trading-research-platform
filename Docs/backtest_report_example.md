# Backtest Report: Intraday Gap-Continuation (Nifty 500)

**Strategy ID:** GAPCONT-NSE-v1.3
**Author:** [name]
**Report date:** 2026-01-15
**Backtest engine:** vectorbt / custom event loop (bar close simulation)
**Status:** Research candidate — NOT approved for live capital

> This is an illustrative example built to show the structure of a sound report.
> The numbers are internally consistent and realistic but are not a live result.
> Replace every section with your own rules, data, and outputs.

---

## 1. Hypothesis and rationale

If a stock gaps at the open and the gap has not filled within the first 45 minutes of trading, order flow favors continuation in the gap direction for the rest of the session. The economic rationale is that an unfilled gap after the initial auction reflects genuine repricing (news, results, block activity) rather than noise, and late/reluctant participants chase the move into the close.

This is a directional intraday momentum strategy, not a statistical arbitrage. It is expected to work in trending regimes and struggle in choppy, mean-reverting ones.

---

## 2. Universe and data

| Item | Detail |
|---|---|
| Instruments | Nifty 500 constituents, **point-in-time** (survivorship-bias free) |
| Liquidity filter | 20-day median turnover > ₹50 cr on signal day |
| Data source | Exchange-provided 1-minute bars (NSE), adjusted for splits/bonuses |
| Corporate actions | Split/bonus adjusted; dividends ignored (intraday, so immaterial) |
| Period | 2016-01-01 to 2025-12-31 (10 years) |
| In-sample (IS) | 2016-01-01 to 2022-12-31 (7 yrs, used for rule design) |
| Out-of-sample (OOS) | 2023-01-01 to 2025-12-31 (3 yrs, never touched during design) |
| Benchmark | Nifty 500 TRI (total return) |

**Data quality notes:** 1-min bars had ~0.3% missing/zero-volume bars, forward-filled only within-session. Suspended and circuit-locked symbols on a given day were excluded from that day's universe.

---

## 3. Rules (fully specified, no discretion)

**Entry**
- At 09:15 open, flag stocks gapping >= 2.0% (up or down) vs prior day's close.
- At 10:00 (45 min mark), if price has **not** traded back to the prior close (gap unfilled), submit a market order in the gap direction.
- Max 5 concurrent positions; if more than 5 signals, rank by gap size and take the largest.

**Exit**
- Hard stop at the prior-day close level (i.e. a full gap fill = exit).
- Time exit: square off all positions at 15:15 (before closing auction).
- No overnight holds.

**Position sizing**
- Risk 0.5% of current equity per trade. Position size = (0.5% × equity) / (entry − stop distance).
- Shorts only in symbols with confirmed SLB/intraday-shortable status on that date.

**Parameters (fixed on IS, frozen for OOS):** gap threshold 2.0%, decision time 10:00, risk 0.5%, max positions 5.

---

## 4. Cost and execution assumptions

Realistic frictions matter more than any single parameter for an intraday strategy. Modeled per round trip:

| Cost component | Assumption |
|---|---|
| Brokerage | ₹20 per order (₹40 round trip), Zerodha intraday |
| STT | 0.025% on sell side |
| Exchange txn + SEBI + stamp | ~0.012% of turnover |
| GST | 18% on (brokerage + txn charges) |
| **Slippage** | **0.05% per side** (market orders on liquid names) |
| Total friction | **~0.18%–0.22% per round trip** |

**Fill model:** market orders fill at the next 1-min bar open after signal, plus slippage. No assumption of fills at the extreme of a bar. No look-ahead: the liquidity filter uses only data available before the signal.

---

## 5. Headline results (net of all costs)

| Metric | Strategy | Nifty 500 TRI |
|---|---|---|
| Starting capital | ₹10,00,000 | ₹10,00,000 |
| Ending capital | ₹34,60,000 | ₹37,10,000 |
| **CAGR** | **13.2%** | 14.0% |
| Annualized volatility | 6.1% | 17.9% |
| **Sharpe** (rf 6.7%) | **1.07** | 0.41 |
| Sortino | 1.58 | 0.57 |
| **Max drawdown** | **-11.2%** | -38.2% |
| Calmar | 1.18 | 0.37 |
| Correlation to Nifty 500 | 0.14 | 1.00 |
| Exposure (avg time in market) | ~28% intraday | 100% |

**Read this honestly:** the strategy slightly *underperforms* buy-and-hold on raw CAGR. Its case is risk-adjusted return and low correlation: roughly one-third the volatility, one-third the drawdown, and near-zero correlation to the index. That makes it a diversifier, not a standalone index-beater. A report claiming a simple intraday strategy crushes the index after realistic costs should be treated with suspicion.

---

## 6. Trade statistics

| Metric | Value |
|---|---|
| Total trades | 4,218 |
| Avg trades / month | ~35 |
| Win rate | 43.8% |
| Avg win / avg loss (R) | +1.9R / -1.0R |
| Profit factor | 1.34 |
| Expectancy (gross) | +0.27R per trade |
| Expectancy (net of costs) | +0.19R per trade |
| Avg holding time | 3.2 hours |
| Longest losing streak | 11 trades |
| % of profit from top 5% of trades | 41% |

The last row is a warning flag worth always reporting: a large share of profit concentrated in a few outlier trades means results are fragile to missing those days.

---

## 7. Equity curve and drawdown

![Equity curve: strategy vs Nifty 500 TRI, log scale](equity_curve.png)

![Underwater drawdown curve](drawdown_curve.png)

*Figures are computed on month-end equity. The metrics table (Section 5) quotes daily peak-to-trough max drawdown (-11.2% strategy, -38.2% benchmark), which is naturally deeper than the month-end underwater curve above (-10.9% and -27.6%). Drawdown depth is sensitive to sampling frequency, so always state which you are reporting.*

Key episodes:

- Smooth compounding 2016–2019.
- March 2020 (COVID): strategy +4.1% for the month while Nifty 500 fell ~23%. High realized volatility produced many clean, unfilled gaps. This single regime flatters the full-period stats.
- 2022–2023 sideways market: 14 consecutive months near flat (the real test of whether you'd have stuck with it).
- Max drawdown -11.2% occurred Aug–Nov 2023 (choppy, gap-fill-heavy tape).

---

## 8. Monthly and annual return statistics

Net-of-cost monthly returns (%). Rounding means individual months may not tie exactly to the year column.

| Year | Jan | Feb | Mar | Apr | May | Jun | Jul | Aug | Sep | Oct | Nov | Dec | **Year** |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 2016 | +2.8 | -2.6 | +4.7 | +5.5 | -6.1 | -3.6 | +2.1 | +0.3 | +1.5 | -1.8 | +5.2 | +4.8 | **+12.5** |
| 2017 | +1.3 | +5.6 | +2.9 | -2.4 | +2.5 | -2.8 | +4.6 | +0.8 | +0.2 | -1.7 | +6.0 | +0.4 | **+18.2** |
| 2018 | -2.0 | -1.7 | +1.8 | +1.1 | +1.3 | +1.4 | +8.6 | -1.9 | -2.3 | -3.5 | +2.2 | +4.3 | **+8.9** |
| 2019 | +0.3 | -2.6 | -2.6 | +3.4 | +3.8 | +2.9 | -1.9 | +1.7 | +1.2 | +1.6 | +4.3 | +1.6 | **+14.1** |
| 2020 | +6.3 | +2.8 | +4.1 | +4.0 | +6.0 | -5.5 | +0.6 | -0.2 | -1.2 | +0.8 | +11.2 | -2.4 | **+28.6** |
| 2021 | +5.4 | -5.2 | +0.0 | +2.0 | +3.8 | +4.3 | +4.6 | -0.0 | -0.5 | +4.9 | +0.6 | -3.7 | **+16.8** |
| 2022 | -2.4 | -1.8 | +2.5 | +1.4 | +3.1 | -0.3 | +1.2 | +1.8 | +0.5 | +1.6 | +0.1 | +0.5 | **+8.2** |
| 2023 | +1.5 | +0.4 | +2.7 | +1.4 | +2.1 | +3.6 | +3.4 | -3.6 | -2.9 | -2.8 | -2.1 | +4.1 | **+7.8** |
| 2024 | +2.1 | +1.1 | +2.2 | -2.6 | -1.9 | -1.6 | -0.6 | +3.7 | -0.3 | +1.3 | +6.5 | +1.3 | **+11.4** |
| 2025 | +3.9 | -1.2 | +1.0 | -1.3 | +0.6 | +4.2 | -3.5 | +2.9 | +2.3 | -0.2 | -2.7 | +1.8 | **+7.6** |

**Distribution summary**

| Stat | Value |
|---|---|
| Positive months | 67% (80 / 120) |
| Avg positive month | +2.8% |
| Avg negative month | -2.3% |
| Best month | +11.2% (Nov 2020) |
| Worst month | -6.1% (May 2016) |
| Best year | +28.6% (2020) |
| Worst year | +7.6% (2025) |
| Positive years | 10 / 10 |

Every calendar year closed positive, but the annual column hides the intra-year -11.2% drawdown of Aug–Nov 2023 (the four consecutive red months). Always read the monthly grid next to the drawdown curve, never the year column on its own.

**Strategy vs benchmark, annual (%)**

| Year | Strategy | Nifty 500 TRI | Diff |
|---|---|---|---|
| 2016 | +12.5 | +5.1 | +7.4 |
| 2017 | +18.2 | +37.6 | -19.4 |
| 2018 | +8.9 | -2.1 | +11.0 |
| 2019 | +14.1 | +8.9 | +5.2 |
| 2020 | +28.6 | +17.9 | +10.7 |
| 2021 | +16.8 | +30.2 | -13.4 |
| 2022 | +8.2 | +4.2 | +4.0 |
| 2023 | +7.8 | +26.9 | -19.1 |
| 2024 | +11.4 | +15.2 | -3.8 |
| 2025 | +7.6 | +2.9 | +4.7 |

This table is the whole thesis in one place: the strategy lags badly in strong bull years (2017, 2021, 2023) and outperforms in flat or falling ones (2018, 2022). That is the signature of a low-correlation diversifier, not an index-beater. A strategy that beat the benchmark every single year would be the suspicious result, not the impressive one.

---

## 9. Robustness and validation

This is the section most bad reports skip. Passing here matters more than a pretty equity curve.

**In-sample vs out-of-sample**

| Metric | IS (2016–2022) | OOS (2023–2025) |
|---|---|---|
| CAGR | 15.1% | 9.0% |
| Sharpe | 1.19 | 0.81 |
| Max DD | -9.4% | -11.2% |
| Win rate | 44.6% | 42.1% |

OOS degrades but stays positive. ~40% Sharpe decay from IS to OOS is normal and acceptable; a strategy that looks *identical* OOS is often a sign of leakage.

**Walk-forward:** 12 anchored windows (2-yr train, 6-mo test). 9 of 12 test windows profitable net of costs.

**Parameter sensitivity:** varied gap threshold 1.5%–3.0% and decision time 09:45–10:30. Sharpe stayed in 0.85–1.15 across the grid, i.e. no sharp cliff around the chosen values. A result that only works at exactly 2.0% and 10:00 would indicate overfitting.

**Monte Carlo (trade-order reshuffle, 5,000 runs):** 5th-percentile max drawdown -17.8%, 5th-percentile CAGR 8.1%. Plan risk around the tail, not the median.

**Regime split**

| Regime | Ann. return |
|---|---|
| Trending (ADX-defined) | +19.4% |
| Choppy / range | +2.1% |
| High-vol (VIX > 20) | +24.6% |

The edge is concentrated in trending and high-volatility regimes, as the hypothesis predicts.

---

## 10. Known limitations and risks

- **Point-in-time universe** is approximate; index reconstitution history has gaps that may leak a small survivorship bias.
- **1-min bars** understate intra-bar slippage on fast gaps; true fills may be worse than modeled.
- **Short availability:** SLB/intraday-short eligibility is modeled from current lists, not fully historical. Short-side results are likely optimistic.
- **Capacity:** at larger AUM, 0.05% slippage is unrealistic on all 500 names; strategy likely caps out well below institutional size.
- **Regime dependence:** flat-to-negative in range-bound markets; expect long, morale-testing flat stretches.
- **No account for margin/leverage costs** on the intraday exposure.

---

## 11. Conclusion and next steps

The strategy shows a real but modest edge that survives realistic costs and out-of-sample testing, with strong risk-adjusted characteristics and low correlation to the index. It is a diversification candidate, not a core return engine.

Before any capital:
1. Rebuild the universe with a verified point-in-time constituents dataset.
2. Re-run with tick or quote data on a subset to validate the 1-min slippage assumption.
3. Forward/paper trade for one quarter and compare live slippage to the 0.05% assumption.
4. Size initial live risk at 25% of backtested risk per trade.

---

### Appendix: reusable checklist for any backtest report

- [ ] Hypothesis stated *before* results, with economic rationale
- [ ] Point-in-time universe (no survivorship bias)
- [ ] IS/OOS split defined, OOS untouched during design
- [ ] All costs, slippage, and fill model spelled out
- [ ] Benchmark comparison on the same period
- [ ] Risk-adjusted metrics (Sharpe, Sortino, Calmar), not just CAGR
- [ ] Full trade stats incl. profit concentration and worst losing streak
- [ ] Parameter sensitivity + walk-forward + Monte Carlo
- [ ] Regime breakdown
- [ ] Honest limitations section
- [ ] Explicit "not approved for live" gate and next steps
