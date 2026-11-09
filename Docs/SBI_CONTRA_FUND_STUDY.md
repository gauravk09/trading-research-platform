# SBI Contra Fund Behaviour and Price-Effect Study

## Question

1. How does SBI Contra Fund allocate, add, trim, enter, and exit companies over
   time?
2. After those changes become public, do the affected shares exhibit abnormal
   price performance?

## Coverage

The focused collector currently stores 56 monthly portfolios from October 2021
through September 2026. Four unavailable source months remain visible gaps. The
dashboard supports one-, two-, three-, and five-year windows.

The source is SBI Mutual Fund's monthly full-portfolio workbook. Equity rows are
mapped to NSE symbols by ISIN. The scheme's stated strategy is contrarian and its
benchmark is BSE 500 TRI; the local event study uses Nifty 500 price returns because
that is the daily broad-market series already maintained in the project.

## Behaviour definitions

- Company weight: disclosed company market value divided by the scheme's disclosed
  listed-equity value in that month.
- Add/trim: positive/negative change in company weight between available snapshots.
- Entry/exit: change between zero and a positive disclosed position.
- Monthly change proxy: half the sum of absolute company-weight changes. It is not
  audited portfolio turnover because weights also move with prices and fund flows.
- Observed tenure: consecutive available monthly snapshots with a positive holding.

## Price-effect design

Material events require an absolute weight change of at least 10 basis points, or
an entry/exit. The information date is conservatively set to month-end plus ten
calendar days. Event returns start only after that date.

For horizon `h`:

`signed effect = sign(weight change) × (stock return[h] − Nifty 500 return[h])`

A positive value means an addition subsequently outperformed the benchmark, or a
trim subsequently underperformed it. The dashboard reports sample size, mean,
median, aligned-event rate, and t-statistic for 1, 5, 20, and 60 trading days.

## Current three-year result

Across 852 material events, the average signed abnormal effects are approximately:

- 1 day: -0.08%, t-stat -1.18
- 5 days: +0.06%, t-stat +0.45
- 20 days: -0.23%, t-stat -0.85
- 60 days: -0.12%, t-stat -0.25

None meets a conventional absolute t-statistic threshold of 2. The current study
therefore finds no reliable broad price effect after disclosure. Company-level
results remain exploratory and can be inspected by clicking a row.

## Run

Double-click `launchers/dashboards/run_fund_study.command`, or run:

```bash
PYTHONPATH=src python -m experimentation.studies.fund_behavior collect 5
./launchers/dashboards/run_fund_study.command
```

The independent dashboard opens at `http://localhost:5180/fund-study` and uses
ports separate from the trading dashboard.

## Limits

Monthly disclosures do not reveal exact execution dates or prices. Weight changes
mix trading, market-price movement, corporate actions, and scheme subscriptions or
redemptions. Event returns show association after public disclosure, not proof that
the fund caused the move. The study is research, not investment advice.
