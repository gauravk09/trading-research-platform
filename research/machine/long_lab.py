"""long_lab.py — measure large-cap LONG setups as TRADEABLE books (ret/DD + era
split), not as engine bucket-edges. This is how we decide if a long "works":
a real leveraged portfolio sim, and an era split to kill COVID-only mirages.

A hypothesis is a JSON config:
{
  "id": "...", "plain": "...",
  "source": "trigger" | "csv",
  "trigger": "four_pct" | "bounce" | "burst" | "four_pct_down" | "ep",   # if trigger
  "csv": "connors_rsi2_events.csv",                                       # if csv
  "filters": [["ti65",">=",1.0], ["market:net4",">=",50], ...],          # AND-ed; engine vocab
  "horizon": 5 | 10 | 20 | 60,        # time-exit bars (6% signal-low stop always)
  "risk": 0.0075                       # fraction of equity per trade
}
mcap_rank<=150 is enforced automatically (large-cap / F&O universe).

Grade a directory:  ~/anaconda3/bin/python research/machine/long_lab.py specs/<dir>
Bar: ret/DD clearly > 0.16 (burst-long) with era-B (2023+) POSITIVE and maxDD < 25%.
"""
import glob
import json
import os
import sys

import numpy as np
import pandas as pd

HERE = os.path.dirname(__file__)
# append backtest paths, but keep HERE at sys.path[0] so `engine` resolves to the
# research-machine engine (a different engine.py lives in src/backtest).
sys.path.append(os.path.join(HERE, "..", "..", "src", "backtest"))
sys.path.append(os.path.join(HERE, "..", "..", "src", "backtest", "studies"))
sys.path.insert(0, HERE)
import engine as E  # noqa: E402
import common  # noqa: E402
import event_store as ES  # noqa: E402
import batch5_fno_portfolio as P  # noqa: E402

OUT = common.OUTPUT_DIR
ERAS = [("A15-19", 2015, 2019), ("COVID20-22", 2020, 2022),
        ("B23-26", 2023, 2026), ("sub24-26", 2024, 2026)]


def load_events(cfg):
    if cfg["source"] == "trigger":
        ev = E.load_events()
        return ev[ev["trigger"] == cfg["trigger"]][["date", "symbol"]].copy()
    df = pd.read_csv(os.path.join(OUT, cfg["csv"]),
                     usecols=lambda c: c in ("date", "symbol"))
    return df[["date", "symbol"]].copy()


def make_trades(events, filters, horizon):
    events = events.copy()
    events["date"] = pd.DatetimeIndex(events["date"]).tz_localize(None)
    # enforce large-cap + apply hypothesis filters via the engine (same vocab)
    flt = [["mcap_rank", "<=", 150]] + [f for f in (filters or [])]
    ev = E.apply_filters(events, flt)
    if not len(ev):
        return None
    m = common.load_cache()
    close = m["close"]
    idx = close.index.tz_localize(None) if close.index.tz is not None else close.index
    di = idx.get_indexer(pd.DatetimeIndex(ev["date"]))
    ci = close.columns.get_indexer(ev["symbol"])
    ok = (di >= 0) & (ci >= 0) & (di + 1 < len(idx))
    ev, di, ci = ev[ok].reset_index(drop=True), di[ok], ci[ok]
    O, L, C = m["open"].values, m["low"].values, m["close"].values
    entry = O[np.minimum(di + 1, len(idx) - 1), ci]
    slow = L[di, ci]
    R = ES._stop_r(entry, slow, di, ci, O, L, C, len(idx), horizon)
    stop = np.maximum(slow, entry * 0.94)
    tr = pd.DataFrame({"date": ev["date"].values, "symbol": ev["symbol"].values,
                       "R": R, "stop_pct": (entry - stop) / entry, "side": "long"})
    return tr.dropna(subset=["R", "stop_pct"])


def era_stats(curve):
    out = {}
    for nm, y0, y1 in ERAS:
        c = curve[(curve.index.year >= y0) & (curve.index.year <= y1)]
        if len(c) < 5:
            out[nm] = None
            continue
        yrs = max((c.index[-1] - c.index[0]).days / 365.25, 0.25)
        out[nm] = round(((c.iloc[-1] / c.iloc[0]) ** (1 / yrs) - 1) * 100, 1)
    return out


def grade(cfg, cal):
    tr = make_trades(load_events(cfg), cfg.get("filters"), cfg["horizon"])
    if tr is None or len(tr) < 80:
        return dict(id=cfg["id"], n=(0 if tr is None else len(tr)), verdict="THIN")
    P.HOLD_BARS = cfg["horizon"]
    x = P.simulate(tr, cal, cfg.get("risk", 0.0075),
                   lev_cap=2.5, cost_side=0.0005, heat_cap=0.08)
    if not x:
        return dict(id=cfg["id"], n=len(tr), verdict="EMPTY")
    rdd = x["cagr"] / abs(x["maxdd"]) if x["maxdd"] else 0.0
    es = era_stats(x["curve"])
    return dict(id=cfg["id"], n=len(tr), per_yr=round(x["per_yr"], 0),
                cagr=round(x["cagr"] * 100, 1), maxdd=round(x["maxdd"] * 100, 1),
                retdd=round(rdd, 2), net_R=round(x["avg_net_R"], 3),
                win=round(x["win"] * 100, 0), eras=es,
                verdict=("WORKS" if rdd > 0.30 and x["maxdd"] > -0.25
                         and (es.get("B23-26") or -9) > 0 else "weak"))


def main(spec_dir):
    cal = common.load_cache()["close"].index.tz_localize(None)
    paths = sorted(glob.glob(os.path.join(HERE, spec_dir, "*.json")))
    print(f"{'id':28s} {'verdict':7s} {'retDD':>5s} {'CAGR':>6s} {'maxDD':>6s} "
          f"{'/yr':>4s} {'n':>5s}  {'A/COVID/B/24+':>18s}")
    for p in paths:
        cfg = json.load(open(p))
        r = grade(cfg, cal)
        e = r.get("eras") or {}
        estr = f"{e.get('A15-19')}/{e.get('COVID20-22')}/{e.get('B23-26')}/{e.get('sub24-26')}"
        print(f"{r['id']:28s} {r['verdict']:7s} {r.get('retdd','-'):>5} "
              f"{r.get('cagr','-'):>6} {r.get('maxdd','-'):>6} {str(r.get('per_yr','-')):>4} "
              f"{r['n']:>5}  {estr:>18s}")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "specs/long5")
