"""
ep_volume_spike.py — Event study of Episodic-Pivot-style volume spikes

Replicates the structure of Stockbee's "EP9M" study on NSE data: find every
day a stock traded massive volume with a strong up move, then measure forward
returns per event (not a portfolio simulation — every event is independent).

India adaptation: the US rule "9 million shares" is meaningless here (share
counts vary with face value and float), so the trigger is RELATIVE volume
plus an absolute turnover floor so signals are actually tradeable.

Signal (all inputs known at Day 0 close — averages use shift(1)):
    volume   >= vol_mult × prior 50-day average volume
    turnover >= min_turnover_cr (Day 0 close × volume)
    close    >= min_gain_pct above previous close
    ADR%     >= min_adr over the PRIOR 20 days
    cooldown bars since this symbol's last signal (one episode = one event)

Measurement:
    Entry = Day 1 open (daily-bar approximation of the ORH entry — optimistic,
    same caveat as the main backtest). Unstopped returns at D+5/20/60 closes.
    Stopped mode: stop = Day 0 low, walked forward daily; a gap through the
    stop exits at the open (real slippage, not the stop price).

Usage:
    python src/backtest/studies/ep_volume_spike.py
    python src/backtest/studies/ep_volume_spike.py --vol-mult 5 --min-gain 8
    python src/backtest/studies/ep_volume_spike.py --symbols RELIANCE TATAMOTORS

Outputs output/studies/ep_volume_spike_<params>.csv (one row per event)
and a printed summary report.
"""

import os
import sys
import argparse
import numpy as np
import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from storage import read_daily, list_stored_symbols

OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "..", "output", "studies")

MIN_BARS = 60          # need 50d volume average + a little slack before a signal
MAX_HORIZON = 60       # longest forward window tracked (trading days)
FAKE_SPIKE_PCT = 35.0  # day moves beyond this are unrepaired splits/bad data (see integrity.py)


def find_events(df: pd.DataFrame, vol_mult: float, min_turnover_cr: float,
                min_gain_pct: float, min_adr: float, cooldown: int) -> list:
    """Return the row positions of every signal day in one symbol's history."""
    close, high, low, volume = df["close"], df["high"], df["low"], df["volume"]

    avg_vol_50 = volume.rolling(50).mean().shift(1)
    day_gain = close.pct_change() * 100
    turnover_cr = close * volume / 1e7
    adr_prior_20 = ((high - low) / low * 100).rolling(20).mean().shift(1)

    mask = (
        (volume >= vol_mult * avg_vol_50)
        & (turnover_cr >= min_turnover_cr)
        & (day_gain >= min_gain_pct)
        & (day_gain <= FAKE_SPIKE_PCT)
        & (adr_prior_20 >= min_adr)
    )
    mask.iloc[:MIN_BARS] = False

    events = []
    last = -10**9
    for pos in np.flatnonzero(mask.values):
        if pos - last >= cooldown:
            events.append(pos)
            last = pos
    return events


def measure_event(df: pd.DataFrame, pos: int, hv180_ratio: pd.Series) -> dict:
    """Forward returns for one event. Day 0 = df row `pos`, entry = Day 1 open."""
    if pos + 1 >= len(df):
        return None  # signal on the last stored bar — no Day 1 yet

    day0 = df.iloc[pos]
    entry = float(df["open"].iloc[pos + 1])
    stop = float(day0["low"])
    if entry <= 0 or entry <= stop:
        return None  # gapped below Day 0 low — the ORH entry never triggers

    row = {
        "symbol":       day0["symbol"],
        "date":         day0["date"].date(),
        "day0_gain_pct": round(float(df["close"].pct_change().iloc[pos]) * 100, 2),
        "vol_ratio":    round(float(day0["volume"] / df["volume"].rolling(50).mean().shift(1).iloc[pos]), 1),
        "turnover_cr":  round(float(day0["close"] * day0["volume"] / 1e7), 1),
        "adr_pct":      round(float(((df["high"] - df["low"]) / df["low"] * 100).rolling(20).mean().shift(1).iloc[pos]), 1),
        "hv180":        int((hv180_ratio.iloc[max(0, pos - 180):pos] >= 3).sum()),
        "entry":        round(entry, 2),
        "stop_pct":     round((entry - stop) / entry * 100, 2),
    }

    closes = df["close"].values
    for horizon in (5, 20, 60):
        end = pos + 1 + horizon
        row[f"ret_{horizon}d"] = (
            round((float(closes[end]) - entry) / entry * 100, 2) if end < len(df) else np.nan
        )

    # Stopped walk-forward: from Day 1 close onward, exit if any day's low
    # touches the stop (gap-down exits at that day's open), else exit at the
    # 60-day close. Day 1's own low can stop us out even though we entered
    # at its open.
    exit_ret, exit_day, stopped = np.nan, np.nan, False
    lows, opens = df["low"].values, df["open"].values
    last_pos = min(pos + 1 + MAX_HORIZON, len(df) - 1)
    for day in range(pos + 1, last_pos + 1):
        if lows[day] <= stop:
            exit_price = min(float(opens[day]), stop)
            exit_ret = (exit_price - entry) / entry * 100
            exit_day = day - pos
            stopped = True
            break
    if not stopped and last_pos == pos + 1 + MAX_HORIZON:
        exit_ret = (float(closes[last_pos]) - entry) / entry * 100
        exit_day = MAX_HORIZON

    row["stopped_ret"] = round(exit_ret, 2) if pd.notna(exit_ret) else np.nan
    row["stopped_out"] = stopped
    row["exit_day"] = exit_day
    return row


def run_study(symbols: list, start: str, end: str, vol_mult: float,
              min_turnover_cr: float, min_gain_pct: float, min_adr: float,
              cooldown: int) -> pd.DataFrame:
    rows = []
    for i, symbol in enumerate(symbols, start=1):
        if i % 500 == 0:
            print(f"  Scanning [{i}/{len(symbols)}]...")
        df = read_daily(symbol)
        if len(df) < MIN_BARS:
            continue

        positions = find_events(df, vol_mult, min_turnover_cr, min_gain_pct, min_adr, cooldown)
        if not positions:
            continue

        hv180_ratio = df["volume"] / df["volume"].rolling(50).mean().shift(1)
        for pos in positions:
            date = df["date"].iloc[pos]
            if start and date < pd.Timestamp(start, tz="Asia/Kolkata"):
                continue
            if end and date > pd.Timestamp(end, tz="Asia/Kolkata"):
                continue
            row = measure_event(df, pos, hv180_ratio)
            if row:
                rows.append(row)

    return pd.DataFrame(rows)


def _pct_table(series: pd.Series) -> str:
    q = series.dropna().quantile([0.05, 0.25, 0.50, 0.75, 0.95])
    return "  ".join(f"p{int(p * 100)}: {v:+.1f}%" for p, v in q.items())


def print_report(events: pd.DataFrame) -> None:
    print(f"\n{'=' * 64}")
    print(f"EP VOLUME SPIKE STUDY — {len(events)} events, "
          f"{events['symbol'].nunique()} symbols, "
          f"{events['date'].min()} → {events['date'].max()}")
    print(f"{'=' * 64}")

    print("\nEvents per year:")
    per_year = events.groupby(pd.to_datetime(events["date"]).dt.year).size()
    for year, n in per_year.items():
        print(f"  {year}: {n}")

    print("\nUNSTOPPED forward returns (entry = Day 1 open):")
    for horizon in (5, 20, 60):
        r = events[f"ret_{horizon}d"].dropna()
        if r.empty:
            continue
        print(f"  D+{horizon:<3} n={len(r):<5} mean {r.mean():+6.1f}%  "
              f"median {r.median():+6.1f}%  win {(r > 0).mean() * 100:.1f}%")
        print(f"        {_pct_table(r)}")

    s = events["stopped_ret"].dropna()
    stopped = events.loc[s.index, "stopped_out"]
    print(f"\nSTOPPED (stop = Day 0 low, 60-day horizon): n={len(s)}")
    print(f"  mean {s.mean():+.1f}%  median {s.median():+.1f}%  "
          f"win {(s > 0).mean() * 100:.1f}%  stop-out rate {stopped.mean() * 100:.1f}%")
    print(f"  avg loss when stopped {s[stopped].mean():+.1f}%  "
          f"avg when not stopped {s[~stopped].mean():+.1f}%")
    print(f"  {_pct_table(s)}")

    big = events["ret_20d"] >= 20
    print(f"\nBig winners (>=20% by D+20): {big.sum()} "
          f"({big.mean() * 100:.1f}% of events)")

    print("\nSlices — median D+20 return / win rate / n:")
    slices = {
        "ADR 4-6%":    events["adr_pct"] < 6,
        "ADR >=6%":    events["adr_pct"] >= 6,
        "RVOL 3-5x":   events["vol_ratio"] < 5,
        "RVOL 5-10x":  (events["vol_ratio"] >= 5) & (events["vol_ratio"] < 10),
        "RVOL >=10x":  events["vol_ratio"] >= 10,
        "HV180 <= 5":  events["hv180"] <= 5,
        "HV180 > 5":   events["hv180"] > 5,
    }
    for name, mask in slices.items():
        r = events.loc[mask, "ret_20d"].dropna()
        if len(r) < 10:
            continue
        print(f"  {name:<11} {r.median():+6.1f}%  {(r > 0).mean() * 100:5.1f}%  n={len(r)}")

    valid = events.dropna(subset=["ret_20d"])
    if len(valid) > 30:
        corr = valid["hv180"].corr(valid["ret_20d"])
        print(f"\nCorrelation hv180 vs D+20 return: r = {corr:+.4f}")

    print("\nKnown biases (read before trusting the numbers):")
    print("  - Entry at Day 1 open approximates the intraday ORH entry (optimistic)")
    print("  - No historical ASM/GSM exclusion; no brokerage/slippage/STT")
    print("  - Events dropped if Day 0 move > 35% (suspected unrepaired splits)")
    print("  - Volume is as stored — unadjusted for splits, so vol_ratio near a")
    print("    corporate action can be distorted; run integrity.py --repair first")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--start", default=None, help="YYYY-MM-DD (default: all history)")
    parser.add_argument("--end", default=None, help="YYYY-MM-DD")
    parser.add_argument("--vol-mult", type=float, default=3.0, help="Min volume / 50d avg (default 3)")
    parser.add_argument("--min-turnover", type=float, default=10.0, help="Min Day 0 turnover ₹cr (default 10)")
    parser.add_argument("--min-gain", type=float, default=5.0, help="Min Day 0 close gain %% (default 5)")
    parser.add_argument("--min-adr", type=float, default=4.0, help="Min prior-20d ADR %% (default 4)")
    parser.add_argument("--cooldown", type=int, default=20, help="Min bars between signals per symbol (default 20)")
    parser.add_argument("--symbols", nargs="+", default=None, help="Optional symbol subset")
    args = parser.parse_args()

    symbols = args.symbols or list_stored_symbols()
    print(f"Scanning {len(symbols)} symbols "
          f"(vol>={args.vol_mult}x, turnover>=₹{args.min_turnover}cr, "
          f"gain>={args.min_gain}%, ADR>={args.min_adr}%, cooldown={args.cooldown})...")

    events = run_study(symbols, args.start, args.end, args.vol_mult,
                       args.min_turnover, args.min_gain, args.min_adr, args.cooldown)
    if events.empty:
        print("No events found with these parameters.")
        return

    events = events.sort_values(["date", "symbol"]).reset_index(drop=True)
    print_report(events)

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    tag = f"v{args.vol_mult:g}_g{args.min_gain:g}_t{args.min_turnover:g}"
    out_path = os.path.join(OUTPUT_DIR, f"ep_volume_spike_{tag}.csv")
    events.to_csv(out_path, index=False)
    print(f"\nEvent log → {out_path}")


if __name__ == "__main__":
    main()
