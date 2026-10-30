"""evolve.py — genetic search over experiment specs, holdout-safe.

Evolves spec genomes ({trigger, filters, condition}) by mutation/crossover,
but the search NEVER sees era B: fitness is CROSS-VALIDATED evidence inside
era A — 4 chronological date-block folds with a 21-day embargo (outcome
windows never straddle folds), score = mean cross-fold date-clustered t
minus an instability penalty (VAR_PEN * std across folds) minus a parsimony
penalty (PARS_PEN per filter). Bucket edges are train-only. Early stopping
ends evolution when best fitness stalls for PATIENCE generations. Only the
final handful of survivors are run once through the standard
engine.run_spec, where era B and the permutation luck test deliver the
real verdict.

Controls: --placebo shuffles every condition/filter series before evolving
(stock series within date, market series across dates — matching the
engine's two null modes), destroying all condition-outcome links while
preserving distributions and outcome structure. The best fitness a placebo
run reaches is the noise floor for the real run's champions. Placebo runs
never write specs/results.

Protocol: run ONCE per trigger and accept the outcome. Re-running until
era B likes the finalists destroys the holdout.

Two modes:
  gradient (default) — genomes are {filters, condition}; finalists certified
      by the unmodified engine.run_spec (the standard scoreboard bars).
  pocket — genomes are pure filter stacks; fitness is evidence that the
      pocket's ABSOLUTE mean stop_r is positive in both era-A halves
      (date-clustered t, Stouffer-combined). This is the tradeable-strategy
      claim: "when the trigger fires and the stack holds, take the trade."
      Certified here (engine.run_spec judges gradients, not pockets) with
      pre-registered bars:
        PASS   n >= 200 & dates >= 40 per era; mean stop_r > 0 in A and B;
               era-B date-clustered t >= 2 and era-A t >= 1; era-B mean
               beats >= 95% of 200 random same-size era-B subsets of the
               naked trigger cohort ("skill vs naked trigger" null)
        WEAK   means > 0 both eras, era-B t >= 1, subset null >= 90%
        INSUFFICIENT / FAIL analogous to the engine
      Pocket results stay in evolve_runs/ (never results/ — the scoreboard
      is gradients only). COVID (2020-22) reported nowhere, judged never.
  seeded — gradient genomes whose INITIAL POPULATION is part hand-written
      seeds and part random. A seed (`specs/ga_seeds/<trigger>.json`) supplies
      the FILTER half of the genome — a cohort prior translated from an
      external idea corpus (index 10/20-DMA regime gates, breadth gates,
      base/VCP tightness, multi-year-high proximity, vol-scaled momentum,
      liquidity segment) — and the GA draws its condition at random and then
      evolves it. Registered 2026-08-06 as a mode DISTINCT from `gradient`,
      with its own one-run-per-trigger budget, because the search distribution
      is not the same one: seeds inject their own thresholds into the mutation
      menu and may reference mm_history series outside engine.MARKET
      (`ma1020_*`, `net50m`, `dd2y_*`), which a plain `gradient` run can never
      reach. Pre-registered bars, written before any seeded run:
        finalists are judged by the UNMODIFIED engine.run_spec — the standard
        scoreboard bars, nothing added, nothing relaxed. Finalists capped by
        --finalists (default 4) as in the other modes; each finalist is one
        era-B look.
      Three extra conditions specific to this mode:
        (a) a champion whose era-A CV fitness sits BELOW the seeded-mode
            placebo floor — established the same way fitness v2 was, by
            --placebo runs of THIS mode with THESE seeds, before any real run
            is interpreted — is reported but never promoted without a
            factory red-team, whatever era B says;
        (b) a seed naming a feature with no era-A data (deliv_x20, the mcap
            trio) is UNEVALUABLE here by construction: era-A CV fitness is 0
            because the filter empties the training cohort. Such seeds are
            dropped from the initial population with a printed warning and
            listed in the run log — never reported as a negative finding.
            Delivery is a NEXT_OPEN feature, so it would in any case be legal
            only on the D+1-open ruler this file grades;
        (c) the ABSOLUTE-pocket form of the same seeds (`--genome pocket`,
            judged by the pocket bars above INCLUDING the vs-naked-trigger
            null) is pre-registered too, but must not be spent on a trigger
            whose era-A naked expectancy is negative: on such a cohort
            `evaluate_pocket` can only ever return 0 and the run is
            predetermined. Check era A first — it is training data and costs
            no holdout.
      Seeds naming a series that does not resolve at all fail loudly.
      Run log goes to evolve_runs/ as for the other modes.
  fitted-pocket (--fit, pocket genome only) — registered 2026-08-11 as a
      mode DISTINCT from pocket, with its own one-run-per-trigger budget and
      its own placebo floor (the old pocket/seeded floors are void here:
      the inner fit is a large flexibility increase, and the null bar must
      grow with search flexibility). Structure/param split: genomes are
      [series, op] structures WITHOUT thresholds; per CV fold, thresholds
      are grid-fit (FIT_QUANTS, train-only quantiles) on the other folds'
      dates and the fitted rule is scored on the held-out fold, so every
      structure competes on its best fitted self and the numbers are never
      scored on the dates they were fit on. Mutation is purely structural
      (add/drop/swap series, flip op — tweak_thr does not exist here).
      Finalists are re-fit once on ALL of era A, then judged by the same
      certify_pockets bars as plain pockets (era B + vs-naked null, one
      look). Seeds contribute structure only; their thresholds land on the
      fit grid. No champion is believed below the fitted-mode placebo
      floor, established by --placebo runs of THIS mode before any real
      run is interpreted.

Usage:
  ~/anaconda3/bin/python evolve.py --trigger bounce [--mode pocket]
      [--side long|short] [--pop 24] [--gens 10] [--seed 1]
      [--finalists 4] [--placebo] [--dry]
  ~/anaconda3/bin/python evolve.py --trigger burst --mode seeded \
      --seeds specs/ga_seeds/burst.json --pop 60
"""

import argparse
import hashlib
import itertools
import json
import os
import random
from types import SimpleNamespace

import numpy as np
import pandas as pd

import engine
import motif_ledger

TRAIN_END = 2020     # evolution sees only years < 2020 (era A)
HALF_MIN_N = 100     # era-level floors used by pocket certification
MIN_DATES = 20
N_FOLDS = 4          # CV fitness: era A in 4 chronological date-blocks
EMBARGO = 21         # trading days dropped at each fold start so 20d outcome
                     # windows never straddle folds (the one real leak; fixed
                     # rules are never FITTED per fold, so classic train-on-
                     # future/test-on-past CV leakage does not arise)
FOLD_MIN_N = 60      # per-fold floors (fold = ~1/4 of era A)
FOLD_MIN_DATES = 15
VAR_PEN = 0.5        # instability penalty: score = |mean t| - 0.5*std(t)
PARS_PEN = 0.15      # parsimony: t-units charged per filter (XGBoost's L1)
PATIENCE = 3         # early stopping: generations without improvement
MAX_FILTERS = 3
# Coverage charge (Hubble, arXiv:2604.09601 — its heaviest fitness weight is
# on data-drop): z-units per unit of valid training panel the genome's series
# silently NaN out. A rule that only exists on the names with 2 years of
# history is scored on a survivor subset and must pay for it.
COV_PEN = 0.5
# Perturbation fidelity (AlphaEval PFS, arXiv:2508.13174): agreement between
# the labels a genome assigns on clean inputs and on inputs jittered by
# PFS_NOISE x the series' spread, worst case over Gaussian and t(3) noise.
# Applied as a finalist gate: a knife-edge threshold fails it, a real rule
# barely notices.
PFS_NOISE = 0.10
PFS_MIN = 0.80
# MAP-Elites (QuantEvolve, arXiv:2510.18569): parents are drawn half from the
# population elites and half from a behaviour archive holding the best genome
# per (series-family set, log2 event count) cell, so the search keeps
# climbing instead of collapsing onto one family.
ARCHIVE_MIX = 0.5
FAMILIES = {
    "trend": {"ti65", "trend_template", "trend_age", "dist_50dma", "rs",
              "rsline_pct52wh", "sector_rs", "pct_52wh", "days_since_52wh"},
    "range": {"adr20", "tightness", "consol_days", "eff_ratio", "pct_52wl"},
    "volume": {"rvol50", "volc5_50", "updown_vol50", "turn_decile", "deliv_x20",
               "pocket_pivot"},
    "momentum": {"ret7", "ret21", "ret30", "burst_success", "days_since_burst",
                 "bounce_low21", "ret_63", "ret_126", "ret_252", "ret_504"},
    "size": {"mcap_decile", "pit_mcap", "dilution_factor"},
}


def family_of(name):
    if name.startswith("market:"):
        return "market"
    return next((fam for fam, names in FAMILIES.items() if name in names), "other")


def genome_series(ind):
    names = [f[0] for f in ind["filters"]]
    if "condition" in ind:
        names.append(cond_key(ind["condition"]))
    return names
QUANTS = [0.1, 0.25, 0.5, 0.75, 0.9]
FIT_QUANTS = [0.05, 0.1, 0.2, 0.3, 0.4, 0.5,
              0.6, 0.7, 0.8, 0.9, 0.95]  # fitted-pocket grid: thresholds are
                                         # the FIT's job, so the grid is finer
BUCKET_CHOICES = ["quartiles", "quintiles"]

FILTER_NAMES = (engine.FEATURES + engine.DERIVED
                + [f"market:{m}" for m in engine.MARKET])
COND_CHOICES = ([("feature", f) for f in engine.FEATURES]
                + [("derived", d) for d in engine.DERIVED]
                + [("market", m) for m in engine.MARKET])


def cond_key(cond):
    return f"market:{cond['name']}" if cond["type"] == "market" else cond["name"]


def build_ctx(trigger, placebo, seed, side="long", full=False, extra=(),
              fit=False, ruler="stop_r"):
    ev = engine.load_events()
    ev = ev[ev["trigger"] == trigger].reset_index(drop=True)
    rcol = ruler if side == "long" else f"{ruler}_short"
    train = (ev if full
             else ev[ev["date"].dt.year < TRAIN_END]).reset_index(drop=True)
    vals, thresholds, empty = {}, {}, set()
    for name in list(FILTER_NAMES) + [n for n in extra if n not in FILTER_NAMES]:
        cond = ({"type": "market", "name": name[7:]} if name.startswith("market:")
                else {"type": "feature" if name in engine.FEATURES else "derived",
                      "name": name})
        v = engine.condition_values(train, cond)[0]
        if np.isnan(v).all():
            empty.add(name)
            continue
        vals[name] = v
        q = np.unique(np.round(np.nanquantile(v, FIT_QUANTS if fit else QUANTS),
                               4))
        thresholds[name] = [float(x) for x in q]
    if placebo:
        # true null: shuffle CONDITION VALUES, not outcomes, matching the
        # engine's two null modes — stock series permuted within date,
        # market series permuted across dates (an outcome shuffle within
        # date leaves genuine market-condition signal fully intact)
        rng = np.random.default_rng(seed + 1000)
        idx_by_date = [np.asarray(ii)
                       for ii in train.groupby("date").indices.values()]
        dser = train["date"]
        for name, v in vals.items():
            if name.startswith("market:"):
                per_date = pd.Series(v, index=dser.values).groupby(level=0).first()
                shuffled = pd.Series(rng.permutation(per_date.to_numpy()),
                                     index=per_date.index)
                vals[name] = shuffled.reindex(dser).to_numpy()
            else:
                v2 = v.copy()
                for ii in idx_by_date:
                    v2[ii] = v[ii[rng.permutation(len(ii))]]
                vals[name] = v2
    conds = [(t, n) for t, n in COND_CHOICES
             if (f"market:{n}" if t == "market" else n) in vals]
    uniq = np.sort(train["date"].unique())
    edges = [uniq[int(len(uniq) * k / N_FOLDS)] for k in range(1, N_FOLDS)]
    fold = np.searchsorted(edges, train["date"].to_numpy(), side="right")
    date_pos = pd.Series(np.arange(len(uniq)), index=uniq)
    pos = date_pos.reindex(train["date"]).to_numpy()
    for k in range(1, N_FOLDS):
        start = date_pos[edges[k - 1]]
        fold = np.where((fold == k) & (pos < start + EMBARGO), -1, fold)
    stop_r = train[rcol].to_numpy()
    return SimpleNamespace(trigger=trigger, side=side, train=train, vals=vals,
                           thresholds=thresholds, conds=conds, empty=empty,
                           stop_r=stop_r,
                           dates=train["date"].to_numpy(),
                           year=train["date"].dt.year.to_numpy(),
                           fold=fold, cache={}, fit=fit,
                           valid=~np.isnan(stop_r),
                           dcode=pos.astype(int), n_dates=len(uniq),
                           fmasks={})


def known_series(name):
    """True if `name` resolves to a series build_ctx can compute. Any
    mm_history column is reachable as market:<col>, not just engine.MARKET."""
    if name in FILTER_NAMES:
        return True
    if not name.startswith("market:"):
        return False
    mm = pd.read_parquet(engine.MM_HIST)
    return name[7:] in mm.columns


def load_seeds(path):
    """Read a seed file into genomes. Unknown series names FAIL LOUDLY —
    a typo'd feature must never be silently dropped into a random genome."""
    with open(path) as f:
        raw = json.load(f)
    seeds, bad = [], []
    for s in raw:
        filters = [[n, op, float(t)] for n, op, t in s["filters"]]
        if len(filters) > MAX_FILTERS:
            raise ValueError(f"seed {s.get('id')} has {len(filters)} filters "
                             f"> MAX_FILTERS={MAX_FILTERS}")
        for n, op, _ in filters:
            if op not in (">=", "<="):
                raise ValueError(f"seed {s.get('id')}: bad op {op}")
            if not known_series(n):
                bad.append((s.get("id"), n))
        seeds.append({"id": s.get("id"), "filters": filters})
    if bad:
        raise ValueError(f"seeds name unknown series: {bad}")
    return seeds


def register_seeds(seeds, ctx, gmode, rng):
    """Split seeds into usable / unevaluable (a filter series with no era-A
    data empties the training cohort by construction) and put every seed
    threshold on the mutation menu so the GA can return to it. A seed carries
    only the FILTER half of a genome; in gradient mode its condition is drawn
    at random (from a private stream, so the random half of the population is
    unaffected) and evolved from there."""
    cond_rng = random.Random(4242)   # fixed: seed conditions must reproduce
    usable, dead = [], []
    for s in seeds:
        if any(n in ctx.empty for n, _, _ in s["filters"]):
            dead.append(s)
            continue
        for n, _, t in s["filters"]:
            if t not in ctx.thresholds[n]:
                ctx.thresholds[n] = sorted(ctx.thresholds[n] + [t])
        ind = {"filters": s["filters"]}
        if gmode == "gradient":
            t, name = cond_rng.choice(ctx.conds)
            ind["condition"] = {"type": t, "name": name,
                                "buckets": cond_rng.choice(BUCKET_CHOICES)}
        usable.append(ind)
    return usable, dead


def canon(ind):
    return json.dumps({"f": sorted(ind["filters"]),
                       "c": ind.get("condition")}, sort_keys=True)


def filter_mask(ind, ctx, vals=None):
    vals = ctx.vals if vals is None else vals
    mask = np.ones(len(ctx.train), bool)
    for name, op, thr in ind["filters"]:
        v = vals[name]
        m = v >= thr if op == ">=" else v <= thr
        mask &= np.where(np.isnan(v), False, m)
    return mask


def coverage_drop(ind, ctx):
    """Share of valid training events on which at least one of the genome's
    series is NaN — rows the rule drops without ever scoring them."""
    names = genome_series(ind)
    if not names:
        return 0.0
    nan_any = np.zeros(len(ctx.train), bool)
    for n in names:
        nan_any |= np.isnan(ctx.vals[n])
    return float(nan_any[ctx.valid].mean())


def _labels(ind, ctx, vals):
    """Per-event label the genome assigns: -1 outside its filter mask; 1
    inside (pocket); 10 + condition bucket inside (gradient)."""
    mask = filter_mask(ind, ctx, vals)
    if "condition" not in ind:
        return np.where(mask, 1.0, -1.0)
    cond = vals[cond_key(ind["condition"])]
    lab = np.full(len(cond), -1.0)
    m = mask & ~np.isnan(cond)
    try:
        b = np.asarray(engine.bucketize(cond[m], ind["condition"]["buckets"]),
                       dtype=float)
    except (ValueError, IndexError):
        return lab
    inside = np.flatnonzero(m)[~np.isnan(b)]
    lab[inside] = 10.0 + b[~np.isnan(b)]
    return lab


def perturbation_fidelity(ind, ctx, seed=0):
    """min over {Gaussian, t(3)} input noise of the share of events (labelled
    by either run) whose label survives the noise. 1.0 = the rule does not
    depend on exactly where its thresholds sit."""
    names = genome_series(ind)
    if not names:
        return 1.0
    base = _labels(ind, ctx, ctx.vals)
    if not (base != -1).any():
        return 0.0
    rng = np.random.default_rng(seed)
    worst = 1.0
    for kind in ("gauss", "t3"):
        vals = dict(ctx.vals)
        for n in names:
            v = ctx.vals[n]
            k = ctx.n_dates if n.startswith("market:") else len(v)
            e = (rng.standard_normal(k) if kind == "gauss"
                 else rng.standard_t(3, k) / np.sqrt(3.0))
            if n.startswith("market:"):
                e = e[ctx.dcode]        # one draw per date, shared by that date's events
            vals[n] = v + e * np.nanstd(v) * PFS_NOISE
        pert = _labels(ind, ctx, vals)
        either = (base != -1) | (pert != -1)
        worst = min(worst, float((base[either] == pert[either]).mean()))
    return worst


def pfs_gate(finalists, ctx, seed):
    kept = []
    for res, ind in finalists:
        pfs = perturbation_fidelity(ind, ctx, seed)
        res = dict(res, pfs=round(pfs, 3))
        if pfs < PFS_MIN:
            print(f"  PFS gate: {pfs:.2f} < {PFS_MIN} — knife-edge genome dropped "
                  f"before its holdout look: {ind}")
            continue
        kept.append((res, ind))
    return kept


def pocket_stats(d, r, min_n=HALF_MIN_N, min_dates=MIN_DATES):
    """(mean of daily means, clustered SE, n_events, n_dates) or None."""
    if len(r) < min_n:
        return None
    daily = pd.Series(r).groupby(pd.Series(d)).mean()
    if len(daily) < min_dates:
        return None
    return (float(daily.mean()),
            float(daily.std() / np.sqrt(len(daily))),
            int(len(r)), int(len(daily)))


def cv_score(t_folds, n_filters, signed=False, d_drop=0.0):
    """CV fitness: mean cross-fold t minus instability, parsimony and
    coverage penalties. Disagreeing folds cancel in the mean; std punishes
    rules that live in one sub-period; each filter costs PARS_PEN; each unit
    of silently dropped panel costs COV_PEN."""
    t = np.array(t_folds)
    m = np.mean(t) if signed else abs(np.mean(t))
    return float(max(0.0, m - VAR_PEN * np.std(t, ddof=1)
                     - PARS_PEN * n_filters - COV_PEN * d_drop))


def evaluate_pocket(ind, ctx):
    key = canon(ind)
    if key in ctx.cache:
        return ctx.cache[key]
    mask = filter_mask(ind, ctx)
    r, fo, d = ctx.stop_r[mask], ctx.fold[mask], ctx.dates[mask]
    ok = ~np.isnan(r) & (fo >= 0)
    r, fo, d = r[ok], fo[ok], d[ok]
    res = {"score": 0.0, "fold_eff": [], "min_eff": 0.0, "n": int(len(r)),
           "d_drop": round(coverage_drop(ind, ctx), 3)}
    ts, effs = [], []
    for k in range(N_FOLDS):
        st = pocket_stats(d[fo == k], r[fo == k], FOLD_MIN_N, FOLD_MIN_DATES)
        if st is None:
            ts = None
            break
        effs.append(st[0])
        ts.append(st[0] / st[1])
    if ts:
        res["fold_eff"] = [round(e, 3) for e in effs]
        if np.mean(r) > 0:
            res["score"] = cv_score(ts, len(ind["filters"]), signed=True,
                                    d_drop=res["d_drop"])
            res["min_eff"] = float(min(effs))
    ctx.cache[key] = res
    return res


def _fmask(name, op, thr, ctx):
    key = (name, op, thr)
    m = ctx.fmasks.get(key)
    if m is None:
        v = ctx.vals[name]
        m = np.where(np.isnan(v), False, v >= thr if op == ">=" else v <= thr)
        ctx.fmasks[key] = m
    return m


def _daily_t(mask, ctx, min_n, min_dates):
    """(mean of daily means, date-clustered t) on the masked rows, or None
    if too thin. bincount over precomputed date codes — this runs once per
    threshold combo per fold, so it must stay cheap."""
    if mask.sum() < min_n:
        return None
    cnt = np.bincount(ctx.dcode[mask], minlength=ctx.n_dates)
    sm = np.bincount(ctx.dcode[mask], weights=ctx.stop_r[mask],
                     minlength=ctx.n_dates)
    got = cnt > 0
    if got.sum() < min_dates:
        return None
    daily = sm[got] / cnt[got]
    se = float(daily.std(ddof=1) / np.sqrt(len(daily)))
    if not se > 0:
        return None
    m = float(daily.mean())
    return m, m / se


def fit_thresholds(structure, train_mask, ctx, min_n, min_dates):
    """The inner fit of the structure/param split: grid-search thresholds
    for a [series, op] structure over the train-only quantile grid,
    maximizing the date-clustered t on train_mask rows ONLY. Returns
    (filters_with_thresholds, train_t) for the best combo, or None if no
    combo clears the floors. The GA never touches numbers; this does."""
    grids = [[(n, op, t) for t in ctx.thresholds[n]] for n, op in structure]
    best = None
    for combo in itertools.product(*grids):
        m = train_mask
        for n, op, t in combo:
            m = m & _fmask(n, op, t, ctx)
        st = _daily_t(m, ctx, min_n, min_dates)
        if st and (best is None or st[1] > best[1]):
            best = ([[n, op, float(t)] for n, op, t in combo], st[1])
    return best


def evaluate_pocket_fit(ind, ctx):
    """Fitted-pocket fitness: per CV fold, thresholds are fit on the OTHER
    folds and the fitted rule is scored on the held-out fold, so structures
    compete on their best fitted selves without ever scoring the dates the
    numbers were fit on. Fitness stays cv_score's z-form (signed, like the
    plain pocket) on the validation folds only."""
    key = canon(ind)
    if key in ctx.cache:
        return ctx.cache[key]
    res = {"score": 0.0, "fold_eff": [], "min_eff": 0.0, "n": 0,
           "d_drop": round(coverage_drop(ind, ctx), 3)}
    tm = N_FOLDS - 1
    ts, effs, ns = [], [], []
    for k in range(N_FOLDS):
        train = ctx.valid & (ctx.fold >= 0) & (ctx.fold != k)
        fitted = fit_thresholds(ind["filters"], train, ctx,
                                FOLD_MIN_N * tm, FOLD_MIN_DATES * tm)
        if fitted is None:
            ts = None
            break
        m = ctx.valid & (ctx.fold == k)
        for n, op, t in fitted[0]:
            m = m & _fmask(n, op, t, ctx)
        st = _daily_t(m, ctx, FOLD_MIN_N, FOLD_MIN_DATES)
        if st is None:
            ts = None
            break
        effs.append(st[0])
        ts.append(st[1])
        ns.append(int(m.sum()))
    if ts:
        res["fold_eff"] = [round(e, 3) for e in effs]
        res["n"] = int(np.mean(ns))
        res["score"] = cv_score(ts, len(ind["filters"]), signed=True,
                                d_drop=res["d_drop"])
        if res["score"] > 0:
            res["min_eff"] = float(min(effs))
    ctx.cache[key] = res
    return res


def refit_full(ind, ctx):
    """Re-fit a finalist's thresholds on ALL of era A (embargo rows included
    — the embargo only separates folds) before certification, mirroring the
    protocol's 're-fit on everything the search saw, then one holdout look'.
    Returns concrete [series, op, thr] filters, or None if era-A floors
    can't be met."""
    fitted = fit_thresholds(ind["filters"], ctx.valid, ctx,
                            2 * HALF_MIN_N, 2 * MIN_DATES)
    return fitted and fitted[0]


def evaluate(ind, ctx):
    if "condition" not in ind:
        return (evaluate_pocket_fit(ind, ctx) if ctx.fit
                else evaluate_pocket(ind, ctx))
    key = canon(ind)
    if key in ctx.cache:
        return ctx.cache[key]
    mask = filter_mask(ind, ctx)
    cond = ctx.vals[cond_key(ind["condition"])][mask]
    r, fo, d = ctx.stop_r[mask], ctx.fold[mask], ctx.dates[mask]
    ok = ~np.isnan(cond) & ~np.isnan(r) & (fo >= 0)
    cond, r, fo, d = cond[ok], r[ok], fo[ok], d[ok]
    res = {"score": 0.0, "fold_eff": [], "min_eff": 0.0, "n": int(len(r)),
           "d_drop": round(coverage_drop(ind, ctx), 3)}
    try:
        b = np.asarray(engine.bucketize(cond, ind["condition"]["buckets"]),
                       dtype=float)
    except (ValueError, IndexError):
        b = np.full(len(cond), np.nan)
    ok = ~np.isnan(b)
    b, r, fo, d = b[ok].astype(int), r[ok], fo[ok], d[ok]
    mode = "market" if ind["condition"]["type"] == "market" else "stock"
    if len(b) and b.min() != b.max():
        lo, hi = b.min(), b.max()
        ts, effs = [], []
        for k in range(N_FOLDS):
            st = half_stats(d[fo == k], b[fo == k], r[fo == k], lo, hi, mode)
            if st is None:
                ts = None
                break
            effs.append(st[0])
            ts.append(st[0] / st[1])
        if ts:
            # fitness is EVIDENCE (cross-fold mean of date-clustered t),
            # not effect size: an R-unit fitness let a placebo GA reach
            # +1.04R via tiny noisy buckets, while hard SE gates killed
            # every known-real signal (per-half t only 0.8-3.7)
            res["fold_eff"] = [round(e, 3) for e in effs]
            res["score"] = cv_score(ts, len(ind["filters"]), d_drop=res["d_drop"])
            res["min_eff"] = float(min(abs(e) for e in effs))
    ctx.cache[key] = res
    return res


def half_stats(d, b, r, lo, hi, mode):
    """(effect, date-clustered SE) for one CV fold, or None if too thin.
    Mirrors the engine's two null modes: market conditions are date-level
    (bucket constant within a date; within-date outcome shuffles leave them
    untouched), stock conditions use per-date top-minus-bottom diffs."""
    is_lo, is_hi = b == lo, b == hi
    if min(is_lo.sum(), is_hi.sum()) < FOLD_MIN_N:
        return None
    if mode == "market":
        m_lo = pd.Series(r[is_lo]).groupby(pd.Series(d[is_lo])).mean()
        m_hi = pd.Series(r[is_hi]).groupby(pd.Series(d[is_hi])).mean()
        if min(len(m_lo), len(m_hi)) < FOLD_MIN_DATES:
            return None
        return (float(m_hi.mean() - m_lo.mean()),
                float(np.sqrt(m_hi.var() / len(m_hi) + m_lo.var() / len(m_lo))))
    keep = is_lo | is_hi
    g = (pd.DataFrame({"d": d[keep], "hi": is_hi[keep], "r": r[keep]})
         .groupby(["d", "hi"])["r"].mean().unstack())
    if True not in g.columns or False not in g.columns:
        return None
    diffs = (g[True] - g[False]).dropna()
    if len(diffs) < FOLD_MIN_DATES:
        return None
    return float(diffs.mean()), float(diffs.std() / np.sqrt(len(diffs)))


def random_filter(ctx, rng):
    name = rng.choice(sorted(ctx.thresholds))
    return [name, rng.choice([">=", "<="]), rng.choice(ctx.thresholds[name])]


def random_structure_filter(ctx, rng):
    return [rng.choice(sorted(ctx.thresholds)), rng.choice([">=", "<="])]


def random_ind(ctx, rng, mode="gradient"):
    if mode == "pocket":
        make = random_structure_filter if ctx.fit else random_filter
        return {"filters": [make(ctx, rng)
                            for _ in range(rng.randint(1, MAX_FILTERS))]}
    t, name = rng.choice(ctx.conds)
    return {"filters": [random_filter(ctx, rng) for _ in range(rng.randint(0, 2))],
            "condition": {"type": t, "name": name,
                          "buckets": rng.choice(BUCKET_CHOICES)}}


def mutate(ind, ctx, rng):
    return mutate_labeled(ind, ctx, rng)[0]


def mutate_labeled(ind, ctx, rng):
    """Returns (child, motif). The motif names the EDIT by op and series
    family ("add_filter:volume") — the key the motif ledger learns on."""
    ind = json.loads(json.dumps(ind))
    if ctx.fit and "condition" not in ind:
        # structure/param split: mutation is purely structural — the inner
        # fit owns every number, so there is no tweak_thr here
        ops = ["drop_filter", "swap_series", "flip_op"] if ind["filters"] else []
        if len(ind["filters"]) < MAX_FILTERS:
            ops.append("add_filter")
        op = rng.choice(ops)
        if op == "add_filter":
            f = random_structure_filter(ctx, rng)
            ind["filters"].append(f)
            return ind, f"add_filter:{family_of(f[0])}"
        if op == "drop_filter":
            f = ind["filters"].pop(rng.randrange(len(ind["filters"])))
            return ind, f"drop_filter:{family_of(f[0])}"
        if op == "swap_series":
            f = rng.choice(ind["filters"])
            old = f[0]
            f[0] = rng.choice(sorted(ctx.thresholds))
            return ind, f"swap_series:{family_of(old)}->{family_of(f[0])}"
        f = rng.choice(ind["filters"])
        f[1] = "<=" if f[1] == ">=" else ">="
        return ind, f"flip_op:{family_of(f[0])}"
    ops = [] if "condition" not in ind else ["swap_cond", "swap_buckets"]
    if ind["filters"]:
        ops += ["tweak_thr", "drop_filter"]
    if len(ind["filters"]) < MAX_FILTERS:
        ops.append("add_filter")
    op = rng.choice(ops)
    if op == "swap_cond":
        t, name = rng.choice(ctx.conds)
        ind["condition"].update(type=t, name=name)
        return ind, f"swap_cond:{family_of(name)}"
    if op == "swap_buckets":
        ind["condition"]["buckets"] = rng.choice(BUCKET_CHOICES)
        return ind, "swap_buckets"
    if op == "add_filter":
        f = random_filter(ctx, rng)
        ind["filters"].append(f)
        return ind, f"add_filter:{family_of(f[0])}"
    if op == "drop_filter":
        f = ind["filters"].pop(rng.randrange(len(ind["filters"])))
        return ind, f"drop_filter:{family_of(f[0])}"
    f = rng.choice(ind["filters"])
    old = f[2]
    f[2] = rng.choice(ctx.thresholds[f[0]])
    return ind, f"tweak_thr:{family_of(f[0])}:{'up' if f[2] > old else 'down' if f[2] < old else 'same'}"


def crossover(a, b, rng):
    pool = [json.loads(json.dumps(f)) for f in a["filters"] + b["filters"]]
    rng.shuffle(pool)
    seen, filters = set(), []
    for f in pool:
        if f[0] not in seen and len(filters) < MAX_FILTERS:
            seen.add(f[0])
            filters.append(f)
    if "condition" not in a:
        return {"filters": filters}
    return {"filters": filters,
            "condition": dict(rng.choice([a, b])["condition"])}


def behaviour_cell(ind, res):
    """MAP-Elites cell: which series families the rule uses x how many
    events it keeps (log2 bins). Two rules in one cell are the same bet at
    the same selectivity; only the better one survives there."""
    fams = tuple(sorted({family_of(n) for n in genome_series(ind)}))
    return fams, int(np.log2(max(res["n"], 1)))


def evolve(ctx, pop_size, gens, rng, log, mode="gradient", seeds=(),
           archive=True, ledger=None, ledger_scope=None):
    """`archive`: MAP-Elites parent pool. `ledger` + `ledger_scope`
    (trigger, side, genome): the cross-run motif ledger; confidently-bad
    edits are re-drawn, every (parent, edit, child) outcome is recorded."""
    pop = [random_ind(ctx, rng, mode) for _ in range(pop_size)]
    if mode == "pocket":
        pop[0] = {"filters": []}  # naked-trigger baseline individual
    # seeds replace random individuals 1..k, leaving the rng draw sequence
    # and the pop[0] baseline exactly as an unseeded run would have them
    for i, s in enumerate(seeds[:pop_size - 1]):
        pop[i + 1] = json.loads(json.dumps(s))
    cells, pending, vetoes = {}, [], 0
    for gen in range(1, gens + 1):
        scored = sorted(((evaluate(i, ctx), i) for i in pop),
                        key=lambda x: (-x[0]["score"], -x[0]["n"]))
        by_canon = {canon(i): s["score"] for s, i in scored}
        for key, parent_score, child_key in pending:
            if child_key in by_canon:
                motif_ledger.record(ledger, key, by_canon[child_key] - parent_score)
        pending = []
        if archive:
            for res, ind in scored:
                cell = behaviour_cell(ind, res)
                if res["score"] > 0 and (cell not in cells
                                         or res["score"] > cells[cell][0]["score"]):
                    cells[cell] = (res, ind)
        scores = [s["score"] for s, _ in scored]
        log.append({"gen": gen, "best": scores[0],
                    "median": float(np.median(scores)),
                    "best_ind": scored[0][1], "archive": len(cells),
                    "vetoes": vetoes})
        print(f"  gen {gen:>2}: best z {scores[0]:.2f}  "
              f"median z {np.median(scores):.2f}  evals {len(ctx.cache)}"
              + (f"  archive {len(cells)}" if archive else "")
              + (f"  vetoes {vetoes}" if ledger is not None else ""))
        best_so_far = max(g["best"] for g in log)
        stale = sum(1 for g in log[-PATIENCE:] if g["best"] < best_so_far)
        if gen == gens or (gen > PATIENCE and stale == PATIENCE):
            if gen < gens:
                print(f"  early stop: no improvement in {PATIENCE} gens")
            break
        elites = [i for _, i in scored[:max(2, pop_size // 4)]]
        archived = [i for _, i in cells.values()]

        def parent():
            pool = archived if (archived and rng.random() < ARCHIVE_MIX) else elites
            return rng.choice(pool)

        pop = list(elites)
        while len(pop) < pop_size - 2:
            pa, pb = parent(), parent()
            child = crossover(pa, pb, rng)
            parent_score = max(by_canon.get(canon(pa), 0.0), by_canon.get(canon(pb), 0.0))
            key = None
            for _ in range(4):
                mutant, motif = mutate_labeled(child, ctx, rng)
                if ledger is None:
                    break
                key = motif_ledger.key_of(*ledger_scope, parent_score, motif)
                if not motif_ledger.vetoed(ledger, key):
                    break
                vetoes += 1
            if key is not None:
                pending.append((key, parent_score, canon(mutant)))
            pop.append(mutant)
        pop += [random_ind(ctx, rng, mode) for _ in range(2)]
    # the archive holds cell-best genomes that may have left the population;
    # they compete for finalist slots on equal terms
    seen = set(by_canon)
    extra = [(r, i) for r, i in cells.values() if canon(i) not in seen]
    return sorted(scored + extra, key=lambda x: (-x[0]["score"], -x[0]["n"]))


def pick_finalists(scored, k):
    out, seen = [], set()
    for res, ind in scored:
        c = (cond_key(ind["condition"]) if "condition" in ind
             else frozenset(f[0] for f in ind["filters"]))
        if res["score"] > 0 and c not in seen:
            seen.add(c)
            out.append((res, ind))
        if len(out) == k:
            break
    return out


def certify(finalists, ctx, tag, write):
    ev_all = engine.load_events()
    rows = []
    for res, ind in finalists:
        h = hashlib.md5(canon(ind).encode()).hexdigest()[:6]
        sid = f"ga_{ctx.trigger}_{tag}_{h}"
        dirn = "better" if np.mean(res["fold_eff"]) > 0 else "worse"
        filt = ", ".join(f"{n} {op} {v}" for n, op, v in ind["filters"]) or "none"
        folds = "/".join(f"{e:+.2f}" for e in res["fold_eff"])
        spec = {"id": sid,
                "question": (f"GA-evolved ({ctx.trigger}): filters [{filt}]; "
                             f"condition {cond_key(ind['condition'])} "
                             f"({ind['condition']['buckets']}). Train CV folds "
                             f"{folds}R — expect more of it = {dirn}. "
                             f"Era B untouched until this run."),
                "cohort": {"trigger": ctx.trigger, "filters": ind["filters"],
                           **({"side": ctx.side} if ctx.side != "long" else {})},
                "condition": ind["condition"]}
        full = engine.run_spec(spec, ev_all)
        if write:
            with open(os.path.join(engine.HERE, "specs", f"{sid}.json"), "w") as f:
                json.dump(spec, f, indent=1)
            with open(os.path.join(engine.RESULTS, f"{sid}.json"), "w") as f:
                json.dump(full, f, indent=1, default=float)
        rows.append({"id": sid, "train_score": res["score"],
                     "pfs": res.get("pfs"), "d_drop": res.get("d_drop"),
                     "verdict": full["verdict"], "effect_R": full["effect_R"],
                     "null_beat_pct": full["null_beat_pct"], "n": full["n"],
                     "spec": spec})
        print(f"  {full['verdict']:<12} {sid}  train z {res['score']:.2f} "
              f"min_eff {res['min_eff']:+.2f}R  "
              f"B {full['effect_R']['B']:+.2f}R  null {full['null_beat_pct']:.0f}%  "
              f"n={full['n']:,}")
    return rows


def pocket_verdict(st_a, st_b, null_pct):
    if st_a is None or st_b is None:
        return "INSUFFICIENT"
    (ma, sea, na, ka), (mb, seb, nb, kb) = st_a, st_b
    if min(na, nb) < 2 * HALF_MIN_N or min(ka, kb) < 2 * MIN_DATES:
        return "INSUFFICIENT"
    if ma <= 0 or mb <= 0:
        return "FAIL"
    if mb / seb >= 2 and ma / sea >= 1 and null_pct >= 95:
        return "PASS"
    if mb / seb >= 1 and null_pct >= 90:
        return "WEAK"
    return "FAIL"


def certify_pockets(finalists, trigger, side, extra=(), ruler="stop_r"):
    """One-shot full-period judgment of pocket finalists: era A/B absolute
    expectancy (date-clustered t) plus a skill-vs-naked-trigger null (200
    random same-size era-B subsets). Never writes to results/."""
    full = build_ctx(trigger, False, 0, side, full=True, extra=extra, ruler=ruler)
    yr = full.year
    era_b = yr >= 2023
    rows = []
    rng = np.random.default_rng(7)
    b_all = full.stop_r[era_b]
    b_all = b_all[~np.isnan(b_all)]
    years_b = max((full.train["date"].dt.year.max() - 2023) + 1, 1)
    for res, ind in finalists:
        mask = filter_mask(ind, full) & ~np.isnan(full.stop_r)
        r, d = full.stop_r[mask], full.dates[mask]
        y = yr[mask]
        st_a = pocket_stats(d[y < TRAIN_END], r[y < TRAIN_END])
        st_b = pocket_stats(d[y >= 2023], r[y >= 2023])
        null_pct = np.nan
        if st_b is not None:
            n_b = st_b[2]
            pocket_mean = float(np.mean(r[y >= 2023]))
            draws = [b_all[rng.choice(len(b_all), n_b, replace=False)].mean()
                     for _ in range(200)]
            null_pct = float((pocket_mean > np.array(draws)).mean() * 100)
        v = pocket_verdict(st_a, st_b, null_pct)
        row = {"verdict": v, "filters": ind["filters"],
               **({"structure": res["structure"]} if "structure" in res else {}),
               "train_z": res["score"], "pfs": res.get("pfs"), "d_drop": res.get("d_drop"),
               "era_A": st_a and {"mean_r": round(st_a[0], 3), "n": st_a[2],
                                  "t": round(st_a[0] / st_a[1], 1)},
               "era_B": st_b and {"mean_r": round(st_b[0], 3), "n": st_b[2],
                                  "t": round(st_b[0] / st_b[1], 1),
                                  "trades_per_year": round(st_b[2] / years_b)},
               "null_vs_naked_pct": null_pct}
        rows.append(row)
        eb = row["era_B"] or {}
        print(f"  {v:<12} [{', '.join(f'{n} {op} {t}' for n, op, t in ind['filters']) or 'naked'}]")
        print(f"      train z {res['score']:.2f}  "
              f"B mean {eb.get('mean_r', float('nan')):+.3f}R "
              f"t {eb.get('t', float('nan'))} "
              f"({eb.get('trades_per_year', 0)}/yr)  "
              f"vs-naked {null_pct:.0f}%")
    return rows


def main():
    global TRAIN_END
    ap = argparse.ArgumentParser()
    ap.add_argument("--trigger", required=True,
                    choices=["burst", "four_pct", "four_pct_down", "ep",
                             "bounce", "pullback"])
    ap.add_argument("--mode", default="gradient",
                    choices=["gradient", "pocket", "seeded"])
    ap.add_argument("--seeds", help="JSON file of seed genomes (mode seeded)")
    ap.add_argument("--genome", default="gradient", choices=["gradient", "pocket"],
                    help="mode seeded: which genome family the seeds build")
    ap.add_argument("--side", default="long", choices=["long", "short"])
    ap.add_argument("--pop", type=int, default=24)
    ap.add_argument("--gens", type=int, default=30)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--finalists", type=int, default=4)
    ap.add_argument("--fit", action="store_true",
                    help="fitted-pocket: GA evolves [series, op] structures; "
                         "thresholds are grid-fit per CV fold (pocket only)")
    ap.add_argument("--placebo", action="store_true")
    ap.add_argument("--dry", action="store_true")
    ap.add_argument("--no-archive", action="store_true",
                    help="plain elites only (no MAP-Elites parent pool)")
    ap.add_argument("--no-ledger", action="store_true",
                    help="ignore and do not update the motif ledger")
    ap.add_argument("--no-certify", action="store_true",
                    help="stop after the search: no PFS gate, no holdout look "
                         "(fitness A/B runs only)")
    ap.add_argument("--ruler", default="stop_r", choices=["stop_r", "stop_r_20"],
                    help="outcome column the search scores (5-day or 20-day stop ruler)")
    ap.add_argument("--train-end", type=int, default=TRAIN_END,
                    help="evolution sees only years < this (default 2020). "
                         "Raise it ONLY for a trigger too thin before 2020; "
                         "era B (>= 2023) stays the one holdout look")
    args = ap.parse_args()
    TRAIN_END = args.train_end

    if (args.mode == "seeded") != bool(args.seeds):
        ap.error("--mode seeded and --seeds go together")
    if args.fit and not (args.mode == "pocket"
                         or (args.mode == "seeded" and args.genome == "pocket")):
        ap.error("--fit applies to the pocket genome only")

    rng = random.Random(args.seed)
    tag = (f"s{args.seed}"
           + {"pocket": "_pocket", "seeded": "_seeded"}.get(args.mode, "")
           + ("_fit" if args.fit else "")
           + ("_short" if args.side == "short" else "")
           + ("_noarch" if args.no_archive else "")
           + ("_r20" if args.ruler == "stop_r_20" else "")
           + (f"_te{args.train_end}" if args.train_end != 2020 else "")
           + ("_placebo" if args.placebo else ""))
    print(f"evolve: trigger={args.trigger} mode={args.mode} side={args.side} "
          f"pop={args.pop} gens={args.gens} "
          f"seed={args.seed}{' PLACEBO' if args.placebo else ''}")

    seeds = load_seeds(args.seeds) if args.seeds else []
    extra = sorted({n for s in seeds for n, _, _ in s["filters"]}
                   - set(FILTER_NAMES))
    gmode = (args.genome if args.mode == "seeded"
             else "pocket" if args.mode == "pocket" else "gradient")
    ctx = build_ctx(args.trigger, args.placebo, args.seed, args.side,
                    extra=extra, fit=args.fit, ruler=args.ruler)
    dead = []
    if seeds:
        seeds, dead = register_seeds(seeds, ctx, gmode, rng)
        if args.fit:
            # seeds contribute structure only — their thresholds are already
            # on the grid via register_seeds; the fit owns the numbers
            seeds = [{"filters": [[n, op] for n, op, _ in s["filters"]]}
                     for s in seeds]
        print(f"  seeds: {len(seeds)} usable, {len(dead)} UNEVALUABLE "
              f"(no era-A data): {[d['id'] for d in dead]}")
        print(f"  seeded fraction of initial population: "
              f"{len(seeds) / args.pop:.0%}")
    print(f"  train: {len(ctx.train):,} events (<{TRAIN_END}), "
          f"{len(ctx.vals)} usable filter/condition series")

    # placebo runs shuffle the series, so their (edit -> outcome) pairs are
    # a different population; they must never teach the ledger
    ledger = None if (args.placebo or args.no_ledger) else motif_ledger.load()
    scope = (args.trigger, args.side, gmode)
    log = []
    scored = evolve(ctx, args.pop, args.gens, rng, log, gmode, seeds,
                    archive=not args.no_archive, ledger=ledger, ledger_scope=scope)
    if ledger is not None:
        # --dry skips writing promotion artifacts; the search itself was real
        # (real series, real fitness), so its edit outcomes are real memory
        motif_ledger.save(ledger)
        vetoed = motif_ledger.report(ledger, "|".join(scope) + "|")
        print(f"  motif ledger: {sum(1 for ln in vetoed.splitlines() if 'VETO' in ln)} "
              f"vetoed edits in scope {scope}")
    finalists = pick_finalists(scored, args.finalists)
    rows = []
    if args.placebo:
        print(f"\nplacebo run — certification skipped (it would see the "
              f"real, unshuffled series)")
    elif args.no_certify:
        print("\n--no-certify: search only, holdout untouched")
    elif gmode == "pocket":
        if args.fit:
            refit = []
            for res, ind in finalists:
                filters = refit_full(ind, ctx)
                if filters is None:
                    print(f"  refit failed (era-A floors): {ind['filters']}")
                    continue
                refit.append((dict(res, structure=ind["filters"]),
                              {"filters": filters}))
            finalists = refit
        finalists = pfs_gate(finalists, ctx, args.seed)
        print(f"\nfinalists ({len(finalists)}) → pocket judge (era B + "
              f"vs-naked null, first and only look):")
        rows = certify_pockets(finalists, args.trigger, args.side, extra, args.ruler)
    else:
        finalists = pfs_gate(finalists, ctx, args.seed)
        print(f"\nfinalists ({len(finalists)}) → full engine (era B + luck "
              f"test, first and only look):")
        rows = certify(finalists, ctx, tag, not args.dry)

    run_dir = os.path.join(engine.HERE, "evolve_runs")
    os.makedirs(run_dir, exist_ok=True)
    out = os.path.join(run_dir, f"{args.trigger}_{tag}.json")
    with open(out, "w") as f:
        json.dump({"args": vars(args), "generations": log,
                   "unevaluable_seeds": dead, "finalists": rows},
                  f, indent=1, default=float)
    print(f"\nrun log → {out}")
    if args.placebo:
        best = max((g["best"] for g in log), default=0)
        print(f"PLACEBO noise floor: best train fitness z {best:.2f} "
              f"(real champions must clearly beat this)")


if __name__ == "__main__":
    main()
