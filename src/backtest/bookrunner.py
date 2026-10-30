"""
bookrunner.py — the three fixes from HARNESS_AUDIT_2026-08-07.md.

One responsibility: turn a list of trades into an honest portfolio verdict.

FIX 1 — two sizing models, pick the one that matches the account.
  mode="risk"     fixed-fractional risk, notional = risk_amt/stop_pct, capped by
                  leverage and portfolio heat. Correct for F&O, where leverage
                  is real. This is the incumbent batch5_fno_portfolio model.
  mode="capital"  N equal capital slots, no leverage. Correct for cash delivery:
                  the slot is fixed and the STOP determines risk (a 2% stop on a
                  10% slot risks 0.2% of equity, not 0.75%). Using "risk" on a
                  tight-stop cash strategy demands leverage the account does not
                  have, so the caps refuse 74-90% of signals and the verdict is
                  an artifact of the constraint, not the strategy.

FIX 2 — seed_spread(): never report a point estimate when the book skips a
  material fraction of signals. Which same-day signals get taken is decided by
  row order, and re-ordering the identical pool moved CAGR by 10 points and
  maxDD by 23. Report p10 / median / p90 over >=20 tie-break orders.

FIX 3 — random_control(): a matched random-entry baseline, same universe, hold,
  stop rule, side, sizing and costs. research/README.md already requires this
  for mover stats; it was never applied to R/portfolio studies, so nothing
  subtracted the market. Random long entries score +0.23R at a 60-bar hold —
  a strategy scoring +0.20R is BELOW the market, not a pass.

Trade schema (one row per trade):
    date       tz-naive Timestamp on the trading calendar
    symbol     str
    R          outcome in units of initial risk (house rulers: stop_r etc.)
    stop_pct   initial stop distance as a fraction of entry
    side       "long" | "short"   (informational; R is already signed correctly)
    hold       optional int bars held; falls back to the `horizon` argument

Usage:
    from bookrunner import run_book, seed_spread, random_control
"""

import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "studies"))

START_EQ = 1_000_000.0
DEFAULT_SEEDS = 20
SKIP_WARN = 0.20          # above this skipped fraction, a point estimate is banned


def _prep(trades, cal, horizon):
    t = trades.dropna(subset=["R", "stop_pct"]).copy()
    t = t[t["stop_pct"] > 0]
    pos = pd.Series(range(len(cal)), index=cal)
    t["bar"] = t["date"].map(pos)
    t = t.dropna(subset=["bar"])
    t["bar"] = t["bar"].astype(int)
    t["bars"] = t["hold"].astype(int) if "hold" in t.columns else int(horizon)
    return t.sort_values("bar", kind="stable")


def run_book(trades, cal, mode="capital", slots=10, risk_pct=0.0075,
             lev_cap=5.0, heat_cap=0.06, cost_side=0.0015, horizon=5,
             order=None):
    """Sequence trades through a book. Returns None if fewer than 50 are taken."""
    t = _prep(trades if order is None else order, cal, horizon)
    eq, open_pos, taken, skipped, curve, net = START_EQ, [], 0, 0, [], []

    for x in t.itertuples():
        open_pos = [p for p in open_pos if p[0] > x.bar]
        if mode == "capital":
            if len(open_pos) >= slots:
                skipped += 1
                continue
            slot = eq / slots
            if sum(p[1] for p in open_pos) + slot > eq:
                skipped += 1
                continue
            r_net = x.R - 2 * cost_side / x.stop_pct
            eq += (x.R * x.stop_pct - 2 * cost_side) * slot
            open_pos.append((x.bar + x.bars, slot))
        else:
            risk_amt = risk_pct * eq
            notional = risk_amt / x.stop_pct
            if sum(p[1] for p in open_pos) + notional > lev_cap * eq:
                skipped += 1
                continue
            if sum(p[2] for p in open_pos) + risk_amt > heat_cap * eq:
                skipped += 1
                continue
            r_net = x.R - 2 * cost_side / x.stop_pct
            eq += r_net * risk_amt
            open_pos.append((x.bar + x.bars, notional, risk_amt))
        net.append(r_net)
        taken += 1
        curve.append((min(x.bar + x.bars, len(cal) - 1), eq))

    if taken < 50:
        return None
    c = pd.Series(dict(curve))
    c.index = cal[c.index.values]
    c = c.sort_index()
    yrs = max((c.index[-1] - c.index[0]).days / 365.25, 0.25)
    return {"taken": taken, "skipped": skipped,
            "skip_frac": skipped / max(taken + skipped, 1),
            "cagr": (eq / START_EQ) ** (1 / yrs) - 1,
            "maxdd": float((1 - c / c.cummax()).max()),
            "net_R": float(np.mean(net)), "win": float(np.mean(np.array(net) > 0))}


def seed_spread(trades, cal, seeds=DEFAULT_SEEDS, **kw):
    """
    Run the book over `seeds` tie-break orders. Returns the distribution, plus
    `banned` = True when the skip fraction is high enough that a single-number
    verdict would be dishonest.
    """
    cg, dd, tk, sk, nr = [], [], [], [], []
    for s in range(seeds):
        o = trades.sample(frac=1.0, random_state=7000 + s)
        x = run_book(trades, cal, order=o, **kw)
        if x:
            cg.append(x["cagr"] * 100)
            dd.append(x["maxdd"] * 100)
            tk.append(x["taken"])
            sk.append(x["skip_frac"])
            nr.append(x["net_R"])
    if len(cg) < max(5, seeds // 4):
        return None
    return {"n": len(trades), "taken": int(np.median(tk)),
            "skip_frac": float(np.median(sk)), "net_R": float(np.median(nr)),
            "med": float(np.median(cg)), "lo": float(np.percentile(cg, 10)),
            "hi": float(np.percentile(cg, 90)), "dd": float(np.median(dd)),
            "pos": float(np.mean(np.array(cg) > 0)),
            "banned": bool(np.median(sk) > SKIP_WARN)}


def _stop_r(entry, anchor, rows, cols, O, H, L, C, n_dates, horizon, side):
    """
    House convention: enter D+1 open; stop = max(signal low, entry*0.94) long /
    min(signal high, entry*1.06) short; gap through the stop fills at the open;
    otherwise time-exit at `horizon` bars' close. Result in R.
    """
    out = np.full(len(entry), np.nan)
    for i in range(len(entry)):
        r0, c0, e = rows[i], cols[i], entry[i]
        if r0 + 1 >= n_dates or not np.isfinite(e):
            continue
        if side == "long":
            stop = max(anchor[i], e * 0.94)
            risk = e - stop
        else:
            stop = min(anchor[i], e * 1.06)
            risk = stop - e
        if not np.isfinite(risk) or risk <= 0:
            continue
        px = np.nan
        for t in range(r0 + 1, min(r0 + 1 + horizon, n_dates)):
            if not np.isfinite(C[t, c0]):
                continue
            if side == "long":
                if O[t, c0] <= stop:
                    px = O[t, c0]
                    break
                if L[t, c0] <= stop:
                    px = stop
                    break
            else:
                if O[t, c0] >= stop:
                    px = O[t, c0]
                    break
                if H[t, c0] >= stop:
                    px = stop
                    break
            px = C[t, c0]
        if not np.isfinite(px):
            continue
        out[i] = ((px - e) if side == "long" else (e - px)) / risk
    return out


def random_control(m, universe, n, horizon, side, seed=0):
    """
    `n` random (date, symbol) entries drawn from the boolean `universe` mask,
    priced with the SAME entry clock, stop rule and hold as the strategy being
    benchmarked. Returns a trade frame in the standard schema.
    """
    rows, cols = np.where(universe.reindex_like(m["close"]).fillna(False).values)
    rng = np.random.default_rng(seed)
    pick = rng.choice(len(rows), size=min(n, len(rows)), replace=False)
    r, c = rows[pick], cols[pick]

    O, H, L, C = (m[k].to_numpy() for k in ("open", "high", "low", "close"))
    n_dates = len(m["close"].index)
    nxt = np.minimum(r + 1, n_dates - 1)
    entry = O[nxt, c]
    anchor = L[r, c] if side == "long" else H[r, c]
    R = _stop_r(entry, anchor, r, c, O, H, L, C, n_dates, horizon, side)
    stop = (np.maximum(anchor, entry * 0.94) if side == "long"
            else np.minimum(anchor, entry * 1.06))
    stop_pct = np.abs(entry - stop) / entry

    out = pd.DataFrame({"date": m["close"].index[r], "symbol": m["close"].columns[c],
                        "R": R, "stop_pct": stop_pct, "side": side})
    out["date"] = pd.DatetimeIndex(out["date"]).tz_localize(None)
    return out.dropna(subset=["R", "stop_pct"]).reset_index(drop=True)


def fmt(label, s, indent=2):
    if not s:
        return " " * indent + f"{label:<30} --"
    flag = "  [POINT ESTIMATE BANNED]" if s["banned"] else ""
    return (" " * indent +
            f"{label:<30} n={s['n']:<6} taken {s['taken']:<5} "
            f"skip {s['skip_frac']*100:3.0f}%  R {s['net_R']:+.3f}  "
            f"CAGR {s['med']:+6.1f}% [p10 {s['lo']:+6.1f}, p90 {s['hi']:+6.1f}]  "
            f"DD {s['dd']:5.1f}%  seeds>0 {s['pos']*100:3.0f}%{flag}")


def same_date_control(m, universe, rows, k=1, seed=0):
    """
    The control the audit should have used from the start.

    `random_control` draws entries anywhere in the sample, so if a strategy
    only fires in good tape its control still fires everywhere — the two
    cohorts face different market paths and a bad era confounds the comparison.
    A SAME-DATE control inherits the strategy's date distribution exactly, and
    therefore its regime distribution: for every signal bar, draw `k` random
    symbols that were tradeable on THAT bar. Any remaining difference is entry
    selection, with habitat held constant by construction.

    This is the rule research/README.md already states for mover stats
    ("every mover stat is shown against a same-date non-mover baseline").

    Returns a frame with date/symbol/di/si — feed it to whichever exit engine
    the strategy uses so exits are held constant too.
    """
    univ = universe.reindex_like(m["close"]).fillna(False).to_numpy()
    rng = np.random.default_rng(seed)
    out_r, out_c = [], []
    for r in np.unique(rows):
        cols = np.flatnonzero(univ[r])
        if not len(cols):
            continue
        n_here = int((rows == r).sum()) * k
        out_r.append(np.full(n_here, r))
        out_c.append(rng.choice(cols, size=n_here, replace=len(cols) < n_here))
    if not out_r:
        return pd.DataFrame(columns=["date", "symbol", "di", "si"])
    r = np.concatenate(out_r)
    c = np.concatenate(out_c)
    return pd.DataFrame({"date": m["close"].index[r], "symbol": m["close"].columns[c],
                         "di": r, "si": c})
