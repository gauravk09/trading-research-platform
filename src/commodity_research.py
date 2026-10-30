"""
commodity_research.py — The series to actually build strategies on, per commodity,
with the measured reason for each choice.

WHY FUTURES AND NOT SPOT, despite spot having no roll gaps:

Spot looked like the higher-quality option and measurement said otherwise.

  * Spot is close-only. LBMA prints one auction price, EIA one survey quote.
    A positional strategy needs highs and lows for ATR and stop placement, and
    no amount of history compensates for a series that has no daily range.
  * Spot is a different market. Residual daily-return sd of the offshore future
    against its own spot: GOLD 0.80%, SILVER 2.23%, NATGAS 6.87%. Henry Hub cash
    is a physical delivery market that spikes on weather while the futures do
    not — as a futures proxy it is not usable at all.
  * MCX trades FUTURES. Researching a signal on cash and firing it at a futures
    contract adds a basis that the research never saw.

ROLL GAPS, MEASURED (Yahoo continuous vs a single live contract, daily log-return
residual — this isolates the splice, without spot's venue noise):

    GOLD     sd 0.15%   12 days of 1417 exceed 0.5%   -> negligible
    SILVER   sd 0.21%   26 days of 1164 exceed 0.5%   -> negligible
    CRUDE    sd 2.48%  1552 days of 2196 exceed 0.5%  -> term structure dominates
    NATGAS   sd 3.95%  2482 days of 2924 exceed 0.5%  -> different asset per month

For gold and silver the continuous series is effectively clean and the "roll gap"
worry is a non-issue. For crude and especially natural gas, WHICH CONTRACT you
hold is a first-order decision, not a detail — seasonal gas contracts are close to
separate assets, so a signal fitted on a continuous series will not survive.

Ranked by how safe it is to research here:
    GOLD, SILVER   green   clean series, MCX tracks, small and smooth carry
    COPPER         amber   no free spot cross-check exists
    CRUDEOIL       amber   real term structure; front-month discipline required
    NATURALGAS     red     seasonality makes continuous history misleading
"""

import pandas as pd

import commodity_store
from commodity_map import PAIRS

QUALITY = {
    "GOLD":       "green",
    "SILVER":     "green",
    "COPPER":     "amber",
    "CRUDEOIL":   "amber",
    "NATURALGAS": "red",
}


def load(root: str, start: str = None) -> pd.DataFrame:
    """Daily OHLCV for the offshore benchmark, in USD. The research substrate."""
    df = commodity_store.read("global", PAIRS[root]["global_symbol"])
    if start:
        df = df[df["date"] >= pd.Timestamp(start)]
    return df.reset_index(drop=True)


def load_spot(root: str, start: str = None) -> pd.DataFrame:
    """Close-only cash benchmark, for cross-checking a result — not for fitting."""
    symbol = PAIRS[root]["spot_symbol"]
    if symbol is None:
        return pd.DataFrame()
    df = commodity_store.read("spot", symbol)
    if start:
        df = df[df["date"] >= pd.Timestamp(start)]
    return df.reset_index(drop=True)


def universe(max_risk: str = "amber") -> list:
    """Commodities safe enough to research on, worst tier allowed given."""
    order = ["green", "amber", "red"]
    cutoff = order.index(max_risk)
    return [r for r in PAIRS if order.index(QUALITY[r]) <= cutoff]


if __name__ == "__main__":
    for root in PAIRS:
        f, s = load(root), load_spot(root)
        span = f"{f['date'].min():%Y-%m-%d} -> {f['date'].max():%Y-%m-%d}"
        spot = f"{len(s):>6} spot" if not s.empty else "  no spot"
        print(f"{root:11} {QUALITY[root]:6} {len(f):>6} OHLC bars  {span}  {spot}")
    print(f"\nresearch universe (amber and better): {universe()}")
