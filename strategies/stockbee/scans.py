"""scans.py — Stockbee momentum scans over the universe summary table.

Each function takes the universe summary DataFrame (one row per stock, with the
columns precompute.py produces) plus thresholds, and returns a filtered, ranked
DataFrame. Pure and fast — no file or network I/O.
"""

import pandas as pd


def apply_base_filters(df, min_turnover_cr=1.0, min_price=0.0,
                       fo_only=False, excluded=None):
    """Liquidity, price, F&O and surveillance filters shared by every scan."""
    out = df[df["avg_turnover_cr"] >= min_turnover_cr]
    out = out[out["close"] >= min_price]
    if fo_only:
        out = out[out["is_fo"]]
    if excluded:
        out = out[~out["symbol"].isin(excluded)]
    return out.copy()


def four_pct(df, min_change=4.0, require_vol_up=True, require_close_strong=True,
             max_up_streak=None, **base):
    """Stockbee 4% breakout: a range-expansion day with volume confirmation.

    - close up >= min_change% vs prior close
    - today's volume > yesterday's volume         (require_vol_up)
    - close in the top 30% of the day's range      (require_close_strong)
    - optional: not already up max_up_streak+ days in a row (freshness)
    """
    out = apply_base_filters(df, **base)
    out = out[out["chg_pct"] >= min_change]
    if require_vol_up:
        out = out[out["volume"] > out["prev_volume"]]
    if require_close_strong:
        out = out[out["range_pos"] >= 0.70]
    if max_up_streak is not None:
        out = out[out["up_streak"] <= max_up_streak]
    return out.sort_values(["chg_pct", "volume_ratio"],
                           ascending=False).reset_index(drop=True)


def four_pct_up_7d(df, min_change=4.0, **base):
    """Stockbee 4% up move within the last 7 trading days (not just today).

    Catches range-expansion movers that fired earlier in the week — today's
    single-day `four_pct` scan misses them. A stock qualifies if its largest
    single-day close-to-close gain over the last 7 sessions is >= min_change%.
    Ranked by that biggest move, largest first.
    """
    out = apply_base_filters(df, **base)
    out = out[out["max_up_7d"] >= min_change]
    return out.sort_values("max_up_7d", ascending=False).reset_index(drop=True)


def four_pct_down_7d(df, min_change=4.0, **base):
    """Bearish mirror of `four_pct_up_7d`: a >= min_change% single-day drop on
    any of the last 7 sessions. Ranked by the biggest drop first."""
    out = apply_base_filters(df, **base)
    out = out[out["max_down_7d"] <= -min_change]
    return out.sort_values("max_down_7d", ascending=True).reset_index(drop=True)


def ti65(df, min_ti=1.05, **base):
    """Trend Intensity 65: 7-day average close >= min_ti x 65-day average close.

    min_ti = 1.05 means the short average is 5%+ above the long average — Bonde's
    threshold for an established up-trend. Ranked by TI value, strongest first.
    """
    out = apply_base_filters(df, **base)
    out = out[out["ti65"] >= min_ti]
    return out.sort_values("ti65", ascending=False).reset_index(drop=True)


def anticipation(df, max_range_5d=12.0, max_vol_contraction=0.85,
                 min_prior_move=20.0, require_nr7=False, **base):
    """Stockbee Anticipation (Pradeep Bonde): catch the coil before the burst.

    Don't chase the breakout day — anticipate it the evening before, when a stock
    that already had a move goes quiet: a tight, low-volume range near its highs.

    - had a prior up-leg:   r3mo_pct >= min_prior_move (the 3-month base trend)
    - tight range now:      range_pct_5d <= max_range_5d        (5-day high-low as % of price)
    - volume drying up:     vol_contraction <= max_vol_contraction  (5-day avg / 20-day avg)
    - optional: today is the narrowest range of the last 7 days (NR7)

    Tightest, quietest coils rank first.
    """
    out = apply_base_filters(df, **base)
    out = out[out["r3mo_pct"] >= min_prior_move]
    out = out[out["range_pct_5d"] <= max_range_5d]
    out = out[out["vol_contraction"] <= max_vol_contraction]
    if require_nr7:
        out = out[out["nr7"]]
    return out.sort_values(["range_pct_5d", "vol_contraction"],
                           ascending=True).reset_index(drop=True)


def reversal_bullish(df, min_cascade=2, min_range_pos=0.60,
                     inst_turnover_cr=25.0, **base):
    """Bonde reversal bullish (TraderLion 2026): a 2-3 day selling cascade on an
    INSTITUTIONAL-QUALITY stock, then a reversal bar — institutions defend their
    names at these levels, so the bounce has real buyers behind it. "If you try
    it on a random stock, you're going to get killed."

    - institutional quality: F&O member OR avg turnover >= inst_turnover_cr
    - closes fell min_cascade+ days in a row ending yesterday (down_streak)
    - today reversed: closed up, in the top 40% of the day's range
    Bonde enters these at 3:58 pm; EOD this is tonight's list to act on at
    tomorrow's open (or near tomorrow's close if it holds).
    """
    out = apply_base_filters(df, **base)
    out = out[out["is_fo"] | (out["avg_turnover_cr"] >= inst_turnover_cr)]
    out = out[out["down_streak"] >= min_cascade]
    out = out[out["chg_pct"] > 0]
    out = out[out["range_pos"] >= min_range_pos]
    return out.sort_values("avg_turnover_cr",
                           ascending=False).reset_index(drop=True)


def reversal_bearish(df, min_cascade=2, max_range_pos=0.40,
                     inst_turnover_cr=25.0, **base):
    """Bearish mirror of `reversal_bullish`: an institutional-quality name that
    rose min_cascade+ days in a row into today, then reversed down — early
    profit-taking/distribution in a name big players were buying, so the
    rollover has real sellers behind it rather than noise.

    - institutional quality: F&O member OR avg turnover >= inst_turnover_cr
    - closes rose min_cascade+ days in a row ending yesterday (up_streak)
    - today reversed: closed down, in the bottom 40% of the day's range
    """
    out = apply_base_filters(df, **base)
    out = out[out["is_fo"] | (out["avg_turnover_cr"] >= inst_turnover_cr)]
    out = out[out["up_streak"] >= min_cascade]
    out = out[out["chg_pct"] < 0]
    out = out[out["range_pos"] <= max_range_pos]
    return out.sort_values("avg_turnover_cr",
                           ascending=False).reset_index(drop=True)


def bottom_bounce(df, min_chg=4.0, min_off_high=25.0, **base):
    """Bonde bottom bounce (TraderLion 2026): a beaten-down stock's first big
    up day — ONLY tradeable when the market itself is washed out and turning
    (T2108/pct40ma < 20). The context gate lives in the caller; this function
    just finds the candidates.

    - down min_off_high%+ from its 52-week high (beaten down, not extended)
    - up min_chg%+ today on volume > prior day (the turn, with confirmation)
    """
    out = apply_base_filters(df, **base)
    out = out[out["chg_pct"] >= min_chg]
    out = out[out["volume"] > out["prev_volume"]]
    out = out[out["pct_from_52w_high"] <= -min_off_high]
    return out.sort_values("chg_pct", ascending=False).reset_index(drop=True)


# ── Short side (Pradeep Bonde) — only trade in a confirmed downtrend ────────────

def four_pct_down(df, min_change=4.0, require_vol_up=True, **base):
    """Stockbee 4% breakdown — the bearish mirror of `four_pct`.

    - close DOWN >= min_change% vs prior close
    - today's volume > yesterday's volume (selling on expanding volume)

    Ranked by the biggest drop first. Shorts only work in a weak market — confirm
    a 10-day+ downtrend or an active correction before acting.
    """
    out = apply_base_filters(df, **base)
    out = out[out["chg_pct"] <= -min_change]
    if require_vol_up:
        out = out[out["volume"] > out["prev_volume"]]
    return out.sort_values(["chg_pct", "volume_ratio"],
                           ascending=[True, False]).reset_index(drop=True)


def weak_structure_short(df, require_downtrend=True, **base):
    """Bonde weak-structure short (TraderLion 2026): a very weak stock that
    sold off 3 days in a row, paused 2-3 days, and resumed selling today
    (precomputed `weak_structure` flag). require_downtrend keeps it to broken
    names (TI65 < 1). Weak markets only — in a bull tape these squeeze."""
    out = apply_base_filters(df, **base)
    out = out[out["weak_structure"]]
    if require_downtrend:
        out = out[out["ti65"].notna() & (out["ti65"] < 1.0)]
    return out.sort_values("chg_pct").reset_index(drop=True)


def swing_exhaustion(df, **base):
    """Stockbee swing-exhaustion short: an exhausted rally leader's first crack.

    Bonde's formula: three green, ascending-close days in a row, then today closes
    lower than yesterday — the first down day after an extended run-up. Precomputed
    as the `swing_exhaustion` flag. Ranked by 1-month gain (most extended first).
    """
    out = apply_base_filters(df, **base)
    out = out[out["swing_exhaustion"]]
    return out.sort_values("r1mo_pct", ascending=False).reset_index(drop=True)
