# SESSION SUMMARY — 2026-08-30

A cross-sectional snapshot of where alpha_forge stands after this session.
(LEARNING.md is the chronological journey; this is the current-state cross-section.)

---

## The one-line result

The project's central problem — "nothing on this data clears retail cost" — is **solved**.
Wiring in **non-price, low-turnover information** (delivery %, then fundamentals) produced the
first factors that clear retail 15bps. The deliverable is a **combined long-only book:
OOS Sharpe 1.37, max drawdown 15%**.

## What changed the game

The whole prior project mined only 5 OHLCV fields and concluded the edge was smaller than the
cost. It was **starved, not exhausted**. Two new information axes broke the wall:

| axis | best factor | OOS result | why it works |
|---|---|---|---|
| **Delivery %** | `deliv_high` = `rank(deliv_x20)` | t +8.4, robust in 100% of windows | non-price: real accumulation vs churn |
| **Fundamentals (GARP)** | `value_growth` = `rank(earn_yield + pat_yoy)` | net SR **+1.36 long-only OOS @15bps** | cheap AND growing; ~1mo PEAD; turnover 0.05 |

Low turnover (quarterly signals) is the ingredient the 5-day OHLCV factors never had.

## The three working sleeves (the book)

| sleeve | horizon | OOS Sharpe | notes |
|---|---|---|---|
| Momentum | 6-12mo | 1.13 | zoo_final; retail-viable price edge |
| Fundamentals / GARP | ~1mo | 1.36 | zoo_fundamentals; new, non-price, decorrelated axis |
| **Combined + regime overlay** | blend | **1.37, DD -15%** | the deliverable → `backtest_reports/combined_book.pdf` |

Key nuance: the two long-only sleeves are **0.77 correlated** (shared market beta). The **regime
overlay** (skip weak markets) does the drawdown work, not factor diversification — it cuts combined
DD -41% → -20% for ~0 CAGR cost.

## New engine capabilities built this session

- **Feature wiring** (`data.load_features`, `dsl` `extra=`): the miner can now score the 29 pre-built
  feature matrices + fundamentals + debt, not just OHLCV. tz-alignment trap closed.
- **As-of-safe fundamentals** (`fundamentals.py`): quarterly earnings as factor fields, keyed on
  filing_date+1 (never quarter_end), bounded YoY growth, 11 derived fields.
- **Walk-forward robustness gate** (`walkforward.py`): classifies factors REAL / DECAYING / DEAD
  across ~24 half-year windows — separates a faded edge from a fake one (a single OOS split can't).
- **Tradeable-score selection** (`calibrate.py` `tradeable_score`): selection metric is now banded
  net-SR, not raw IC (#4).
- **Debt extraction** (`extract_debt.py`): balance-sheet debt from cached XBRL, as-of-safe (built,
  but the leverage factor it feeds is dead — see below).

## Decisions locked this session

- **λ CALIBRATION RESOLVED (DECISIONS D5):** enable **λ2=0.001 (complexity)** — it lifts OOS-rank
  prediction +0.21; complex factors ARE the overfits (AlphaAgent thesis confirmed on NSE). Keep
  **λ1=0** — soft originality adds nothing beyond the hard novelty gate (D9).
- **The gate is two-dimensional:** sign-consistency (walk-forward) = "is it real"; recent magnitude
  (OOS t) = "is it still alive". One number mislabels decaying edges.
- **Regime filter = risk overlay, not alpha:** +0.2 Sharpe, -9pts DD, ~0 CAGR. Keeper on the book.

## Negative results (honest, gate-caught)

- **Leverage: DEAD** — no leverage premium in liquid top-500 (priced/slow; anomaly lives in small-caps).
- **Growth acceleration: DECAYING** — level (YoY) beats change (accel) on NSE; walk-forward caught it.
- **Volume-character, sector-relative: fade OOS** — price-derived, overfit-prone family.
- **Size, mcap: unusable** — runs backwards in top-500 / data too sparse.

## Standing caveats (apply to ALL claims)

1. **Data-store survivorship:** `data/parquet/daily/` holds only currently-listed names (0 delistings
   in 11yr). Inflates absolute returns, esp. long-only. Fundamentals edge survives it (long-only + decile
   monotone + no staleness), but trust Sharpe/DD over absolute CAGR. Fix = PIT universe with delistings.
2. **Unadjusted splits:** e.g. PRIVISCL +567,400% in the store. Rank-IC immune; raw-return backtests
   exposed. → background task scanning the store (running).
3. **Short leg:** L/S Sharpes assume shortability (SLB/futures). Long-only is the retail-real version.

## Next candidates (not started)

- Balance-sheet EQUITY data for ROE/accruals — parser change is ~20 lines but data too young
  (equity from Mar-2025, half-yearly); revisit ~2yr out.
- Wider universe (sub-500) — where size/reversion/illiquidity premia actually live.
- PIT-with-delistings universe — to retire caveat #1.
- Productionise the combined book into the live scanner / brief.
