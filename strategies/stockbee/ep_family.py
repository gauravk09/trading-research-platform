"""ep_family.py — Bonde's EP conveyor belt, adapted to NSE (TraderLion 2026 talk).

Three surfaces, one hypothesis: unusual volume is the footprint of institutions.

EP9M    "top 2% of the market by volume today" — scan-based, mostly non-gap.
        Bonde's US version is a fixed 9M shares (~top 2% of 13,000
        instruments); India's equivalent is a fixed 15M shares, the top ~2%
        of all NSE stock-days (ep9m_redefined study). Qualifiers:
          - price floor and minimum turnover — proxy for Bonde's "no $3 stocks"
            (true market-cap filtering needs a shares-outstanding feed: LATER).
          - 3x the stock's own prior-20d peak volume: 26 NSE names trade 15M+
            shares on a median day, so the absolute bar alone fired on them
            ~20% of all sessions and drowned the scan.
        The old novelty gate (stock usually NOT high-rank) was removed: the
        backtest showed repeat volume-outlier names OUTPERFORM first-timers.
        The scan finds the footprint; the WHY (catalyst) is research, done by
        joining the cached NSE announcements for that day.

DEP     delayed-reaction EP: an institutional-quality stock (F&O member OR
        avg turnover >= 25 cr — India proxy for Bonde's "1000+ funds") that had
        an EP9M event in the last 25 sessions, hasn't given the move back, and
        is now pulling back / tightening. Watchlist, not a trigger: Bonde
        allows 3 tight-stop tries, then waits for a confirmed breakout.

EP      the classic gap EP stays in episodic_pivot.py (gap >= 8%, volume >= 3x).
        ep_checklist() is the evening half: tonight's catalyst-category
        announcements joined with neglect metrics — the "tomorrow morning EP"
        list to review before open, since catalysts on NSE surface EOD via
        corporate filings, not pre-market wires.
"""

import glob
import os
import sys

import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src"))
import data_collection.nse.announcements_store as announcements_store

EP9M_SHARES = 15_000_000  # top ~2% of all NSE stock-days — India's "9M" (ep9m_redefined study)
EP9M_VOL_MULT = 3.0      # ...AND 3x the stock's own prior-20d peak volume, so
EP9M_VOL_WINDOW = 20     # perpetually-liquid names (ETERNAL, SUZLON) don't fire daily
MIN_PRICE = 30.0         # no penny stocks (Bonde: "I'm not going to buy $3 $5")
MIN_TURNOVER_CR = 10.0   # the volume must also be real money
DEP_WINDOW = 25          # Bonde: low-risk entry within 25 days of the catalyst
DEP_MIN_DAYS = 2         # need an actual pullback, not the day after the event
DEP_MIN_EVENT_CHG = 4.0  # the event day must have been a real repricing
DEP_MAX_PULLBACK = 15.0  # % off the post-event high before the setup is broken
DEP_MAX_RANGE_5D = 8.0   # must be TIGHT now — Bonde watches 3-4 names, not 50
INST_TURNOVER_CR = 25.0  # institutional quality: F&O member OR this liquid

CATALYST_CATEGORIES = ["results", "guidance", "order_win", "acquisition",
                       "regulatory", "buyback", "credit_rating", "fundraise"]


def ep9m_mask(close_matrix, volume_matrix, min_shares=EP9M_SHARES,
              min_price=MIN_PRICE, min_turnover_cr=MIN_TURNOVER_CR,
              vol_mult=EP9M_VOL_MULT, vol_window=EP9M_VOL_WINDOW):
    """Boolean date x symbol frame: True where an EP9M event fired.

    Absolute rarity (>= min_shares) AND self-relative rarity (>= vol_mult x the
    highest volume of the PRIOR vol_window sessions — shifted so today is not
    part of its own benchmark).
    """
    cm, vm = close_matrix.align(volume_matrix, join="inner")
    turnover_cr = cm * vm / 1e7
    prior_peak = vm.rolling(vol_window, min_periods=vol_window // 2).max().shift(1)
    return ((vm >= min_shares) & (cm >= min_price)
            & (turnover_cr >= min_turnover_cr)
            & (vm >= vol_mult * prior_peak))


def ep9m_today(close_matrix, volume_matrix, summary, catalysts=None, **kw):
    """Today's EP9M candidates with summary features and catalyst tags.

    Direction-agnostic on purpose — institutions leave the same footprint
    accumulating and distributing; chg_pct column tells you which."""
    mask = ep9m_mask(close_matrix, volume_matrix, **kw)
    hits = mask.iloc[-1]
    syms = hits[hits].index.tolist()
    out = summary[summary["symbol"].isin(syms)].copy()
    if out.empty:
        return out
    rank = volume_matrix.rank(axis=1, pct=True).iloc[-1] * 100
    out["vol_rank"] = out["symbol"].map(rank).round(1)
    out = _attach(out, catalysts)
    return out.sort_values("avg_turnover_cr", ascending=False).reset_index(drop=True)


def dep_watchlist(close_matrix, volume_matrix, summary,
                  window=DEP_WINDOW, max_pullback=DEP_MAX_PULLBACK,
                  inst_turnover_cr=INST_TURNOVER_CR, **kw):
    """Institutional-quality stocks with an EP9M event in the last `window`
    sessions that pulled back in an orderly way — Bonde's DEP watchlist.

    Orderly = the pre-event close is still defended (gains not fully given
    back) and price is within `max_pullback`% of the post-event high.
    Tightest names (range_pct_5d) rank first — those are the watch-like-a-hawk
    entries. Today's own events are excluded; they belong to the EP9M scan.
    """
    mask = ep9m_mask(close_matrix, volume_matrix, **kw)
    cm = close_matrix
    recent = mask.iloc[-(window + 1):-(DEP_MIN_DAYS)]      # events old enough to pull back
    rows = []
    for sym in recent.columns[recent.any()]:
        event_day = recent.index[recent[sym]][-1]          # newest qualifying event
        e = cm.index.get_loc(event_day)
        pre, now = cm[sym].iloc[e - 1], cm[sym].iloc[-1]
        high_since = cm[sym].iloc[e:].max()
        if pd.isna(pre) or pd.isna(now) or now <= pre:     # move fully given back
            continue
        event_chg = (cm[sym].iloc[e] / pre - 1) * 100
        if event_chg < DEP_MIN_EVENT_CHG:                  # footprint without repricing
            continue
        pullback = (high_since - now) / high_since * 100
        if pullback > max_pullback:
            continue
        rows.append({"symbol": sym, "event_date": str(event_day.date()),
                     "days_since": len(cm) - 1 - e,
                     "event_chg_pct": round(event_chg, 1),
                     "pullback_pct": round(pullback, 1)})
    if not rows:
        return pd.DataFrame()
    out = pd.DataFrame(rows).merge(summary, on="symbol", how="left")
    inst = out["is_fo"] | (out["avg_turnover_cr"] >= inst_turnover_cr)
    out = out[inst & (out["range_pct_5d"] <= DEP_MAX_RANGE_5D)]
    out = _attach(out, _event_catalysts(out))
    return out.sort_values("range_pct_5d").reset_index(drop=True)


def ep_checklist(summary, catalysts,
                 categories=CATALYST_CATEGORIES, min_turnover_cr=1.0):
    """Tomorrow-morning EP review list: tonight's catalyst-category filings
    joined with neglect metrics. Neglected names (no TI65 trend, flat half
    year) are the ones a genuine catalyst can reprice violently — they sort
    first. This is the evening half of Bonde's pre-market routine."""
    if catalysts is None or catalysts.empty:
        return pd.DataFrame()
    cat = catalysts[catalysts["category"].isin(categories)]
    out = cat.merge(summary, on="symbol", how="inner")
    out = out[out["avg_turnover_cr"] >= min_turnover_cr]
    if out.empty:
        return out
    out["neglected"] = ((out["ti65"].isna() | (out["ti65"] < 1.02))
                        & (out["r6mo_pct"] < 15))
    return out.sort_values(["neglected", "avg_turnover_cr"],
                           ascending=[False, False]).reset_index(drop=True)


def _attach(df, catalysts):
    """Left-join catalyst category/subject onto a candidate frame."""
    df = df.copy()
    if catalysts is None or catalysts.empty:
        df["catalyst"], df["catalyst_subject"] = None, None
        return df
    cat = catalysts.drop_duplicates("symbol").rename(
        columns={"category": "catalyst", "subject": "catalyst_subject"})
    return df.merge(cat[["symbol", "catalyst", "catalyst_subject"]],
                    on="symbol", how="left")


def _event_catalysts(dep_df):
    """Catalysts for DEP rows, read from each row's own event-date archive day."""
    frames = []
    for d in dep_df["event_date"].unique():
        try:
            ann = announcements_store.load_day(pd.Timestamp(d).date())
        except OSError:
            continue
        if ann.empty or "category" not in ann.columns:
            continue
        ann = ann[ann["category"].isin(CATALYST_CATEGORIES)][["symbol", "category", "subject"]]
        frames.append(ann[ann["symbol"].isin(
            dep_df.loc[dep_df["event_date"] == d, "symbol"])])
    return pd.concat(frames).drop_duplicates("symbol") if frames else None
