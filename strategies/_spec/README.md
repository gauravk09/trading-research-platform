# Strategy spec format (v1.0)

One JSON file per **setup** (a trader who teaches three setups gives three files).
The structure is fixed by [`strategy.schema.json`](strategy.schema.json); a filled
example is [`examples/dan_zanger_breakout.json`](examples/dan_zanger_breakout.json).

The file is the machine-readable form of the S1 pre-registration in
[`research/FACTORY.md`](../../research/FACTORY.md). It replaces nothing there:
`SPEC.md`, `LEDGER.md` and the S2-S8 stages still apply.

## How a spec gets filled: two agents

| Step | Agent | Fills | Searches for |
|---|---|---|---|
| 1 | **Researcher** | `must_have`, most of `good_to_have`, `extras` | The trader's own rules: books, interviews, videos, blogs, forum posts. Several searches, several sources. |
| 2 | **Evaluation checker** | `good_to_have.external_evaluations` only | Whether **other people** already tested this setup, and what they found: backtests, live records, papers, forum threads. |

The checker runs on every spec. "Searched and found nothing" is a valid answer
(`found_any: false`, empty `results`) and still needs the `search_log`, so
nobody repeats the same search later. What the trader claims about their own
results goes in `claimed_performance`; independent tests go in
`external_evaluations`. Keep them apart.

## The three tiers

| Tier | Who fills it | If missing |
|---|---|---|
| `must_have.from_source` | Researcher, from public sources | **Stop. The strategy cannot be formed.** |
| `must_have.from_house` | Researcher, copying repo defaults and running repo checks (never scraped) | Fill from the defaults below |
| `good_to_have` | Researcher and checker, from sources when they say it; otherwise a flagged proxy or empty | Fine to leave empty |
| `extras` | Anyone | Fine to leave empty |

**The stop rule.** A source must at least *describe* the direction, the entry
event, the stop and an exit. Numbers may be proxies (`"origin": "proxy"`) when
the source gives none, as in the Zanger example, but if the source never says
how you get in or out, there is no strategy to test.

## Rules every agent follows

1. **Every rule carries its origin.** `source` needs a verbatim `quote` (the
   schema rejects it otherwise). `proxy` means "our number, the source gives
   none". `house_default` means a repo convention. Never present a proxy as a
   source rule.
2. **Check prior work first** (`prior_work_check`): search `ROADMAP.md` (Rejected
   section), `research/factory/LEDGER.md`, `src/backtest/studies/` and
   `src/scanners/strategy_registry.py`. A Rejected match blocks the spec unless
   `new_evidence` says what is new.
3. **No look-ahead.** Each condition states `known_at`. A condition evaluated at
   the signal close may only use data up to that close. Delivery % (`deliv_x20`)
   is `next_open`.
4. **At most 3 variants, named before any test.** Nothing is added after
   results are seen; a new idea is a new file.
5. **Uncodable rules go in `uncodable_elements`** with the proxy used, never
   silently dropped.
6. **Use only the vocabulary below** in `expr`. Anything else goes in
   `new_features_needed` with an exact, causal definition.
7. **External results are quoted, not summarised from memory.** Each result
   needs the page it came from, a verbatim `quote`, how closely their rules
   match ours (`rules_match`, `differences`), and a `credibility` with a
   reason. A page that would not load is left out, not guessed.

## House defaults for `from_house`

| Key | Default | Where it comes from |
|---|---|---|
| `stage` | `S1` | FACTORY.md |
| `instrument` | `nse_cash` for long; `nse_stock_futures` for short | STYLE.md |
| `universe` | `nse_eq_all`, `min_turnover_cr` 5 (10 for EP/gap), `min_price` 0 | STYLE.md |
| `costs_pct_per_side` | 0.2 | FACTORY.md (0.4% round trip) |
| `entry_clocks_tested` | `["signal_close_strong", "next_open"]` | FACTORY.md lever 1 |
| `eras` | A 2015-19, COVID 2020-22, B 2023-26, sub_2024_26 | FACTORY.md |
| `control_type` | `same-date matched random` | canonical_runner.py |
| `survivorship` | "Survivors-only price cache; delisted names absent" | root README |
| `success_bars` | S2: PF >= 1.2 in eras A and B, n >= 150. S5: >= +3%/yr after costs | FACTORY.md |
| `dedup_bars` | 10 | house studies |

## Expression vocabulary

Expressions are evaluated per stock on the signal bar. `x[n]` means the value
`n` bars ago (`[1]` = yesterday); negative lags are not allowed. Operators:
`> >= < <= == and or not + - * /`.

**Bar fields:** `open high low close volume`. In exits and stops, also `entry`
(the fill price) and any name defined in `entry.levels` (e.g. `pivot`).

**Functions:**

| Function | Meaning |
|---|---|
| `sma(x,n)`, `ema(x,n)` | Moving averages |
| `max(x,n)`, `min(x,n)`, `avg(x,n)` | Rolling max / min / mean over the last n bars, including today |
| `ret(x,n)` | % change over n bars |
| `atr(n)`, `adr(n)` | Average true range (price); average daily range (%) |
| `range_pos` | `(close - low) / (high - low)`, 0 to 1 |
| `gap_pct` | `(open - close[1]) / close[1] * 100` |
| `turnover_cr(n)` | Average daily traded value over n bars, ₹ crore |
| `bars_since(cond)` | Bars since `cond` was last true |

**Repo feature store** (`data/processed/features/`, built by `src/backtest/features.py`, all `known_at: close` unless noted):
`rs` `ti65` `ret7` `ret21` `ret30` `bounce_low21` `pct_52wh` `pct_52wl`
`days_since_52wh` `eff_ratio` `adr20` `tightness` `rvol50` `volc5_50`
`turn_decile` `dist_50dma` `trend_age` `consol_days` `days_since_burst`
`burst_success` `sector_rs` `trend_template` `updown_vol50` `pocket_pivot`
`rsline_pct52wh`, and `deliv_x20` (**`next_open`**, from 2020-10).

**Market breadth** (`data/processed/mm_history.parquet`): `market.pct40ma`
(% of stocks above their 40-DMA), `market.pct20ma`, `market.net4`,
`market.ratio10`, `market.net25q`, `market.ti65_nifty50`, `market.ti65_nifty500`.
These follow the house previous-close rule: a signal on day t sees day t-1's value.

**Calendar:** `month` `dow` `dom`.

**Reserved, not yet computable:** fundamentals (`fin.revenue_cr`, `fin.pat_cr`,
`yoy()` from `data/processed/financials.parquet`) need a point-in-time join on
`filing_date` that is not built yet. Describe such rules in `variants` or
`uncodable_elements` for now.

**Data with no history (cannot be backtested):** ASM/GSM lists, FII/DII, bulk
deals, stock OI, the live news feed. A rule that needs one of these is
uncodable for backtest purposes.

## Validate a file

```bash
pip install jsonschema
python -c "import json,jsonschema; jsonschema.validate(json.load(open('FILE.json')), json.load(open('strategies/_spec/strategy.schema.json'))); print('valid')"
python -m pytest strategies/_spec -q    # schema self-tests
```
