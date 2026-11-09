---
name: brief
description: Generate the daily trading brief from the latest daily state file plus the live Kite account. Use when the user says /brief, "daily brief", "what's the plan today/tomorrow", or after an EOD update completes.
---

# Daily Trading Brief

Produce a one-page, decision-ready brief from deterministic inputs. You add
judgment and prose; you NEVER override the regime tier, recompute breadth, or
invent candidates not present in the state file. You NEVER place, modify, or
cancel orders — the brief prepares decisions, the human executes.

## Inputs

1. `output/state/latest.json` — regime + knobs, breadth trend, scans, OHLCV
   windows, open tracked trades. If its `meta.data_date` is older than the last
   trading day, warn prominently and offer to run
   `PYTHONPATH=src python -m data_collection.run_daily` (anaconda3 python) first.
   The file also carries `news` — the latest archived Pulse headlines
   (published, source, headline, url). These are raw aggregated headlines, NOT
   a signal: use them only for context/color, never to justify a trade the
   scans did not surface. Note Pulse mixes in non-market news (sport, cinema) —
   ignore the noise.
2. Recent history for the situational-awareness read: the last ~10 files in
   `output/state/` (watchlist-size trend = each day's scan `total_matches`,
   breadth trend, and `participation.ratio_20d` — today's market turnover vs
   its 20-day average) and yesterday's line in `output/brief/journal.jsonl`
   (its `situational_awareness` field, for the review).
3. Other markets: run `PYTHONPATH=src python -m data_collection.other.global_markets` (anaconda3 python) —
   prints last close + day change for Nifty/Bank Nifty, S&P 500, Nasdaq, Dow,
   Nikkei, Hang Seng, USD/INR, Brent, Gold. Context only — never a regime
   input. If the fetch fails (offline), say so and move on.
4. Live account: run `python src/kite_account.py` (anaconda3 python) — prints
   a JSON snapshot of available balance, open positions, and holdings via the
   KiteConnect API (same `.env` token as `auth.py`). Use this instead of the
   Kite MCP — the MCP has proven unreliable ("please log in first" even with
   a valid token) while this script reads the token directly. If it exits
   with an `error` field (token actually expired), say so (fix:
   `PYTHONPATH=src python -m data_collection.kite.auth`) and fall back to the last known equity figure from
   the journal, clearly labelled as stale.

## Position sizing (mechanical — show the arithmetic)

For each candidate with an `entry_price` and `stop_price`:

- `risk_amount = equity × knobs.risk_per_trade_pct / 100`
- `qty = floor(risk_amount / (entry_price − stop_price))`
- `position_value = qty × entry_price`; cap so total open + new positions stay
  within `knobs.max_gross_exposure_pct` of equity, and count of positions
  within `knobs.max_open_positions`.
- **One risk bucket (user decision 2026-07-18): F&O notional counts against the
  gross-exposure cap.** The F&O book is NOT ring-fenced — if futures/options
  notional already exceeds the cap, every new swing entry is BLOCKed, and that
  is the intended behaviour. Do not re-ask; revisit only if grader evidence
  shows blocked recos consistently outperform.
- Flag any candidate whose entry-to-stop distance exceeds ~1.5× its `adr_pct`
  and suggest a smaller size — as RISK-NORMALIZATION only. The backtest found
  wide-stop trades no worse per R (slightly higher win rate); do not present
  the flag as a quality strike against the setup.
- Only draw candidates from scans listed in `knobs.allowed_entries`.
- Stops follow Bonde's universal formula (TraderLion 2026): entry early in the
  day → stop at the day's low (`stop_price` from the scan); entry in the later
  half of the day → stop at HALF the day's range (`low + (high−low)/2`) so the
  risk stays proportional. State which one each recommendation uses.

## Output — write both files

1. `output/brief/<data_date>.md` — the human page, in this order:
   - **Plain language throughout**: this page is read by a human, not the code.
     Never print raw state-file keys. Use the descriptions, not the variables:
     `ratio_20d` → "market participation (turnover vs its 20-day average)";
     `ratio5`/`ratio10` → "the 5- and 10-day 4% up/down ratios"; `up25q`/`dn25q`
     → "stocks up/down 25% in a quarter"; `pct20ma`/`pct40ma` → "% of stocks
     above their 20-/40-day average". Keep numbers; drop the jargon names.
   - **TL;DR**: one sentence — regime tier + allowed entries, FII/DII, how many
     clean candidates, and the biggest overnight move in other markets.
   - **Regime**: the HMM risk regime — tier (CALM / ELEVATED), the crash-risk
     dial `p_drop_20d` vs its historical average `baseline_p_drop_20d` (say it
     as "X% chance of a 5%+ Nifty 500 drop within a month, vs Y% normally"),
     knobs in one line, FII/DII. It forecasts RISK, not direction — never
     present it as bullish/bearish. Two sentences max of interpretation, e.g.
     breadth from the 5-day monitor tail as separate context.
   - **Open positions**: each tracked trade and live Kite position — current
     stop, day count, and the action from `open_trades` (hold / move stop to
     breakeven / exit due). Reconcile: a Kite position not in the tracker (or
     vice versa) gets flagged.
   - **Sector pulse**: from `sector_breadth` (per-sector medians over the liquid
     universe), name the 2-3 leading and lagging sectors today (med_chg_pct,
     pct_up, movers_4pct) and any sector whose 1mo/3mo medians say leadership is
     rotating. Then cluster today's scan candidates by their `sector`/`industry`
     fields — if hits concentrate in one group, say so explicitly ("4 of 6
     breakout candidates are Capital Goods"). Candidates aligned with a leading
     sector deserve a nudge up in the ranking below; fighting a lagging sector
     is worth one warning sentence. Use `name`, `mcap_cr` and `cap_segment` to
     describe each candidate like a company, not a ticker ("₹3,200 Cr small-cap
     wire maker"), and flag any microcap (< ₹1,000 Cr) for liquidity risk.
   - **Top candidates**: at most 5, ranked by your read of setup quality
     (tightness of base, volume dry-up, RS rank, catalyst, chart structure
     from the OHLCV window). Each: entry, stop, qty, position value, risk ₹,
     the scan's `reason` string, and one sentence of your own judgment
     (including anything that argues AGAINST the trade — circuit-limit risk on
     EP gaps, wide stops, late-stage base_count, old trend_age_d).
   - **Passed over**: one line each for notable candidates you excluded and why.
   - **🧪 Incubation — paper signals only (NOT trades)**: render
     `state["incubation"]` as its own clearly-separated section, ALWAYS with
     this exact framing: a "🧪 PAPER ONLY — S7 forward test, do not trade"
     banner line first. For each strategy under `incubation.strategies`:
     its `label`, one line saying whether the market gates passed today
     (translate `gates` to plain words — e.g. "tape healthy: yes (net 4%
     breadth +15, 10-day ratio 1.8)"), and if `gates_pass` is true list its
     `candidates` (symbol, % change, reference stop) as SHORT paper entries
     at tomorrow's open. If gates failed, one line: "stood down (<plain
     reason>); N candidates suppressed". NEVER size these, NEVER put them in
     recommendations or the journal's recommendations array, NEVER mix them
     with Top candidates — they are being graded silently by the nightly
     grader against the backtest. If the section is missing from the state
     file, skip it.
   - **#SituationalAwareness**: 3-6 short bullet points in the trader's-notebook
     voice — first person, plain, opinionated, ONE idea per bullet and ideally
     one line each (lead with the point, not a wind-up). Write them as a markdown
     list, every line starting with "- ". One bullet per topic: (a) watchlist
     size today vs the last ~2 weeks of state files and what that says about how
     loaded the tape is (descriptive color only — watchlist size did NOT predict
     outcomes in the backtest; never present it as a signal); (b) participation —
     state the market-participation ratio (from `participation.ratio_20d`, in
     words like "0.95× its 20-day average") and read it per playbook item 9
     (<0.7 = hard no-chase; falling over 5d = soft warning; rising = mild
     positive for bursts); (c) which setup families deserve preference in this
     tape (in weak participation avoid chasing market-driven breakouts —
     playbook items 4 and 9; catalyst-driven EP/DEP entries are less
     tape-dependent but carry no validated boost from weak tapes — judge each
     on its catalyst and its own playbook rule); (d) what would change the read (the specific
     number you're watching). Ground every claim in a state-file number; never
     contradict the regime tier — interpret it.
   - **Validated signal playbook** (backtested on 2015-2026 NSE data AND
     re-validated with 2020-2022 removed; treat as ground truth and cite the
     numbers when the condition is live):
     1. *(Retired 2026-09-28.)* The follow-through day is no longer computed —
        the regime is now the validated HMM crash-risk dial. Do not cite FTD.
     2. *T2108 washout* (`pct40ma` < 20): median stock +2.7% D+20 with ~65%
        win rate vs +0.7%/55% baseline — the strongest market signal in this
        playbook. A bounce is the base case: frame reversal/bounce setups as
        the play; pilot buys on a reversal day, never knife-catching. The
        edge exists ONLY below 20 — pct40ma in 20-40 predicts nothing.
     3. *Breadth zones do NOT grade breakout quality* — bullish tape does not
        improve a breakout's odds. Never justify a marginal breakout with
        "breadth is strong"; selection flags outrank tape, always.
     4. *Burst kill-switch — net 4% movers LOW*: bottom-quartile net-4%-mover
        days produce fewer bursts (0.3-0.4x frequency) and worse ones
        (-0.07 to -0.18R, win -4 pts). Asymmetric: a HIGH reading does NOT
        help — this gauge only warns, never green-lights.
     5. *EP rules — the catalyst and the tape decide, never the chart*: no
        stock feature (RS, tightness, linearity, sector, delivery) moves
        EP9M outcomes consistently — never reject an EP9M for chart
        aesthetics, never talk one up for a pretty base. The one tape
        effect: EPs are WORSE on hot burst-momentum days (10-day 4% ratio
        top quartile: -0.05/-0.23R) — don't chase EPs when everything is
        bursting. (Scope: proven for EP9M; DEP has its own rule below.)
     6. *Dip-buy gate — the STOCK's own trend*: bounce entries require the
        stock's TI65 in its top quintile (+0.08/+0.17R). The market's trend
        adds only a mild tailwind, not a gate. Broad-market washouts favor
        LEADER bounces specifically (washout study).
     7. *Raw-4%-day freshness*: a 4% mover is only interesting FRESH — the
        tight-prior-range leg is the strongest (-0.06/-0.08R penalty for
        loose bases); stretched-off-lows and far-above-50DMA point the same
        way. Never chase a 4% day on an extended stock.
     8. *DEP = mature-base BREAKOUT only*: ~70% of orderly post-EP bases die
        before breaking out, and fast breakouts (3-5d bases, 41% of all)
        carry no edge. The entry: base age >= 11 days, buy the close that
        clears the post-event high, stop = base low -1% (+0.10/+0.08R, ~50%
        win, PF ~1.4-1.6). Never enter inside the base, never anticipate the
        breakout early; DEP names younger than ~11 days are watch-only.
     9. *Participation floor*: market turnover below 0.7x its 20-day average
        is a hard no-chase signal — 4%-day win rate collapses to 27-32%
        (-0.09/-0.35R). Participation FALLING over 5 days is a soft warning
        (-0.07 to -0.11R); RISING is a mild positive for bursts
        (+0.06/+0.09R). The extreme low level is the loudest signal; the
        direction of change adds on top.
     10. *Circuit-breaker — the largest effect measured anywhere*: after 3
        sessions in which >=60% of burst entries hit their stops, next-day
        trades average -0.5R at ~20% win vs -0.06R/39% baseline. When the
        stop-out cluster fires, standing down is mandatory.
   - **Yesterday's read — review**: quote yesterday's situational_awareness
     from the journal (skip the section if none) and grade it in 2-3
     sentences against what actually happened today: breadth/monitor-tail
     move, participation change, whether the preferred setups were where the
     action was. Verdict: held up / partly / wrong — and the lesson if wrong.
   - **Other markets**: one line from the `global_markets.py` output — lead
     with anything moving more than ~1% (a Nikkei/S&P shock, crude or USD/INR
     spike); otherwise "quiet overnight".
   - **Market news**: 3-5 headlines from `news` that plausibly bear on the
     regime or on an open position / candidate (macro, index, sector, a held
     name). Skip if nothing relevant — do not pad with entertainment headlines.
2. Write the draft entry to `output/brief/plan_draft.json`:
   `{"date", "regime_tier", "equity", "recommendations": [{"symbol", "scan",
   "entry", "stop", "qty", "risk_inr", "verdict"}], "open_trade_actions": [...],
   "situational_awareness": "<the #SituationalAwareness bullet list, verbatim —
   newline-separated '- ' lines; the dashboard renders each as a bullet>",
   "sa_review": "<the review of yesterday's read>"}`
   then run the plan contract (the gates live in code, not here):
   ```bash
   python src/plan_contract.py output/brief/plan_draft.json
   ```
   It prints PASS/BLOCK per symbol with the measured value behind each gate
   and writes `output/brief/plan_gated.json` with `gates` attached to every
   recommendation and any BLOCKed names moved to `rejected` with a
   `reject_reason`. Append the gated JSON (one line) to
   `output/brief/journal.jsonl` — never the draft. Rejected names stay in
   the entry: the grader scores them too (FalseBlock rate).
   — this is the decision journal the post-study will grade later; the SA
   fields are what the dashboard renders and what tomorrow's review grades.

## Validation gates (Ragi-style — refuse to emit a broken brief)

The gates are computed by `src/plan_contract.py` (step 2 above), never by
hand. Print its PASS/BLOCK table verbatim in the brief. The hard gates it
enforces, each with the measured number:
- **circuit-breaker**: 3+ trades in `open_trades` with status "stopped"
  BLOCK every new entry — Bonde's rule: three stop-outs in a row means the
  tape is wrong, not the setups. The brief still reports regime and
  open-position actions, but recommends zero new positions and says why.
- **participation**: `participation.ratio_20d` < 0.7 BLOCKs every entry
- state file date matches the plan date; every symbol exists in the state
  file's scans; entry within 5% of the state-file close (leakage check)
- stop on the correct side of entry; risk ≤ `risk_per_trade_pct`;
  positions ≤ `max_open_positions`; cumulative notional ≤ exposure cap
- soft (warning only): results due within 5 days
Emit the brief from the gated file: BLOCKed names are reported with their
reject_reason, never recommended.
