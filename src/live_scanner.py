"""live_scanner.py — turn live intraday quotes + EOD history into scan tables.

During market hours the EOD `universe_summary` is stale by one day: its `close`
is yesterday's close and its `volume` is yesterday's full-day volume. This module
rebuilds only the "today" columns the Stockbee scans need — `chg_pct`,
`range_pos`, `volume`, `prev_volume`, `volume_ratio`, `close` — from a live quote,
keeps every *history* column (down_streak, r3mo_pct, range_pct_5d,
vol_contraction, is_fo, avg_turnover_cr, adr_pct, avg_vol_7d, up_streak ...)
straight from the summary, then runs the SAME predicates used at EOD. So the
intraday list and tonight's EOD list agree on what a hit is.

A quote is a dict: {last, open, high, low, prev_close, vol} where `vol` is
today's cumulative traded volume and `open/high/low` are today's, `prev_close`
is yesterday's close (Kite's tick `ohlc.close`).

No look-ahead: the history columns are as-of yesterday's close (e.g. down_streak
is the losing streak *coming into* today), and the live columns use only prices
already printed up to `now` — never a future bar. `range_pos` is where the last
trade sits in the day's *realized-so-far* range, which is exactly what a trader
sees on screen.
"""

import json
import os
from datetime import datetime
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

from stockbee import ep_family, scans

IST = ZoneInfo("Asia/Kolkata")
OPEN_MIN = 9 * 60 + 15            # 09:15 IST
SESSION_MIN = (15 * 60 + 30) - OPEN_MIN   # 375-minute regular session
MIN_FRACTION = 0.10              # floor so the first few minutes can't blow up RVOL

# Typical cumulative volume fraction per minute-of-session, measured from ~400
# liquid symbol-days (src/preprocessing/build_vol_curve.py). NSE volume is U-shaped — heavy
# open, quiet midday, heavy close — so dividing by elapsed *time* overstates
# projected volume ~2-3x in the first hour. Dividing by this curve is fair at
# any time of day.
_CURVE_PATH = os.path.join(os.path.dirname(__file__), "..",
                           "data", "processed", "intraday_vol_curve.json")


def _load_curve():
    try:
        with open(_CURVE_PATH) as f:
            d = json.load(f)
        return [d[str(m)] for m in range(SESSION_MIN)]
    except (OSError, KeyError, ValueError):
        return None


VOL_CURVE = _load_curve()


def session_fraction(now=None):
    """Typical fraction of the full day's volume traded by `now`, floored at
    MIN_FRACTION. Projected day volume = cum_vol / fraction. Falls back to
    linear elapsed time if the measured curve file is missing."""
    now = now or datetime.now(IST)
    minute = now.hour * 60 + now.minute - OPEN_MIN
    if VOL_CURVE and 0 <= minute < SESSION_MIN:
        frac = VOL_CURVE[minute]
    else:
        frac = minute / SESSION_MIN
    return min(max(frac, MIN_FRACTION), 1.0)


def live_frame(quotes, hist, now=None):
    """Merge live quotes onto the EOD history, overriding the today-columns.

    `hist` is the summary indexed by symbol (with a `symbol` column retained, so
    the scan predicates that read `out["symbol"]` keep working). Returns a frame
    the Stockbee scans can consume directly, plus display extras (`last`, `rvol`,
    `day_high`, `day_low`).
    """
    frac = session_fraction(now)
    syms = [s for s in quotes if s in hist.index]
    if not syms:
        return pd.DataFrame()

    q = pd.DataFrame.from_dict({s: quotes[s] for s in syms}, orient="index")
    q = q.reindex(syms)
    f = hist.loc[syms].copy()

    prev = q["prev_close"].where(q["prev_close"].fillna(0) > 0, f["close"].values)
    last = q["last"].astype(float)
    rng = (q["high"] - q["low"])

    f["last"] = last.values
    f["day_high"] = q["high"].values
    f["day_low"] = q["low"].values
    f["chg_pct"] = ((last.values / prev.values) - 1.0) * 100.0
    f["range_pos"] = np.where(rng.values > 0,
                              (last.values - q["low"].values) / rng.values, np.nan)

    projected = q["vol"].astype(float).values / frac
    f["rvol"] = (projected / f["avg_vol_7d"]).replace([np.inf, -np.inf], np.nan)

    # Point the scan-facing columns at live values. Order matters: read
    # yesterday's full-day volume into prev_volume BEFORE overwriting `volume`.
    f["prev_volume"] = f["volume"]
    f["volume"] = projected                 # projected day volume vs yesterday's
    f["volume_ratio"] = f["rvol"]
    f["close"] = f["last"]                   # base min_price filter + sort keys
    return f.dropna(subset=["last", "chg_pct"])


# ── The three intraday scans (thin wrappers over the EOD predicates) ────────────

def four_pct_live(frame, excluded=None, min_turnover_cr=5.0, min_change=4.0):
    """Live 4% breakout: up >= min_change%, projected volume above yesterday's,
    closing strong in the day's range. Entry = last, stop = day's low."""
    if frame.empty:
        return frame
    hits = scans.four_pct(frame, min_change=min_change, require_vol_up=True,
                          require_close_strong=True, max_up_streak=None,
                          min_turnover_cr=min_turnover_cr, excluded=excluded).copy()
    hits["entry"] = hits["last"]
    hits["stop"] = hits["day_low"]
    hits["trigger"] = "breakout"
    return hits


def breakdown_live(frame, excluded=None, min_turnover_cr=5.0, min_change=4.0):
    """Live 4% breakdown — the bearish mirror of `four_pct_live`: down >=
    min_change%, projected volume above yesterday's. Entry = last (short),
    stop = day's high."""
    if frame.empty:
        return frame
    hits = scans.four_pct_down(frame, min_change=min_change, require_vol_up=True,
                               min_turnover_cr=min_turnover_cr, excluded=excluded).copy()
    hits["entry"] = hits["last"]
    hits["stop"] = hits["day_high"]
    hits["trigger"] = "breakdown"
    return hits


def reversal_live(frame, excluded=None, min_turnover_cr=5.0):
    """Live bullish reversal: an institutional-quality name that fell 2-3 days
    into today and is reversing up now, closing in the top 40% of its range."""
    if frame.empty:
        return frame
    hits = scans.reversal_bullish(frame, min_cascade=2, min_range_pos=0.60,
                                  inst_turnover_cr=25.0,
                                  min_turnover_cr=min_turnover_cr, excluded=excluded).copy()
    hits["trigger"] = "reversal up"
    return hits


def reversal_down_live(frame, excluded=None, min_turnover_cr=5.0):
    """Live bearish reversal — the mirror of `reversal_live`: an
    institutional-quality name that rose 2-3 days into today and is rolling
    over now, closing in the bottom 40% of its range."""
    if frame.empty:
        return frame
    hits = scans.reversal_bearish(frame, min_cascade=2, max_range_pos=0.40,
                                  inst_turnover_cr=25.0,
                                  min_turnover_cr=min_turnover_cr, excluded=excluded).copy()
    hits["trigger"] = "reversal down"
    return hits


def four_pct_up_7d_live(frame, excluded=None, min_turnover_cr=5.0, min_change=4.0):
    """Recent movers: any liquid name whose biggest single-day gain over the last
    7 EOD sessions was >= min_change%, shown with its *live* LTP/Chg%/RVOL so you
    can watch what those movers are doing right now. The 7-day window is as-of
    last night's close (max_up_7d comes straight from the EOD summary)."""
    if frame.empty:
        return frame
    hits = scans.four_pct_up_7d(frame, min_change=min_change,
                                min_turnover_cr=min_turnover_cr, excluded=excluded).copy()
    hits["trigger"] = "4% up 7d"
    return hits


def four_pct_down_7d_live(frame, excluded=None, min_turnover_cr=5.0, min_change=4.0):
    """Bearish mirror of `four_pct_up_7d_live`: liquid names that dropped
    >= min_change% on any of the last 7 EOD sessions, viewed live."""
    if frame.empty:
        return frame
    hits = scans.four_pct_down_7d(frame, min_change=min_change,
                                  min_turnover_cr=min_turnover_cr, excluded=excluded).copy()
    hits["trigger"] = "4% down 7d"
    return hits


def user_picks(quotes, full_hist, picks, tracked=None, now=None):
    """Live view of your watchlist: the picks CSV plus everything you stamped
    with ⊕ today, each with its live LTP, Chg%, RVOL and range position.

    `picks` is the DataFrame from load_picks (symbol + date + reason); `tracked`
    is today's frame from tracker.load (symbol + time + price). A tracked row
    also carries `since_pct` — the move since YOU picked it, which Chg% can't
    tell you because it measures from yesterday's close.

    Unlike the scans this applies NO filter — a pick that isn't moving still
    shows, so the list stays complete. It reads against the *full* summary
    (`full_hist`), not the liquid stream universe, so an illiquid pick isn't
    silently dropped. A pick with no live quote yet (not streaming) drops out."""
    syms = set(picks["symbol"]) if picks is not None and not picks.empty else set()
    if tracked is not None and not tracked.empty:
        syms |= set(tracked["symbol"])
    frame = live_frame(quotes, full_hist, now=now)
    if not syms or frame.empty:
        return frame.iloc[0:0]
    frame = frame[frame["symbol"].isin(syms)].copy()
    if frame.empty:
        return frame
    ann = picks.set_index("symbol")
    frame["date"] = frame["symbol"].map(ann["date"])
    frame["reason"] = frame["symbol"].map(ann["reason"])

    stamp = tracked.set_index("symbol") if tracked is not None and not tracked.empty \
        else pd.DataFrame(columns=["time", "price"])
    frame["track_time"] = frame["symbol"].map(stamp["time"])
    # to_numeric: an all-missing map is object dtype, which can't be divided
    frame["track_price"] = pd.to_numeric(frame["symbol"].map(stamp["price"]),
                                         errors="coerce")
    frame["since_pct"] = (frame["last"] / frame["track_price"] - 1) * 100
    # tracked names first (untracked have no since_pct), best move on top
    return frame.sort_values(["since_pct", "chg_pct"], ascending=False,
                             na_position="last").reset_index(drop=True)


def anticipation_live(frame, excluded=None, min_turnover_cr=5.0,
                      fire_chg=3.0, fire_rvol=1.5,
                      ep_shares=ep_family.EP9M_SHARES, ep_chg=5.0,
                      ep_min_price=ep_family.MIN_PRICE):
    """Anticipation coils firing today + EP9M unusual-volume footprints.

    A) coil firing: a name that was a tight, quiet anticipation coil at last
       close is now moving up (>= fire_chg%) on real relative volume (>= fire_rvol).
    B) ep9m: the same definition ep_family/the ep9m_redefined study use — up
       >= ep_chg% on >= ep_shares traded (15M shares = top ~2% of all NSE
       stock-days), price >= ep_min_price. Absolute rarity, not a multiple of
       the stock's own average: that is Bonde's actual rule.

       Live caveat: `volume` here is today's cumulative volume projected to a
       full session via the intraday curve, so before the close this is a
       forecast of crossing 15M, not a realized crossing. Tonight's EOD ep9m
       scan is the one that confirms.
    """
    if frame.empty:
        return frame
    coil = scans.anticipation(frame, max_range_5d=12.0, max_vol_contraction=0.85,
                              min_prior_move=20.0, min_turnover_cr=min_turnover_cr,
                              excluded=excluded)
    coil = coil[(coil["chg_pct"] >= fire_chg) & (coil["rvol"] >= fire_rvol)].copy()
    coil["trigger"] = "coil firing"

    ep = scans.apply_base_filters(frame, min_turnover_cr=min_turnover_cr,
                                  min_price=ep_min_price, excluded=excluded)
    ep = ep[(ep["volume"] >= ep_shares) & (ep["chg_pct"] >= ep_chg)].copy()
    ep["trigger"] = "ep9m"

    parts = [d for d in (coil, ep) if not d.empty]
    if not parts:
        return coil            # empty, but carries the expected columns
    out = pd.concat(parts).drop_duplicates("symbol", keep="first")
    return out.sort_values("rvol", ascending=False).reset_index(drop=True)


# ── Per-row TAKE/SKIP signals from the validated strategy registry ─────────────
# `market` is strategy_registry.market_snapshot() (+ mcap150_cr, the 150th-largest
# market cap, computed at server start). Reasons quote the live gate values so a
# SKIP always says which validated rule blocked it. Thresholds mirror the
# backtests: see the "Tape Rules" playbook doc for provenance.

NET4_SHORT_GATE = 18       # green-tape gate for the lone-loser short (batch 5)
NET4_LONG_STRONG = 130     # strong-tape cell where liquid 4%-days turn positive
TI65_HOT = 1.04            # index-extension stand-down for the short (F3b)
PCT40_QULLA_GATE = 55      # breadth gate for the gated Qullamaggie breakout
PCT40_WASHOUT = 40         # below this, dip-buy pockets graded negative
LIQUID_TURN_CR = 25.0      # "liquid" cut where the long edges live
RVOL_CHASE = 3.0           # Zanger inverted: biggest spikes underperform


def _annotate_breakdown(hits, market):
    net4, ti65 = market.get("net4"), market.get("ti65_nifty")
    mcap150 = market.get("mcap150_cr")
    sig, why = [], []
    for r in hits.itertuples():
        mcap = getattr(r, "mcap_cr", None)
        if mcap150 and (mcap is None or pd.isna(mcap) or mcap < mcap150):
            sig.append("—")
            why.append("not top-150 mcap — short edge only validated on large caps")
        elif net4 is not None and net4 < NET4_SHORT_GATE:
            sig.append("SKIP")
            why.append(f"tape not green (net4={net4} < {NET4_SHORT_GATE}) — "
                       "shorting weakness in a weak tape loses")
        elif ti65 is not None and ti65 >= TI65_HOT:
            sig.append("SKIP")
            why.append(f"Nifty extended (ti65={ti65:.3f} >= {TI65_HOT}) — "
                       "stand down when the index is hot")
        else:
            sig.append("TAKE")
            why.append(f"lone-loser short: top-150 + green tape (net4={net4}) "
                       f"+ index not hot (ti65={ti65}) | stop 6%, exit D+5")
    return sig, why


def _annotate_four_pct(hits, market):
    net4 = market.get("net4")
    sig, why = [], []
    for r in hits.itertuples():
        turn = getattr(r, "avg_turnover_cr", None)
        rvol = getattr(r, "rvol", None)
        if net4 is not None and net4 < NET4_LONG_STRONG:
            sig.append("CAUTION")
            why.append(f"tape not strong (net4={net4} < {NET4_LONG_STRONG}) — "
                       "4% days only turned positive in strong breadth")
        elif turn is not None and not pd.isna(turn) and turn < LIQUID_TURN_CR:
            sig.append("CAUTION")
            why.append(f"thin ({turn:.0f}Cr < {LIQUID_TURN_CR:.0f}Cr) — "
                       "the edge lives in liquid names")
        elif rvol is not None and not pd.isna(rvol) and rvol >= RVOL_CHASE:
            sig.append("CAUTION")
            why.append(f"extreme RVOL ({rvol:.1f}x) — biggest volume spikes "
                       "underperform (Zanger inverted)")
        else:
            sig.append("TAKE")
            why.append(f"strong tape (net4={net4}) + liquid + volume not "
                       "frenzied — the confirmed positive cell")
    return sig, why


def _annotate_anticipation(hits, market):
    pct40 = market.get("pct40ma")
    gate_open = pct40 is not None and pct40 >= PCT40_QULLA_GATE
    sig, why = [], []
    for r in hits.itertuples():
        r3mo = getattr(r, "r3mo_pct", None)
        if not gate_open:
            sig.append("CAUTION")
            why.append(f"breadth gate closed (pct40ma="
                       f"{pct40 if pct40 is None else round(pct40)} < "
                       f"{PCT40_QULLA_GATE}) — ungated breakouts are index-like "
                       "with double the DD")
        elif r3mo is not None and not pd.isna(r3mo) and r3mo >= 30:
            sig.append("TAKE")
            why.append(f"Qullamaggie profile: 3mo +{r3mo:.0f}% + breadth gate "
                       f"open (pct40ma={pct40:.0f}) | trail MA20, half off +1R")
        else:
            sig.append("TAKE")
            why.append(f"breadth gate open (pct40ma={pct40:.0f}) — but prior "
                       "3mo move < 30%, not the full Qullamaggie profile")
    return sig, why


def _annotate_reversal(hits, market):
    pct40 = market.get("pct40ma")
    sig, why = [], []
    for r in hits.itertuples():
        ti65 = getattr(r, "ti65", None)
        if pct40 is not None and pct40 < PCT40_WASHOUT:
            sig.append("SKIP")
            why.append(f"market washout (pct40ma={pct40:.0f} < {PCT40_WASHOUT}) "
                       "— washout dip pockets graded strongly negative")
        elif ti65 is None or pd.isna(ti65) or ti65 < 1.0:
            sig.append("SKIP")
            why.append("stock not in an uptrend (ti65 < 1.0) — dip-buy edge "
                       "only exists in stock-level uptrends")
        else:
            sig.append("TAKE")
            why.append(f"dip-buy in a stock uptrend (ti65={ti65:.2f}) with "
                       "breadth not washed out")
    return sig, why


ANNOTATORS = {"breakdown": _annotate_breakdown,
              "four_pct": _annotate_four_pct,
              "anticipation": _annotate_anticipation,
              "reversal": _annotate_reversal}


def annotate(name, hits, market):
    """Attach `signal` + `why` columns for scans with validated TAKE/SKIP rules."""
    fn = ANNOTATORS.get(name)
    if fn is None or hits is None or hits.empty or not market:
        return hits
    sig, why = fn(hits, market)
    hits = hits.copy()
    hits["signal"], hits["why"] = sig, why
    return hits


SCANS = {"four_pct": four_pct_live,
         "breakdown": breakdown_live,
         "anticipation": anticipation_live,
         "reversal": reversal_live,
         "reversal_down": reversal_down_live,
         "four_pct_up_7d": four_pct_up_7d_live,
         "four_pct_down_7d": four_pct_down_7d_live}

# Columns each scan table exposes: (source_column, header). The front-end renders
# these generically and colours chg_pct / rvol itself.
#
# RVOL  = today's volume projected to a full session, divided by the 7-day
#         average volume. >1x means trading busier than usual for this name;
#         the tables highlight 2x+ and 3x+ since real setups run hot.
# Rng   = where the last trade sits in *today's realized-so-far* high-low
#         range, as a %. 100% = printing at the day's high, 0% = at the low.
#         A high Rng on an up move (or low Rng on a down move) means the
#         move is closing strong, not fading.
# Trigger = which rule fired this row — since anticipation/reversal scans can
#         match more than one pattern, this says which one so you don't have
#         to re-derive it from the other columns.
COLUMNS = {
    "four_pct": [("symbol", "Symbol"), ("last", "LTP"), ("chg_pct", "Chg%"),
                 ("rvol", "RVOL"), ("range_pos", "Rng"), ("entry", "Entry"),
                 ("stop", "Stop"), ("mcap_cr", "Mcap Cr"), ("trigger", "Trigger"),
                 ("signal", "Signal")],
    "breakdown": [("symbol", "Symbol"), ("last", "LTP"), ("chg_pct", "Chg%"),
                  ("rvol", "RVOL"), ("range_pos", "Rng"), ("entry", "Entry"),
                  ("stop", "Stop"), ("mcap_cr", "Mcap Cr"), ("trigger", "Trigger"),
                  ("signal", "Signal")],
    "anticipation": [("symbol", "Symbol"), ("last", "LTP"), ("chg_pct", "Chg%"),
                     ("rvol", "RVOL"), ("volume", "Vol M"), ("range_pos", "Rng"),
                     ("range_pct_5d", "5d Rng%"), ("mcap_cr", "Mcap Cr"),
                     ("trigger", "Trigger"), ("signal", "Signal")],
    "reversal": [("symbol", "Symbol"), ("last", "LTP"), ("chg_pct", "Chg%"),
                 ("rvol", "RVOL"), ("range_pos", "Rng"),
                 ("down_streak", "Down d"), ("avg_turnover_cr", "T/O Cr"),
                 ("mcap_cr", "Mcap Cr"), ("trigger", "Trigger"),
                 ("signal", "Signal")],
    "reversal_down": [("symbol", "Symbol"), ("last", "LTP"), ("chg_pct", "Chg%"),
                       ("rvol", "RVOL"), ("range_pos", "Rng"),
                       ("up_streak", "Up d"), ("avg_turnover_cr", "T/O Cr"),
                       ("mcap_cr", "Mcap Cr"), ("trigger", "Trigger")],
    "four_pct_up_7d": [("symbol", "Symbol"), ("last", "LTP"), ("chg_pct", "Chg%"),
                       ("rvol", "RVOL"), ("max_up_7d", "7d Up%"), ("range_pos", "Rng"),
                       ("avg_turnover_cr", "T/O Cr"), ("mcap_cr", "Mcap Cr"),
                       ("trigger", "Trigger")],
    "four_pct_down_7d": [("symbol", "Symbol"), ("last", "LTP"), ("chg_pct", "Chg%"),
                         ("rvol", "RVOL"), ("max_down_7d", "7d Dn%"), ("range_pos", "Rng"),
                         ("avg_turnover_cr", "T/O Cr"), ("mcap_cr", "Mcap Cr"),
                         ("trigger", "Trigger")],
    "user_picks": [("symbol", "Symbol"), ("last", "LTP"), ("chg_pct", "Chg%"),
                   ("track_time", "Tracked"), ("track_price", "Track ₹"),
                   ("since_pct", "Since%"),
                   ("rvol", "RVOL"), ("range_pos", "Rng"), ("adr_pct", "ADR%"),
                   ("avg_turnover_cr", "T/O Cr"), ("mcap_cr", "Mcap Cr"),
                   ("date", "Date"), ("reason", "Reasoning")],
}


def _cell(col, v):
    """JSON-safe, rounded value for one table cell."""
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return None
    if col in ("symbol", "trigger", "date", "reason", "track_time",
               "signal", "why"):
        return str(v)
    if col in ("down_streak", "up_streak", "mcap_cr"):
        return int(v)
    if col == "range_pos":                 # store as a 0-100 % for the header "Rng"
        return round(float(v) * 100, 0)
    if col == "volume":                    # shares -> millions; EP9M is a 15M rule
        return round(float(v) / 1e6, 2)
    return round(float(v), 2)


def _table(hits, cols, extras=("why",)):
    """Turn a hits frame into a JSON-safe {columns, rows} payload. `extras` are
    row fields shipped without a column (rendered as tooltips, like `dep`)."""
    rows = [] if hits is None or hits.empty else [
        {**{c: _cell(c, r.get(c)) for c, _ in cols},
         **{e: _cell(e, r.get(e)) for e in extras if e in r}}
        for r in hits.to_dict("records")
    ]
    return {"columns": [{"key": c, "label": lbl} for c, lbl in cols], "rows": rows}


def run(name, quotes, hist, excluded=None, now=None, market=None):
    """Compute one scan and return {columns, rows} ready to JSON-serialise.
    `market` (strategy_registry.market_snapshot() + mcap150_cr) enables the
    per-row TAKE/SKIP signal; without it the tables render as before."""
    frame = live_frame(quotes, hist, now=now)
    hits = SCANS[name](frame, excluded=excluded) if not frame.empty else frame
    hits = annotate(name, hits, market or {})
    out = _table(hits, COLUMNS[name])
    if market:
        out["market"] = {k: market[k] for k in
                         ("date", "net4", "pct40ma", "ti65_nifty")
                         if k in market}
    return out


# ── Live order pad ─────────────────────────────────────────────────────────────
# Bonde's setups are entered at ~15:58, so their tickets must be built from
# LIVE quotes — tonight's state file does not exist yet at 15:20. Entry is the
# last trade, stop is today's realized low (longs) / high (shorts): the same
# stop the EOD scans would record, just measured so-far.
#
# Only TAKE rows become tickets. The lone-loser short is included even though
# it is a D+1-open book — seeing it before the close is what lets you punch the
# AMO tonight — and its card says so rather than pretending it is a now-trade.

PAD_SCANS = {"four_pct": "breakout", "reversal": "reversal",
             "anticipation": "breakout", "breakdown": "lone_loser_short"}


def order_tickets(quotes, hist, excluded=None, market=None, equity=1_000_000,
                  risk_pct=0.5, now=None):
    """Live TAKE rows -> sized order tickets, best move first."""
    import order_pad

    frame = live_frame(quotes, hist, now=now)
    if frame.empty:
        return []
    out = []
    for name, family in PAD_SCANS.items():
        hits = annotate(name, SCANS[name](frame, excluded=excluded),
                        market or {})
        if hits is None or hits.empty or "signal" not in hits.columns:
            continue
        short = family == "lone_loser_short"
        for r in hits[hits["signal"] == "TAKE"].to_dict("records"):
            entry = r.get("last")
            stop = r.get("day_high") if short else r.get("day_low")
            if not entry or not stop:
                continue
            if short:
                stop = min(stop, entry * 1.06)   # the book's 6% stop cap
            t = order_pad.ticket(r["symbol"], family, entry, stop,
                                 equity, risk_pct, now=now)
            if not t.get("qty"):
                continue
            t["chg_pct"] = r.get("chg_pct")
            t["rvol"] = r.get("rvol")
            t["why"] = r.get("why")
            t["card"] = order_pad.punch_card(t)
            out.append(t)
    out.sort(key=lambda t: -abs(t.get("chg_pct") or 0))
    return out


def run_picks(quotes, full_hist, picks, tracked=None, now=None):
    """User Picks table: the watchlist CSV + today's ⊕ stamps, no filtering."""
    return _table(user_picks(quotes, full_hist, picks, tracked, now=now),
                  COLUMNS["user_picks"])
