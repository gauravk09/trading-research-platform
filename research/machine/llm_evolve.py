"""llm_evolve.py — A/B: does an LLM mutation operator earn its place?

Phase 2 of the structure/param split (registered 2026-08-11 with evolve.py's
fitted-pocket mode). A steady-state search over [series, op] pocket
STRUCTURES — whole scored history in, one batch of proposals out, evaluate,
insert — with the mutation operator swappable:

  random — the same structural moves evolve.py uses (crossover of elites +
      add/drop/swap series, flip op). The dumb-operator control.
  llm   — a file bridge: each call writes request_NNN.json (scored history
      best-first, series glossary, grammar rules) to --bridge-dir and blocks
      until response_NNN.json appears with proposed structures. Whoever
      answers (a Claude subagent, a local model, a human) never sees market
      data — only structures and scores, exactly the FunSearch division of
      labor. Invalid proposals are dropped and counted (the repair pass);
      duplicates burn budget like any other proposal.

Fitness is evolve.evaluate_pocket_fit — thresholds are grid-fit per CV fold
inside era A; the operator only ever chooses WHICH series and WHICH side.
This file NEVER certifies and never touches era B: the A/B costs zero
holdout budget.

Pre-registered A/B verdict (written before any run): 3 seeds per arm,
identical --budget evaluated proposals, identical seed-matched initial
populations. The LLM operator WINS only if (a) its mean final best fitness
across the 3 seeds beats the random arm's mean, AND (b) it wins the
per-seed pairing in at least 2 of 3. Anything else is a loss: the LLM
earns no holdout budget and the fitted-pocket protocol stays random-only.
Every 5th LLM call is an exploration turn: scores are hidden and the rules
ask for something unlike anything tried.

Usage:
  ~/anaconda3/bin/python llm_evolve.py --trigger pullback --operator random \
      --seed 1 --budget 240
  ~/anaconda3/bin/python llm_evolve.py --trigger pullback --operator llm \
      --seed 1 --budget 240 --bridge-dir /tmp/bridge_s1
"""

import argparse
import json
import os
import random
import time

import numpy as np

import evolve

POP = 24
ELITE = 8
BATCH = 6            # proposals per operator call
EXPLORE_EVERY = 5    # every 5th LLM call hides scores and asks for novelty
HIST_CAP = 60
POLL_S = 2
TIMEOUT_S = 900

GLOSSARY = {
    "adr20": "20d average daily range %",
    "bounce_low21": "% above the 21d low",
    "burst_success": "fraction of recent 4% bursts that followed through",
    "consol_days": "days spent in the current consolidation",
    "days_since_52wh": "days since the 52-week high",
    "days_since_burst": "days since the last 4% up day",
    "dist_50dma": "% distance from the 50DMA",
    "eff_ratio": "efficiency ratio of the recent trend (smoothness)",
    "pct_52wh": "% of the 52-week high (100 = at the high)",
    "pct_52wl": "% above the 52-week low",
    "pocket_pivot": "pocket-pivot volume signature flag",
    "ret7": "7d return %", "ret21": "21d return %", "ret30": "30d return %",
    "ret_63": "63d return %", "ret_126": "126d return %",
    "ret_252": "252d return %", "ret_504": "504d return %",
    "rs": "composite relative-strength rank 0-100",
    "rsline_pct52wh": "RS line vs its own 52w high (RS line blue-sky-ness)",
    "rvol50": "volume vs 50d average",
    "sector_rs": "sector relative-strength rank",
    "ti65": "% above the 65d trend intensity line",
    "tightness": "recent range tightness (low = tight/VCP-like)",
    "trend_age": "bars since the trend began",
    "trend_template": "Minervini trend-template score",
    "turn_decile": "liquidity decile by turnover (9 = most liquid)",
    "updown_vol50": "up-volume vs down-volume ratio, 50d",
    "volc5_50": "5d vs 50d volume contraction",
    "market:score": "market breadth score -5..+5 (regime)",
    "market:pct40ma": "% of all stocks above their 40DMA",
    "market:ratio10": "market 10d up/down ratio",
    "market:net4": "market net 4% up minus 4% down days",
    "market:net25q": "market net 25%-in-a-quarter movers",
}

RULES = (
    "You are evolving FILTER STRUCTURES for a stock-trading event cohort. "
    "A structure is 1-3 filters; each filter is [series_name, op] with op "
    "'>=' or '<='. It means: only take trigger events where that series is "
    "in the high (>=) or low (<=) part of its range — the exact numeric "
    "threshold is fitted separately by an optimizer, NOT by you. You see "
    "the structures tried so far with their cross-validated fitness "
    "(higher = better, 0 = worthless). Propose structures that BEAT the "
    "best so far: keep series/directions that score well, drop what "
    "scores 0, and combine differently. Fewer filters is better when "
    "equal (each filter is penalized). Return ONLY valid JSON: "
    '{"proposals": [[["series", ">="], ...], ...]} with exactly the '
    "requested number of proposals. Series names must come from the "
    "provided list, verbatim."
)
RULES_EXPLORE = (
    "EXPLORATION TURN: scores are hidden on purpose. Propose structures "
    "as UNLIKE the ones already tried as possible — unused series, "
    "opposite directions, different combinations. Same JSON format."
)


def canon_s(structure):
    return json.dumps(sorted(structure))


def random_batch(scored, ctx, rng, n):
    elites = [ind for _, ind in scored[:ELITE]]
    out = []
    for _ in range(n):
        if len(elites) >= 2 and rng.random() < 0.5:
            child = evolve.crossover(rng.choice(elites), rng.choice(elites),
                                     rng)
        else:
            child = json.loads(json.dumps(rng.choice(elites)))
        out.append(evolve.mutate(child, ctx, rng)["filters"])
    return out


def llm_batch(scored, tried, ctx, bridge, call_no, n):
    explore = call_no % EXPLORE_EVERY == 0
    hist = [{"structure": ind["filters"],
             **({} if explore else {"score": round(res["score"], 3),
                                    "fold_eff": res["fold_eff"],
                                    "n": res["n"]})}
            for res, ind in scored[:HIST_CAP]]
    if explore:
        hist = [{"structure": s} for s in tried[-HIST_CAP:]]
    req = {"iteration": call_no, "n_proposals": n,
           "max_filters": evolve.MAX_FILTERS, "ops": [">=", "<="],
           "rules": RULES + (" " + RULES_EXPLORE if explore else ""),
           "series": [{"name": s, "meaning": GLOSSARY.get(s, "")}
                      for s in sorted(ctx.thresholds)],
           "history_best_first": hist}
    rq = os.path.join(bridge, f"request_{call_no:03d}.json")
    rs_ = os.path.join(bridge, f"response_{call_no:03d}.json")
    with open(rq + ".tmp", "w") as f:
        json.dump(req, f, indent=1)
    os.rename(rq + ".tmp", rq)
    t0 = time.time()
    while True:
        if os.path.exists(rs_):
            try:
                with open(rs_) as f:
                    resp = json.load(f)
                break
            except (json.JSONDecodeError, OSError):
                pass  # partial write — poll again
        if time.time() - t0 > TIMEOUT_S:
            raise TimeoutError(f"no response to {rq} in {TIMEOUT_S}s")
        time.sleep(POLL_S)
    good, bad = [], 0
    for p in (resp.get("proposals") or [])[:n]:
        ok = (isinstance(p, list) and 1 <= len(p) <= evolve.MAX_FILTERS
              and all(isinstance(f, list) and len(f) == 2
                      and f[0] in ctx.thresholds and f[1] in (">=", "<=")
                      for f in p))
        if ok:
            good.append([list(f) for f in p])
        else:
            bad += 1
    return good, bad


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--trigger", required=True,
                    choices=["burst", "four_pct", "four_pct_down", "ep",
                             "bounce", "pullback"])
    ap.add_argument("--operator", required=True, choices=["random", "llm"])
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--budget", type=int, default=240)
    ap.add_argument("--bridge-dir")
    ap.add_argument("--placebo", action="store_true")
    args = ap.parse_args()
    if (args.operator == "llm") != bool(args.bridge_dir):
        ap.error("--operator llm and --bridge-dir go together")

    rng = random.Random(args.seed)
    ctx = evolve.build_ctx(args.trigger, args.placebo, args.seed, fit=True)
    print(f"ab: trigger={args.trigger} operator={args.operator} "
          f"seed={args.seed} budget={args.budget}"
          f"{' PLACEBO' if args.placebo else ''}")
    print(f"  train: {len(ctx.train):,} era-A events, "
          f"{len(ctx.thresholds)} series")

    if args.bridge_dir:
        os.makedirs(args.bridge_dir, exist_ok=True)

    # seed-matched init: both arms consume the SAME rng draws here, so a
    # given --seed yields an identical starting population in either arm
    pop = [evolve.random_ind(ctx, rng, "pocket") for _ in range(POP)]
    scored = sorted(((evolve.evaluate_pocket_fit(i, ctx), i) for i in pop),
                    key=lambda x: (-x[0]["score"], -x[0]["n"]))
    seen = {canon_s(ind["filters"]) for _, ind in scored}
    tried = [ind["filters"] for _, ind in scored]

    spent, call_no, dups, invalid = 0, 0, 0, 0
    curve = []
    best = scored[0][0]["score"]
    while spent < args.budget:
        call_no += 1
        n = min(BATCH, args.budget - spent)
        if args.operator == "random":
            batch = random_batch(scored, ctx, rng, n)
        else:
            batch, bad = llm_batch(scored, tried, ctx, args.bridge_dir,
                                   call_no, n)
            invalid += bad
            spent += bad  # an unusable proposal is spent budget too
        for structure in batch:
            spent += 1
            key = canon_s(structure)
            if key in seen:
                dups += 1
                continue
            seen.add(key)
            tried.append(structure)
            res = evolve.evaluate_pocket_fit({"filters": structure}, ctx)
            scored.append((res, {"filters": structure}))
            scored.sort(key=lambda x: (-x[0]["score"], -x[0]["n"]))
            scored = scored[:POP]
            best = max(best, res["score"])
        curve.append({"spent": spent, "best": round(best, 4)})
        print(f"  call {call_no:>3}: spent {spent:>4}/{args.budget}  "
              f"best z {best:.3f}  dups {dups}  invalid {invalid}")

    if args.bridge_dir:
        with open(os.path.join(args.bridge_dir, "done.json"), "w") as f:
            json.dump({"spent": spent}, f)

    out_dir = os.path.join(evolve.engine.HERE, "evolve_runs")
    os.makedirs(out_dir, exist_ok=True)
    tag = (f"ab_{args.trigger}_{args.operator}_s{args.seed}"
           + ("_placebo" if args.placebo else ""))
    top = [{"structure": ind["filters"], "score": round(res["score"], 4),
            "fold_eff": res["fold_eff"], "n": res["n"]}
           for res, ind in scored[:10]]
    with open(os.path.join(out_dir, f"{tag}.json"), "w") as f:
        json.dump({"args": vars(args), "curve": curve, "dups": dups,
                   "invalid": invalid, "final_best": best, "top": top},
                  f, indent=1, default=float)
    print(f"\nfinal best z {best:.3f}  (dups {dups}, invalid {invalid})")
    print(f"run log → evolve_runs/{tag}.json")


if __name__ == "__main__":
    main()
