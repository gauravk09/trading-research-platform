"""
mcx_data.py — MCX futures daily OHLCV from Kite, spliced into a front-month
continuous series per commodity.

Two hard limits of this source, both of which silently produce wrong-looking
history if ignored:

1. Kite's instrument dump lists only CURRENTLY LISTED contracts. Expired
   contracts are gone and their instrument_tokens are unrecoverable.

   This is worse than a short history — it silently changes WHAT the series is.
   Because the earliest reachable bars belong to a contract that is live TODAY,
   those bars were, at the time, a DEFERRED month, not the front month. Asking
   for "the nearest unexpired contract" on a 2025 date returns the only contract
   we can still see, which back then was 4th or 5th in the queue: thinner, wider
   spread, and carrying a different basis.

   So `is_front_month` is computed by extrapolating each commodity's expiry
   cycle backwards, and only bars where it is True are a real front-month
   series. Everything before that is a deferred-month series wearing the same
   name. For genuine multi-year front-month history you need the MCX bhavcopy
   archive; Kite cannot supply it.

2. Kite's `close` is the last traded price of the session, NOT the official
   daily settlement price (DSP), which MCX computes from a weighted average of
   the last 30 minutes. Margin, MTM and expiry all reference the DSP. If the
   strategy is specified "at settle", this close is a proxy, not the number.

Continuous series are built by splicing front-month contracts at rollover and
are NOT back-adjusted: `is_roll` marks the bar where the underlying contract
changed, and the return across that bar is a calendar spread, not a price move.

CLI:
    python src/mcx_data.py --list          # what MCX contracts are live now
    python src/mcx_data.py                 # fetch + splice mapped commodities
"""

import sys
from datetime import date, timedelta

import pandas as pd

import commodity_store
from auth import get_kite_client
from commodity_map import PAIRS


def live_contracts(kite) -> pd.DataFrame:
    """All live MCX futures, one row per contract, nearest expiry first."""
    df = pd.DataFrame(kite.instruments(exchange="MCX"))
    df = df[df["instrument_type"] == "FUT"].copy()
    df["expiry"] = pd.to_datetime(df["expiry"])
    return df.sort_values(["name", "expiry"]).reset_index(drop=True)


def _contract_history(kite, token: int, start: date, end: date) -> pd.DataFrame:
    """Daily bars for one contract. Kite caps a day-interval request at 2000 days."""
    bars = kite.historical_data(token, start, end, "day")
    if not bars:
        return pd.DataFrame()
    df = pd.DataFrame(bars)
    df["date"] = pd.to_datetime(df["date"]).dt.tz_localize(None).dt.normalize()
    return df[["date", "open", "high", "low", "close", "volume"]]


def _cycle_days(expiries: pd.Series) -> float:
    """Typical gap between consecutive expiries for a commodity.

    GOLD lists bi-monthly (~61d), CRUDEOIL monthly (~30d). Used to reconstruct
    when a contract WOULD have become the front month, since the contract that
    preceded it has already expired out of Kite's instrument dump.
    """
    gaps = expiries.sort_values().diff().dt.days.dropna()
    return float(gaps.median()) if not gaps.empty else 30.0


def build_continuous(kite, root: str, contracts: pd.DataFrame,
                     start: date, end: date) -> pd.DataFrame:
    """Splice the mapped commodity's contracts into one series, flagging which
    bars are genuinely front-month.

    Front-month is decided per DATE, not per contract: for each bar we keep the
    row belonging to the nearest contract that had not yet expired on that date.
    Doing it the other way round (take contract A up to its expiry, then B)
    quietly double-counts days where both traded.
    """
    legs = contracts[contracts["name"] == root]
    if legs.empty:
        return pd.DataFrame()

    frames = []
    for _, leg in legs.iterrows():
        hist = _contract_history(kite, int(leg["instrument_token"]), start, end)
        if hist.empty:
            continue
        hist["expiry"] = leg["expiry"]
        hist["contract"] = leg["tradingsymbol"]
        frames.append(hist)

    if not frames:
        return pd.DataFrame()

    allbars = pd.concat(frames, ignore_index=True)
    # keep only bars from contracts not yet expired on that bar's date
    allbars = allbars[allbars["expiry"] >= allbars["date"]]
    allbars = allbars.sort_values(["date", "expiry"])
    front = allbars.drop_duplicates(subset="date", keep="first").reset_index(drop=True)
    front["is_roll"] = front["contract"] != front["contract"].shift(1)
    front.loc[0, "is_roll"] = False

    # A contract with expiry E is front month only from E-cycle onwards; before
    # that the true front month was a contract Kite can no longer see.
    cycle = pd.Timedelta(days=_cycle_days(legs["expiry"]))
    front["is_front_month"] = front["date"] > (front["expiry"] - cycle)
    return front


def update(years_back: int = 3) -> dict:
    kite = get_kite_client()
    contracts = live_contracts(kite)
    start = date.today() - timedelta(days=365 * years_back)
    end = date.today()

    out = {}
    for root in PAIRS:
        series = build_continuous(kite, root, contracts, start, end)
        if series.empty:
            print(f"{root:12} no data")
            continue
        commodity_store.write("mcx", root, series)
        fm = series[series["is_front_month"]]
        fm_span = f"{fm['date'].min():%Y-%m-%d}" if not fm.empty else "none"
        print(f"{root:12} {len(series):>5} bars total | "
              f"front-month {len(fm):>4} bars from {fm_span} | "
              f"{int(series['is_roll'].sum())} rolls | last {series['close'].iloc[-1]:,.2f}")
        out[root] = series
    return out


if __name__ == "__main__":
    if "--list" in sys.argv:
        c = live_contracts(get_kite_client())
        print(c["name"].value_counts().to_string())
        print()
        print(c[["tradingsymbol", "name", "expiry", "lot_size"]].head(40).to_string(index=False))
    else:
        update()
