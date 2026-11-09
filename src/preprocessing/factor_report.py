"""factor_report.py — print the factor-model read-out for today's universe.

Run:  PYTHONPATH=src python -m preprocessing.factor_report
"""

import os

import pandas as pd

from data_collection.paths import ROOT_DIR
from indicators import factor_model
from preprocessing.build_sector_map import load_sector_map


def report() -> str:
    cm = pd.read_parquet(os.path.join(ROOT_DIR, "data", "processed", "close_matrix.parquet"))
    lines = ["Factor model — hidden forces in the universe"]

    ser = factor_model.absorption_series(cm)
    if not ser.empty:
        cur = ser.iloc[-1]
        pct = float((ser <= cur).mean() * 100)
        lines.append(f"\n#1  Absorption ratio (PC1 crowding): {cur * 100:.1f}% of variance "
                     f"in one force — {pct:.0f}th percentile of the last {len(ser)} readings.")
        lines.append("     High = crowded/fragile (breakouts fail together); "
                     "low = healthy dispersion (stock-picking rewarded).")
        # RMT count on the latest window of the liquid basket.
        px = factor_model._liquid_basket(cm, 250, 63 + 260)
        latest = px.pct_change(fill_method=None).iloc[-63:].dropna(axis=1)
        nf = factor_model.n_significant_factors(latest)
        lines.append(f"     Marchenko-Pastur: {nf} eigenvalue(s) clear the noise band "
                     f"today — {latest.shape[1]} names, {latest.shape[0]}-day window.")

    rm = factor_model.residual_momentum(cm, load_sector_map())
    if not rm.empty:
        top = rm.sort_values(ascending=False).head(10)
        lines.append("\n#2  Residual (idiosyncratic) momentum — strongest AFTER removing "
                     "market + sector, last 63 sessions:")
        for sym, val in top.items():
            lines.append(f"     {sym:<14} {val * 100:+6.1f}% residual")
    return "\n".join(lines)


if __name__ == "__main__":
    print(report())
