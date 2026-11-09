"""One authoritative, side-aware position sizing and portfolio-risk engine.

All monetary inputs are rupees.  Gross exposure and portfolio heat are the
already-open rupee notional and rupee stop-risk respectively.  The engine is
pure: callers supply account state and decide how/when to persist an order.
"""
import math


def _reason(code, message):
    return {"code": code, "message": message}


def size_position(*, equity, risk_pct, entry, stop, side,
                  existing_gross_exposure=0.0, existing_heat=0.0,
                  open_positions=0, max_positions=1,
                  max_gross_exposure_pct=100.0, max_heat_pct=100.0,
                  leverage=1.0, margin_rate=None, max_position_pct=None):
    """Return a floor-sized position that cannot breach a supplied constraint.

    ``leverage`` is notional/equity buying power.  Alternatively callers may
    pass ``margin_rate`` (margin/notional); it takes precedence over leverage.
    The result is rejected, rather than rounded up, when no whole unit fits.
    """
    reasons, limits = [], []
    try:
        values = {name: float(value) for name, value in {
            "equity": equity, "risk_pct": risk_pct, "entry": entry, "stop": stop,
            "existing_gross_exposure": existing_gross_exposure,
            "existing_heat": existing_heat, "max_gross_exposure_pct": max_gross_exposure_pct,
            "max_heat_pct": max_heat_pct, "leverage": leverage,
        }.items()}
    except (TypeError, ValueError):
        return _rejected(reasons + [_reason("invalid_input", "Sizing inputs must be numeric.")])
    if any(not math.isfinite(value) for value in values.values()):
        return _rejected(reasons + [_reason("invalid_input", "Sizing inputs must be finite.")])
    if values["equity"] <= 0 or values["risk_pct"] <= 0 or values["entry"] <= 0:
        return _rejected(reasons + [_reason("non_positive_input", "Equity, risk percent, and entry must be positive.")])
    if values["existing_gross_exposure"] < 0 or values["existing_heat"] < 0:
        return _rejected(reasons + [_reason("invalid_existing_portfolio", "Existing gross exposure and heat cannot be negative.")])
    normalized_side = str(side).upper()
    if normalized_side in {"BUY", "LONG"}:
        long = True
    elif normalized_side in {"SELL", "SHORT"}:
        long = False
    else:
        return _rejected(reasons + [_reason("invalid_side", "Side must be BUY/LONG or SELL/SHORT.")])
    if (long and values["stop"] >= values["entry"]) or (not long and values["stop"] <= values["entry"]):
        direction = "below" if long else "above"
        return _rejected(reasons + [_reason("invalid_stop_geometry", f"Stop must be {direction} entry for this side.")])
    if not isinstance(open_positions, int) or isinstance(open_positions, bool) or open_positions < 0:
        return _rejected(reasons + [_reason("invalid_open_positions", "Open positions must be a non-negative integer.")])
    if not isinstance(max_positions, int) or isinstance(max_positions, bool) or max_positions <= 0:
        return _rejected(reasons + [_reason("invalid_max_positions", "Max positions must be a positive integer.")])
    if open_positions >= max_positions:
        return _rejected(reasons + [_reason("position_slots_exhausted", "The maximum number of open positions is already reached.")])
    if values["max_gross_exposure_pct"] <= 0 or values["max_heat_pct"] <= 0:
        return _rejected(reasons + [_reason("invalid_cap", "Gross-exposure and heat caps must be positive.")])
    if margin_rate is None:
        if values["leverage"] <= 0:
            return _rejected(reasons + [_reason("invalid_leverage", "Leverage must be positive.")])
        rate = 1.0 / values["leverage"]
    else:
        try:
            rate = float(margin_rate)
        except (TypeError, ValueError):
            return _rejected(reasons + [_reason("invalid_margin_rate", "Margin rate must be numeric.")])
        if not math.isfinite(rate) or rate <= 0:
            return _rejected(reasons + [_reason("invalid_margin_rate", "Margin rate must be positive.")])

    per_unit_risk = abs(values["entry"] - values["stop"])
    risk_budget = values["equity"] * values["risk_pct"] / 100.0
    gross_cap = values["equity"] * values["max_gross_exposure_pct"] / 100.0
    heat_cap = values["equity"] * values["max_heat_pct"] / 100.0
    remaining_gross = gross_cap - values["existing_gross_exposure"]
    remaining_heat = heat_cap - values["existing_heat"]
    # Existing exposure consumes margin at the same supplied rate.
    remaining_margin_notional = (values["equity"] - values["existing_gross_exposure"] * rate) / rate
    caps = [("risk_budget", risk_budget / per_unit_risk),
            ("gross_exposure", remaining_gross / values["entry"]),
            ("portfolio_heat", remaining_heat / per_unit_risk),
            ("margin", remaining_margin_notional / values["entry"])]
    if max_position_pct is not None:
        try:
            position_cap = float(max_position_pct)
        except (TypeError, ValueError):
            return _rejected(reasons + [_reason("invalid_position_cap", "Max position percent must be numeric.")])
        if not math.isfinite(position_cap) or position_cap <= 0:
            return _rejected(reasons + [_reason("invalid_position_cap", "Max position percent must be positive.")])
        caps.append(("position", values["equity"] * position_cap / 100.0 / values["entry"]))
    for code, maximum in caps:
        if maximum <= 0:
            return _rejected(reasons + [_reason(f"{code}_cap_exhausted", f"{code.replace('_', ' ')} cap is exhausted.")])
    raw_risk_qty = caps[0][1]
    qty = math.floor(min(maximum for _, maximum in caps))
    if qty <= 0:
        return _rejected(reasons + [_reason("quantity_below_one", "No whole unit fits the risk and portfolio limits.")])
    for code, maximum in caps[1:]:
        if maximum < raw_risk_qty:
            limits.append(code)
    notional = qty * values["entry"]
    rupee_risk = qty * per_unit_risk
    margin_estimate = notional * rate
    return {"accepted": True, "rejection_reasons": [], "limits_applied": limits,
            "side": "LONG" if long else "SHORT", "qty": qty,
            "per_unit_risk": round(per_unit_risk, 2), "rupee_risk": round(rupee_risk, 2),
            "notional": round(notional, 2), "stop_pct": round(per_unit_risk / values["entry"] * 100, 4),
            "risk_pct_of_equity": round(rupee_risk / values["equity"] * 100, 4),
            "resulting_gross_exposure": round(values["existing_gross_exposure"] + notional, 2),
            "resulting_portfolio_heat": round(values["existing_heat"] + rupee_risk, 2),
            "margin_estimate": round(margin_estimate, 2), "margin_rate": rate}


def _rejected(reasons):
    return {"accepted": False, "rejection_reasons": reasons, "limits_applied": [],
            "qty": 0, "per_unit_risk": 0.0, "rupee_risk": 0.0, "notional": 0.0,
            "stop_pct": 0.0, "risk_pct_of_equity": 0.0,
            "resulting_gross_exposure": None, "resulting_portfolio_heat": None,
            "margin_estimate": 0.0}
