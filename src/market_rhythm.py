"""market_rhythm.py — "what is the market paying right now", for the dashboard's
Market Rhythm view.

Two daily series, both computed point-in-time from the full close matrix:

1. Leader follow-through — the RS>90 basket FROZEN 5 sessions ago (composite RS
   rank as of T-5, so membership never uses the returns being measured), median
   5-day return vs the eligible-universe median. A negative spread while the
   tape holds up = leaders being distributed.

2. Winner attribution — every stock that moved ≥10% in the last 5 sessions,
   classified by its state at T-5 (the day the move started, not after it):
     Bottom bounce      ≥25% below its 252-day closing high AND below 200-DMA
     Pullback reversal  above 200-DMA AND 3+ consecutive down closes into T-5
     Breakout           within 15% of the 252-day high AND above 50-DMA
     Other              everything else (honest bucket — not force-fit)
   Priority is that order: bounce, then reversal, then breakout. Counts are
   stored raw; the dashboard smooths shares over a rolling window.

Same caveats as mm_history: survivorship (today's symbols only) and warm-up
(252-day high + 126-day RS need ~1 year, so 2015 is unreliable).

Rebuild standalone (also prints a validation report vs mm_history):
    python src/market_rhythm.py
"""

import os

import pandas as pd

import mm_history
from backtest.pointintime import composite_rs_matrix

RHYTHM_PATH = os.path.join(mm_history._PROCESSED, "market_rhythm.parquet")

WARMUP_ROWS = 260        # 252-day high + 5-day shift need ~a year of bars
WINNER_5D_PCT = 10.0     # a "winner" moved at least this % in 5 sessions
LEADER_RS = 90.0
MIN_PRICE = 30.0
MIN_TURNOVER_CR = 1.0
MIN_BARS = 130

WIN_COLS = ["w_breakout", "w_reversal", "w_bounce", "w_other"]


def _down_streak(cm: pd.DataFrame) -> pd.DataFrame:
    """Consecutive down closes ending at each bar (vectorized run-length:
    cumulative downs minus the cumulative count frozen at the last up bar)."""
    down = cm.diff() < 0
    cum = down.cumsum()
    return cum - cum.where(~down).ffill().fillna(0)


def build_history(cm: pd.DataFrame = None, vm: pd.DataFrame = None,
                  write: bool = True) -> pd.DataFrame:
    """Daily leader-spread + winner-attribution history.
    Pass the mm_history matrices to reuse them; loads them itself when None."""
    if cm is None:
        cm, vm = mm_history._full_matrices()

    r5 = cm / cm.shift(5) - 1                       # move over the last 5 bars
    rs = composite_rs_matrix(cm)

    # Everything describing "state at the start of the move" is shifted 5 bars
    # so no feature can see the move it is classifying (no look-ahead, and RS
    # membership can't be selected on the returns being measured).
    turnover_cr = (cm * vm / 1e7).rolling(20).mean()
    eligible = ((cm >= MIN_PRICE)
                & (turnover_cr >= MIN_TURNOVER_CR)
                & (cm.notna().cumsum() >= MIN_BARS)).shift(5, fill_value=False)

    hi252 = cm.rolling(252, min_periods=126).max()
    off_high = (1 - cm / hi252).shift(5)
    above_ma50 = (cm > cm.rolling(50).mean()).shift(5, fill_value=False)
    above_ma200 = (cm > cm.rolling(200).mean()).shift(5, fill_value=False)
    streak = _down_streak(cm).shift(5)

    leaders = (rs.shift(5) > LEADER_RS) & eligible
    out = pd.DataFrame(index=cm.index)
    out["leader_5d"] = (r5.where(leaders).median(axis=1) * 100).round(2)
    out["univ_5d"] = (r5.where(eligible).median(axis=1) * 100).round(2)
    out["leader_spread"] = (out["leader_5d"] - out["univ_5d"]).round(2)
    out["n_leaders"] = leaders.sum(axis=1)

    winners = eligible & (r5 >= WINNER_5D_PCT / 100)
    bounce = winners & (off_high >= 0.25) & ~above_ma200
    reversal = winners & ~bounce & above_ma200 & (streak >= 3)
    breakout = winners & ~bounce & ~reversal & (off_high <= 0.15) & above_ma50
    out["n_winners"] = winners.sum(axis=1)
    out["w_bounce"] = bounce.sum(axis=1)
    out["w_reversal"] = reversal.sum(axis=1)
    out["w_breakout"] = breakout.sum(axis=1)
    out["w_other"] = out["n_winners"] - out[["w_bounce", "w_reversal",
                                             "w_breakout"]].sum(axis=1)
    if write:
        os.makedirs(mm_history._PROCESSED, exist_ok=True)
        out.to_parquet(RHYTHM_PATH, compression="snappy")
    return out


def rolling_shares(hist: pd.DataFrame, window: int = 21) -> pd.DataFrame:
    """Attribution shares (%) over a rolling window of summed counts — the
    smoothing the dashboard plots, so single thin weeks can't whipsaw it."""
    sums = hist[WIN_COLS + ["n_winners"]].rolling(window).sum()
    shares = sums[WIN_COLS].div(sums["n_winners"], axis=0) * 100
    return shares.round(1)


def _validate(hist: pd.DataFrame) -> None:
    """Does the rhythm carry information? Checked against mm_history's forward
    returns (run `python src/mm_history.py` first)."""
    mm = pd.read_parquet(mm_history.HISTORY_PATH)
    df = rolling_shares(hist).join(hist[["leader_spread"]]) \
        .join(mm[["fwd_20d"]]).iloc[WARMUP_ROWS:].dropna()

    print("\n[Breakout share terciles] → median fwd-20d universe return:")
    df["brk_bucket"] = pd.qcut(df["w_breakout"], 3, labels=["low", "mid", "high"])
    print(df.groupby("brk_bucket", observed=True)["fwd_20d"].median().round(2).to_string())

    print("\n[Leader spread terciles] → median fwd-20d universe return:")
    df["spr_bucket"] = pd.qcut(df["leader_spread"], 3, labels=["lagging", "inline", "leading"])
    print(df.groupby("spr_bucket", observed=True)["fwd_20d"].median().round(2).to_string())


if __name__ == "__main__":
    hist = build_history()
    print(f"market_rhythm {hist.shape}  "
          f"{hist.index.min().date()} → {hist.index.max().date()}")
    print(f"  written: {os.path.abspath(RHYTHM_PATH)}")
    _validate(hist)
