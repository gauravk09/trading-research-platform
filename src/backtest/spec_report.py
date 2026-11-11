"""spec_report.py — write a spec backtest to one .xlsx.

Sheets:
  Summary     one row per entry clock: trades, win rate, avg/median return, profit factor, avg R, excess
  Eras        the same metrics per era (eras may overlap, e.g. B and sub_2024_26)
  Trades      every trade. The first eight columns match research/alpha_forge/export_excel.py:
              asset, side, entry, exit, days, raw_ret, mkt_ret, pnl
              raw_ret = trade return net of costs; mkt_ret = equal-weight universe return over
              the same window; pnl = raw_ret's excess over it, signed for the side
  Per_stock   per clock and stock: trades, win rate, average and summed return
  Conditions  how many stock-days passed each entry condition (spots conditions that never fire)
  Run         run settings, the look-ahead check, and every spec item NOT applied
  Spec        the strategy JSON, flattened to path -> value (includes success bars and
              external evaluations, for the human verdict)
"""

import json
import os

import numpy as np
import pandas as pd

TRADE_COLUMNS = ["asset", "side", "entry", "exit", "days", "raw_ret", "mkt_ret", "pnl",
                 "clock", "era", "signal", "entry_price", "exit_price", "stop_price", "r_multiple", "exit_reason"]
EXCEL_TEXT_LIMIT = 32000


def metrics(trades):
    r = trades["raw_ret"].dropna()
    wins, losses = r[r > 0], r[r <= 0]
    loss_sum = abs(losses.sum())
    return {
        "trades": len(r),
        "stocks_traded": trades["asset"].nunique(),
        "win_rate_pct": _pct(len(wins) / len(r)) if len(r) else None,
        "avg_ret_pct": _pct(r.mean()) if len(r) else None,
        "median_ret_pct": _pct(r.median()) if len(r) else None,
        "avg_win_pct": _pct(wins.mean()) if len(wins) else None,
        "avg_loss_pct": _pct(losses.mean()) if len(losses) else None,
        "profit_factor": round(wins.sum() / loss_sum, 3) if loss_sum > 0 else None,
        "avg_r": _round(trades["r_multiple"].mean()),
        "avg_days": _round(trades["days"].mean(), 1),
        "avg_mkt_ret_pct": _pct(trades["mkt_ret"].mean()),
        "avg_excess_pct": _pct(trades["pnl"].mean()),
        "excess_win_rate_pct": _pct((trades["pnl"].dropna() > 0).mean()) if trades["pnl"].notna().any() else None,
    }


def summary_sheet(trades, skipped):
    rows = []
    for clock, n_skipped in skipped.items():
        t = trades[trades["clock"] == clock] if not trades.empty else trades
        row = {"clock": clock, **(metrics(t) if len(t) else {"trades": 0}),
               "skipped_stop_through_entry": n_skipped}
        rows.append(row)
    return pd.DataFrame(rows)


def eras_sheet(trades, eras):
    rows = []
    if trades.empty:
        return pd.DataFrame(rows)
    for clock in trades["clock"].unique():
        for name, span in eras.items():
            start, end = (pd.Timestamp(x) for x in span.split("/"))
            t = trades[(trades["clock"] == clock) & trades["entry"].between(start, end)]
            rows.append({"clock": clock, "era": name, "from": start.date(), "to": end.date(),
                         **(metrics(t) if len(t) else {"trades": 0})})
    return pd.DataFrame(rows)


def per_stock_sheet(trades):
    if trades.empty:
        return pd.DataFrame()
    grouped = trades.groupby(["clock", "asset"])
    out = pd.DataFrame({
        "trades": grouped.size(),
        "win_rate_pct": grouped["raw_ret"].apply(lambda r: _pct((r > 0).mean())),
        "avg_ret_pct": grouped["raw_ret"].mean().map(_pct),
        "sum_ret_pct": grouped["raw_ret"].sum().map(_pct),
        "avg_r": grouped["r_multiple"].mean().round(3),
    })
    return out.reset_index().sort_values(["clock", "sum_ret_pct"], ascending=[True, False])


def conditions_sheet(counts):
    rows = [{"clock": clock, "condition": cid, "stock_days_true": n} for (clock, cid), n in counts.items()]
    return pd.DataFrame(rows)


def run_sheet(run_info, notes):
    rows = [{"item": k, "value": v} for k, v in run_info.items()]
    rows += [{"item": "not applied", "value": note} for note in notes]
    return pd.DataFrame(rows)


def spec_sheet(spec_path):
    if not spec_path:
        return pd.DataFrame([{"path": "(spec.json not found next to the strategy file)", "value": ""}])
    with open(spec_path) as f:
        spec = json.load(f)
    return pd.DataFrame([{"path": p, "value": str(v)[:EXCEL_TEXT_LIMIT]} for p, v in _flatten(spec)])


def write_report(path, trades, run_info, notes, counts, skipped, eras, spec_path):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    if trades.empty:
        trades = pd.DataFrame(columns=TRADE_COLUMNS)
    trade_view = trades[[c for c in TRADE_COLUMNS if c in trades.columns]].sort_values(["clock", "entry"])
    with pd.ExcelWriter(path, engine="openpyxl") as xl:
        summary_sheet(trades, skipped).to_excel(xl, sheet_name="Summary", index=False)
        eras_sheet(trades, eras).to_excel(xl, sheet_name="Eras", index=False)
        trade_view.to_excel(xl, sheet_name="Trades", index=False)
        per_stock_sheet(trades).to_excel(xl, sheet_name="Per_stock", index=False)
        conditions_sheet(counts).to_excel(xl, sheet_name="Conditions", index=False)
        run_sheet(run_info, notes).to_excel(xl, sheet_name="Run", index=False)
        spec_sheet(spec_path).to_excel(xl, sheet_name="Spec", index=False)
    return path


def _flatten(value, prefix=""):
    if isinstance(value, dict):
        for k, v in value.items():
            yield from _flatten(v, f"{prefix}.{k}" if prefix else k)
    elif isinstance(value, list) and any(isinstance(v, (dict, list)) for v in value):
        for i, v in enumerate(value):
            yield from _flatten(v, f"{prefix}[{i}]")
    elif isinstance(value, list):
        yield prefix, "; ".join(map(str, value))
    else:
        yield prefix, value


def _pct(x):
    return round(float(x) * 100, 3) if x is not None and np.isfinite(x) else None


def _round(x, digits=3):
    return round(float(x), digits) if x is not None and np.isfinite(x) else None
