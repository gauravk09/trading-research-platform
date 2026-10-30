"""
commodity_basis.py — Convert a global USD reference price into MCX-equivalent
INR terms, and measure how well MCX actually tracks it.

This is the bridge the whole "research offshore, execute in India" idea rests
on. If the basis is stable, an offshore signal transfers. If it wanders, the
Indian leg has its own driver (duty, local premium, currency) that the offshore
series cannot see, and the transfer is unsafe.

    fair_mcx = reference_usd * usdinr * unit_conversion

UNIT CONVERSIONS — the single easiest place to be silently wrong, because a
wrong constant still produces a beautiful correlation and a nonsense premium:
    GOLD        MCX per 10 g          vs COMEX per troy oz   x 10/31.1035
    SILVER      MCX per 1 kg          vs COMEX per troy oz   x 32.1507
    COPPER      MCX per 1 kg          vs COMEX per pound     x 2.20462
    CRUDEOIL    MCX per barrel        vs NYMEX per barrel    x 1
    NATURALGAS  MCX per mmBtu         vs NYMEX per mmBtu     x 1

The residual premium is NOT noise. For gold and silver it is mostly India's
import duty plus GST, which moves in Budget-day steps, not smoothly — a level
break there is a policy change, not a trading signal.
"""

import pandas as pd

import commodity_store
from commodity_map import PAIRS, FX_SYMBOL

# MCX quote unit per one unit of the offshore contract's quote.
UNIT_CONVERSION = {
    "GOLD":       10 / 31.1034768,
    "SILVER":     32.1507466,
    "COPPER":     2.20462262,
    "CRUDEOIL":   1.0,
    "NATURALGAS": 1.0,
}


def _fx() -> pd.DataFrame:
    return commodity_store.read("global", FX_SYMBOL)[["date", "close"]].rename(columns={"close": "usdinr"})


def build(root: str, reference: str = "futures") -> pd.DataFrame:
    """Join MCX against its offshore reference in INR terms.

    reference: "futures" (COMEX/NYMEX front-month, has roll gaps) or
               "spot" (LBMA/EIA cash, no roll gaps, close-only).

    Returns one row per date both sides traded, with `fair` and `premium_pct`.
    Dates are joined on the calendar day, which is correct here: MCX closes
    23:30 IST, inside the same CME session, so lag 0 is the right alignment
    (verified empirically — lags +/-1 correlate near zero).
    """
    meta = PAIRS[root]
    symbol = meta["global_symbol"] if reference == "futures" else meta["spot_symbol"]
    if symbol is None:
        raise ValueError(f"{root} has no {reference} reference (see commodity_map)")

    market = "global" if reference == "futures" else "spot"
    mcx = commodity_store.read("mcx", root)
    ref = commodity_store.read(market, symbol)[["date", "close"]].rename(columns={"close": "ref"})

    df = mcx.merge(ref, on="date").merge(_fx(), on="date")
    df["fair"] = df["ref"] * df["usdinr"] * UNIT_CONVERSION[root]
    df["premium_pct"] = (df["close"] / df["fair"] - 1) * 100
    return df


def tracking(root: str, reference: str = "futures", front_month_only: bool = False) -> dict:
    """Correlation of daily returns, plus the level and drift of the premium."""
    df = build(root, reference)
    if front_month_only and "is_front_month" in df.columns:
        df = df[df["is_front_month"]]
    if len(df) < 3:
        return {"root": root, "reference": reference, "n": len(df)}

    rets = df[["close", "fair"]].pct_change(fill_method=None)
    return {
        "root": root,
        "reference": reference,
        "n": len(df),
        "return_corr": round(rets["close"].corr(rets["fair"]), 3),
        "premium_mean_pct": round(df["premium_pct"].mean(), 2),
        "premium_sd_pct": round(df["premium_pct"].std(), 2),
    }


if __name__ == "__main__":
    rows = []
    for root, meta in PAIRS.items():
        for ref in ("futures", "spot"):
            if ref == "spot" and meta["spot_symbol"] is None:
                continue
            rows.append(tracking(root, ref))
    print(pd.DataFrame(rows).to_string(index=False))
