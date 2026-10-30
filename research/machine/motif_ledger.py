"""
motif_ledger.py — cross-run memory of which EDITS helped or hurt the GA.

evolve_runs/ remembers champions; nothing remembered what was tried and
failed, so every run re-discovers that (say) adding a size filter to a
strong trend pocket is a dead end. This ledger keys on the EDIT, not the
genome (AlphaMemo, arXiv:2606.20625):

    key   = trigger|side|genome|parent-score-bucket|motif
    motif = mutation op + series family, e.g. "add_filter:volume"
    delta = z(child) - z(parent) - E[delta | bucket]     (residual: a neutral
            edit on a strong parent must not inherit the parent's score)

Confidence  c = n/(n+KAPPA) * min(1, |mu| / (sigma+eps)).
Used ASYMMETRICALLY: an edit with confident negative evidence is vetoed at
mutation time; positive evidence is only reported, never boosted (a GA that
rewards its own favourite edits converges on them).

Entries decay with a one-year half-life, otherwise a 2016 verdict vetoes
forever. Placebo and --dry runs never write.
"""

import json
import math
import os
import time

HERE = os.path.dirname(os.path.abspath(__file__))
PATH = os.path.join(HERE, "motif_ledger.json")
KAPPA = 5.0
HALF_LIFE_DAYS = 365.0
VETO_CONF = 0.5
_ALL = "_all"


def bucket_of(score):
    return "z0" if score <= 0 else "z1" if score <= 1 else "z2" if score <= 2 else "z3"


def key_of(trigger, side, genome, parent_score, motif):
    return f"{trigger}|{side}|{genome}|{bucket_of(parent_score)}|{motif}"


def load(path=PATH, now=None):
    if not os.path.exists(path):
        return {}
    now = now or time.time()
    ledger = json.load(open(path))
    for e in ledger.values():
        f = 0.5 ** ((now - e["updated"]) / 86400.0 / HALF_LIFE_DAYS)
        e["n"], e["s1"], e["s2"] = e["n"] * f, e["s1"] * f, e["s2"] * f
    return ledger


def save(ledger, path=PATH):
    with open(path, "w") as f:
        json.dump(ledger, f, indent=1, sort_keys=True)


def stats(e):
    if not e or e["n"] <= 0:
        return 0.0, 0.0, 0.0
    mu = e["s1"] / e["n"]
    sigma = math.sqrt(max(e["s2"] / e["n"] - mu * mu, 0.0))
    c = e["n"] / (e["n"] + KAPPA) * min(1.0, abs(mu) / (sigma + 1e-6))
    return mu, sigma, c


def _bump(ledger, key, delta, now):
    e = ledger.setdefault(key, {"n": 0.0, "s1": 0.0, "s2": 0.0, "updated": now})
    e["n"] += 1
    e["s1"] += delta
    e["s2"] += delta * delta
    e["updated"] = now


def record(ledger, key, raw_delta, now=None):
    """raw_delta = z(child) - z(parent). The bucket baseline (key with the
    motif replaced by _all) is read BEFORE this update so the residual is
    against what other edits from equally-good parents achieved."""
    now = now or time.time()
    base_key = key.rsplit("|", 1)[0] + "|" + _ALL
    baseline = stats(ledger.get(base_key))[0]
    _bump(ledger, base_key, raw_delta, now)
    _bump(ledger, key, raw_delta - baseline, now)


def vetoed(ledger, key):
    mu, _, c = stats(ledger.get(key))
    return mu < 0 and c >= VETO_CONF


def report(ledger, prefix=""):
    rows = []
    for k, e in ledger.items():
        if not k.startswith(prefix) or k.endswith(_ALL):
            continue
        mu, sigma, c = stats(e)
        rows.append((k, e["n"], mu, sigma, c, vetoed(ledger, k)))
    rows.sort(key=lambda r: (-r[5], r[2]))
    return "\n".join(f"  {'VETO ' if v else '     '}{k:<60} n={n:5.1f} mu={mu:+.2f} sd={sd:.2f} c={c:.2f}"
                     for k, n, mu, sd, c, v in rows)
