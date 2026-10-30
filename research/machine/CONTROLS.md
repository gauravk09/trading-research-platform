# CONTROLS.md — proof the machine works, and what was calibrated from it

The evaluator must be validated against itself before its verdicts are
trusted. This battery is the standing proof. **Policy: rerun it after ANY
change to engine.py** (one command, bottom) and update this file. Control
ids use prefixes c_ / x_ (and v_ for red-team perturbations); they are never
research results.

## Battery of 2026-07-29 (16 controls)

| control | what it attacks | must | got |
|---|---|---|---|
| c002 + x_pb1..x_pb6 (7 per-symbol placebos) | can noise look like a stock trait? | FAIL | all FAIL (post-calibration) |
| x_pb_bounce (placebo, 135k-event cohort) | do huge cohorts manufacture significance? | FAIL | FAIL (effects −0.07/−0.15 arose, null 64% killed it) |
| x_pm1..x_pm3 (per-date placebos) | the stricter date-block null path | FAIL | all FAIL |
| x_ps_adr_a/b (real adr20 values, link shuffled) | realistic distribution, destroyed signal | FAIL | both FAIL |
| x_cheat (future ret_o5 as the condition) | can plumbing detect blatant signal? | PASS, huge | PASS +2.34/+2.39R, null 100% |
| c003 (adr20 mechanical truth) | can the null test certify a real stock-level effect? | PASS | PASS, null 97% |
| c001 (ti65-on-bounce, known-real) | is the machine stricter than old studies? | WEAK ok | WEAK (real, top-quintile, partly date-composition) |
| determinism (x_pb1 rerun) | reproducibility | identical | byte-identical |

**Headline: 0 of 13 noise experiments reached PASS, across both battery
runs. The certification bar never leaked.**

Rerun 2026-07-29b (after adding `market:` filter support): all verdicts
reproduced, with one instructive exception — the salted-placebo rewrite gave
c002 a fresh random draw which grades WEAK (−0.07/−0.06R, null 100%). So the
calibrated WEAK bars still leak ~1 noise result in 13 — irreducible without
also killing real signals of the same size. This is why WEAK means
"uncertified" and only PASS + red-team confirmation counts as a finding.

## What the battery taught, and what was changed

1. **WEAK was polluted by sign-luck.** Two eras agreeing in sign is a coin
   flip, so 7/12 placebos initially graded WEAK with tiny effects. Fix
   (calibrated on this battery, encoded in `verdict_of`): WEAK now requires
   min-era |effect| ≥ 0.04R AND (null ≥ 90% OR min ≥ 0.08R). Result: 12/12
   placebos FAIL; every known-real signal kept its grade (burst_success,
   consol_days, eff_ratio, c001, the blow21 liquid-half perturbation).
2. **No single criterion is safe.** x_ps_adr_b — a *shuffled* feature —
   reached null 95% on its own; x_pb1 hit null 98%. Certification must stay
   the triple bar (signs + effect floor + null); never relax to one.
3. **Noise magnitude intuition:** pure noise produced single-era effects up
   to 0.10R on 23k-event cohorts and 0.15R on the 135k bounce cohort. A
   single-era effect below ~0.15R is unremarkable on its own.

## WEAK-bar tightening (2026-07-30)

Batch 4 surfaced a leak: an experiment with a big effect but a FAILED luck
test (e.g. bounce×tightness, |eff| +0.28R but beat only 9.5% of permutations)
was grading WEAK via an `OR |eff|>=0.08` escape. A large effect that beats few
shuffles is high-variance noise, not a hint. Fix: WEAK now ALWAYS requires
`null >= 90%` (and `|eff| >= 0.04`) — no effect-size escape. Battery re-run:
canaries hold (cheat PASS, adr20 control PASS, placebos FAIL); the known-real
ti65-bounce control (c001) now grades FAIL at null 68 (was WEAK) — the machine
is deliberately stricter, and c001's 68% luck-beat genuinely does not clear the
bar. `--regrade` demoted 4 stored results WEAK→FAIL (b3kl_pct52wh_fourpct,
b4lv_bounce_uptrend_adr20, b4tm_dom_bounce, b4vc_bounce_tightness). No PASS
affected (PASS needs null>=95). One fresh-draw placebo (c002) still lands WEAK
— the irreducible ~1-in-13 documented below.

## Battery of 2026-08-06 — close-entry ruler + modern-era track (20 controls)

Two engine changes were validated together: a second entry ruler
(`stop_r_close`, entry at the signal-day close instead of the D+1 open) and
the modern-era judgment track (era A waived when the feature has no pre-2020
data; 2023 vs 2024+ must agree instead). Both needed their own canaries.

### The existing 16 controls, on BOTH rulers

| control | must | D+1-open ruler (primary) | close ruler |
|---|---|---|---|
| c002 + x_pb1..x_pb6, x_pb_bounce, x_pm1..x_pm3, x_ps_adr_a/b (13 noise) | FAIL | 12 FAIL, 1 WEAK (c002 −0.06R null 100 — the documented fresh-draw leaker) | 10 FAIL, 3 WEAK (c002 −0.08/93, x_pb1 −0.09/98, x_pb4 +0.07/100) |
| x_cheat (future ret_o5) | PASS, huge | PASS +2.39R null 100 | PASS +2.58R null 100 |
| c003 (adr20 mechanical truth) | PASS | PASS −0.10R null 97 | FAIL −0.06R null 89 |
| c001 (ti65-on-bounce) | WEAK/FAIL ok | FAIL null 68 (as since 2026-07-30) | FAIL −0.15R null 88 |
| determinism (x_pb1, x_cheat, x_mod_pb1 rerun) | identical | byte-identical | byte-identical |

**Headline: 0 of 13 noise experiments reached PASS on either ruler. The
certification bar did not leak on the new ruler.** Every pre-existing
D+1-open verdict reproduced exactly — the ruler is additive, not a rewrite.

Two honest observations, neither a plumbing fault:

1. **The WEAK bar leaks more on the close ruler: 3/13 vs 1/13.** The bars were
   calibrated on D+1-open noise; close-entry outcomes are a slightly different
   (lower-variance, gap-free) distribution, so borderline placebos cross
   `null >= 90` more often. Treat a close-ruler WEAK as strictly weaker
   evidence than an open-ruler WEAK until the bar is re-calibrated on a
   purpose-built close-ruler placebo battery. PASS is unaffected.
2. **c003 (the known-real adr20 effect) drops PASS→FAIL at the close ruler**
   (−0.10R → −0.06R, null 97 → 89). This is an economic shrink, not a broken
   canary: high-ADR stocks gap the most, so moving entry to the close hands
   the volatile bucket back the gap it was losing and compresses the spread.
   The plumbing canary on the same ruler (x_cheat, +2.58R null 100) is intact.

### New modern-era-track controls (4, permanent, `specs/x_mod_*.json`)

None of the 16 existing controls can reach the modern track — they all have
era-A data. These force it by gating the cohort on `deliv_x20 >= 0`, which
drops every pre-2020 event (delivery data starts 2020-10), giving era-A
extreme-bucket n = 0.

| control | what it attacks | must | got (5d open / close) |
|---|---|---|---|
| x_mod_pb1 (placebo, delivery-gated four_pct, n=53,537) | can the waived-era-A path manufacture significance? | FAIL (modern) | FAIL / FAIL (+0.02R null 14 / +0.03R null 12) |
| x_mod_pb2 (placebo, delivery-gated burst, n=16,020) | ditto, smaller cohort | FAIL (modern) | FAIL / FAIL (−0.08R null 96 → B23/B24 disagree) |
| x_mod_pm1 (per-date placebo, delivery-gated) | the date-block null on the modern path | FAIL (modern) | FAIL / FAIL (+0.02R null 24 / −0.01R null 30) |
| x_mod_cheat (future ret_o5, delivery-gated) | can the modern path detect blatant signal? | PASS (modern), huge | PASS +2.58R null 100 / PASS +2.75R null 100 |

All four correctly report `track: "modern"` and `era_A: "N/A (no data)"` with
era-A extreme n = [0, 0]. x_mod_pb2 is the instructive one: its era-B effect
(−0.08R) would have graded WEAK on a single window, and the mandatory
2023-vs-2024+ sign agreement is exactly what killed it. That sub-split is the
modern track's only substitute for era A, and it is doing real work.
One leak to note: x_mod_pb2 grades **WEAK (modern) at the 20-day horizon**
(−0.16R, null 96) — the same irreducible WEAK leak the full track shows, now
present on the modern path too. No modern PASS leaked.

### What did NOT change

The modern track is unreachable for any feature with era-A data — it is gated
on `min(era-A extreme-bucket n) < MIN_N`, the exact condition that already
returned INSUFFICIENT. Verified on the full board: every primary verdict that
moved was previously INSUFFICIENT-by-era-A; no full-track verdict changed.

## Battery of 2026-08-06b — the three red-team fixes (23 controls)

The red-team of the board above (`research/factory/LEDGER.md`, 2026-08-06)
found three defects in the two engine changes it had just validated. All three
are close-ruler / modern-track only; **the D+1-open path was not touched.**

1. **Earliest-known timing tag.** `deliv_x20` at date t is built from date t's
   `DELIV_PER`, a full-session settlement aggregate NSE publishes in the
   EVENING. It cannot exist at a 15:20 entry, so every `verdict_close`
   conditioned on it was look-ahead (the red-team's constructive proof: lag the
   feature one day — the only close-legal substitute — and +0.27R becomes
   −0.02R). Engine now carries `NEXT_OPEN_FEATURES`; such experiments get
   `verdict_close = "N/A (look-ahead)"` plus a stored `close_flaw` reason, and
   **no** close effect at all. The D+1-open grade is untouched and valid — the
   file is out hours before the 09:15 open.
   *Audit of the whole feature store:* delivery is the only post-close-published
   input. Everything else is price/volume-derived (the full-day-volume caveat in
   `event_store.py` still applies, unchanged); the mcap trio
   (`pit_mcap`/`mcap_decile`/`dilution_factor`) steps on annual filing dates —
   a one-day granularity error on a yearly step, not a daily look-ahead. No
   feature is derived from FII/DII, bulk deals or announcements today.
   *Filters:* the same feature used as a cohort filter is struck only if the
   filter actually **selects** events; `deliv_x20 >= 0` is a pure "this date has
   delivery data" gate, which is why the four `x_mod_*` controls stay valid.
2. **Close-ruler minimum-risk floor + winsorized companion.** A close entry
   puts the stop (the signal-day low) a hair away on reversal triggers — median
   risk 0.76% of price on `bounce` (63.6% of events under 1%, sd 8.71R) and
   1.05% on `four_pct_down` — so R became a ratio with a near-zero denominator
   and single events moved bucket means by an R. Close-ruler R is now recomputed
   with the risk denominator floored at **1% of entry** (`RISK_FLOOR_PCT`);
   P&L is untouched, only the denominator (`R = R_raw * risk / max(risk,
   floor)`). 1% is the point below which a stop stops being a distinct risk
   unit: round-trip cost + slippage is already ~0.3%, and intraday noise on a
   4–5% ADR stock is several times a 0.5% stop. A `effect_R_close_w5`
   companion (the same effect winsorized at ±5R) is stored and shown on the
   scoreboard as a tail diagnostic — a `close` figure far from its `w5` twin is
   carried by a handful of events.
3. **Modern track gated on data absence, not thinness.** The track used to fire
   whenever `min(era-A extreme-bucket n) < MIN_N`, so a bucket re-cut that
   merely thinned era A could reroute a full-history finding onto the weaker
   two-adjacent-window judge (it happened to all four `tapedir_net4_short`
   perturbations). It now additionally requires that the graded sample hold
   **no era-A events at all**. Era-A-thin-but-data-exists is INSUFFICIENT on the
   full track, exactly as before the modern track existed.

### The 23 controls, on both rulers (post-fix)

| control | must | D+1-open ruler (primary) | close ruler |
|---|---|---|---|
| c002 + x_pb1..x_pb6, x_pb_bounce, x_pm1..x_pm3, x_ps_adr_a/b (13 noise) | FAIL | 12 FAIL, 1 WEAK (c002 −0.06R null 99.5 — the documented fresh-draw leaker, unchanged) | **13 FAIL** (was 10 FAIL / 3 WEAK) |
| x_cheat (future ret_o5) | PASS, huge | PASS +2.39R null 100 | PASS +2.58R null 100 |
| c003 (adr20 mechanical truth) | PASS | PASS −0.10R null 97 | FAIL −0.06R null 89 (the documented economic shrink, unchanged) |
| c001 (ti65-on-bounce) | WEAK/FAIL ok | FAIL null 68 | FAIL −0.03R null 7 (was −0.15R null 88 — the risk floor removed most of it) |
| x_mod_pb1 / x_mod_pb2 / x_mod_pm1 (modern-track noise) | FAIL (modern) | all FAIL (modern) | all FAIL (modern) |
| x_mod_cheat (modern-track canary) | PASS (modern), huge | PASS +2.58R null 100 | PASS +2.74R null 100 |
| determinism (x_pb1, x_cheat, x_mod_pb1, c003 rerun) | identical | byte-identical | byte-identical |

**Headline: 0 of 13 noise experiments reach PASS on either ruler, and the close
ruler now grades all 13 FAIL.** Both cheat canaries still detect blatant signal
on both rulers and on the modern track, so nothing was over-tightened.

### Close-ruler WEAK recalibration

The floor alone fixed one of the three leakers (x_pb1 close WEAK → FAIL). The
other two survived it — c002 (−0.064/−0.081R, null 94) and x_pb4
(+0.059/+0.068R, null 99.5) — i.e. close-ruler noise reaches ~0.06R where
D+1-open noise reaches ~0.04R, and neither can be killed by the null bar
(x_pb4 beats 99.5% of permutations). So the close ruler gets its own WEAK
effect floor, `WEAK_MIN_CLOSE = 0.07`, set just above the largest noise effect
the battery produced — the same way the 0.04 open bar was calibrated in
2026-07-29. `WEAK_NULL_CLOSE` stays 90. **PASS bars are shared by both rulers
and were not touched.** The residual open-ruler leak (c002, 1 in 13) is
unchanged and still irreducible.

### Known-real signals kept their grade

`tapedir_net4_short` (the flagship short) stays PASS on the open ruler and WEAK
on the close ruler at +0.66R era B — three orders above the new 0.07 floor, so
the recalibration cannot touch a real effect of tradeable size. The delivery
family keeps its D+1-open **PASS (modern)** verdicts and effects unchanged
(b3dl_deliv_four_pct, b4dl_burst_deliv/h3_burst_deliv_x20,
b4dl_4pct_rvol_deliv) and now shows `N/A look-ahead` in the close column.

### Board impact of the re-grade (`--rerun-all`, 316 experiments)

| column | changed | what moved |
|---|---|---|
| `verdict` (D+1 open, primary) | 47 | **every one** is a modern-by-thinness verdict returning to the full track as INSUFFICIENT (fix 3). PASS count unchanged at 85; no full-track verdict moved; nothing was promoted. Modern-track results: 76 → 29, and all 29 are now genuine "no data" provenance (delivery family + the `x_mod_*` controls). |
| `verdict_20` | 47 | the same 47 specs, same cause |
| `verdict_close` | 102 | 25 struck to `N/A (look-ahead)` (fix 1), 47 modern-suffix corrections (fix 3), the rest re-measured under the risk floor and the new WEAK bar (fix 2). PASS 65 → 49, WEAK 22 → 11, FAIL 175 → 178. |

The struck 25 are every `deliv_x20`-conditioned experiment plus
`b4dl_bounce_deliv_ret7`, whose cohort is *selected* on `deliv_x20 >= 1`.
`b3dl_deliv_bounce` — FAIL on the open ruler but PASS (modern) +0.36 on the
close ruler, the red-team's double artifact — is among them and no longer
appears as a PASS anywhere.

### Two things the battery does NOT certify

- **The risk floor re-measures; it does not sanitise.** Some close verdicts move
  up as well as down, because de-levering the sub-1%-risk events changes every
  bucket mean, not only the inflated ones. `b4tm_dom_bounce` still grades PASS
  (+0.38R after the floor, only +0.18R winsorized), as do `b4lv_bounce_adr20`
  (+0.32R / **−0.01R** w5) and `b4rv_pct52wl` (+0.12R / +0.01R w5) — the `w5`
  gap is the visible tell that a handful of events carries them. The engine's
  bars cannot make the effective-N and concentration judgements that killed
  these in the red-team (807 date clusters, cluster t = 2.35 for dom_bounce);
  `research/factory/LEDGER.md` remains the record of what actually survived
  attack, and no bounce-cohort close PASS should be read as a finding without
  one.
- The 20-day horizon still shows the irreducible WEAK leak on both tracks
  (x_pb3, x_check_ret63, x_mod_pb2). The 20d ruler is D+1-open-based and was
  deliberately left alone by all three fixes.

## Battery of 2026-08-06c — the TRAILED / scale-out ruler (23 controls)

A THIRD outcome ruler was added: `stop_r_trail` (+ `stop_r_trail_short`). Same
D+1-open entry and same initial stop as `stop_r`, but the exit is trailed rather
than timed — half out at +2R, remainder on a ratcheting 20-day low of CLOSES,
hard cap 60 bars. Pre-registered from the exits of the three strategies this
repo has validated end-to-end (ep9m_redefined's scale-out, fno_qullamaggie's MA
trail, ryan_minervini_book's native exits); the +2R and the 20-day window were
NOT searched over. Motivation: both existing rulers exit on the clock, so a
setup whose edge is the winner tail is invisible to — and rejected by — the
screen. Event-store rebuild verified **all 14 pre-existing columns identical
value-for-value over 342,706 rows with the column order unchanged**; the trail
columns are appended.

Unlike the close ruler, the trail ruler needs NO look-ahead guard (it enters at
the D+1 open, so post-close features are legal) and NO risk floor (its
denominator is the same 5-6% stop distance as `stop_r`, not a near-zero close-
entry stop). It does get the `w5` treatment: `effect_R_trail_w5`, the same
effect winsorized at +/-5R, because a 60-bar trail can return +15R on one event.

### The 23 controls (post-calibration)

| control | must | D+1-open (primary) | TRAIL ruler |
|---|---|---|---|
| c002 + x_pb1..x_pb6, x_pb_bounce, x_pm1..x_pm3, x_ps_adr_a/b (13 noise) | FAIL | 12 FAIL, 1 WEAK (c002, the documented leaker) | **13 FAIL** |
| x_cheat (future ret_o5) | PASS, huge | PASS +2.39R null 100 | PASS +2.52R (w5 +2.33) null 100 |
| c003 (adr20 mechanical truth) | PASS | PASS −0.10R null 97 | PASS −0.25R (w5 −0.25) null 100 |
| c001 (ti65-on-bounce) | WEAK/FAIL ok | FAIL null 68 | **PASS +0.18R null 100 — but w5 +0.04** (see below) |
| x_mod_pb1 / x_mod_pb2 / x_mod_pm1 (modern noise) | FAIL (modern) | all FAIL (modern) | **all FAIL (modern)** |
| x_mod_cheat (modern canary) | PASS (modern), huge | PASS +2.58R null 100 | PASS (modern) +2.62R null 100 |
| determinism (x_pb1, x_cheat, x_mod_pb1, c003 rerun) | identical | byte-identical | byte-identical |

**Headline: 0 of 13 noise experiments reach PASS or WEAK on the trail ruler, and
all 3 modern-track placebos FAIL. Both cheat canaries and the adr20 control
still fire, so nothing was over-tightened.**

### Two bars had to be re-cut, and the second one is new in kind

1. **`WEAK_MIN_TRAIL = 0.07`** (full track). Uncalibrated, the trail ruler leaked
   one WEAK: x_pb4 at min|eff| 0.067R, null 96.5 — trail noise reaches ~0.067R
   where D+1-open noise reaches ~0.04R, because a 60-bar hold has a wider outcome
   distribution (burst-cohort sd 1.91R vs 1.44R at 5d). Floor set just above the
   largest noise effect the battery produced, exactly as `WEAK_MIN_CLOSE` was set
   on 2026-07-29/08-06b. `WEAK_NULL_TRAIL` stays 90.
2. **`TRAIL_MODERN_MIN = 0.13` — the first time a PASS bar has moved.**
   Uncalibrated, **x_mod_pb2 (a pure placebo) graded PASS (modern) on the trail
   ruler**: B23 −0.119 / B24 −0.161, null 98.5, both halves clearing the shared
   0.08 PASS floor. A placebo at PASS is the one outcome the battery may never
   permit. Cause: the modern judge compares two ADJACENT short windows (B23 is a
   single year, extreme-bucket n ~870) and a 60-bar hold overlaps heavily inside
   one year, so modern-track trail noise runs ~2x the full-track ceiling — the
   same control reaches only 0.023R on the 5-day ruler. The trail ruler's
   modern-track bars are therefore lifted to 0.13 for BOTH grades (so anything
   under 0.13 is FAIL, not WEAK), above that leaker. The 95% luck bar is
   untouched, and this change can only make trail verdicts stricter — it cannot
   manufacture one. **Caveat: it rests on a SINGLE observed leaker. A
   `PASS (modern)` on the trail ruler is the weakest claim this board can emit
   and must never be reported without a red-team.**

Mechanically this generalised `_grade`'s `bars` argument from a WEAK pair to a
triple `(weak_min, weak_null, pass_floor)`, and `verdict_of` gained a
`bars_modern` override. The open and 20-day rulers pass `None` and are
bit-for-bit unaffected (verified: the four determinism controls are byte-
identical across the bar change).

### The alarm the battery raises but does not fail: c001 on the bounce cohort

c001 (ti65-on-bounce) is the known-real-but-red-team-DECLINED control. It grades
FAIL at 5d, FAIL at 20d — and **PASS at the trail ruler, +0.177R, null 99.5**.
This is not a plumbing leak; it is the trail ruler doing something real and
dangerous. Its `w5` twin is **+0.04R**: four fifths of the effect lives beyond
+/-5R. The 2026-08-06 red-team already established that this exact effect is
tail- and symbol-concentrated (+0.163 → +0.038 clipped, jackknife-10-symbols →
+0.049, cluster t 1.96 on 2,472 dates). A 60-bar trail AMPLIFIES that failure
mode by construction: it is the ruler that pays out the fat right tail, so on the
tail-heavy `bounce` and `four_pct_down` cohorts (D+1-open risk denominators as
small as a fraction of a percent) it will hand out PASSes that a 5-day clock
never could. **Standing rule from this battery: on the bounce / four_pct_down
cohorts, read `trail` only next to `tw5`. A trail PASS whose `tw5` twin is under
the 0.08 floor is a tail artifact until a red-team says otherwise, and no such
result may be certified on the engine's grade alone.**

### Board impact of the re-grade (`--rerun-all`, 348 experiments)

**The additive invariant held exactly: 0 of 348 `verdict`, `verdict_20` and
`verdict_close` values changed.** The trail ruler only adds columns.

5-day open verdict (rows) vs trail verdict (columns), all 348:

| 5d \ trail | PASS | WEAK | INSUFF | FAIL |
|---|---|---|---|---|
| PASS | 59 | 5 | 0 | 29 |
| WEAK | 17 | 1 | 0 | 20 |
| INSUFFICIENT | 0 | 0 | 58 | 0 |
| FAIL | 19 | 4 | 0 | 136 |

Trail PASS count 95 vs 5-day 93 — nearly the same total, materially different
membership. Trail WEAK collapses to 10 (from 38 at 5d) because `WEAK_MIN_TRAIL`
is nearly double `WEAK_MIN`.

### Two ruler-specific reading rules the red-team of these flips produced

1. **The median-difference test is degenerate on the trail ruler.** 62.6% of
   trail trades exit at exactly −1R (stopped before +2R), so every bucket's
   median is −1 and the top-minus-bottom median is 0.000 for most experiments,
   including ones that survive every other attack. On the 5-day ruler a median
   of 0 was evidence of a tail artifact; here it is uninformative. Use the
   **clip ±3R / ±5R** comparison instead — that one still discriminates
   (`b2e_liq_consol_days` GROWS under clipping, +0.166 → +0.185; whereas
   `p5_ret252_burst_band` collapses, +0.202 → +0.073).
2. **The signed-jackknife column only reads correctly for positive effects.**
   `rt_trail.py` drops the symbols with the largest *signed* contribution, so
   for a negative-effect experiment it drops the names fighting the effect and
   the effect appears to grow. Read it only on positive effects, or flip the
   sign first.

## Battery of 2026-08-06d — the `qm_flag` trigger + the BREAKEVEN trail ruler (27 controls)

Two additions validated together, both pre-registered and neither tuned:

1. **`qm_flag`** — a FAITHFUL Qullamaggie flag breakout in the event store,
   copied from `studies/fno_qullamaggie.py` (the S5 study that PASSED) instead
   of the generic 4%-day: prior 3-month move ≥ +30%, within 25% of the 252-day
   high, a tight flag as-of YESTERDAY (20-day range ≤ 25% of price) that did not
   break down (close drift over the same window ≥ −10%), and the break itself —
   close above the prior 10-day HIGH on volume ≥ 1.2× avg50. All stocks with
   close ≥ ₹30 (segment filters stay at scan time); 20-bar cooldown per symbol.
   **11,118 events**, 2015-10 → 2026-07, 1,638 symbols; era A 2,264 / COVID
   3,941 / era B 4,913 — deep enough for the full-history judge on every factor
   except market-series conditions (see below).
2. **`stop_r_trail_be`** (+ short mirror) — the trail ruler with a BREAKEVEN
   move: the stop jumps to the entry price after the first +1R intraday touch.
   Everything else is `stop_r_trail` unchanged (half off at +2R, ratcheting
   20-day close-low trail, 60-bar cap, same gap-fill conventions). The BE move
   takes effect from the NEXT bar — the stop is tested first with the level it
   carried into the bar, so a bar that touches +1R and then collapses through
   the original stop is a full −1R, not a scratch. Same daily-bar,
   no-intraday-path, cost-blind caveats as every other ruler.

Event-store rebuild verified **all 16 pre-existing columns identical
value-for-value over the same 342,706 rows, column order unchanged**; the
`qm_flag` rows are appended after them and the two BE columns after the
existing ones. `_dedupe` gained a `bars` argument defaulting to 5, so every
pre-existing trigger's mask is unchanged.

### A NaN-window defect the new trigger exposed (fixed before any grading)

The first build fired `qm_flag` **6 times in 2017 and 13 times in 2018**. Cause:
`high.rolling(252).max()` with pandas' default `min_periods=252` returns NaN if a
single bar in the trailing year is missing, and **3.6% of post-listing cells in
the cache are NaN holes (1,408 of 2,005 symbols have at least one)** — 37% of
otherwise-valid cells had no 252-day high at all, concentrated in 2015-19. Left
alone this would have emptied era A and silently rerouted every `qm_flag`
verdict onto the weaker modern track. Fixed with `min_periods=200` (~10 months
of observed history before something is called a 52-week high); era A went
694 → 2,264 events. The SHORT windows (10-day high, 20-day range, 50-day volume)
stay strict on purpose: relaxing them would LOWER the breakout reference and
manufacture events, whereas strictness only drops them. This is the
`[backtest_known_biases]` NaN/edge trap in its most expensive form — an
era-selective one.

### The 23 standing controls, on the BE ruler (post-calibration)

| control | must | D+1-open (primary) | TRAIL | TRAIL-BE |
|---|---|---|---|---|
| c002 + x_pb1..x_pb6, x_pb_bounce, x_pm1..x_pm3, x_ps_adr_a/b (13 noise) | FAIL | 12 FAIL, 1 WEAK (c002, the documented leaker) | 13 FAIL | **13 FAIL** |
| x_cheat (future ret_o5) | PASS, huge | PASS +2.39R null 100 | PASS +2.52R null 100 | PASS +2.29R null 100 |
| c003 (adr20 mechanical truth) | PASS | PASS −0.10R null 97 | PASS −0.25R null 100 | PASS −0.24R null 100 |
| c001 (ti65-on-bounce, red-team-DECLINED) | WEAK/FAIL ok | FAIL null 68 | PASS +0.18R (w5 +0.04) | **FAIL +0.12R** |
| x_mod_pb1 / x_mod_pb2 / x_mod_pm1 (modern noise) | FAIL (modern) | all FAIL | all FAIL | **all FAIL (modern)** |
| x_mod_cheat (modern canary) | PASS (modern), huge | PASS +2.58R | PASS +2.62R | PASS (modern) +2.37R |
| determinism (x_pb1, x_cheat, x_mod_pb1, c003 rerun) | identical | byte-identical | byte-identical | byte-identical |

### 4 new permanent controls on the NEW cohort (`specs/x_qm_*.json`)

A new trigger needs its own canaries — nothing else proves its rows are plumbed
like the others'. All four graded on all five rulers:

| control | must | got |
|---|---|---|
| x_qm_cheat (future ret_o5 on qm_flag) | PASS, huge | PASS +2.64R 5d / +3.03 20d / +2.77 trail / +2.40 BE / +3.06 close, null 100 |
| x_qm_pb1 (per-symbol placebo) | FAIL | FAIL on all five (max |eff| +0.11, null ≤ 84) |
| x_qm_pm1 (per-date placebo, date-block null) | FAIL | FAIL on all five (null ≤ 72) |
| x_qm_ps_adr (real adr20 values shuffled) | FAIL | FAIL on all five (null ≤ 44) |

**Headline: 0 of 17 noise experiments reach PASS or WEAK on the BE ruler, and
all three cheat canaries fire on it. The new cohort's own placebos FAIL and its
own cheat PASSes on every ruler, so `qm_flag` rows are plumbed identically.**

### The BE ruler's bars had to be re-cut — the SECOND time a PASS bar has moved

Uncalibrated (inheriting the trail ruler's 0.07 / 0.08), **`x_pb4` — a pure
placebo — graded PASS on the BE ruler at min|eff| 0.095, null 100** (era A
+0.095 / era B +0.105). A placebo at PASS is the one outcome the battery may
never permit. Cause is structural, not a bug: the +1R stop-to-entry move turns
most −1R losses into ~0R scratches, which compresses the outcome distribution
and lets a noise draw separate two buckets with less. Fix, by the same rule that
set `WEAK_MIN_CLOSE` and `TRAIL_MODERN_MIN` — set the floor just above the
largest noise effect the battery produced:

    WEAK_MIN_TRAIL_BE = 0.10      # both grades lifted: under 0.10 is FAIL
    TRAIL_BE_PASS_MIN = 0.10
    TRAIL_BE_MODERN_MIN = 0.13    # inherited from the trail ruler

The next-largest noise effect on this ruler is x_pb6 at 0.043 (null 90.5), so
0.10 leaves a wide margin. The modern bar is *inherited* rather than measured
down: observed BE modern-track noise is smaller than the trail's (x_mod_pb2
B23 −0.094 / B24 −0.075 vs the trail's −0.119 / −0.161), but the structural
cause of the trail's modern leak — two ADJACENT one-year windows with a 60-bar
hold overlapping inside them — is identical here, so the stricter bar stands.
This can only make BE verdicts stricter. **A `trail_be` PASS is, like a trail
`PASS (modern)`, a claim resting on a re-cut bar: always red-team it.**

### What the BE ruler does to c001 — the one canary movement worth reading

c001 (ti65-on-bounce) is the known-real-but-red-team-DECLINED control that the
trail ruler promoted to PASS +0.18R with a `w5` twin of only +0.04R — the
battery's standing warning that a 60-bar trail pays out the fat right tail on
near-zero-risk-denominator cohorts. **The BE ruler grades it FAIL (+0.12R).**
That is the BE move behaving exactly as designed: it truncates the runners that
carried the artifact. It is a useful diagnostic, not a certification — a result
that is PASS at `trail` and FAIL at `trail_be` is tail-carried by construction.

### Board impact of the re-grade (`--rerun-all`, 360 experiments)

**The additive invariant held exactly again: 0 of 360 `verdict`, `verdict_20`,
`verdict_trail` and `verdict_close` values — and 0 of their stored effects —
changed.** Both additions are append-only.

| ruler | PASS | WEAK | INSUFFICIENT | FAIL |
|---|---|---|---|---|
| 5d (D+1 open, primary) | 95 | 39 | 59 | 167 |
| trail | 97 | 10 | 59 | 194 |
| **trail_be** | **81** | **4** | 59 | **216** |

trail (rows) vs trail_be (columns), all 360:

| trail \ be | PASS | WEAK | INSUFF | FAIL |
|---|---|---|---|---|
| PASS | 75 | 2 | 0 | 20 |
| WEAK | 3 | 2 | 0 | 5 |
| INSUFFICIENT | 0 | 0 | 59 | 0 |
| FAIL | 3 | 0 | 0 | 191 |

**33 flips (21 research, 12 controls/perturbations): 22 demotions, 6
promotions.** Of the 33, **8 are caused by the re-cut bar alone** (they keep
their trail verdict if graded at the trail bars) and **25 by the ruler itself** —
checked by re-grading every stored BE effect at `(WEAK_MIN_TRAIL,
WEAK_NULL_TRAIL, EFFECT_FLOOR)`. Read the flip count with that split in mind:
this is not "the BE stop changes 33 verdicts", it is "the BE stop shrinks nearly
every effect by 10-25%, and a quarter of the board sits close enough to a bar for
that shrink to matter."

**Every certified finding held**, with a 10-25% smaller effect: net4→burst
+0.21→+0.16, turn_decile +0.24→+0.20, turn_4pct +0.13→+0.10, the three delivery
cells +0.33/+0.35/+0.34 → +0.31/+0.32/+0.26, lone-loser short +0.69→+0.62,
ratio10 short +0.43→+0.40, the GA four_pct champion +0.21→+0.18, and both
tail-edge `consol_days` survivors (+0.26→+0.26, +0.40→+0.37) — the last two
barely move, which is what a non-tail-carried effect looks like on this ruler.
The 6 promotions are near-bar cases, 3 of them on the `four_pct_down` short
cohort where the trail ruler's tail warning already applies; none is a finding.

**What the BE ruler is FOR, given all that:** it does not re-rank the board and
it is not a better ruler — its unconditional expectancy is WORSE than the plain
trail on every cohort (it converts −1R losses into scratches but pays for that by
cutting a slice of the winners: burst +0.039 → −0.004, four_pct +0.032 → +0.004,
qm_flag +0.007 → −0.050). It is a *tail-dependence diagnostic that costs nothing
to read*: an effect that survives `trail` but dies at `trail_be` was being paid
by the runs a breakeven stop scratches. c001 (trail PASS +0.18 → BE FAIL) and
`b3rg_burst_pct40ma` (+0.27 → +0.14, null 65) are the cleanest examples, and both
were independently red-team-DECLINED before this ruler existed.

## Regrade audit trail (2026-07-29)

Recalibration re-graded 15 stored results via `--regrade` (verdicts are a
pure function of stored effects/ns/null; nothing re-run): 7 controls
WEAK→FAIL, and 8 batch-1 borderliners WEAK→FAIL — fourpct_burst_success,
burst_ret252, burst_volc5_50, burst_ratio10, ep_score, burst_dist50,
burst_tightness, burst_sector_rs. The three confirmed PASSes
(net4, turn_decile, blow21) and their perturbations were untouched.

## Rerun command

    ~/anaconda3/bin/python engine.py specs/c00*.json specs/x_*.json
    ~/anaconda3/bin/python engine.py --regrade && ~/anaconda3/bin/python engine.py --scoreboard

`specs/x_*.json` now includes the four `x_mod_*` modern-era controls and the
four `x_qm_*` new-cohort controls; the glob picks them up automatically.
Determinism check: run any control twice and `diff` the two
`results/<id>.json` — they must be byte-identical.

`--regrade` only re-applies the bars to STORED numbers, and only to the PRIMARY
verdict. A change that alters an outcome column itself (the close-ruler risk
floor), or that adds one (the trail ruler), needs `--rerun-all`.

## evolve.py finalist gates (2026-09-03) — calibration, not a battery

`engine.py` is untouched, so the 27-control battery stands. Two gates were
added to the GA (`evolve.py`) and calibrated against every genome in
`evolve_runs/` (38 real finalists / last-gen bests, 13 placebo champions):

| gate | what it measures | real genomes | placebo champions | verdict |
|---|---|---|---|---|
| PFS (`PFS_MIN=0.80`) | share of events whose label survives 10%-of-spread Gaussian / t(3) input noise (worst case) | 0.47–1.00, 5 of 38 below 0.80 | 0.25–1.00, 5 of 13 below 0.80 | separates knife-edge from robust rules (`consol_days <= 0.0` = 0.47), NOT noise from signal — the holdout + null test keep that job |
| coverage `d_drop` (`COV_PEN=0.5` z/unit) | share of valid era-A events the genome's series NaN out | 0.00–0.86; bounce finalists on days_since_52wh / tightness / pct_52wl at 0.52–0.86 | 0.00–0.85 | a rule that exists only on names with 2y of history was scored on a survivor subset; it now pays for that |

AlphaEval's published 0.90 would drop half the real finalists; 0.80 was cut
from this table. Rerun: `scratchpad/calib_pfs.py` logic — build the trigger
ctx, `perturbation_fidelity` + `coverage_drop` per genome.
