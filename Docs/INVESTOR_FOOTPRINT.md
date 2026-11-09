# Investor Footprint: accumulation, holding period, style, and price reaction

This pipeline answers four different questions without pretending quarterly or
monthly snapshots are exact trade data.

## Data collected

| Source | Grain | Frequency | Availability date | Main limitation |
|---|---|---:|---|---|
| NSE Regulation 31 XBRL | Named shareholder × company | Quarterly | Actual NSE broadcast timestamp | A holder can disappear below a disclosure threshold; exact trade dates are unknown |
| AMC portfolio workbooks | Mutual-fund scheme × company | Monthly | Month-end + 10 calendar days | Current collector covers SBI, Kotak, and ICICI; reported quantity is a month-end snapshot |
| NSE bulk/block deals | Client × company × deal | Daily | Trade/disclosure day | Only qualifying large deals; not the investor's complete trading history |
| Local OHLCV | Company × trading day | Daily | End of session | Price response is association, not proof of causation |

The normalized holdings schema is:

`investor_id, investor_name, investor_type, symbol, as_of_date, disclosure_date,
holding_qty, holding_pct, source_type`

`as_of_date` describes the position. `disclosure_date` is the point-in-time gate for
tests or signals. Never trade or backtest a holding using `as_of_date`.

## Core metrics

For investor *i*, company *c*, and comparable snapshot intervals *t*:

1. **Reported change**

   `delta_qty[t] = holding_qty[t] - holding_qty[t-1]`

   This locates buying within an interval, not on a day. A first appearance is
   `first_observed`, not a buy, because the earlier holding can be undisclosed.

2. **Buy consistency**

   `number of positive-delta intervals / number of comparable intervals`

   This captures how often the investor adds.

3. **Buy scatter score**

   Let positive additions have weights `p[t] = delta_qty[t] / gross additions`.
   Entropy effective periods are `N_eff = exp(-sum(p[t] log(p[t])))`.

   `scatter = (N_eff - 1) / (number of comparable intervals - 1)`

   The score is 0 for one lump and 1 for equal additions in every observable
   interval. It deliberately penalizes buying in only two of eight quarters more
   than buying in two of two quarters.

4. **Observed holding period**

   Days from first to last reported snapshot. For named shareholders this is a
   lower bound (left/right censored), not an exact holding period. Full monthly
   scheme portfolios provide better entry/exit bounds.

5. **Disclosure reaction**

   Post-disclosure return over 1, 5, 20, and 60 sessions, optionally minus an index
   return. The clock starts only after publication; an intraday or after-close
   filing starts at the next full session, while a pre-open filing can use that
   day's session. A signed reaction treats a
   positive response after an add and a negative response after a trim as aligned.

6. **Flow intensity**

   `delta_qty / trailing 20-session average daily volume`

   This estimates how large the snapshot change is relative to normal turnover. It
   does not claim the quantity traded on the disclosure date.

## Interpreting an investor's “style”

Use a profile rather than one magic score:

- patient vs. fast: median observed tenure and trim frequency;
- gradual vs. lumpy: scatter score, effective buy periods, and consistency;
- concentrated vs. diversified: latest portfolio weights and HHI once market-value
  coverage is complete;
- liquidity preference: flow-to-ADV and median stock ADV;
- entry style: stock momentum and volatility at the snapshot interval start;
- observable market response: abnormal disclosure returns with sample size and
  t-statistic.

`investor_style_summary()` produces this card. It labels behavior as patient or
short-observed-history, gradual or lumpy accumulation, and (where comparable
market values exist) concentrated or diversified. It never compares raw share
counts across different companies.

Ashish Kacholia and Vijay Kedia have conservative canonical-name aliases in
`src/investor_footprint.py`. Kedia Securities Private Limited remains a separate
entity so its holdings are not silently attributed to Vijay Kedia.

## Run it

```bash
# Named shareholder filings from the latest filing season.
python src/investor_footprint.py collect-named 40

# Scheme-level collection is now part of the existing MF collector.
PYTHONPATH=src python -m data_collection.other.mf_holdings

# Inspect an investor-company accumulation table.
python src/investor_footprint.py report "Ashish Kacholia"
python src/investor_footprint.py report "Vijay Kedia"

# Tests
python -m unittest src/test_investor_footprint.py
```

For a historical study, backfill one quarter/month at a time and record failed
source downloads. Avoid ranking impact until there are at least 20 independent
events; show the event count and confidence interval beside every score.
