# Trading Setup — Project Instructions

## Project Goal
A modular trading research platform for building, scanning, and backtesting strategies.
Each strategy lives in its own folder under `strategies/`.

## Code Rules
- Write simple, readable code — every function should be understandable without comments
- Keep everything modular: one file = one responsibility
- Do not change adjacent features — only touch what is asked for
- No over-engineering: prefer 10 clear lines over 5 clever ones

## Comprehension Mode — Trading-Specific Additions
On top of the global comprehension-mode rule, flag these failure modes explicitly
whenever a diff touches `indicators/`, `filters/`, `strategies/`, or `updater.py`/`storage.py`:
- **Look-ahead bias**: does the calculation use any data that wouldn't have been
  available at that bar's close (e.g. today's high/low used to confirm today's signal)?
- **Survivorship / universe bias**: does a filter or backtest silently drop delisted,
  suspended, or newly-listed symbols in a way that skews results?
- **Date/index alignment**: off-by-one errors in rolling windows, `shift()`, or
  merging Kite data with bhavcopy data on the wrong trading day.
- **Corporate actions**: splits/bonuses/dividends that break price continuity if
  not adjusted for, especially in `returns.py` and `relative_strength.py`.
- **NaN/edge handling**: what happens at the start of a series (insufficient bars
  for a moving average or ADR window) — silently wrong number vs. explicit NaN.
- **IST timezone**: any place mixing naive timestamps with IST-aware ones from Kite.

These are the traps that "look correct" in a quick read but produce silently wrong
scan/backtest results — call them out even if the general walkthrough would consider
the code obviously correct.

## Project Structure
```
Tading Setup/
├── .claude/CLAUDE.md           ← this file
├── .env                        ← API keys (never commit)
├── requirements.txt
├── src/
│   ├── indicators/             ← reusable indicator building blocks
│   │   ├── returns.py          ← n_day_return(), month_return()
│   │   ├── moving_averages.py  ← sma(), ema(), is_above_ma(), is_surfing_ma()
│   │   ├── volatility.py       ← adr(), atr(), max_stop_distance()
│   │   ├── volume.py           ← avg_volume(), volume_ratio(), avg_turnover_cr()
│   │   ├── relative_strength.py ← rs_rank(), composite_rs_rank(), residual_rs_rank(), top_n_by_rs()
│   │   ├── trend_stage.py      ← trend_age(), base_count(), base_pivots(), maturity_label()
│   │   └── factor_model.py     ← PCA absorption ratio + residual momentum (math only)
│   ├── risk/                   ← market risk state, sizing and the daily plan gates (see its README.md)
│   │   ├── regime.py           ← HMM crash-risk dial (CALM/ELEVATED) that sets sizing knobs
│   │   ├── sizing.py           ← side-aware position sizing and portfolio risk
│   │   └── plan_contract.py    ← typed daily plan + deterministic gates
│   ├── scanners/               ← live and EOD candidate finding, ranking, order tickets (see its README.md)
│   │   ├── live_anticipation.py ← live intraday scanner server (port 8602) + live_anticipation.html
│   │   ├── live_scanner.py     ← live quotes + EOD history → scan tables
│   │   ├── order_pad.py        ← ranked candidates → order tickets and manual punch-in cards
│   │   ├── strategy_registry.py ← the validated strategies, their gates and playbook links
│   │   ├── conviction.py, trade_metrics.py ← ranking queue and P(profit)/expectancy per candidate
│   │   ├── overnight_news.py   ← after-close filings ranked for next-day trades
│   │   └── tracker.py          ← "started watching here" stamps for the live dashboard
│   ├── execution/              ← account, paper trading and order handling (see its README.md)
│   │   ├── kite_account.py     ← live margins, positions, holdings snapshot
│   │   ├── paper_broker.py, rehearsal.py ← paper-trade replay and zero-money execution rehearsal
│   │   └── orders/             ← plan → preview → place → trail (cli.py is the entry point)
│   ├── evaluation/             ← grades decisions and forward-tests strategies (see its README.md)
│   │   ├── grade_decisions.py  ← +1/+3/+5/+20d forward returns for every recorded decision
│   │   ├── incubation.py       ← S7 paper-signal generator for factory strategies
│   │   └── s7_verdict.py       ← nightly read-out of the S7 forward record
│   ├── pipeline/               ← the nightly job and daily state; calls every other layer (see its README.md)
│   │   ├── run_daily.py        ← the nightly 9-step update (cron runs this)
│   │   ├── collect_all.py      ← full history for new IPOs / missing stocks
│   │   └── daily_state.py      ← writes the machine-readable daily state file
│   ├── filters/                ← standalone composable scan filters (True/False)
│   │   ├── liquidity.py        ← min_turnover_filter()
│   │   ├── trend.py            ← above_ma_filter(), surfing_ma_filter(), ma_stack_filter()
│   │   ├── momentum.py         ← min_return_filter(), breakout_return_filter(), rs_rank_filter()
│   │   ├── volatility.py       ← min_adr_filter(), stop_within_adr()
│   │   ├── consolidation.py    ← tightening_range_filter(), higher_lows_filter()
│   │   └── surveillance.py     ← surveillance_filter() (ASM/GSM exclusion)
│   └── data_collection/        ← ALL data collection lives here (see its README.md for the full table)
│       ├── storage.py          ← parquet read/write (single source of truth for file paths)
│       ├── paths.py            ← ROOT_DIR shared by every collector
│       ├── kite/               ← needs a Kite login: auth, instruments, historical, updater,
│       │                         intraday, backfill_intraday, mcx, index_history, fno_iv
│       ├── nse/                ← free NSE data: universe, bhavcopy, fo, fo_bhavcopy, fii_dii,
│       │                         bulk_deals, delivery, stock_oi, insider_trading, shareholding,
│       │                         surveillance, announcements, financial_results, earnings_calendar, bonus
│       └── other/              ← BSE/AMC/GDELT/Yahoo/LBMA: company_master, mf_holdings,
│                                 gdelt_sentiment, news, global_markets, global_commodities, spot_commodities
│   └── preprocessing/          ← builds derived datasets from collected data (see its README.md)
│       ├── precompute.py       ← universe_summary + close/high/low/volume matrices (dashboard base)
│       ├── mm_history.py       ← 10-year Market Monitor breadth history
│       ├── market_rhythm.py    ← frozen-basket leader spread, winner attribution
│       ├── build_sector_map.py, build_vol_curve.py   ← one-off builders (sector map, intraday volume curve)
│       ├── factor_report.py    ← prints the factor-model read-out (reads close_matrix)
│       └── commodities/        ← basis (global → MCX price) and research series
├── strategies/                 ← one folder per strategy
│   └── qullamaggie/
│       ├── SETUP_RULES.md      ← source of truth for all entry/exit/sizing rules
│       ├── scanner.py          ← master entry point (runs all 3 setups)
│       ├── breakout.py         ← Setup 1: Breakout from Consolidation
│       ├── episodic_pivot.py   ← Setup 2: Episodic Pivot
│       ├── parabolic.py        ← Setup 3: Parabolic Short / Long Bounce
│       └── position_sizing.py  ← shared position sizing + partial exit calculator
├── data/
│   ├── raw/                    ← downloaded files as-is
│   └── processed/              ← cleaned/merged data
├── logs/
├── output/                     ← scanner results per strategy
├── webapp/                     ← THE dashboard: FastAPI (server/) + React (frontend/)
│                                  run via run_dashboard.command · Streamlit desk removed 2026-08-06
└── docs/                       ← plain-English strategy references (user-facing)
    ├── SCANS_REFERENCE.md      ← what every scan computes (served by the webapp)
    └── stockbee_pradeep_bonde_trading_setup.md
```

## Documentation
Three layers, kept deliberately separate:
- **`ROADMAP.md`** (repo root) — single source of truth for what's built, what's
  next, what's **rejected and why**, and open decisions. Read it before proposing
  features; update statuses when work lands; never re-propose a Rejected item
  without new evidence.
- **`docs/`** — plain-English strategy references written for the user to *understand*
  a method end-to-end (e.g. `stockbee_pradeep_bonde_trading_setup.md` covers Bonde's
  full momentum-burst / Episodic Pivot / short playbook). Learning material, broader
  than what the code implements.
- **`strategies/**/SETUP_RULES.md`, `strategies/**/SCAN_RULES.md`, `docs/SCANS_REFERENCE.md`**
  — the source of truth for what the code actually computes.

**Design decision:** when a `docs/` reference describes more than the code implements,
that gap is intentional — `docs/` is the roadmap of the full method; the code plus the
rule files define the subset that is currently built and scannable. Use `docs/` to
decide *what to build next*; use the rule files to verify *what exists today*.

## Data Sources
| Source | What | When |
|--------|------|------|
| Kite Connect API | Daily OHLCV, instrument master | EOD daily |
| NSE Bhavcopy | Full market EOD + 52-wk H/L | EOD daily |
| NSE Nifty indices | Configurable scanning universe | Weekly |
| NSE Bulk/Block deals | Institutional activity | EOD daily |
| NSE FII/DII | Market regime filter | EOD daily |

## Universe Philosophy
- **Collection layer:** ALL NSE EQ-series stocks (~2100). We store full history
  for every stock — even illiquid ones — so backtests can reach into the past.
- **Scan layer:** Each strategy applies its own filters (liquidity, ASM/GSM,
  market-cap segment) at scan time, NOT at collection time.
- Helpers in `nse_universe.py`:
  - `get_all_nse_eq_symbols()` — full universe for collection
  - `build_universe([indices])` — index-based subset for scanners that want it
  - `build_full_nse_universe(min_avg_turnover_cr)` — liquidity-filtered subset
- `nse_surveillance.py.get_excluded_symbols()` — ASM/GSM set to exclude at scan time

## Daily Operations

### Automated (cron at 8 PM IST, weekdays)
`src/pipeline/run_daily.py` runs automatically and handles:
- Incremental OHLCV fetch from Kite (only new days, not full history)
- NSE Bhavcopy download + Kite vs bhavcopy price reconciliation
- FII/DII, bulk/block deals, corporate announcements, F&O list
- Rebuilds dashboard summary (`data/processed/universe_summary.parquet` + `close_matrix.parquet`)

At 8:25 PM a Claude desktop scheduled task ("daily-trading-brief") auto-generates
the /brief output — it re-runs `run_daily.py` itself first if the state file is
stale, and warns in the brief if data could not be refreshed. Runs only while
the Claude app is open (queued to next launch otherwise).

### Manual — Kite token refresh (every morning)
Kite access tokens expire daily at 6 AM IST. Regenerate before market open:
```bash
PYTHONPATH=src python -m data_collection.kite.auth
```
Or paste the request_token from the Kite login URL and Claude will exchange it.
Login URL: `https://kite.zerodha.com/connect/login?api_key=<KITE_API_KEY from .env>&v=3`

### Manual — New IPO / new listing
When a new stock lists on NSE it won't have a parquet file yet.
Run once to fetch its full history and add it to the dataset:
```bash
PYTHONPATH=src python -m pipeline.collect_all
```
This re-downloads the NSE master list, finds any new symbols not yet stored,
and fetches their full history from Kite back to 2015.

Then add the new stock's metadata (industry, shares outstanding, description)
to the company master — also the fix after a split/bonus changes share count:
```bash
PYTHONPATH=src python -m data_collection.other.company_master <SYMBOL>
```

## Script Reference

| Script | Purpose | When to run |
|--------|---------|-------------|
| `src/pipeline/run_daily.py` | Full daily update (prices + NSE data + dashboard) | Automated via cron |
| `src/data_collection/kite/updater.py` | Incremental OHLCV only + reconciliation | Called by run_daily.py |
| `src/preprocessing/precompute.py` | Rebuild dashboard summary files | Called by run_daily.py |
| `src/pipeline/collect_all.py` | Full history fetch for new/missing stocks | After new IPO listing |
| `src/data_collection/kite/auth.py` | Regenerate Kite access token | Every morning |

## Environment Variables (.env)
```
KITE_API_KEY=...
KITE_API_SECRET=...
KITE_ACCESS_TOKEN=...   ← regenerate daily via: PYTHONPATH=src python -m data_collection.kite.auth
```
