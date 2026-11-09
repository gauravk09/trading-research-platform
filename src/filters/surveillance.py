"""
filters/surveillance.py — ASM/GSM surveillance exclusion filter

Stocks under NSE surveillance have trading restrictions that make
Qullamaggie-style intraday breakout entries impossible or high-risk.
Exclude them at scan time.
"""

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from data_collection.nse.surveillance import get_excluded_symbols


_cached_excluded = None  # cache so we only hit the API once per scan run


def get_surveillance_exclusions() -> set:
    """
    Return the set of symbols currently under ASM or GSM surveillance.
    Cached for the duration of the process — call this once per scan run.
    """
    global _cached_excluded
    if _cached_excluded is None:
        _cached_excluded = get_excluded_symbols()
    return _cached_excluded


def surveillance_filter(symbol: str) -> bool:
    """
    True if the stock is NOT under any surveillance restriction.
    False = stock is on ASM or GSM list → exclude from scan.

    Args:
        symbol: trading symbol (e.g. "RELIANCE")
    """
    excluded = get_surveillance_exclusions()
    return symbol.upper() not in excluded


def reset_cache() -> None:
    """Reset the surveillance cache. Call this at the start of each daily scan."""
    global _cached_excluded
    _cached_excluded = None
