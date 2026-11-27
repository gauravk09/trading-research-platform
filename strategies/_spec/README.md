# Strategy spec format

Every strategy is one JSON file, `strategies/<id>/spec.json`, for one **setup**
(a trader who teaches three setups gives three folders). The structure is fixed
by [`schema.json`](schema.json). The worked example is
[`strategies/zanger/spec.json`](../zanger/spec.json).

The file is the machine-readable form of the S1 pre-registration in
[`research/FACTORY.md`](../../research/FACTORY.md). The older specs and the
factory ledger now live, read-only, in [`strategies/_archive/`](../_archive/).

## Versioning

The schema carries a `schema_version` (now `"1.0"`), and every spec states the
version it was written against. Any change to `schema.json` bumps the version
and adds one line to [`CHANGELOG.md`](CHANGELOG.md); a test checks that the
two agree. Runs store the `schema_version` they were built from.

## The strategy id

`must_have.from_house.id` is a fixed slug, never free text: lowercase letters,
digits and underscores (`^[a-z0-9_]{3,60}$`). It must equal the folder name,
so `strategies/zanger/spec.json` has `"id": "zanger"`. Folder names are unique,
so ids are too; a test enforces both. When a spec's rules change, the id stays
the same: every run stores the spec's `spec_hash`, which is what tells two
versions of the rules apart.

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
event, the stop and an exit. Numbers may be proxies (see below) when the source
gives none, but if the source never says how you get in or out, there is no
strategy to test.

## Where each rule came from: `origin`

Every condition, stop, exit and number carries an `origin`:

| `origin` | Meaning | Needs a `quote`? |
|---|---|---|
| `source` | The source states this rule, with this number | Yes, verbatim (the schema rejects it otherwise) |
| `proxy` | The source describes the rule but gives no exact, codable version, so **we** chose the number or definition | No, but quote the sentence it stands in for |
| `house_default` | A repo convention, not from the source | No |

**Example (Zanger's volume rule).** His sources say breakout volume must be
*"above the recent trend - know the stock's 30-day average volume"*. That is a
real rule, but it gives no multiple, and code needs one. So the spec writes
`volume >= 2.0 * vol_avg30[1]` and marks it `"origin": "proxy"`: the 30-day
average is his, the 2.0 is ours. By contrast, his chase limit (*"Never pay more
than 5% above the trendline / breakout point"*) gives its own number, so it is
`"origin": "source"`.

This matters when reading results: a strategy that fails may only have failed
on our proxies, not on the trader's rules. The proxies are where to look first.

## Rules every agent follows

1. **Every rule carries its origin** (above). Never present a proxy as a
   source rule.
2. **Check prior work first** (`prior_work_check`): search `ROADMAP.md` (Rejected
   section), `strategies/_archive/LEDGER.md`, `src/backtest/studies/` and
   `src/scanners/strategy_registry.py`. A Rejected match blocks the spec unless
   `new_evidence` says what is new.
3. **No look-ahead.** Each condition states `known_at`. A condition evaluated at
   the signal close may only use data up to that close. Delivery % (`deliv_x20`)
   is `next_open`.
4. **At most 3 variants, named before any test.** Nothing is added after
   results are seen; a new idea is a new spec.
5. **Uncodable rules go in `uncodable_elements`** with the proxy used, never
   silently dropped.
6. **Use only feature-store names** in `expr` (below). A rule that needs
   something else waits until that feature is added to the store.
7. **External results are quoted, not summarised from memory.** Each result
   needs the page it came from, a verbatim `quote`, how closely their rules
   match ours (`rules_match`, `differences`), and a `credibility` with a
   reason. A page that would not load is left out, not guessed.

## Checking quotes and external evaluations: a review step, not code

The schema checks that quotes, URLs and search logs are **present**. It cannot
check that they are **true**. That is a research review step before a spec is
merged: a reviewer (person or agent, not the one that wrote the spec) opens
each `sources` and `external_evaluations` URL and confirms:

- each `quote` appears on that page, word for word;
- each `origin: "source"` rule really is what the quote says, and nothing was
  made stricter or looser along the way;
- `rules_match` and `differences` are honest about how far an external test
  is from this spec;
- `found_any: false` searches were real searches (the `search_log` queries
  make sense for the setup).

Problems are fixed in the spec, not waved through.

## House defaults for `from_house`

| Key | Default | Where it comes from |
|---|---|---|
| `id` | the folder name | this README |
| `stage` | `S1` | `research/FACTORY.md` |
| `instrument` | `nse_cash` for long; `nse_stock_futures` for short | `strategies/_archive/STYLE.md` |
| `universe` | `nse_eq_all`, `min_turnover_cr` 5 (10 for EP/gap), `min_price` 0 | `strategies/_archive/STYLE.md` |
| `costs_pct_per_side` | 0.2 | `research/FACTORY.md` (0.4% round trip) |
| `entry_clocks_tested` | `["signal_close_strong", "next_open"]` | `research/FACTORY.md` lever 1 |
| `eras` | A 2015-19, COVID 2020-22, B 2023-26, sub_2024_26 | `research/FACTORY.md` |
| `control_type` | `same-date matched random` | `src/backtest/canonical_runner.py` |
| `survivorship` | "Survivors-only price cache; delisted names absent" | root README |
| `success_bars` | S2: PF >= 1.2 in eras A and B, n >= 150. S5: >= +3%/yr after costs | `research/FACTORY.md` |
| `dedup_bars` | 10 | house studies |

## Expression vocabulary

An `expr` is evaluated per stock on the signal bar. It may use:

- **Bar fields:** `open high low close volume`.
- **Feature-store names:** exactly the names in `FEATURE_NAMES` in
  [`src/backtest/features.py`](../../src/backtest/features.py), the single list
  of what the central feature store computes. There is no second list here, so
  specs cannot drift from the store. Print the current list with
  `PYTHONPATH=src python -c "from backtest.features import FEATURE_NAMES; print(FEATURE_NAMES)"`.
- **Level names** defined in `entry.levels` (e.g. `"pivot": "close_max20[1]"`),
  and in stops and exits also `entry` (the fill price).
- **Lags:** `x[n]` is the value `n` bars ago (`[1]` = yesterday). Negative lags
  are not allowed.
- **Operators and numbers:** `> >= < <= == and or not + - * /`.

There are **no functions** (no `sma()`, `max()`, `bars_since()`): a strategy
never computes its own indicator. If a rule needs one the store doesn't have,
add it to `features.py` (and `FEATURE_NAMES`) first. That is how the Zanger
spec got `close_max20`, `low_min20`, `sma20`, `vol_avg30`, `turnover20_cr`,
`days_since_20dh` and `range_pos`.

**Data with no history (cannot be backtested):** ASM/GSM lists, FII/DII, bulk
deals, stock OI, the live news feed. A rule that needs one of these is
uncodable for backtest purposes.

## Validate a file

```bash
pip install jsonschema
python -c "import json,jsonschema; jsonschema.validate(json.load(open('strategies/zanger/spec.json')), json.load(open('strategies/_spec/schema.json'))); print('valid')"
python -m pytest strategies/_spec -q    # schema self-tests, ids, changelog, vocabulary
```
