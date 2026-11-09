"""export_excel.py — write a trades ledger + summary to a single .xlsx for the
Streamlit evaluator.

Key column: `pnl` = MARKET-NEUTRAL directional P&L = (leg return - equal-weight
universe return over the same window), signed by side. This reflects the factor's
cross-sectional bet; the raw close-to-close move (`raw_ret`) is beta-dominated and
misleading for a long/short factor, so it's kept only for reference.

Usage: python export_excel.py <factor_name>
  reads  backtest_reports/<factor>_trades.csv , summary.csv
  writes backtest_reports/<factor>_eval.xlsx  (sheets: Trades, Summary)
"""

import sys

import pandas as pd

from data import liquid_universe, load_panels

name = sys.argv[1]
base = "backtest_reports"
trades = pd.read_csv(f"{base}/{name}_trades.csv", parse_dates=["entry", "exit"])

# Equal-weight universe return over each trade's window = the "market" leg.
close, volume = load_panels()
uni = liquid_universe(close, volume, top=500, lookback=60)
daily = close.pct_change(fill_method=None).where(uni)
mkt_cum = (1 + daily.mean(axis=1)).cumprod()          # universe equal-weight index
cum = mkt_cum.reindex(close.index)

def mkt_ret(row):
    try:
        return cum.loc[row["exit"]] / cum.loc[row["entry"]] - 1
    except KeyError:
        return float("nan")

trades["raw_ret"] = trades["ret"]
trades["mkt_ret"] = trades.apply(mkt_ret, axis=1)
excess = trades["raw_ret"] - trades["mkt_ret"]
trades["pnl"] = excess.where(trades["side"] == "LONG", -excess)   # market-neutral, signed
trades = trades[["asset", "side", "entry", "exit", "days", "raw_ret", "mkt_ret", "pnl"]]
trades = trades.dropna(subset=["pnl"]).sort_values("exit").reset_index(drop=True)

out = f"{base}/{name}_eval.xlsx"
with pd.ExcelWriter(out, engine="openpyxl") as xl:
    trades.to_excel(xl, sheet_name="Trades", index=False)
    try:
        pd.read_csv(f"{base}/summary.csv").to_excel(xl, sheet_name="Summary", index=False)
    except FileNotFoundError:
        pass
print(f"{len(trades)} trades -> {out}")
print(f"market-neutral: win rate {(trades.pnl>0).mean()*100:.1f}%, "
      f"expectancy {trades.pnl.mean()*100:+.3f}%")
