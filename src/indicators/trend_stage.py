"""
indicators/trend_stage.py — trend maturity, measured two ways

Research (2026-07-10, see ROADMAP.md) split "how mature is this trend?" into
two separate published concepts, and we track both:

1. TREND AGE — Bonde's own "Young TI65" scan (stockbee.blogspot.com, Trend
   Intensity setup post): a trend is established while TI65 (7-day avg close /
   65-day avg close) is latched above 1.05, and it is YOUNG if it became
   established within the last 25 bars — his exact scan is
   `avgc7/avgc65 >= 1.05 AND avgc7.25/avgc65.25 <= 1.05`.
   We implement the latch with hysteresis (on at >= 1.05, off below 1.00) so a
   one-day dip to 1.04 doesn't restart the age clock, and define young as
   age <= 25 bars — equivalent to his test for a continuously-latched trend.

2. BASE COUNT — Minervini's base counting / Bonde's 2LYNCH "Y" ("first or
   second breakout from consolidation is low risk"): how many bases has this
   advance already burst out of? Volatility-normalized (2026-07-10, after the
   fixed-4% version proved blind to sub-2%-ADR and circuit-band stocks):
   - a base BURSTS on a day whose close-to-close move is >= 1x that stock's
     own ADR50 (floored at 2.5%, capped at 8%) AND that prints a new 20-day
     closing high — the new-high gate keeps violent rallies inside downtrends
     from counting as bases;
   - a QUIET day moves within 1x ADR50 (an average-or-smaller day);
     MIN_BASE_DAYS quiet days must separate bursts, and any non-quiet day
     resets that clock;
   - the ADR window is 50 sessions, not 20 (widened 2026-07-11): during a
     base the trailing 20 days ARE the base, so ADR20 sags to ~87% of the
     stock's characteristic volatility and a routine intra-base pop can
     spuriously reset the clock; at 50 the base is a minority of the window
     while the threshold still adapts to genuine volatility-regime shifts.
   - ADR50 is the *prior* 50 sessions (shifted one bar) — point-in-time, and
     the burst day's own range never inflates its own threshold.
   1st/2nd base = best entries, 3rd acceptable, 4th+ prone to failure.

This burst/quiet vocabulary is shared with consol_days and the Breakout Setup
scan (precompute._consolidation_stats reads these constants) — one definition
of "outsized day" platform-wide. Fixed 4% survives only in market-level
breadth language: the Market Monitor's up4/dn4 counts and the plain 4%
Breakout/Breakdown scans.
"""

import pandas as pd

TI_ON = 1.05            # TI65 level that establishes a trend (Bonde's threshold)
TI_OFF = 1.00           # trend survives until the 7d avg drops below the 65d avg
YOUNG_BARS = 25         # Bonde's Young TI65 lookback: established < 25 bars ago
ADR_WINDOW = 50         # sessions in the threshold ADR — long enough that a base
                        # can't drag its own yardstick down (see module docstring)
BURST_ADR_MULT = 1.0    # a burst: close-to-close move >= 1x ADR50 (range-based,
                        # so c2c >= 1x range is genuinely a big day)...
BURST_FLOOR_PCT = 2.5   # ...but never below 2.5% (dead-calm stocks)
BURST_CAP_PCT = 8.0     # ...and never above 8% (hyper-volatile microcaps)
QUIET_ADR_MULT = 1.0    # a quiet day: c2c move within 1x ADR50 (average or smaller).
                        # Calibrated on 2026-07-10 universe grid: 1.5x/0.75x collapsed
                        # everything to B1 (mean 1.05); 1.0x/1.0x keeps spread
                        # (B1 63%, B2 25%, B3 8%, B4+ 4%) and matches the old fixed-4%
                        # counts on mid-ADR probes (MUTHOOTMF B4, SANSERA B8, EIEL B2).
NEW_HIGH_BARS = 20      # a burst must print a new 20-day closing high
LEGACY_PCT = 4.0        # fallback where the threshold ADR can't be computed yet
MIN_BASE_DAYS = 5       # quiet days required to call the next burst a new base


def _trend_birth(close: pd.Series) -> int | None:
    """Positional index of the first bar of the current established trend.

    None when TI65 can't be computed at the last bar (needs ~65+7 bars);
    -1 when no trend is currently latched on.
    """
    ti = close.rolling(7).mean() / close.rolling(65).mean()
    if len(ti) == 0 or pd.isna(ti.iloc[-1]):
        return None
    on, birth = False, -1
    for i, v in enumerate(ti):
        if pd.isna(v):
            on = False
        elif not on and v >= TI_ON:
            on, birth = True, i
        elif on and v < TI_OFF:
            on = False
    return birth if on else -1


def _burst_indices(close: pd.Series, high: pd.Series, low: pd.Series,
                   birth: int, min_base_days: int = MIN_BASE_DAYS) -> list:
    """Positional indices of each base's first burst day, from birth onward.

    Thresholds are per-stock (ADR50 as of the prior bar) so a 1.5%-ADR large
    cap and a 6%-ADR small cap resolve bases at their own scale."""
    chg = close.pct_change() * 100
    adr = ((high / low).rolling(ADR_WINDOW).mean() - 1).shift(1) * 100
    burst_thr = (BURST_ADR_MULT * adr).clip(BURST_FLOOR_PCT, BURST_CAP_PCT)
    quiet_thr = (QUIET_ADR_MULT * adr)
    new_high = close > close.shift(1).rolling(NEW_HIGH_BARS).max()

    bursts, quiet = [], min_base_days   # pre-seeded so the first burst counts
    for i in range(birth, len(close)):
        c = chg.iloc[i]
        if pd.isna(c):
            continue
        b_thr = burst_thr.iloc[i] if pd.notna(burst_thr.iloc[i]) else LEGACY_PCT
        q_thr = quiet_thr.iloc[i] if pd.notna(quiet_thr.iloc[i]) else LEGACY_PCT
        if c >= b_thr and bool(new_high.iloc[i]):
            if quiet >= min_base_days:
                bursts.append(i)
            quiet = 0
        elif abs(c) > q_thr:
            quiet = 0                   # any non-quiet day resets the clock
        else:
            quiet += 1
    return bursts


def trend_age(close: pd.Series) -> int | None:
    """Bars since TI65 established the current trend (Bonde's trend age).

    None = not enough history OR no trend currently latched;
    young per Bonde's Young TI65 rule when <= YOUNG_BARS.
    """
    birth = _trend_birth(close)
    if birth is None or birth < 0:
        return None
    return len(close) - birth


def base_count(close: pd.Series, high: pd.Series, low: pd.Series,
               min_base_days: int = MIN_BASE_DAYS) -> int | None:
    """How many bases this advance has burst out of (Minervini base count).

    Returns:
        None = not enough history to compute TI65 (~65 bars minimum)
        0    = no established trend (TI65 latch off) — pre-trend or dead money
        1-2  = early bases — best entries (Minervini / 2LYNCH "Y")
        3    = acceptable; 4+ = late-stage, prone to failure
    """
    birth = _trend_birth(close)
    if birth is None:
        return None
    if birth < 0:
        return 0
    return max(len(_burst_indices(close, high, low, birth, min_base_days)), 1)


def base_pivots(close: pd.Series, high: pd.Series, low: pd.Series,
                min_base_days: int = MIN_BASE_DAYS) -> list:
    """Chart markers matching base_count(): the bar where TI65 established
    the trend, plus each base's burst day. Empty when count is None or 0."""
    birth = _trend_birth(close)
    if birth is None or birth < 0:
        return []
    out = [{"index": birth, "price": float(close.iloc[birth]),
            "label": "Trend start"}]
    for n, i in enumerate(_burst_indices(close, high, low, birth, min_base_days),
                          start=1):
        out.append({"index": i, "price": float(close.iloc[i]),
                    "label": f"Base {n}"})
    return out


def maturity_label(age, base) -> str:
    """Compact display label combining both measurements.

    'Young 14d · B2'  — trend established 14 bars ago, on its 2nd base
    'Estd 176d · B7'  — long-established trend, 7th base (late)
    'no trend'        — TI65 latch off; '—' — not enough history.

    Accepts ints, numpy/pandas floats (parquet round-trips ints with NaNs as
    float64), or None/NaN."""
    if base is None or pd.isna(base):
        return "—"
    base = int(base)
    if base == 0:
        return "no trend"
    age = int(age) if age is not None and not pd.isna(age) else 0
    youth = "Young" if age <= YOUNG_BARS else "Estd"
    return f"{youth} {age}d · B{base}"
