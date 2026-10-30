"""
annotators.py — Per-study setup-zone shading + plain-English entry criteria.

Each study encodes its geometry in its own event-csv columns (box_top/bottom,
pole/flag, base depth/length, ...). An annotator draws that geometry onto the
price axis (shaded consolidation zone, reference lines) and returns the bullet
lines that describe why the signal fired, so the chart bank explains itself.

Contract:
    annotate(ax, slug, row, win, sig_pos, entry_x) -> list[str]
      ax       : price Axes (integer x = bar index within the window)
      row      : the event row (Series) from <slug>_events.csv
      win      : windowed OHLCV DataFrame (reset index; columns date/o/h/l/c/...)
      sig_pos  : x-index of the signal bar within win
      entry_x  : x-index of the entry bar (sig_pos + 1)
"""

import numpy as np
from matplotlib.patches import Rectangle

ZONE_FC = "#42a5f5"


def _zone(ax, x0, x1, y0, y1, label, color=ZONE_FC):
    """Shade a horizontal band [y0,y1] over bars [x0,x1] with dashed edges."""
    x0 = max(0, x0)
    ax.add_patch(Rectangle((x0, min(y0, y1)), max(x1 - x0, 0.5),
                           abs(y1 - y0), facecolor=color, alpha=0.12,
                           edgecolor="none", zorder=0))
    for y in (y0, y1):
        ax.plot([x0, x1], [y, y], color=color, lw=0.8, ls="--", zorder=1)
    ax.annotate(label, (x0, max(y0, y1)), xytext=(2, 2),
                textcoords="offset points", fontsize=7, color=color)


def _f(row, key, default=np.nan):
    v = row.get(key, default)
    return v if v is not None else default


def _i(row, key, default):
    """NaN-safe int: falls back to default when the column is missing or NaN."""
    try:
        v = float(row.get(key, default))
    except (TypeError, ValueError):
        return default
    return int(v) if np.isfinite(v) else default


# ----------------------------------------------------------------------------
# per-study annotators
# ----------------------------------------------------------------------------
def darvas_box(ax, row, win, sig_pos, entry_x):
    top, bot = _f(row, "box_top"), _f(row, "box_bottom")
    dur = _i(row, "duration_bars", 15)
    _zone(ax, sig_pos - dur, sig_pos, bot, top, "Darvas box")
    return [
        "Setup: Darvas box breakout (box near 52-wk high)",
        f"Box:  {bot:.1f} - {top:.1f}   height {_f(row,'height_pct'):.1f}%",
        f"Base: {dur} bars (top confirm -> breakout)",
        f"Breakout vol: {_f(row,'vol_ratio'):.1f}x 50d avg",
        "Trigger: high pierces box top on >=1.5x volume",
    ]


def high_tight_flag(ax, row, win, sig_pos, entry_x):
    run_high, flag_low = _f(row, "run_high"), _f(row, "flag_low")
    flag_len = _i(row, "flag_len", 8)
    _zone(ax, sig_pos - flag_len, sig_pos, flag_low, run_high, "flag")
    return [
        "Setup: High Tight Flag (O'Neil / Zanger)",
        f"Pole: +{_f(row,'pole_pct'):.0f}% run into the high",
        f"Flag: {flag_len} bars, depth {_f(row,'flag_depth_pct'):.0f}%",
        f"Flag range: {flag_low:.1f} - {run_high:.1f}",
        "Trigger: close over flag high on >=1.5x volume",
    ]


def ryan_52wk_high(ax, row, win, sig_pos, entry_x):
    base_len = _i(row, "base_len", 20)
    depth = _f(row, "base_depth_pct")
    base = win.iloc[max(0, sig_pos - base_len):sig_pos + 1]
    if len(base):
        _zone(ax, sig_pos - base_len, sig_pos,
              base["low"].min(), base["high"].max(), "base")
    return [
        "Setup: breakout to new 52-week high (Ryan)",
        f"Base: {base_len} bars, depth {depth:.0f}%",
        f"Breakout vol: {_f(row,'vol_ratio'):.1f}x avg",
        f"Stage: {_f(row,'stage','-')}",
        "Trigger: new 52-wk high out of the base",
    ]


def minervini_trend_template(ax, row, win, sig_pos, entry_x):
    return [
        "Setup: Minervini Trend Template (Stage 2)",
        f"Dist to 52-wk high: {_f(row,'dist_52wk_high'):.0f}%",
        f"ADR(20): {_f(row,'adr20'):.1f}%",
        f"Pos in 52-wk range: {_f(row,'pos'):.0f}%",
        "Trigger: all 8 trend-template conditions pass",
    ]


def stockbee_4pct_burst(ax, row, win, sig_pos, entry_x):
    lo = _f(row, "signal_low")
    if np.isfinite(lo):
        ax.plot([sig_pos - 0.4, sig_pos + 0.4], [lo, lo],
                color="#ef5350", lw=1.2)
    return [
        "Setup: Stockbee 4% momentum burst",
        f"Burst day: +{_f(row,'burst_pct'):.1f}%",
        f"Volume: {_f(row,'vol_ratio_50d'):.1f}x 50d avg",
        f"Above 50 MA: {bool(_f(row,'above_50ma'))}",
        "Trigger: >=4% up day on volume expansion",
    ]


def _mark_low(ax, sig_pos, y, color="#ef5350"):
    if np.isfinite(y):
        ax.plot([sig_pos - 0.4, sig_pos + 0.4], [y, y], color=color, lw=1.4)
        ax.annotate("signal low", (sig_pos, y), xytext=(3, -10),
                    textcoords="offset points", fontsize=6.5, color=color)


def donchian_turtle(ax, row, win, sig_pos, entry_x):
    level = _f(row, "level")
    if np.isfinite(level):
        ax.plot([max(0, sig_pos - 55), sig_pos], [level, level],
                color=ZONE_FC, lw=1.0, ls="--")
        ax.annotate("Donchian high", (max(0, sig_pos - 55), level),
                    xytext=(2, 2), textcoords="offset points",
                    fontsize=7, color=ZONE_FC)
    return [
        f"Setup: Donchian / Turtle breakout ({_f(row,'system','-')})",
        f"Breakout level: {level:.1f}",
        f"ATR: {_f(row,'atr_pct'):.1f}%  (stop {_f(row,'n_atr'):.1f}N)",
        f"Above 200 MA: {bool(_f(row,'above_200ma'))}",
        "Trigger: high clears the N-day Donchian high",
    ]


def connors_rsi2(ax, row, win, sig_pos, entry_x):
    return [
        "Setup: Connors RSI(2) pullback (mean-reversion)",
        f"RSI(2): {_f(row,'rsi2'):.0f}  (oversold)",
        f"Above 200 MA by {_f(row,'dist_200ma'):.0f}%",
        f"Leader: {bool(_f(row,'leader'))}",
        "Trigger: short-term oversold inside an uptrend",
    ]


def kell_ema_crossback(ax, row, win, sig_pos, entry_x):
    _mark_low(ax, sig_pos, _f(row, "signal_low"))
    return [
        "Setup: EMA pullback / cross-back continuation",
        f"Prior move: +{_f(row,'prior_move'):.0f}%",
        f"Pullback depth: {_f(row,'pullback_depth'):.0f}%",
        f"Reclaim vol: {_f(row,'vol_ratio'):.1f}x",
        "Trigger: EMA reclaim after a shallow pullback",
    ]


def pocket_pivot(ax, row, win, sig_pos, entry_x):
    _mark_low(ax, sig_pos, _f(row, "pivot_low"))
    return [
        f"Setup: Pocket pivot ({_f(row,'pivot_type','-')})",
        f"Volume: {_f(row,'vol_ratio'):.1f}x (> recent down-day vols)",
        f"Close in day range: {_f(row,'close_pos'):.0f}%",
        "Trigger: volume up-day from within the base",
    ]


def weinstein_stage2(ax, row, win, sig_pos, entry_x):
    return [
        "Setup: Weinstein Stage 2 breakout (30-wk MA up)",
        f"30-wk MA slope (63d): +{_f(row,'ma150_chg63_pct'):.1f}%",
        f"Breakout vol: {_f(row,'vol_ratio'):.1f}x",
        f"RS gate: {bool(_f(row,'rs_gate'))}",
        "Trigger: breakout over a rising 30-week MA",
    ]


def washout_reversal(ax, row, win, sig_pos, entry_x):
    _mark_low(ax, sig_pos, win["low"].iloc[sig_pos] if sig_pos < len(win) else np.nan)
    return [
        "Setup: 3-day washout reversal (dip-buy)",
        f"3-day drop: {_f(row,'depth_3d'):.0f}%",
        f"Above 50 MA: {bool(_f(row,'above_50ma'))}",
        "Trigger: reversal after a sharp 3-day flush",
        "Note: edge concentrated in leaders during bad regimes",
    ]


def movers(ax, row, win, sig_pos, entry_x):
    _mark_low(ax, sig_pos, win["low"].iloc[sig_pos] if sig_pos < len(win) else np.nan)
    return [
        "Screen: +20% within 22 trading days",
        f"22-day return: +{_f(row,'ret_o20'):.0f}%",
        f"Launch close: {_f(row,'close'):.1f}",
        "Not a setup — the raw move. Dashed = D+1 open.",
    ]


def _generic(ax, row, win, sig_pos, entry_x):
    return [
        f"Setup: {row.get('_slug','signal')}",
        f"Signal close: {_f(row,'close'):.1f}",
        f"Entry (D+1 open): {_f(row,'entry_open'):.1f}",
        f"RS rank: {_f(row,'rs_rank'):.0f}   {row.get('regime','')} market",
        "Entry marked at the dashed line (D+1 open).",
    ]


ANNOTATORS = {
    "darvas_box": darvas_box,
    "high_tight_flag": high_tight_flag,
    "ryan_52wk_high": ryan_52wk_high,
    "minervini_trend_template": minervini_trend_template,
    "stockbee_4pct_burst": stockbee_4pct_burst,
    "donchian_turtle": donchian_turtle,
    "connors_rsi2": connors_rsi2,
    "kell_ema_crossback": kell_ema_crossback,
    "pocket_pivot": pocket_pivot,
    "weinstein_stage2": weinstein_stage2,
    "washout_reversal": washout_reversal,
    "movers": movers,
}


def annotate(ax, slug, row, win, sig_pos, entry_x):
    fn = ANNOTATORS.get(slug, _generic)
    row = dict(row)
    row["_slug"] = slug
    try:
        return fn(ax, row, win, sig_pos, entry_x)
    except Exception:
        return _generic(ax, row, win, sig_pos, entry_x)
