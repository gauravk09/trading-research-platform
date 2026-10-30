"""
attribution.py — split a trade list's return into market, style and selection.

The audit's random-entry control subtracts the MARKET from a strategy's
return. It cannot subtract STYLE: a momentum breakout list is long the
momentum factor by construction, and in a momentum year the factor pays
whether or not the entry rule picked good stocks. This module does the
subtraction properly (KTD-Fin, arXiv:2605.28359, Barra-style):

    r[i,t] = f0[t] + sum_k x[i,k,t-1] * lam[k,t] + eps[i,t]

One cross-sectional OLS per day over the tradeable universe. Exposures are
lagged one bar (known at t-1 close), winsorised 1/99 and z-scored per date.
A trade's return over its hold then splits EXACTLY into

    common    = sum_t f0[t]                    what any stock earned
    style     = sum_t sum_k x[i,k,t-1]*lam[k,t] what the stock's factor tilt earned
    selection = sum_t eps[i,t]                 what picking THIS stock earned

Promotion should key on selection. Print raw total alongside: MOM_12_1 and
HIGH_52W absorb a Qullamaggie-style edge by construction, so a small
selection number next to a large style number is a finding, not a failure.

Approximations (state them in any report):
  - returns are close-to-close; a D+1-open entry's open->close piece on the
    entry day is not decomposed (it is not in the factor model either)
  - the hold is a fixed window, not the stop-managed exit: this answers
    "was there selection alpha over the window?", not "what R did the ruler pay?"

Style factors (all OHLCV, no vendor model):
  mom_12_1  close[t-21]/close[t-252]-1         rv_60    60d std of daily returns
  illiq     log 20d mean |ret|/turnover (Amihud) rev_on 20d mean overnight return
  mom_id    20d mean intraday return           skew     60d return skew
  corr_pv   60d corr(ret, turnover change)     high_52w close/252d-high - 1
  cv_vol    60d volume std/mean

Usage:
    from attribution import FactorModel, attribute, fmt_attribution
    fm = FactorModel.build(m, universe)          # m = common.load_cache()
    per, a = attribute(trades, horizon=20, fm=fm)  # trades: date, symbol, side
    print(fmt_attribution("strategy", a))
"""

import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

STYLE = ["mom_12_1", "rv_60", "illiq", "rev_on", "mom_id", "skew", "corr_pv",
         "high_52w", "cv_vol"]
MIN_NAMES = 100          # a day needs this many stocks to fit 10 coefficients
WINSOR = (0.01, 0.99)
RET_CLIP = 0.5           # a +-50% daily move is a data break, not a return


def _naive(idx):
    idx = pd.DatetimeIndex(idx)
    return idx.tz_localize(None) if idx.tz is not None else idx


def _standardize(f, universe):
    """Winsorise and z-score per date WITHIN the universe the regression
    will see. Standardising over the whole panel and then regressing on a
    liquidity-filtered subset leaves every exposure off-centre inside the
    subset, and the intercept (the market term) absorbs the offset."""
    f = f.where(universe)
    lo = f.quantile(WINSOR[0], axis=1)
    hi = f.quantile(WINSOR[1], axis=1)
    f = f.clip(lower=lo, upper=hi, axis=0)
    return f.sub(f.mean(axis=1), axis=0).div(f.std(axis=1), axis=0)


def style_exposures(m, universe):
    """Standardised exposures at date t (NOT yet lagged)."""
    c, o, h, v = m["close"], m["open"], m["high"], m["volume"]
    r = c.pct_change()
    turn = (c * v).replace(0, np.nan)
    with np.errstate(divide="ignore", invalid="ignore"):
        raw = {
            "mom_12_1": c.shift(21) / c.shift(252) - 1,
            "rv_60": r.rolling(60).std(),
            # Amihud spans six orders of magnitude; the log is the usable scale
            "illiq": np.log((r.abs() / turn).rolling(20).mean()),
            "rev_on": (o / c.shift(1) - 1).rolling(20).mean(),
            "mom_id": (c / o - 1).rolling(20).mean(),
            "skew": r.rolling(60).skew(),
            "corr_pv": r.rolling(60).corr(turn.pct_change().replace([np.inf, -np.inf], np.nan)),
            "high_52w": c / h.rolling(252).max() - 1,
            "cv_vol": v.rolling(60).std() / v.rolling(60).mean(),
        }
    return {k: _standardize(f.replace([np.inf, -np.inf], np.nan), universe)
            for k, f in raw.items()}


class FactorModel:
    """f0 (Series by date), lam (DataFrame date x factor), resid (date x symbol)."""

    def __init__(self, f0, lam, resid, ret):
        self.f0, self.lam, self.resid, self.ret = f0, lam, resid, ret

    @classmethod
    def from_exposures(cls, ret, X, universe):
        """`ret` daily returns at t; `X` dict name -> exposure at t (lagged
        inside); `universe` bool frame at t (lagged inside)."""
        names = list(X)
        idx, cols = ret.index, ret.columns
        Xl = np.stack([X[k].shift(1).reindex(index=idx, columns=cols).to_numpy()
                       for k in names], axis=-1)               # T x N x K
        U = (universe.shift(1, fill_value=False)
             .reindex(index=idx, columns=cols, fill_value=False).to_numpy(bool))
        R = ret.to_numpy()
        T, N, K = Xl.shape
        f0 = np.full(T, np.nan)
        lam = np.full((T, K), np.nan)
        resid = np.full((T, N), np.nan)
        for t in range(T):
            ok = U[t] & ~np.isnan(R[t]) & ~np.isnan(Xl[t]).any(axis=1)
            if ok.sum() < MIN_NAMES:
                continue
            A = np.column_stack([np.ones(ok.sum()), Xl[t, ok]])
            beta, *_ = np.linalg.lstsq(A, R[t, ok], rcond=None)
            f0[t], lam[t] = beta[0], beta[1:]
            resid[t, ok] = R[t, ok] - A @ beta
        fm = cls(pd.Series(f0, index=idx),
                 pd.DataFrame(lam, index=idx, columns=names),
                 pd.DataFrame(resid, index=idx, columns=cols), ret)
        fm.Xl = Xl
        return fm

    @classmethod
    def build(cls, m, universe):
        ret = m["close"].pct_change().clip(-RET_CLIP, RET_CLIP)
        return cls.from_exposures(ret, style_exposures(m, universe), universe)


def attribute(trades, horizon, fm, side_col="side"):
    """
    Per-trade decomposition over close-to-close bars (r+2 .. r+1+hold), i.e.
    starting from the D+1 close (the D+1 open->close piece is outside the
    factor model). Returns (per_trade DataFrame, summary dict).
    """
    idx = _naive(fm.ret.index)
    dates = _naive(pd.DatetimeIndex(trades["date"]))
    ri = idx.get_indexer(dates)
    ci = fm.ret.columns.get_indexer(trades["symbol"])
    hold = (trades["hold"].to_numpy() if "hold" in trades.columns
            else np.full(len(trades), horizon)).astype(int)
    sign = np.where(trades[side_col].to_numpy() == "short", -1.0, 1.0) \
        if side_col in trades.columns else np.ones(len(trades))
    T = len(idx)
    R, E, F0, L = fm.ret.to_numpy(), fm.resid.to_numpy(), fm.f0.to_numpy(), fm.lam.to_numpy()
    Xl = fm.Xl
    K = L.shape[1]
    rows = []
    for j in range(len(trades)):
        r, c = ri[j], ci[j]
        if r < 0 or c < 0:
            continue
        lo, hi = r + 2, min(r + 1 + hold[j], T - 1)
        if hi < lo:
            continue
        sl = slice(lo, hi + 1)
        ok = ~np.isnan(E[sl, c])
        if not ok.any():
            continue
        tot = np.nansum(np.where(ok, R[sl, c], np.nan))
        com = np.nansum(np.where(ok, F0[sl], np.nan))
        sty_k = np.nansum(np.where(ok[:, None], Xl[sl, c, :] * L[sl], np.nan), axis=0)
        sel = np.nansum(np.where(ok, E[sl, c], np.nan))
        rows.append([dates[j], trades["symbol"].iloc[j], int(ok.sum()),
                     sign[j] * tot, sign[j] * com, sign[j] * sty_k.sum(),
                     sign[j] * sel] + list(sign[j] * sty_k))
    cols = ["date", "symbol", "bars", "total", "common", "style", "selection"] \
        + [f"style_{k}" for k in fm.lam.columns]
    per = pd.DataFrame(rows, columns=cols)
    return per, summarize(per)


def summarize(per):
    if per.empty:
        return {"n": 0}
    out = {"n": int(len(per)), "dates": int(per["date"].nunique()),
           "bars": float(per["bars"].mean())}
    for k in ("total", "common", "style", "selection"):
        out[f"{k}_pct"] = float(per[k].mean() * 100)
    # t of the per-trade mean with date-clustered SE: trades sharing a date
    # share a market path, so they are one observation, not many
    dev = per["selection"] - per["selection"].mean()
    se = np.sqrt((dev.groupby(per["date"]).sum() ** 2).sum()) / len(per)
    out["selection_t"] = float(per["selection"].mean() / se) if se > 0 else np.nan
    out["style_breakdown_pct"] = {c[6:]: float(per[c].mean() * 100)
                                  for c in per.columns if c.startswith("style_")}
    return out


def fmt_attribution(label, s, indent=2):
    if not s or not s.get("n"):
        return " " * indent + f"{label:<28} --"
    top = sorted(s["style_breakdown_pct"].items(), key=lambda kv: -abs(kv[1]))[:3]
    top_s = " ".join(f"{k}{v:+.2f}" for k, v in top)
    return (" " * indent + f"{label:<28} n={s['n']:<6} per-trade %: total {s['total_pct']:+.2f} = "
            f"market {s['common_pct']:+.2f} + style {s['style_pct']:+.2f} + "
            f"SELECTION {s['selection_pct']:+.2f} (t {s['selection_t']:+.1f})"
            f"   [style: {top_s}]")
