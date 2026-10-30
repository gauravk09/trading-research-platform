"""breakout_setup.py — Bonde's core setup: breakout from a quiet, long consolidation.

Source: stockbee.blogspot.com "Buy range expansion at beginning of a swing" and
"How to identify a quality setup" — buy the *first* day of range expansion out of
an orderly, low-volatility 5-10+ day base, not a stock already 3+ days into its run.

Both sides of the scan are volatility-normalized (2026-07-11): the base is quiet
days *at the stock's own scale* (no move >= 1x its prior-50d ADR, clipped 2.5-8%),
and the trigger is a day that clears that same per-stock threshold. The ADR
window is 50 days so the base can't drag down its own yardstick (a 20-day window
IS the base while one forms). Bonde's fixed
4% was implicitly a volatility filter — that preference is now the explicit
min_adr_pct knob instead. The plain 4% Breakout scan and the Market Monitor's
up4/dn4 counts keep the fixed 4%: those are cross-market breadth vocabulary.

Unlike the plain 4% Breakout scan (which only checks today's bar), this scan also
checks the base that came before it, and returns a suggested Entry/Stop per his
stated rule: enter at the breakout close, stop at the breakout day's low.
"""

import pandas as pd
from .scans import apply_base_filters


def breakout_from_consolidation(df, min_adr_pct=3.0, min_consol_days=5, max_consol_days=20,
                                max_consol_range_pct=15.0, max_consol_vol_ratio=1.10,
                                require_close_strong=True, max_up_streak=2,
                                require_quiet_prior_day=True, **base):
    """Find today's breakouts out of a quality base.

    - a base of min_consol_days..max_consol_days quiet days precedes today
      (no day >= 1x the stock's own ADR50 in that window — Bonde's "orderly
      consolidation", at the stock's own scale)
    - that base was tight: consol_range_pct <= max_consol_range_pct
    - volume dried up in the base: consol_vol_ratio <= max_consol_vol_ratio
    - today: close up >= burst_thr_pct (the same per-stock threshold that would
      have reset the base), volume > prior day (range expansion + confirmation)
    - ADR >= min_adr_pct: only stocks volatile enough for a 3-5 day swing to pay
    - optional: close in top 30% of the day's range (require_close_strong)
    - optional: not already up max_up_streak+ days running (freshness — avoid the
      3rd-day buyer)
    - optional: the day before the breakout was a narrow-range or negative day
      (require_quiet_prior_day — Bonde's "day prior to range expansion day will
      be narrow range day or negative day")
    """
    out = apply_base_filters(df, **base)
    out = out[out["adr_pct"] >= min_adr_pct]
    out = out[out["chg_pct"] >= out["burst_thr_pct"]]
    out = out[out["volume"] > out["prev_volume"]]
    out = out[out["consol_days"].between(min_consol_days, max_consol_days)]
    out = out[out["consol_range_pct"] <= max_consol_range_pct]
    out = out[out["consol_vol_ratio"] <= max_consol_vol_ratio]
    if require_close_strong:
        out = out[out["range_pos"] >= 0.70]
    if max_up_streak is not None:
        out = out[out["up_streak"] <= max_up_streak]
    if require_quiet_prior_day:
        out = out[out["prior_day_quiet"]]

    out = out.copy()
    out["entry_price"] = out["close"]
    out["stop_price"] = out["low"]
    out["risk_pct"] = (out["entry_price"] - out["stop_price"]) / out["entry_price"] * 100
    # list, not out.apply(axis=1): on a zero-match day apply returns a DataFrame and crashes
    out["reason"] = [_build_reason(row) for _, row in out.iterrows()]
    return out.sort_values(["chg_pct", "volume_ratio"],
                           ascending=False).reset_index(drop=True)


def _build_reason(row):
    fresh = ", fresh (not up 3d straight)" if row["up_streak"] <= 2 else ""
    return (
        f"{int(row['consol_days'])}-day quiet base ({row['consol_range_pct']:.1f}% range, "
        f"{row['consol_vol_ratio']:.2f}x avg volume) -> breakout +{row['chg_pct']:.1f}% "
        f"(own bar: {row['burst_thr_pct']:.1f}%) on {row['volume_ratio']:.1f}x volume, "
        f"closed top {int(row['range_pos'] * 100)}% of range{fresh}"
    )
