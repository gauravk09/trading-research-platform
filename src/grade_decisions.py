"""
grade_decisions.py — Forward-return grader for every recorded decision (roadmap item 3)

Reads every decision the platform has captured:
  - scan candidates from output/state/<date>.json   (source = "scan")
  - /brief journal lines from output/brief/journal.jsonl
      recommendations  (source = "brief_reco",       note = verdict)
      passed_over      (source = "brief_passed",     note = reason)
      watchlist        (source = "brief_watchlist")
  - triage verdicts from data/processed/triage_verdicts.json (source = "triage")
  - one "_MARKET_" row per state date (source = "regime") — median universe
    forward return, for grading whether regime tiers coincide with drawdowns

and computes forward returns at +1/+3/+5/+20 trading days on two bases:
  ret_cN_pct — decision-day close -> close at D+N   (signal quality)
  ret_oN_pct — D+1 open           -> close at D+N   (realizable entry; the
               champion-strategies backtest showed D+1-open is where edge bleeds)

Horizons that haven't elapsed yet stay NaN and fill in on later runs.
The output is rebuilt from scratch every run (idempotent, a few hundred rows):
  output/grader/forward_returns.parquet

Run standalone for a summary table:
    python src/grade_decisions.py
"""

import glob
import json
import os

import numpy as np
import pandas as pd

import mm_history
from storage import read_daily

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATE_DIR = os.path.join(ROOT, "output", "state")
JOURNAL_PATH = os.path.join(ROOT, "output", "brief", "journal.jsonl")
TRIAGE_PATH = os.path.join(ROOT, "data", "processed", "triage_verdicts.json")
OUT_PATH = os.path.join(ROOT, "output", "grader", "forward_returns.parquet")

HORIZONS = [1, 3, 5, 20]
MARKET_SYMBOL = "_MARKET_"

FEATURE_COLS = ["close", "rs_rank", "adr_pct", "ti65"]


def _collect_state_rows():
    rows = []
    for path in sorted(glob.glob(os.path.join(STATE_DIR, "????-??-??.json"))):
        state = json.load(open(path))
        date = state["meta"]["data_date"]
        regime = state.get("regime", {})
        tier = regime.get("tier")
        score = regime.get("score")

        rows.append({"date": date, "source": "regime", "scan": None,
                     "symbol": MARKET_SYMBOL, "regime_tier": tier,
                     "regime_score": score})

        for scan_name, scan in state.get("scans", {}).items():
            for cand in scan.get("candidates", []):
                row = {"date": date, "source": "scan", "scan": scan_name,
                       "symbol": cand.get("symbol"), "regime_tier": tier,
                       "regime_score": score}
                for col in FEATURE_COLS:
                    row[col] = cand.get(col)
                rows.append(row)

        # S7 paper signals (short setups; grade on the same forward windows —
        # a SHORT's edge shows as NEGATIVE forward returns)
        incub = state.get("incubation", {}).get("strategies", {})
        for strat_name, strat in incub.items():
            for cand in strat.get("candidates", []):
                rows.append({"date": date, "source": "incubation",
                             "scan": strat_name, "symbol": cand.get("symbol"),
                             "note": strat.get("mechanics", {}).get("side"),
                             "stop": cand.get("stop_ref"),
                             "regime_tier": tier, "regime_score": score})
    return rows


def _collect_journal_rows():
    rows = []
    if not os.path.exists(JOURNAL_PATH):
        return rows
    for line in open(JOURNAL_PATH):
        line = line.strip()
        if not line:
            continue
        entry = json.loads(line)
        date = entry.get("date")
        tier = entry.get("regime_tier")
        for reco in entry.get("recommendations", []):
            rows.append({"date": date, "source": "brief_reco",
                         "scan": reco.get("scan"), "symbol": reco.get("symbol"),
                         "note": reco.get("verdict"), "entry": reco.get("entry"),
                         "stop": reco.get("stop"), "regime_tier": tier})
        for passed in entry.get("passed_over", []):
            rows.append({"date": date, "source": "brief_passed",
                         "symbol": passed.get("symbol"),
                         "note": passed.get("reason"), "regime_tier": tier})
        # names the plan contract's hard gates rejected (src/plan_contract.py);
        # graded so the FalseBlock rate below can catch an over-tight gate
        for rej in entry.get("rejected", []):
            rows.append({"date": date, "source": "brief_rejected",
                         "scan": rej.get("scan"), "symbol": rej.get("symbol"),
                         "note": rej.get("reject_reason"), "entry": rej.get("entry"),
                         "stop": rej.get("stop"), "regime_tier": tier})
        for item in entry.get("watchlist", []):
            # Some days log plain symbols, some log full candidate dicts.
            if isinstance(item, str):
                item = {"symbol": item}
            rows.append({"date": date, "source": "brief_watchlist",
                         "scan": item.get("scan"), "symbol": item.get("symbol"),
                         "note": item.get("verdict"), "regime_tier": tier})
    return rows


def _collect_triage_rows():
    rows = []
    if not os.path.exists(TRIAGE_PATH):
        return rows
    verdicts = json.load(open(TRIAGE_PATH))
    for key, symbols in verdicts.items():
        scan, date = key.rsplit("_", 1)
        for symbol, verdict in symbols.items():
            rows.append({"date": date, "source": "triage", "scan": scan,
                         "symbol": symbol, "note": verdict})
    return rows


def _clean_daily(df):
    # 405 old parquets carry stray intraday rows (see ROADMAP washout study) —
    # keep only midnight bars, one per day.
    df = df[df["date"].dt.time == pd.Timestamp("00:00").time()]
    df = df.drop_duplicates(subset="date", keep="last")
    return df


def _load_opens(symbols):
    opens = {}
    for symbol in symbols:
        df = read_daily(symbol, columns=["date", "open"])
        if df.empty:
            continue
        df = _clean_daily(df)
        opens[symbol] = df.set_index(df["date"].dt.tz_localize(None).dt.normalize())["open"]
    return opens


def _add_forward_returns(df):
    # Full-history close matrix, NOT the 252-row-capped close_matrix.parquet:
    # this file is rebuilt from scratch every run, so a capped matrix would
    # silently erase every grade whose decision date scrolled off the cap.
    cm, _ = mm_history._full_matrices()
    dates = cm.index.tz_localize(None).normalize()
    pos_by_date = {d: i for i, d in enumerate(dates)}
    closes = cm.to_numpy()
    col_by_symbol = {s: i for i, s in enumerate(cm.columns)}

    stock_symbols = sorted(set(df["symbol"]) - {MARKET_SYMBOL})
    opens = _load_opens(stock_symbols)

    for n in HORIZONS:
        df[f"ret_c{n}_pct"] = np.nan
        df[f"ret_o{n}_pct"] = np.nan

    for i, row in df.iterrows():
        p = pos_by_date.get(pd.Timestamp(row["date"]))
        if p is None:
            continue
        if row["symbol"] == MARKET_SYMBOL:
            base = closes[p]
            for n in HORIZONS:
                if p + n < len(dates):
                    with np.errstate(invalid="ignore", divide="ignore"):
                        rets = closes[p + n] / base - 1.0
                    df.at[i, f"ret_c{n}_pct"] = round(float(np.nanmedian(rets)) * 100, 2)
            continue

        c = col_by_symbol.get(row["symbol"])
        if c is None:
            continue
        base_close = closes[p, c]
        open_series = opens.get(row["symbol"])
        base_open = None
        if open_series is not None and p + 1 < len(dates):
            base_open = open_series.get(dates[p + 1])
        for n in HORIZONS:
            if p + n >= len(dates):
                continue
            exit_close = closes[p + n, c]
            if np.isfinite(base_close) and np.isfinite(exit_close):
                df.at[i, f"ret_c{n}_pct"] = round((exit_close / base_close - 1.0) * 100, 2)
            if base_open and np.isfinite(exit_close):
                df.at[i, f"ret_o{n}_pct"] = round((exit_close / base_open - 1.0) * 100, 2)
    return df


def _print_summary(df):
    graded = df[df["symbol"] != MARKET_SYMBOL]
    print(f"\n{len(df)} rows ({len(graded)} candidates) across "
          f"{df['date'].nunique()} dates -> {os.path.relpath(OUT_PATH, ROOT)}")
    for (source, scan), grp in graded.groupby(["source", "scan"], dropna=False):
        label = source if pd.isna(scan) else f"{source}/{scan}"
        parts = []
        for n in HORIZONS:
            vals = grp[f"ret_c{n}_pct"].dropna()
            if len(vals):
                parts.append(f"+{n}d n={len(vals)} med={vals.median():+.2f}% "
                             f"win={100 * (vals > 0).mean():.0f}%")
        print(f"  {label:32s} n={len(grp):3d}  " + ("  ".join(parts) or "(no horizon elapsed yet)"))
    # FalseBlock (SAE, arXiv:2603.10092): share of gate-rejected names that
    # would have paid. A gate that blocks winners as often as losers is noise.
    rejected = graded[graded["source"] == "brief_rejected"]
    for n in (5, 20):
        vals = rejected[f"ret_o{n}_pct"].dropna()
        if len(vals):
            print(f"  FalseBlock +{n}d: {100 * (vals > 0).mean():.0f}% of {len(vals)} "
                  f"rejected names gained (med {vals.median():+.2f}%)")


def run():
    rows = _collect_state_rows() + _collect_journal_rows() + _collect_triage_rows()
    if not rows:
        print("No decisions recorded yet — nothing to grade.")
        return
    df = pd.DataFrame(rows)
    df = _add_forward_returns(df)
    os.makedirs(os.path.dirname(OUT_PATH), exist_ok=True)
    df.to_parquet(OUT_PATH, index=False)
    _print_summary(df)


if __name__ == "__main__":
    run()
