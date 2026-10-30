"""conviction.py — turn a scan hit-list into a ranked research queue.

Every hit gets:
  priority      0-100 score built ONLY from red-team-validated factors
  signal        TAKE / CAUTION / SKIP
  strategy_fit  which playbook (if any) the row belongs to
  why           the factors that moved the score, best-first
  pop/exp_ret/exp_r/cohort_n
                the historical cohort's P(profit), mean 5-day return and
                expected R from trade_metrics.py (D+1-open basis, era 2023+)

The point: a scan says "this matched a pattern"; this module says "look at
these first, skip those, and here is which playbook each belongs to".
Weights are coarse on purpose — the machine certified directions, not
fine-grained coefficients. Provenance for every factor: the Tape Rules doc
and research/machine/SCOREBOARD.md.

Families map the dashboard setups onto rule-sets:
  breakout      Breakout Setup            (burst family, pct40ma gate)
  anticipation  Anticipation coils        (Qullamaggie profile check)
  reversal      Reversal Bullish          (dip-buy rules: stock trend + tape)
  bounce        Bottom Bounce             (leader-washout rules)
  ep            EP9M / DEP / EP Checklist (EP family — positive, uncertified)
  short         Weak Structure / Swing Exhaustion (no certified book)
"""

import pandas as pd

import trade_metrics

PCT40_GATE = 55        # Qullamaggie breadth gate
PCT40_WASHOUT = 40     # below this, dip-buy pockets graded negative
PCT40_BONDE = 20       # Bonde's bottom-bounce washout context


def _cohort_factor(m, add):
    """Move the score by how much better/worse this candidate's historical
    cohort did than its OWN family base rate.

    Deliberately relative, never absolute: the holdout study
    (output/studies/trade_metrics_calibration.md) found the ordering holds on
    unseen dates (8-16pp between the top and bottom third) but the absolute
    level drifts by up to 7pp across regimes. So a cohort that beats its family
    is evidence; a printed 55% is not."""
    if not m or m.get("confidence") != "high":
        return
    pp = (m["p_profit_5d"] - m["base_p_profit_5d"]) * 100
    if abs(pp) < 1.5:
        return
    delta = 8 if abs(pp) >= 4 else 4
    add(delta if pp > 0 else -delta,
        f"cohort {m['p_profit_5d']:.0%} vs {m['family']} base "
        f"{m['base_p_profit_5d']:.0%} ({m['cohort']}, n={m['n']:,})")


def _row_score(r, market, family, metrics=None):
    pts, why = 50.0, []

    def add(delta, reason):
        nonlocal pts
        pts += delta
        why.append((abs(delta), f"{'+' if delta > 0 else '−'} {reason}"))

    hard_skip = None
    gate_closed = False
    pct40 = market.get("pct40ma")

    turn = r.get("avg_turnover_cr") or 0
    if turn >= 100:
        add(10, f"very liquid (₹{turn:.0f}cr) — liquidity confirmed everywhere")
    elif turn >= 25:
        add(5, f"liquid (₹{turn:.0f}cr)")
    elif turn < 5:
        add(-15, f"illiquid (₹{turn:.0f}cr) — illiquid names graded worst")

    r1w = r.get("r1w_pct")
    if family in ("breakout", "anticipation", "ep") and r1w is not None \
            and pd.notna(r1w) and r1w >= 10:
        add(-10, f"already ran +{r1w:.0f}% this week (short-term exhaustion, "
                 "Kell inverted)")

    vr = r.get("volume_ratio")
    if family in ("breakout", "anticipation") and vr is not None \
            and pd.notna(vr) and vr >= 3:
        add(-10, f"volume frenzy ({vr:.1f}x) — biggest spikes underperform "
                 "(Zanger inverted)")

    ti65 = r.get("ti65")
    in_uptrend = ti65 is not None and pd.notna(ti65) and ti65 >= 1.0

    fit = "—"
    if family in ("breakout", "anticipation"):
        gate = pct40 is not None and pct40 >= PCT40_GATE
        if gate:
            add(15, f"breadth gate open (pct40ma={pct40:.0f})")
        else:
            gate_closed = True
            add(-20, f"breadth gate closed (pct40ma="
                     f"{'?' if pct40 is None else round(pct40)} < {PCT40_GATE})")
        r3mo = r.get("r3mo_pct")
        near_hi = r.get("pct_from_52w_high")
        qm = (r3mo is not None and pd.notna(r3mo) and r3mo >= 30
              and near_hi is not None and pd.notna(near_hi) and near_hi >= -15)
        if qm:
            add(15, f"Qullamaggie profile (3mo +{r3mo:.0f}%, near 52wH)")
            fit = "Qullamaggie (gated)"
        else:
            fit = "Stockbee burst — no certified book"
        rs = r.get("rs_rank")
        if rs is not None and pd.notna(rs) and rs >= 80:
            add(5, f"RS {rs:.0f} (20-day selection factor)")

    elif family == "reversal":
        fit = "Dip-buy (tape rules)"
        if pct40 is not None and pct40 < PCT40_WASHOUT:
            hard_skip = (f"market washout (pct40ma={pct40:.0f} < "
                         f"{PCT40_WASHOUT}) — washout dip pockets graded "
                         "strongly negative")
        elif not in_uptrend:
            hard_skip = ("stock not in an uptrend (ti65 < 1.0) — dip-buy "
                         "edge only exists in stock-level uptrends")
        else:
            add(15, f"dip inside a stock uptrend (ti65={ti65:.2f})")
            if vr is not None and pd.notna(vr) and vr >= 2:
                add(10, f"capitulation volume ({vr:.1f}x) on the dip — "
                        "confirmed bounce grader")

    elif family == "bounce":
        fit = "Leader-washout bounce"
        if pct40 is None or pct40 >= PCT40_BONDE:
            hard_skip = (f"no washout (pct40ma="
                         f"{'?' if pct40 is None else round(pct40)} >= "
                         f"{PCT40_BONDE}) — bounce edge exists only in washed-"
                         "out markets")
        else:
            add(15, f"washout context ON (pct40ma={pct40:.0f})")
            rs = r.get("rs_rank")
            if rs is not None and pd.notna(rs) and rs >= 70:
                add(10, f"was a leader (RS {rs:.0f}) — leader washouts carry "
                        "the bounce edge")

    elif family == "ep":
        fit = "EP family (positive, uncertified)"
        if in_uptrend:
            add(10, f"prior uptrend intact (ti65={ti65:.2f}) — EP momentum "
                    "tilt")
        net4 = market.get("net4")
        if net4 is not None and net4 >= 0:
            add(5, f"tape not hostile (net4={net4})")

    elif family == "short":
        fit = "No certified book — validated short = lone loser in GREEN tape"
        add(-15, "weak-structure shorts untested by the machine; the "
                 "confirmed short wants a STRONG tape, not a weak one")

    if family != "short" and family != "reversal" and not in_uptrend \
            and family != "bounce":
        add(-5, "no stock-level uptrend (ti65 < 1.0)")

    _cohort_factor(metrics, add)

    if hard_skip:
        pts, signal = min(pts - 30, 25), "SKIP"
        why.insert(0, (99, f"− {hard_skip}"))
    else:
        pts = max(0.0, min(100.0, pts))
        signal = "TAKE" if pts >= 60 else "CAUTION" if pts >= 40 else "SKIP"
        if gate_closed and signal == "TAKE":
            signal = "CAUTION"   # a closed playbook gate always caps at watch

    why.sort(key=lambda t: -t[0])
    return round(max(0.0, min(100.0, pts))), signal, fit, \
        " · ".join(w for _, w in why[:4])


def rank(frame, market, family):
    """Return `frame` + priority/signal/strategy_fit/why + the cohort metrics
    (pop / exp_r / cohort_n), best-first."""
    if frame is None or frame.empty:
        return frame
    out = frame.copy()
    try:
        mets = trade_metrics.for_rows(out["symbol"], family, market or {})
    except (OSError, KeyError, ValueError):
        mets = [None] * len(out)
    scored = [_row_score(r, market or {}, family, m)
              for r, m in zip(out.to_dict("records"), mets)]
    out["pop"] = [m["p_profit_5d"] if m else None for m in mets]
    out["exp_ret"] = [m["mean_ret_5d_pct"] if m else None for m in mets]
    out["exp_r"] = [m["exp_r_trail"] if m else None for m in mets]
    out["cohort_n"] = [m["n"] if m else None for m in mets]
    out["priority"] = [s[0] for s in scored]
    out["signal"] = [s[1] for s in scored]
    out["strategy_fit"] = [s[2] for s in scored]
    out["why"] = [s[3] for s in scored]
    return out.sort_values("priority", ascending=False).reset_index(drop=True)
