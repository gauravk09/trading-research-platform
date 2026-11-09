"""
precompute.py — Pre-compute summary table and close matrix after daily data collection

Saves to data/processed/:
  universe_summary.parquet  — one row per stock with returns, ADR, RS rank
  close_matrix.parquet      — wide DataFrame: date × symbol (last 252 days of closes)
  mm_history.parquet        — full-history Market Monitor for the
                              dashboard's 10-year comparison view (see mm_history.py)

The dashboard reads these two files instead of looping over 2132 parquet files.
Startup time: ~30s → under 1s.

Run automatically at the end of collect_data.py, or manually:
    PYTHONPATH=src python -m preprocessing.precompute
"""

import os

from data_collection.paths import ROOT_DIR

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
from data_collection.storage import read_daily, list_stored_symbols
from indicators.returns import month_return, n_day_return
from indicators.volatility import adr
from indicators.volume import avg_turnover_cr, volume_ratio
from indicators.relative_strength import composite_rs_rank
from indicators.trend_stage import (base_count, trend_age, ADR_WINDOW,
                                    BURST_ADR_MULT, BURST_FLOOR_PCT,
                                    BURST_CAP_PCT, LEGACY_PCT)
from data_collection.nse.fo import get_fo_symbols, get_fo_with_lotsize
import preprocessing.market_rhythm as market_rhythm
import preprocessing.mm_history as mm_history

PROCESSED_DIR = os.path.join(ROOT_DIR, "data", "processed")
SUMMARY_PATH  = os.path.join(PROCESSED_DIR, "universe_summary.parquet")
CLOSE_MATRIX_PATH = os.path.join(PROCESSED_DIR, "close_matrix.parquet")
VOLUME_MATRIX_PATH = os.path.join(PROCESSED_DIR, "volume_matrix.parquet")
HIGH_MATRIX_PATH = os.path.join(PROCESSED_DIR, "high_matrix.parquet")
LOW_MATRIX_PATH = os.path.join(PROCESSED_DIR, "low_matrix.parquet")
COMPANY_MASTER_PATH = os.path.join(PROCESSED_DIR, "company_master.parquet")
os.makedirs(PROCESSED_DIR, exist_ok=True)

# How many days of history to keep in the matrices. RS rank needs 126. The
# Ryan rule in incubation.py needs 252 (high window) + 1 (shift) + 35 (base
# age looks back over prior new highs) + 10 (dedup) = 298 rows before the
# LAST bar is computed the way the backtest computed it; at 252 exactly the
# rule was silently never true (incubation.MIN_MATRIX_ROWS).
CLOSE_MATRIX_DAYS = 330


MAX_CONSOL_WINDOW = 30  # cap how far back we look for a "quiet base" — Bonde's bases run 5-17 days


def _consolidation_stats(close, high, low, volume, lookback_cap=MAX_CONSOL_WINDOW):
    """How long/tight/quiet was the base before today's (possible breakout) bar?

    consol_days:      bars since the last day (before today) whose close-to-close
                       move was outsized *for this stock* — >= 1x its prior-50d ADR,
                       clipped to 2.5%..8% (same thresholds as base counting in
                       indicators/trend_stage.py). A fixed 4% reset was volatility-
                       biased (corr with ADR -0.6): calm large caps read as
                       consolidating forever, 6%-ADR stocks never accumulated a base.
                       The window is 50d, not 20d: a base IS the trailing 20 days,
                       so ADR20 sagged ~13% during bases and cut them short.
    consol_range_pct: that base's high-low range as % of today's close (tightness).
    consol_vol_ratio: base's average volume / 20-day average volume (<1 = drying up,
                       the "buyer/seller in equilibrium" signature Bonde looks for).
    burst_thr_pct:    today's outsized-move threshold — the scan-side trigger, so
                       the burst that ends a base and the quiet that defines it
                       always share one definition.
    """
    if len(close) < 3:
        return 0, float("nan"), float("nan"), LEGACY_PCT

    adr_prior = ((high / low).rolling(ADR_WINDOW).mean() - 1).shift(1) * 100
    thr = (BURST_ADR_MULT * adr_prior).clip(BURST_FLOOR_PCT, BURST_CAP_PCT)
    thr = thr.fillna(LEGACY_PCT)
    pct_chg = close.pct_change().iloc[:-1] * 100  # excludes today (the candidate breakout bar)
    big_move = pct_chg.abs() >= thr.iloc[:-1]
    consol_days = 0
    for flag in reversed(big_move.tolist()):
        if flag:
            break
        consol_days += 1
    consol_days = min(consol_days, lookback_cap)

    window = max(consol_days, 1)
    base_high = high.iloc[-(window + 1):-1]
    base_low  = low.iloc[-(window + 1):-1]
    base_vol  = volume.iloc[-(window + 1):-1]
    last_close = float(close.iloc[-1])

    consol_range_pct = ((base_high.max() - base_low.min()) / last_close * 100
                        if last_close > 0 and len(base_high) else float("nan"))
    vol20 = float(volume.iloc[-20:].mean())
    consol_vol_ratio = float(base_vol.mean()) / vol20 if vol20 > 0 and len(base_vol) else float("nan")

    return consol_days, consol_range_pct, consol_vol_ratio, float(thr.iloc[-1])


def _trend_quality_raw(close, n):
    """Clenow's momentum quality: annualized log-regression slope x R^2 over n bars.

    Rewards steady, linear risers (Bonde: "stock should have linear and orderly
    move ... avoid drunken man walk"); punishes churn (low R^2) and downtrends
    (negative slope). Ranked cross-sectionally into trend_quality as the MIN of
    the 60d and 126d ranks — each window alone has a blind spot the other
    covers (found on user's visual checks, 2026-07-11):
      60d alone:  a 2-month bounce inside a downtrend scores as linear
                  (INDOAMIN raw +425 at 60d, 0 at 6mo, down over the year);
      126d alone: a trend that broke 2 months ago still scores on its old rise
                  (AXISCADES +64% then -20%: raw +96, rank 92 at 6mo alone).
    min(ranks) = "linear over the longer term AND still linear now". Both
    windows under-score young trends and flat bases by construction — which is
    why this is a sort/display rank, not a gate.
    """
    if len(close) < n:
        return None
    c = np.log(close.iloc[-n:].values)
    if not np.isfinite(c).all():
        return None
    t = np.arange(n)
    slope = np.polyfit(t, c, 1)[0]
    r = np.corrcoef(t, c)[0, 1]
    annualized_pct = (np.exp(slope * 252) - 1) * 100
    return annualized_pct * r * r


def build_universe_summary(symbols: list) -> pd.DataFrame:
    """
    Read the last ~130 rows of each stock's parquet file and compute
    all metrics needed by the dashboard in one pass.
    """
    rows = []
    total = len(symbols)

    for i, symbol in enumerate(symbols, start=1):
        if i % 300 == 0:
            print(f"  {i}/{total}...")

        # Only read the last 130 rows — enough for all indicators
        df = read_daily(symbol)
        if df.empty or len(df) < 30:
            continue

        # 1Y return needs 253 rows — take it from the full history before the
        # tail(252) trim so 52w-high/low windows keep their exact meaning
        r12mo = month_return(df["close"].reset_index(drop=True), 12)

        df = df.tail(252).reset_index(drop=True)
        close  = df["close"]
        high   = df["high"]
        low    = df["low"]
        volume = df["volume"]
        last   = df.iloc[-1]
        prev   = df.iloc[-2]

        last_close  = float(last["close"])
        prev_close  = float(prev["close"])
        day_range   = float(last["high"]) - float(last["low"])
        hi_52w      = float(high.max())
        lo_52w      = float(low.min())

        avg7  = float(close.iloc[-7:].mean())
        avg65 = float(close.iloc[-65:].mean()) if len(close) >= 65 else float("nan")
        ti65  = avg7 / avg65 if avg65 == avg65 and avg65 > 0 else float("nan")

        # consecutive up-closes ending today
        up_streak = 0
        for flag in reversed((close.diff() > 0).tolist()):
            if flag:
                up_streak += 1
            else:
                break

        # consecutive down-closes ending YESTERDAY — the "selling cascade" length
        # for Bonde's reversal-bullish setup (today may be the reversal bar, so
        # today is excluded from the streak)
        down_streak = 0
        for flag in reversed((close.diff() < 0).iloc[:-1].tolist()):
            if flag:
                down_streak += 1
            else:
                break

        # Anticipation (Stockbee): tight, quiet consolidation after a move
        rng        = high - low
        last_range = float(last["high"]) - float(last["low"])
        range_5d   = float(high.iloc[-5:].max()) - float(low.iloc[-5:].min())
        nr7        = bool(last_range <= rng.iloc[-7:-1].min()) if len(rng) >= 7 else False
        v5, v20    = float(volume.iloc[-5:].mean()), float(volume.iloc[-20:].mean())

        inside = (df["high"] <= df["high"].shift(1)) & (df["low"] >= df["low"].shift(1))
        inside_days = 0
        for flag in reversed(inside.tolist()):
            if flag:
                inside_days += 1
            else:
                break

        # Bonde swing-exhaustion short: 3 green ascending-close days, then today down
        swing_exhaustion = False
        if len(df) >= 4:
            o = df["open"]
            swing_exhaustion = bool(
                close.iloc[-1] < close.iloc[-2] and close.iloc[-2] > close.iloc[-3]
                and close.iloc[-3] > close.iloc[-4] and close.iloc[-2] > o.iloc[-2]
                and close.iloc[-3] > o.iloc[-3] and close.iloc[-4] > o.iloc[-4]
            )

        # Bonde weak-structure short (TraderLion 2026): "sells off three days in
        # a row, has two or three days of pause, then starts selling off" —
        # today is the resumption day. Pause = |c2c| < 1.5%; the three cascade
        # days must each close lower.
        weak_structure = False
        pc_all = close.pct_change() * 100
        if len(df) >= 8 and pc_all.iloc[-1] < 0:
            i, pause = len(pc_all) - 2, 0
            while pause < 3 and abs(pc_all.iloc[i]) < 1.5:
                i -= 1
                pause += 1
            if 2 <= pause <= 3 and i >= 2:
                weak_structure = all(pc_all.iloc[i - k] < 0 for k in range(3))

        # Bonde "quality setup": how long/tight/quiet was the base before today?
        consol_days, consol_range_pct, consol_vol_ratio, burst_thr = _consolidation_stats(
            close, high, low, volume)

        # Bonde: "day prior to range expansion day will be narrow range day or
        # negative day" — yesterday's range under 0.75x the 20 days before it,
        # or yesterday closed red. True when too little history (pass-through).
        rng_all = high - low
        prior_day_quiet = True
        if len(df) >= 23:
            prior_day_quiet = bool(
                rng_all.iloc[-2] < 0.75 * rng_all.iloc[-22:-2].mean()
                or close.iloc[-2] < close.iloc[-3])

        # Trend maturity, both lenses: Bonde's Young TI65 age + Minervini base count.
        age = trend_age(close)
        bases = base_count(close, high, low)

        rows.append({
            "symbol":          symbol,
            "last_date":       str(last["date"].date()),
            "close":           round(last_close, 2),
            "open":            round(float(last["open"]), 2),
            "high":            round(float(last["high"]), 2),
            "low":             round(float(last["low"]), 2),
            "volume":          int(last["volume"]),
            "prev_volume":     int(prev["volume"]),
            "chg_pct":         round((last_close - prev_close) / prev_close * 100, 2),
            "gap_pct":         round((float(last["open"]) - prev_close) / prev_close * 100, 2),
            # Largest single-day close-to-close move over the last 7 sessions —
            # lets a scan catch 4% movers that fired earlier in the week, not
            # just today. Ranking/threshold both read off these one value.
            "max_up_7d":       round(float(pc_all.iloc[-7:].max()), 2),
            "max_down_7d":     round(float(pc_all.iloc[-7:].min()), 2),
            "r1w_pct":         round(n_day_return(close, 5), 2),
            "r1mo_pct":        round(month_return(close, 1), 2),
            "r3mo_pct":        round(month_return(close, 3), 2),
            "r6mo_pct":        round(month_return(close, 6), 2),
            "r12mo_pct":       round(r12mo, 2),
            "adr_pct":         round(adr(high, low, 20), 2),
            "avg_turnover_cr": round(avg_turnover_cr(close, volume, 20), 1),
            "avg_vol_7d":      int(volume.iloc[-8:-1].mean()) if len(volume) >= 8 else int(volume.mean()),
            "volume_ratio":    round(volume_ratio(volume, 20), 2),
            "range_pos":       round((last_close - float(last["low"])) / day_range, 2) if day_range > 0 else 1.0,
            "ti65":            round(ti65, 3) if ti65 == ti65 else None,
            "up_streak":       up_streak,
            "down_streak":     down_streak,
            "weak_structure":  weak_structure,
            "range_pct_5d":    round(range_5d / last_close * 100, 2) if last_close > 0 else None,
            "nr7":             nr7,
            "inside_days":     inside_days,
            "vol_contraction": round(v5 / v20, 2) if v20 > 0 else None,
            "swing_exhaustion": swing_exhaustion,
            "pct_from_52w_high": round((last_close - hi_52w) / hi_52w * 100, 1) if hi_52w > 0 else None,
            "pct_from_52w_low":  round((last_close - lo_52w) / lo_52w * 100, 1) if lo_52w > 0 else None,
            "consol_days":       consol_days,
            "consol_range_pct":  round(consol_range_pct, 2) if consol_range_pct == consol_range_pct else None,
            "consol_vol_ratio":  round(consol_vol_ratio, 2) if consol_vol_ratio == consol_vol_ratio else None,
            "burst_thr_pct":     round(burst_thr, 2),
            "prior_day_quiet":   prior_day_quiet,
            "_tq_60":            _trend_quality_raw(close, 60),
            "_tq_126":           _trend_quality_raw(close, 126),
            "trend_age_d":       age,
            "base_count":        bases,
        })

    out = pd.DataFrame(rows)
    # Clenow slope x R^2 ranked cross-sectionally like RS; final score is the
    # weaker of the two horizons — linear long term AND still linear now
    # (see _trend_quality_raw for the failure mode each window covers).
    r60  = out["_tq_60"].rank(pct=True) * 100
    r126 = out["_tq_126"].rank(pct=True) * 100
    out["trend_quality"] = pd.concat([r60, r126], axis=1).min(axis=1).round(1)
    return out.drop(columns=["_tq_60", "_tq_126"])


def build_matrices(symbols: list) -> dict:
    """
    Wide DataFrames (index=date, columns=symbol) for close, volume, high and
    low, last CLOSE_MATRIX_DAYS rows per stock, read in a single pass.
    Closes drive RS ranks and breadth; volumes let the Market Monitor apply
    Bonde's v>v1 condition to 4% mover counts; highs/lows let the incubation
    signals (Minervini trend template + VCP) run on the same nightly data.
    """
    cols = ["close", "volume", "high", "low"]
    frames = {c: {} for c in cols}
    for symbol in symbols:
        df = read_daily(symbol, columns=["date"] + cols)
        if df.empty:
            continue
        df = df.tail(CLOSE_MATRIX_DAYS).set_index("date")
        for c in cols:
            frames[c][symbol] = df[c]

    return {c: pd.DataFrame(series).sort_index() for c, series in frames.items()}


def add_company_metadata(summary: pd.DataFrame) -> pd.DataFrame:
    """
    Join name/sector/industry from company_master.parquet and compute market cap
    as shares outstanding × today's close (shares change rarely; price daily).
    Cap segments follow SEBI's rank-based definition:
    top 100 by mcap = large, 101-250 = mid, rest = small.
    """
    if not os.path.exists(COMPANY_MASTER_PATH):
        print("  company_master.parquet not found — skipping company metadata")
        return summary

    master = pd.read_parquet(
        COMPANY_MASTER_PATH,
        columns=["symbol", "name", "sector", "industry", "shares_out"])
    summary = summary.merge(master, on="symbol", how="left")
    summary["mcap_cr"] = (summary["shares_out"] * summary["close"] / 1e7).round(1)

    mcap_rank = summary["mcap_cr"].rank(ascending=False)
    summary["cap_segment"] = np.where(mcap_rank <= 100, "large",
                             np.where(mcap_rank <= 250, "mid", "small"))
    summary.loc[summary["mcap_cr"].isna(), "cap_segment"] = None
    return summary.drop(columns=["shares_out"])


def run():
    print("Pre-computing summary table and close matrix...")
    symbols = list_stored_symbols()
    print(f"  Symbols: {len(symbols)}")

    print("\n[1/4] Building close + volume + high + low matrices...")
    matrices = build_matrices(symbols)
    close_matrix = matrices["close"]
    for name, path in [("close", CLOSE_MATRIX_PATH), ("volume", VOLUME_MATRIX_PATH),
                       ("high", HIGH_MATRIX_PATH), ("low", LOW_MATRIX_PATH)]:
        matrices[name].to_parquet(path, compression="snappy")
        print(f"  Saved {name} matrix {matrices[name].shape} → {path}")

    print("\n[2/4] Computing RS ranks...")
    rs_ranks = composite_rs_rank(close_matrix)

    print("\n[3/4] Building universe summary...")
    fo_symbols  = get_fo_symbols()       # current month F&O list
    fo_lotsizes = get_fo_with_lotsize()  # symbol → lot size

    summary = build_universe_summary(symbols)
    summary["rs_rank"] = summary["symbol"].map(rs_ranks).round(1)
    summary["is_fo"]   = summary["symbol"].isin(fo_symbols)
    summary["lot_size"] = summary["symbol"].map(fo_lotsizes).fillna(0).astype(int)

    # Market cap from the company master (shares_out refreshed nightly by
    # company_master.py) — in the summary so scans and both dashboards see it.
    master_path = os.path.join(PROCESSED_DIR, "company_master.parquet")
    if os.path.exists(master_path):
        shares = (pd.read_parquet(master_path, columns=["symbol", "shares_out"])
                  .set_index("symbol")["shares_out"])
        summary["mcap_cr"] = (summary["symbol"].map(shares)
                              * summary["close"] / 1e7).round(0)
    summary = summary.sort_values("r3mo_pct", ascending=False).reset_index(drop=True)
    summary.insert(0, "rank", range(1, len(summary) + 1))

    summary.to_parquet(SUMMARY_PATH, compression="snappy", index=False)
    print(f"  Saved universe summary {summary.shape} → {SUMMARY_PATH}")

    print("\n[4/4] Building full-history Market Monitor + rhythm...")
    cm, vm = mm_history._full_matrices()
    hist = mm_history.build_history(matrices=(cm, vm))
    print(f"  Saved mm_history {hist.shape} → {mm_history.HISTORY_PATH}")
    rhythm = market_rhythm.build_history(cm, vm)
    print(f"  Saved market_rhythm {rhythm.shape} → {market_rhythm.RHYTHM_PATH}")
    print("\nPre-compute complete.")


if __name__ == "__main__":
    run()
