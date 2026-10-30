"""
position_sizing.py — Qullamaggie position sizing calculator

Formula: Shares = (Account Size × Risk %) ÷ (Entry Price − Stop Price)

Rules:
  - Risk per trade:   0.25–1% of account
  - Position size:    10–20% of account (cap enforced)
  - Max overnight:    30% of account in any single stock
  - Stop width:       never wider than 1× ADR
"""

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src"))
from indicators.volatility import adr
from risk_sizing import size_position


def calculate_position(
    account_size:  float,
    entry:         float,
    stop:          float,
    risk_pct:      float = 1.0,
    max_position_pct: float = 20.0,
) -> dict:
    """
    Calculate share count and validate position sizing rules.

    Args:
        account_size:     total account value in ₹
        entry:            planned entry price
        stop:             planned stop price
        risk_pct:         % of account to risk (0.25–1.0)
        max_position_pct: max % of account in this trade (default 20%)

    Returns dict with:
        shares:           number of shares to buy
        position_value:   total position value in ₹
        position_pct:     position as % of account
        risk_amount:      ₹ at risk
        stop_distance_pct: stop distance as % of entry
        valid:            True if all rules pass
        warnings:         list of rule violations
    """
    sizing = size_position(equity=account_size, risk_pct=risk_pct, entry=entry,
                           stop=stop, side="BUY", max_positions=1,
                           max_position_pct=max_position_pct)
    warnings = [reason["message"] for reason in sizing["rejection_reasons"]]
    if not sizing["accepted"]:
        return {"shares": 0, "position_value": 0.0, "position_pct": 0.0,
                "risk_amount": 0.0, "risk_pct": risk_pct,
                "stop_distance_pct": 0.0, "valid": False, "warnings": warnings}
    shares = sizing["qty"]
    position_value = sizing["notional"]
    position_pct = position_value / account_size * 100
    stop_distance_pct = sizing["stop_pct"]

    if risk_pct < 0.25 or risk_pct > 1.0:
        warnings.append(f"Risk {risk_pct}% outside recommended range (0.25–1.0%)")

    if "position" in sizing["limits_applied"]:
        warnings.append(f"Position capped at {max_position_pct}% of account.")

    if position_pct > 30:
        warnings.append(f"Position {position_pct:.1f}% exceeds 30% overnight limit.")

    return {
        "shares":             shares,
        "position_value":     round(position_value, 2),
        "position_pct":       round(position_pct, 2),
        "risk_amount":        sizing["rupee_risk"],
        "risk_pct":           risk_pct,
        "stop_distance_pct":  round(stop_distance_pct, 2),
        "valid":              len(warnings) == 0,
        "warnings":           warnings,
    }


def validate_stop_vs_adr(
    entry: float,
    stop:  float,
    high:  "pd.Series",
    low:   "pd.Series",
    n:     int = 20,
) -> dict:
    """
    Check if the stop distance is within 1× ADR.
    If not, Qullamaggie's rule is to SKIP the trade entirely.

    Returns dict with:
        adr_pct:          stock's ADR%
        stop_pct:         stop distance as % of entry
        within_adr:       True if stop ≤ ADR (trade is valid)
        max_stop_price:   lowest price the stop can be set at
    """
    stock_adr     = adr(high, low, n)
    stop_pct      = abs(entry - stop) / entry * 100
    max_stop_price = entry * (1 - stock_adr / 100)

    return {
        "adr_pct":        round(stock_adr, 2),
        "stop_pct":       round(stop_pct, 2),
        "within_adr":     stop_pct <= stock_adr,
        "max_stop_price": round(max_stop_price, 2),
    }


def partial_exit_plan(shares: int, entry: float, stop: float, r_multiple: float = 2.5) -> dict:
    """
    Generate the partial exit plan per Qullamaggie rules:
      - Sell 1/3 to 1/2 at 2–3R profit
      - Move remaining stop to breakeven immediately

    Args:
        shares:     number of shares held
        entry:      entry price
        stop:       initial stop price
        r_multiple: R multiple to take first partial (default 2.5 = midpoint of 2–3R)
    """
    risk_per_share = abs(entry - stop)
    target_price   = entry + risk_per_share * r_multiple

    partial_shares = shares // 3         # sell 1/3
    remaining      = shares - partial_shares

    return {
        "partial_shares":   partial_shares,
        "remaining_shares": remaining,
        "target_price":     round(target_price, 2),
        "breakeven_stop":   round(entry, 2),
        "r_multiple":       r_multiple,
    }


if __name__ == "__main__":
    result = calculate_position(
        account_size=1_000_000,
        entry=500,
        stop=480,
        risk_pct=1.0,
    )
    print("Position sizing:")
    for k, v in result.items():
        print(f"  {k}: {v}")

    plan = partial_exit_plan(result["shares"], entry=500, stop=480)
    print("\nPartial exit plan:")
    for k, v in plan.items():
        print(f"  {k}: {v}")
