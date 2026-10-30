"""
scanner.py — Qullamaggie master scanner

Runs all three setup scans and saves output to output/qullamaggie_YYYY-MM-DD.csv

Usage:
    python strategies/qullamaggie/scanner.py

Optional args:
    --setup breakout          run only the breakout scan
    --setup ep                run only the EP scan
    --setup parabolic         run only the parabolic scan
    --turnover 5              set min liquidity filter to ₹5 crore/day
    --rs-pct 60               set minimum RS percentile (default 60)
"""

import sys, os
import argparse
import pandas as pd
from datetime import date

# Allow imports from src/
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src"))

from storage import read_universe_close, list_stored_symbols
from nse_universe import get_all_nse_eq_symbols
from indicators.relative_strength import composite_rs_rank, residual_rs_rank
from filters.surveillance import reset_cache

import breakout as breakout_scanner
import episodic_pivot as ep_scanner
import parabolic as parabolic_scanner

OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "output")
os.makedirs(OUTPUT_DIR, exist_ok=True)


def build_ranks(symbols: list):
    """Composite RS + residual (idiosyncratic) RS ranks, from one universe read.

    Both are derived from the same wide close matrix so the expensive per-symbol
    parquet read happens once. Returns (rs_ranks, residual_ranks)."""
    print("  Computing RS + residual-RS ranks across universe...")
    close_wide = read_universe_close(symbols, start_date="2025-01-01")
    if close_wide.empty:
        return pd.Series(dtype=float), pd.Series(dtype=float)
    return composite_rs_rank(close_wide), residual_rs_rank(close_wide)


def save_output(df: pd.DataFrame, setup_name: str, today: str) -> str:
    """Save scan results to output directory. Returns the file path."""
    if df.empty:
        return None
    path = os.path.join(OUTPUT_DIR, f"qullamaggie_{setup_name}_{today}.csv")
    df.to_csv(path, index=False)
    return path


def print_summary(df: pd.DataFrame, setup_name: str) -> None:
    """Print a compact summary of scan results to the terminal."""
    if df.empty:
        print(f"  {setup_name}: No candidates found.")
        return

    print(f"\n  {'='*55}")
    print(f"  {setup_name.upper()} — {len(df)} candidates")
    print(f"  {'='*55}")

    display_cols = [c for c in ["symbol", "close", "r1mo_pct", "r3mo_pct",
                                 "adr_pct", "gap_pct", "vol_ratio",
                                 "r30d_pct", "residual_rs", "conviction"]
                    if c in df.columns]
    print(df[display_cols].head(20).to_string(index=False))


def run(
    setup:            str   = "all",
    min_turnover_cr:  float = 1.0,
    min_rs_pct:       float = 60.0,
    min_residual_pct: float = 80.0,
) -> dict:
    """
    Run the Qullamaggie scanner.

    Args:
        setup:            "all", "breakout", "ep", or "parabolic"
        min_turnover_cr:  liquidity filter — minimum ₹ crore/day average turnover
        min_rs_pct:       RS percentile cutoff for breakout scanner
        min_residual_pct: residual (idiosyncratic) RS cutoff for breakout scanner

    Returns:
        dict with keys "breakout", "ep", "parabolic" → each a DataFrame (may be empty)
    """
    today = date.today().isoformat()
    reset_cache()  # refresh ASM/GSM list at scan start

    print("="*60)
    print(f"QULLAMAGGIE SCANNER — {today}")
    print("="*60)

    print("\nLoading universe...")
    all_symbols   = list_stored_symbols()
    print(f"  Stored symbols: {len(all_symbols)}")

    results = {"breakout": pd.DataFrame(), "ep": pd.DataFrame(), "parabolic": pd.DataFrame()}

    # ── Setup 1: Breakout ──────────────────────────────────────
    if setup in ("all", "breakout"):
        print("\n[1/3] Breakout from Consolidation scan...")
        rs_ranks, residual_ranks = build_ranks(all_symbols)
        results["breakout"] = breakout_scanner.scan(
            symbols         = all_symbols,
            rs_ranks        = rs_ranks,
            residual_ranks  = residual_ranks,
            min_turnover_cr = min_turnover_cr,
            min_rs_pct      = min_rs_pct,
            min_residual_pct= min_residual_pct,
        )
        print_summary(results["breakout"], "Breakout")
        path = save_output(results["breakout"], "breakout", today)
        if path:
            print(f"\n  Saved → {path}")

    # ── Setup 2: Episodic Pivot ────────────────────────────────
    if setup in ("all", "ep"):
        print("\n[2/3] Episodic Pivot scan...")
        results["ep"] = ep_scanner.scan(
            symbols        = all_symbols,
            min_gap_pct    = 10.0,
            min_vol_ratio  = 2.0,
            min_turnover_cr= min_turnover_cr,
        )
        print_summary(results["ep"], "Episodic Pivot")
        path = save_output(results["ep"], "ep", today)
        if path:
            print(f"\n  Saved → {path}")

    # ── Setup 3: Parabolic ─────────────────────────────────────
    if setup in ("all", "parabolic"):
        print("\n[3/3] Parabolic Short / Long Bounce scan...")
        results["parabolic"] = parabolic_scanner.scan(
            symbols        = all_symbols,
            min_r30d_pct   = 100.0,
            min_drop_pct   = 50.0,
            min_turnover_cr= min_turnover_cr,
        )
        print_summary(results["parabolic"], "Parabolic")
        path = save_output(results["parabolic"], "parabolic", today)
        if path:
            print(f"\n  Saved → {path}")

    print(f"\n{'='*60}")
    print("Scan complete.")
    print(f"{'='*60}")

    return results


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--setup",    default="all",
                        choices=["all", "breakout", "ep", "parabolic"])
    parser.add_argument("--turnover", type=float, default=1.0,
                        help="Min avg daily turnover in ₹ crore (default 1.0)")
    parser.add_argument("--rs-pct",   type=float, default=60.0,
                        help="Min RS percentile for breakout scan (default 60)")
    parser.add_argument("--residual-pct", type=float, default=80.0,
                        help="Min residual (idiosyncratic) RS percentile for breakout "
                             "scan — filters sector-carried breakouts (default 80)")
    args = parser.parse_args()

    run(
        setup            = args.setup,
        min_turnover_cr  = args.turnover,
        min_rs_pct       = args.rs_pct,
        min_residual_pct = args.residual_pct,
    )
