"""
event_store.py — unified trigger log with standardized outcomes.

One long parquet (data/processed/events.parquet): every occurrence of every
registered trigger as (date, symbol, trigger) plus outcomes computed the SAME
way for all triggers, so setups are comparable apples-to-apples:

  ret_o5, ret_o20   D+1 open -> D+n close, %
  stop_r            entry D+1 open, stop = signal-day low capped 6% under
                    entry, gap-through fills at open, time exit D+5 close, in R
  stop_r_20         same, time exit D+20 close
  stop_r_short, stop_r_20_short   short mirrors (stop = signal high capped 6%
                    above entry); positive R = the short made money
  *_close           the SAME four rulers with entry moved to the SIGNAL-DAY
                    CLOSE instead of the D+1 open (stop_r_close,
                    stop_r_20_close, stop_r_short_close, stop_r_20_short_close).
                    Stop logic, gap-through fill and time exit are unchanged —
                    only the entry anchor moves. The D+1-open convention gives
                    away the overnight gap (bursts gap +0.55% on average, worth
                    ~+0.11R on a ~5.5% stop distance), so the close ruler is the
                    realistic same-day-entry measure.
  stop_r_trail      TRAILED / SCALE-OUT ruler (2026-08-06). Same D+1-open entry
                    and same initial stop as stop_r, but the exit is the one the
                    validated strategies actually use: sell HALF at +2R, trail
                    the rest on a ratcheting 20-day low of CLOSES, hard cap 60
                    trading days. See _stop_r_trail for the full convention.
  stop_r_trail_short  the short mirror (cover half at -2R, trail on the 20-day
                    close HIGH, ratcheting down).
  stop_r_trail_be   BREAKEVEN variant of the trail ruler (2026-08-06). Identical
                    to stop_r_trail in every respect EXCEPT that the stop is
                    moved to the entry price once the trade has touched +1R
                    intraday. Same half-off-at-+2R, same ratcheting 20-day-low
                    trail, same 60-bar cap, same gap-fill conventions.
  stop_r_trail_be_short  the short mirror (stop to entry after a -1R touch).
  ep_r              EP events only: the ep9m_redefined study's r_stop (half-range
                    stop, in R; still-open trades marked at the 250-bar cap)

CAVEAT on the *_close ruler: entering at the signal-day close assumes the
signal is computable by ~15:20 IST (the Order Pad's entry window). Triggers
built on FULL-DAY volume (`four_pct`/`burst` require volume > yesterday's
volume; `pullback` uses only price) are therefore slightly OPTIMISTIC — at
15:20 you know ~95% of the day's volume, not 100%, so a small tail of events
would not have qualified in real time. Price-only conditions and the stop
anchor itself carry no such error. Treat close-ruler expectancies as an upper
bound of roughly the same size as that tail.

The close ruler is NOT free money — it is a directional bet on the overnight
gap. The same average up-gap that pays the close-entry LONG (+0.11R on bursts)
is charged to the close-entry SHORT, and shorts of an up-day trigger carry a
tighter stop (median risk 1.4% of entry vs 6% for four_pct_down), so the gap
costs them several tenths of an R. Read stop_r_short_close on up-day triggers
with that in mind.

Triggers (v1 — the core setups the user trades):
  burst      4% burst out of a tight 5-day base (stockbee_4pct_burst rules).
             This IS the anticipation-range breakout: every event requires the
             consolidation first.
  four_pct   raw 4% up day on rising volume, no base requirement (the wide-net
             scan) — kept as the unselective contrast to `burst`.
  ep         EP9M events (ep9m_redefined study: gain>=5%, 15M+ shares —
             output/studies/ep9m_redefined_events.csv).
  bounce     washout-reversal events (3rd consecutive down close).

Triggers (v2, 2026-07-31 — long terrain for the GA):
  pullback   first touch of the rising 20DMA by a recent leader: close >
             200DMA, 20DMA rising vs 5 bars ago, stock printed a 63d high
             within the last 15 sessions, today's low touches the 20DMA
             (low <= 20DMA*1.01) but close holds >= 20DMA*0.97 (a dip,
             not a breakdown). All conditions causal at signal close.

Triggers (v3, 2026-08-06 — trigger FIDELITY):
  qm_flag    a FAITHFUL Qullamaggie flag breakout, mirroring the validated
             recipe in studies/fno_qullamaggie.py (which PASSED S5 on the
             large-cap universe) instead of the generic 4%-day. Pre-registered,
             NOT tuned: prior 3-month move (ret63) >= +30%; close within 25% of
             the 252-day high; a TIGHT FLAG measured as-of YESTERDAY (20-day
             high-low range <= 25% of price) that did not break down (close
             drift across that same 20-bar window >= -10%); and the TRIGGER
             itself — today's close above the prior 10-day HIGH on volume >=
             1.2x its 50-day average. Universe is every stock with close >= Rs
             30 (segment/liquidity filters stay at scan time, per the house
             philosophy); cooldown 20 bars per symbol. It exists to test whether
             the generic `burst`/`four_pct` bleed is a TRIGGER-fidelity problem
             rather than a setup problem.

Build/refresh:  ~/anaconda3/bin/python src/backtest/event_store.py
Load:           from backtest.event_store import load_events
"""

import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "studies"))

EVENTS_PATH = os.path.join(os.path.dirname(__file__), "..", "..",
                           "data", "processed", "events.parquet")
OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "..", "..",
                          "output", "studies")


def _positions(df: pd.DataFrame, close: pd.DataFrame) -> pd.DataFrame:
    """Map (date, symbol) rows to matrix positions; drop rows not in the cache."""
    date_pos = pd.Series(range(len(close.index)), index=close.index)
    sym_pos = pd.Series(range(len(close.columns)), index=close.columns)
    df = df.copy()
    df["date_idx"] = date_pos.reindex(df["date"]).to_numpy()
    df["sym_idx"] = sym_pos.reindex(df["symbol"]).to_numpy()
    return df.dropna(subset=["date_idx", "sym_idx"]).astype(
        {"date_idx": int, "sym_idx": int})


def _stop_r(entry, signal_low, d, s, O, L, C, n_dates, horizon):
    """Stop-based R: enter D+1 open, stop = max(signal low, entry*0.94),
    gap-through fills at open, else time-exit at `horizon` days' close. In R."""
    out = np.full(len(entry), np.nan)
    for i in range(len(entry)):
        d0, si = d[i], s[i]
        if d0 + 1 >= n_dates or np.isnan(entry[i]):
            continue
        stop = max(signal_low[i], entry[i] * 0.94)
        risk = entry[i] - stop
        if risk <= 0 or np.isnan(risk):
            continue
        for k in range(1, horizon + 1):
            if d0 + k >= n_dates or np.isnan(C[d0 + k, si]):
                break
            if L[d0 + k, si] <= stop:
                out[i] = (min(O[d0 + k, si], stop) - entry[i]) / risk
                break
            if k == horizon:
                out[i] = (C[d0 + k, si] - entry[i]) / risk
    return out


def _stop_r_short(entry, signal_high, d, s, O, H, C, n_dates, horizon):
    """Short mirror of _stop_r: enter short D+1 open, stop = min(signal high,
    entry*1.06), gap-through fills at open, else time-exit at `horizon` close.
    Positive R = the short made money (price fell). In R."""
    out = np.full(len(entry), np.nan)
    for i in range(len(entry)):
        d0, si = d[i], s[i]
        if d0 + 1 >= n_dates or np.isnan(entry[i]):
            continue
        stop = min(signal_high[i], entry[i] * 1.06)
        risk = stop - entry[i]
        if risk <= 0 or np.isnan(risk):
            continue
        for k in range(1, horizon + 1):
            if d0 + k >= n_dates or np.isnan(C[d0 + k, si]):
                break
            if H[d0 + k, si] >= stop:
                out[i] = (entry[i] - max(O[d0 + k, si], stop)) / risk
                break
            if k == horizon:
                out[i] = (entry[i] - C[d0 + k, si]) / risk
    return out


TRAIL_TARGET_R = 2.0   # scale out half here
TRAIL_WINDOW = 20      # trailing stop = rolling low/high of CLOSES
TRAIL_CAP = 60         # hard time cap, trading days
TRAIL_BE_R = 1.0       # breakeven variant: stop -> entry after this R is touched


def _stop_r_trail(entry, signal_low, d, s, O, H, L, C, RL, n_dates, be_at=None):
    """Trailed / scale-out ruler, long. Pre-registered 2026-08-06; NOT tuned.

    Why it exists: `stop_r` and `stop_r_20` exit on the CLOCK (5 or 20 days),
    which truncates the winner tail. Every validated strategy in this repo
    (ep9m_redefined's 80% scale-out, fno_qullamaggie's MA trail,
    ryan_minervini_book's native exits) instead scales out and trails, so a
    time-exit screen can systematically reject setups whose edge lives in the
    tail. This ruler is the third judge, deliberately built from those
    conventions rather than from a search over parameters.

    Mechanics (identical entry and initial stop to `stop_r`):
      entry   D+1 open
      stop    max(signal-day low, entry * 0.94); risk = entry - stop
      stop hit  L <= stop, checked FIRST each bar; gap-through fills at
                min(open, stop) — the same conservative convention as _stop_r
      partial  first bar with H >= entry + 2*risk sells HALF; a bar that opens
               beyond the target fills at that open (max(open, target)), the
               mirror of the stop's gap convention
      trail    ratcheting TRAIL_WINDOW-day low of CLOSES: level = max over the
               trade of close.rolling(20).min(); it only moves up. A close BELOW
               it exits the remainder at the NEXT open (causal: the signal is a
               close, the fill is the following bar).
      cap      TRAIL_CAP bars -> exit at that day's close
      unresolved  a trade still open when the data ends is NaN, never a
                partial mark — the same convention _stop_r uses for a truncated
                window (it costs the last ~60 trading days of events).

    `be_at` (None on this ruler, TRAIL_BE_R on stop_r_trail_be) moves the stop
    to the ENTRY price once the trade has touched entry + be_at*risk intraday.
    The move takes effect from the NEXT bar: the stop is tested first with the
    level it carried into the bar, so a bar that touches +1R and then collapses
    through the original stop is a full -1R loss, not a scratch. That is the
    conservative daily-bar reading — intraday we cannot know which came first.

    Approximations follow the daily-bar conventions documented in
    [backtest_known_biases]: one bar can both touch the target and later hit the
    stop and we resolve stop-first; the partial fill assumes a resting limit at
    the target; no intraday path is modelled. Like every other ruler here this
    is COST-BLIND — no brokerage, slippage or impact is charged, and a scale-out
    pays two round trips instead of one, so its R is optimistic by more than the
    single-exit rulers'.
    """
    out = np.full(len(entry), np.nan)
    for i in range(len(entry)):
        d0, si = d[i], s[i]
        if d0 + 1 >= n_dates or np.isnan(entry[i]):
            continue
        e = entry[i]
        stop = max(signal_low[i], e * 0.94)
        risk = e - stop
        if risk <= 0 or np.isnan(risk):
            continue
        target = e + TRAIL_TARGET_R * risk
        be_level = e + be_at * risk if be_at is not None else None
        half_r, half_done, trail = 0.0, False, -np.inf
        for k in range(1, TRAIL_CAP + 1):
            day = d0 + k
            if day >= n_dates or np.isnan(C[day, si]):
                break                                   # unresolved -> NaN
            if L[day, si] <= stop:
                fill = min(O[day, si], stop)
                out[i] = half_r + (0.5 if half_done else 1.0) * (fill - e) / risk
                break
            if not half_done and H[day, si] >= target:
                half_r = 0.5 * (max(O[day, si], target) - e) / risk
                half_done = True
            if be_level is not None and stop < e and H[day, si] >= be_level:
                stop = e
            lvl = RL[day, si]
            if lvl > trail:                              # NaN never passes
                trail = lvl
            if C[day, si] < trail:
                nxt = day + 1
                px = O[nxt, si] if nxt < n_dates and not np.isnan(O[nxt, si]) \
                    else C[day, si]
                out[i] = half_r + (0.5 if half_done else 1.0) * (px - e) / risk
                break
            if k == TRAIL_CAP:
                out[i] = half_r + (0.5 if half_done else 1.0) * (C[day, si] - e) / risk
    return out


def _stop_r_trail_short(entry, signal_high, d, s, O, H, L, C, RH, n_dates,
                        be_at=None):
    """Exact short mirror of _stop_r_trail: cover HALF at -2R (a bar that opens
    below the target fills at min(open, target)), trail the rest on a ratcheting
    TRAIL_WINDOW-day HIGH of closes that only moves DOWN, exit the next open
    after a close ABOVE it, hard cap TRAIL_CAP bars. Positive R = the short made
    money. `be_at` mirrors the long's breakeven move (stop down to entry after a
    -be_at*R touch, effective from the next bar). Same cost-blind, daily-bar
    caveats as the long."""
    out = np.full(len(entry), np.nan)
    for i in range(len(entry)):
        d0, si = d[i], s[i]
        if d0 + 1 >= n_dates or np.isnan(entry[i]):
            continue
        e = entry[i]
        stop = min(signal_high[i], e * 1.06)
        risk = stop - e
        if risk <= 0 or np.isnan(risk):
            continue
        target = e - TRAIL_TARGET_R * risk
        be_level = e - be_at * risk if be_at is not None else None
        half_r, half_done, trail = 0.0, False, np.inf
        for k in range(1, TRAIL_CAP + 1):
            day = d0 + k
            if day >= n_dates or np.isnan(C[day, si]):
                break
            if H[day, si] >= stop:
                fill = max(O[day, si], stop)
                out[i] = half_r + (0.5 if half_done else 1.0) * (e - fill) / risk
                break
            if not half_done and L[day, si] <= target:
                half_r = 0.5 * (e - min(O[day, si], target)) / risk
                half_done = True
            if be_level is not None and stop > e and L[day, si] <= be_level:
                stop = e
            lvl = RH[day, si]
            if lvl < trail:
                trail = lvl
            if C[day, si] > trail:
                nxt = day + 1
                px = O[nxt, si] if nxt < n_dates and not np.isnan(O[nxt, si]) \
                    else C[day, si]
                out[i] = half_r + (0.5 if half_done else 1.0) * (e - px) / risk
                break
            if k == TRAIL_CAP:
                out[i] = half_r + (0.5 if half_done else 1.0) * (e - C[day, si]) / risk
    return out


def _outcomes(df: pd.DataFrame, m: dict) -> pd.DataFrame:
    """Uniform forward returns + stop-based R (5-/20-day, long and short),
    at two entry rulers: D+1 open (bare names) and signal close (*_close)."""
    O, H, L, C = (m["open"].values, m["high"].values,
                  m["low"].values, m["close"].values)
    d, s = df["date_idx"].to_numpy(), df["sym_idx"].to_numpy()
    n_dates = C.shape[0]

    entry = np.where(d + 1 < n_dates, O[np.minimum(d + 1, n_dates - 1), s], np.nan)
    for n, col in ((5, "ret_o5"), (20, "ret_o20")):
        fwd = np.where(d + n < n_dates, C[np.minimum(d + n, n_dates - 1), s], np.nan)
        df[col] = (fwd / entry - 1) * 100

    signal_low, signal_high = L[d, s], H[d, s]
    df["stop_r"] = _stop_r(entry, signal_low, d, s, O, L, C, n_dates, 5)
    df["stop_r_20"] = _stop_r(entry, signal_low, d, s, O, L, C, n_dates, 20)
    df["stop_r_short"] = _stop_r_short(entry, signal_high, d, s, O, H, C, n_dates, 5)
    df["stop_r_20_short"] = _stop_r_short(entry, signal_high, d, s, O, H, C, n_dates, 20)

    entry_c = C[d, s]
    df["stop_r_close"] = _stop_r(entry_c, signal_low, d, s, O, L, C, n_dates, 5)
    df["stop_r_20_close"] = _stop_r(entry_c, signal_low, d, s, O, L, C, n_dates, 20)
    df["stop_r_short_close"] = _stop_r_short(entry_c, signal_high, d, s, O, H, C,
                                             n_dates, 5)
    df["stop_r_20_short_close"] = _stop_r_short(entry_c, signal_high, d, s, O, H, C,
                                                n_dates, 20)

    # Appended last so the pre-existing column order is unchanged.
    RL = m["close"].rolling(TRAIL_WINDOW).min().to_numpy()
    RH = m["close"].rolling(TRAIL_WINDOW).max().to_numpy()
    df["stop_r_trail"] = _stop_r_trail(entry, signal_low, d, s, O, H, L, C, RL,
                                       n_dates)
    df["stop_r_trail_short"] = _stop_r_trail_short(entry, signal_high, d, s, O, H,
                                                   L, C, RH, n_dates)
    df["stop_r_trail_be"] = _stop_r_trail(entry, signal_low, d, s, O, H, L, C, RL,
                                          n_dates, be_at=TRAIL_BE_R)
    df["stop_r_trail_be_short"] = _stop_r_trail_short(entry, signal_high, d, s, O,
                                                      H, L, C, RH, n_dates,
                                                      be_at=TRAIL_BE_R)
    return df


def _dedupe(mask: pd.DataFrame, bars: int = 5) -> pd.DataFrame:
    """Drop repeats of the same symbol within `bars` bars (autocorrelation
    control). 5 is the house default; qm_flag uses 20, its own cooldown."""
    recent = mask.shift(1, fill_value=False).rolling(bars, min_periods=1).sum() > 0
    return mask & ~recent


def build(m: dict) -> pd.DataFrame:
    import common
    from stockbee_4pct_burst import find_events

    close, volume = m["close"], m["volume"]
    frames = []

    ev = find_events(m)[["date", "symbol"]]
    ev["trigger"] = "burst"
    frames.append(ev)

    chg = close.pct_change(fill_method=None)
    tradeable = common.tradeable_mask(close, volume)
    mask = _dedupe((chg >= 0.04) & (volume > volume.shift(1)) & tradeable)
    dates, syms = np.where(mask.fillna(False))
    frames.append(pd.DataFrame({"date": close.index[dates],
                                "symbol": close.columns[syms],
                                "trigger": "four_pct"}))

    low, high = m["low"], m["high"]
    sma20 = close.rolling(20).mean()
    sma200 = close.rolling(200).mean()
    uptrend = (close > sma200) & (sma20 > sma20.shift(5))
    hit_high_recent = ((close >= close.rolling(63).max() * 0.999)
                       .rolling(15, min_periods=1).max() > 0)
    touch = (low <= sma20 * 1.01) & (close >= sma20 * 0.97)
    mask_pb = _dedupe(uptrend & hit_high_recent & touch & tradeable)
    dp, sp = np.where(mask_pb.fillna(False))
    frames.append(pd.DataFrame({"date": close.index[dp],
                                "symbol": close.columns[sp],
                                "trigger": "pullback"}))

    mask_dn = _dedupe((chg <= -0.04) & (volume > volume.shift(1)) & tradeable)
    dd, ss = np.where(mask_dn.fillna(False))
    frames.append(pd.DataFrame({"date": close.index[dd],
                                "symbol": close.columns[ss],
                                "trigger": "four_pct_down"}))

    def _ist(s):
        return s.dt.tz_convert("Asia/Kolkata") if s.dt.tz is not None \
            else s.dt.tz_localize("Asia/Kolkata")

    ep = pd.read_csv(os.path.join(OUTPUT_DIR, "ep9m_redefined_events.csv"),
                     parse_dates=["date"], usecols=["date", "symbol", "r_stop"])
    ep["date"] = _ist(ep["date"])
    ep = ep.rename(columns={"r_stop": "ep_r"})
    ep["trigger"] = "ep"
    frames.append(ep)

    bo = pd.read_csv(os.path.join(OUTPUT_DIR, "washout_reversal_events.csv"),
                     parse_dates=["date"], usecols=["date", "symbol"])
    bo["date"] = _ist(bo["date"])
    bo["trigger"] = "bounce"
    frames.append(bo)

    # qm_flag — the FAITHFUL Qullamaggie flag breakout (see module docstring).
    # Every leg is as-of the signal close; the flag legs are measured as-of
    # YESTERDAY so the breakout bar itself never counts toward its own base.
    # The 252-day window needs min_periods: 3.6% of post-listing cells are NaN
    # holes (1,408 of 2,005 symbols have at least one), and a STRICT 252-bar
    # window returns NaN if a single bar in the trailing year is missing — 37%
    # of otherwise-valid cells, concentrated in 2015-19. Left strict, the
    # trigger fired 6 times in 2017 and 13 in 2018 purely from missing windows,
    # which would have emptied era A and rerouted every verdict onto the weaker
    # modern track. 200 bars (~10 months observed) is the floor for calling
    # something a 52-week high. The SHORT windows stay strict on purpose:
    # relaxing them would LOWER the 10-day high and manufacture breakouts,
    # whereas strictness only drops events.
    ret63 = close / close.shift(63) - 1.0
    hh252 = high.rolling(252, min_periods=200).max()
    range20 = (high.rolling(20).max() - low.rolling(20).min()) / close
    flag_drift = close.shift(1) / close.shift(20) - 1.0   # same 20-bar window
    mask_qm = _dedupe(
        (ret63 >= 0.30)
        & (close / hh252 - 1 >= -0.25)
        & (range20.shift(1) <= 0.25)
        & (flag_drift >= -0.10)
        & (close > high.rolling(10).max().shift(1))
        & (volume >= 1.2 * volume.rolling(50).mean())
        & (close >= common.MIN_PRICE), bars=20)
    dq, sq = np.where(mask_qm.fillna(False))
    frames.append(pd.DataFrame({"date": close.index[dq],
                                "symbol": close.columns[sq],
                                "trigger": "qm_flag"}))

    events = pd.concat(frames, ignore_index=True)
    events = _positions(events, close)
    events = _outcomes(events, m)
    events = events.drop(columns=["date_idx", "sym_idx"])
    events.to_parquet(EVENTS_PATH, compression="snappy", index=False)
    return events


def load_events(triggers: list = None) -> pd.DataFrame:
    ev = pd.read_parquet(EVENTS_PATH)
    return ev[ev["trigger"].isin(triggers)] if triggers else ev


if __name__ == "__main__":
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "studies"))
    import common
    events = build(common.load_cache())
    print(events.groupby("trigger").agg(
        n=("date", "size"), first=("date", "min"), last=("date", "max"),
        stop_r=("stop_r", "mean"), ret_o5=("ret_o5", "mean")).round(3).to_string())
    print(f"\nEvent store -> {os.path.abspath(EVENTS_PATH)}")
