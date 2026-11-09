# data_collection

Everything that fetches data from outside the repo lives here, grouped by **source**.
Computing on the fetched data (`precompute.py`, `regime.py`, `daily_state.py`, …) stays in `src/`.

| Folder | Source | Needs a login? |
|---|---|---|
| `kite/` | Zerodha Kite Connect API | **Yes** — Kite API key; token expires every morning |
| `nse/` | NSE archives and APIs | No |
| `other/` | BSE, AMC websites, GDELT, Yahoo, LBMA/EIA, Zerodha Pulse | No |

Top level: `commodity_store.py` / `commodity_map.py` (commodity series storage and symbol map), `run_daily.py` (the nightly job), `collect_all.py` (full history for new IPOs),
`storage.py` (parquet price files — the only place that knows their paths), `paths.py` (`ROOT_DIR`).

## How to run anything

From the repo root, as a module (so imports resolve):

```bash
PYTHONPATH=src python -m data_collection.run_daily          # nightly update
PYTHONPATH=src python -m data_collection.kite.auth          # morning token refresh
PYTHONPATH=src python -m data_collection.nse.bulk_deals     # one collector alone
```

## What `run_daily.py` does, in order

1. `kite/updater` — new daily candles from Kite, then check against NSE `bhavcopy`
2. NSE side feeds (`fii_dii`, `bulk_deals`, `delivery`, `stock_oi`, `insider_trading`, `shareholding`, `earnings_calendar`, `bonus`) and `other/mf_holdings`
3. `nse/announcements`
4. `nse/update_financials`
5. `other/company_master`, `kite/index_history`, then **`precompute`** (in `preprocessing/`)
6. split/bonus repair (re-fetches a broken stock's full history from Kite)
7. daily state, 8. decision grader, 9. S7 verdict (all compute, in `src/`)

## Data map

"Re-fetchable" = can a teammate rebuild it later, or is it gone if the day is missed?

| Data | Script | Writes to | Kite? | Re-fetchable? |
|---|---|---|---|---|
| Daily prices (all stocks) | `kite/updater`, `kite/historical` | `data/parquet/daily/<SYMBOL>.parquet` | Yes | Yes, with a Kite login |
| Index closes | `kite/index_history` | `data/parquet/indices/` | Yes | Yes |
| 5-minute bars | `kite/backfill_intraday` | `data/parquet/intraday_5m/` | Yes | Yes |
| Intraday candles (on demand) | `kite/intraday` | `data/raw/intraday/` | Yes | Yes |
| F&O implied volatility (live snapshot) | `kite/fno_iv` | `output/live/fno_iv_latest.json` | Yes | **No — live snapshot** |
| MCX futures | `kite/mcx` | `data/parquet/commodities/mcx/` | Yes | Only live contracts |
| Instrument master | `kite/instruments` | `data/raw/instruments_*.csv` | Yes | Yes |
| Stock universe, index lists | `nse/universe` | `data/raw/all_nse_eq_*.csv` | No | Yes |
| EOD bhavcopy | `nse/bhavcopy` | `data/raw/bhavcopy/` | No | Yes |
| F&O stock list | `nse/fo` | `data/raw/fo/` | No | Yes |
| Nifty futures closes | `nse/fo_bhavcopy` | `data/processed/nifty_futures.parquet` | No | Yes |
| FII/DII flows | `nse/fii_dii` | `data/raw/fii_dii/` | No | **No — live day only** |
| Bulk and block deals | `nse/bulk_deals` | `data/processed/bulk_block_deals.parquet` | No | **No — live day only** |
| Delivery % | `nse/delivery` | `data/processed/delivery_matrix.parquet` | No | Yes |
| Stock OI and PCR | `nse/stock_oi` | `data/processed/stock_oi.parquet` | No | **No — forward only** |
| Insider trading | `nse/insider_trading` | `data/processed/insider_trading.parquet` | No | Yes |
| Shareholding pattern | `nse/shareholding` | `data/processed/shareholding_pattern.parquet` | No | Yes |
| ASM/GSM lists | `nse/surveillance` | `data/raw/surveillance/` | No | **No — no history** |
| Announcements | `nse/announcements`, `announcements_store` | `data/raw/announcements/` | No | Yes (`backfill_announcements`) |
| Quarterly financials | `nse/financial_results`, `update_financials` | `data/raw/financials/`, `data/processed/financials.parquet` | No | Yes (`backfill_financials`) |
| Earnings calendar | `nse/earnings_calendar` | `data/processed/earnings_calendar.parquet` | No | **No — rolling** |
| Bonus events | `nse/bonus` | `data/processed/bonus_events.parquet` | No | Yes |
| Shares outstanding | `other/company_master` | `data/processed/company_master.parquet`, `shares_out_history.parquet` | No | **History: forward only** |
| Mutual-fund holdings | `other/mf_holdings` | `data/processed/mf_holdings.parquet`, `mf_scheme_holdings.parquet` | No | Monthly files only |
| Macro news sentiment | `other/gdelt_sentiment` | `data/raw/gdelt/` | No | Yes |
| News feed | `other/news` | `data/raw/news/` | No | **No — live feed** |
| Global markets, commodities | `other/global_markets`, `global_commodities` | `data/parquet/commodities/global/` | No | Yes |
| Spot commodities | `other/spot_commodities` | `data/parquet/commodities/spot/` | No | Yes |

Rows marked **No** must run every trading day, or the missed day is lost for good.
