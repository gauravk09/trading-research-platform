# BUGS.md — alpha_forge

Grouped by the lesson, not by date. Each entry: what looked fine, what was
actually wrong, how it was found, the fix. Ends with a tally of what caught each.

---

## Lesson: a "convenience default" can re-introduce a bug you already fixed elsewhere

### B1 — `pct_change()` silently pads gaps → fabricated returns
- **Where:** `dsl.py`, `build_fields`, the `returns` field.
- **Looked fine:** `close.pct_change()` is the obvious way to get daily returns.
- **Actually wrong:** pandas' default `fill_method='pad'` forward-fills NaNs *before*
  differencing. For a stock with a gap in its history (suspension, missing day), it
  fabricates a **0% return** across the gap — the exact forward-fill trap that `data.py`
  was careful to avoid, sneaking back in one layer up. Any alpha using `returns` would
  inherit fake data on non-trading days.
- **Found by:** a `FutureWarning` pandas emitted at runtime — not a wrong number I chased,
  the library warned about the deprecated pad default and that flagged the semantics.
- **Fix:** `close.pct_change(fill_method=None)`. Output on the three seed alphas was
  identical (they don't use `returns`), but the field is now correct for every future one.

---

## Lesson: the number you PRINT must be the number that DECIDED — or the evidence lies

### B2 — originality shown as 0.00 for every banked factor
- **Where:** `run.py`, first version of `run_batch`.
- **Looked fine:** each candidate was scored (IC, complexity, originality) in `evaluate_candidate`,
  then banked in a sequential loop.
- **Actually wrong:** originality was measured *once*, in `evaluate_candidate`, against the zoo as it
  stood at eval time — which was **empty** for the whole batch. Banking is sequential, so the second
  factor really faced a one-item zoo, the third a two-item zoo, etc. The printed `orig=0.00` for
  banked factors was the empty-zoo number, not the number that actually gated them. The decision was
  still correct (re-checked live), but the *displayed evidence* didn't match the decision.
- **Found by:** eyeballing the output — every banked row showing `orig 0.00` while `rev_5` was banked
  right after `pv_corr` looked impossible.
- **Fix:** moved originality + net-fitness out of `evaluate_candidate` (they are zoo-relative) into the
  sequential bank loop, measured against the live zoo. `rev_5` now correctly shows `orig 0.19` vs the
  already-banked `pv_corr`. Evidence == decision.

---

## Lesson: code that worked with one input silently breaks when the input grows a second element

### B3 — `sqlite3` `execute()` runs only ONE statement; schema had two
- **Where:** `ledger.py`, `RunLedger.__init__`.
- **Looked fine:** `self.conn.execute(SCHEMA)` created the `runs` table perfectly while `SCHEMA` held a
  single `CREATE TABLE`.
- **Actually wrong:** when the `run_meta` table was added, `SCHEMA` became TWO statements. `execute()`
  raises `sqlite3.Warning: You can only execute one statement at a time` — it never runs multi-statement
  SQL. The exception crashed `__init__`, which crashed `run.py` *before any factor banked*, so the whole
  definitive run produced no zoo file.
- **Found by:** the ledger CLI threw on open, and `factors.jsonl` was mysteriously missing after a
  "successful" (exit-0, because backgrounded) run — the missing output was the tell.
- **Fix:** `self.conn.executescript(SCHEMA)`, which runs multiple statements.
- **Lesson:** the single-statement version passed every test until a second statement existed. Same shape
  as B1 — a default that's fine until the input changes under it.

---

## Lesson: a hardcoded output path silently contaminates a "separate" run

### B4 — bank_validated wrote to a fixed `zoo_oos`, ignoring the intended new dir
- **Where:** `bank_validated.py`, `FactorZoo("zoo_oos", ...)` hardcoded.
- **Looked fine:** I ran it "to build zoo_20" with a target/tmin; it appended factors as expected.
- **Actually wrong:** the output dir was hardcoded to `zoo_oos`, so the run APPENDED to the validated
  10-factor deliverable instead of creating a separate `zoo_20`. It timed out mid-run, leaving `zoo_oos`
  at 12 (10 real + 2 partial contaminants), and `zoo_20` never existed.
- **Found by:** the hypothesis-join print showed 12 rows where 10 were expected — the count was wrong.
- **Fix:** restored `zoo_oos` to its first 10 lines; wrote `assemble_zoo.py` which takes the output dir
  as a parameter (and also carries the hypothesis + strength tier, which bank_validated never stored).
- **Lesson:** an output path that can't vary per run will eventually write to the wrong place. Parameterize
  destinations; never hardcode a shared artifact dir in a tool meant to be re-run with different targets.

---

### Tally — what found each bug
| bug | found by |
|---|---|
| B1 pct_change pad | runtime FutureWarning (library told on itself) |
| B2 stale originality display | eyeballing output — all-zeros looked impossible |
| B3 execute vs executescript | CLI crash + a missing output file after an "ok" run |
| B4 hardcoded zoo_oos path | a row count of 12 where 10 was expected |
