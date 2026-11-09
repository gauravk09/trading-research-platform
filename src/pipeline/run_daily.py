"""
run_daily.py — Full daily EOD update: prices + all NSE data + dashboard rebuild

Run manually:
    PYTHONPATH=src python -m pipeline.run_daily

Or triggered via the /eod-update skill every day at 10 PM IST.

Steps (numbering matches the [x/9] progress prints):
  1. Incremental OHLCV from Kite + NSE Bhavcopy + price reconciliation
  2. NSE supplementary data: FII/DII, bulk/block deals, F&O list (monthly),
     earnings calendar (forthcoming results dates)
  3. Corporate announcements
  4. Quarterly financials (new filings only)
  5. Index closes + rebuild dashboard summary (precompute, incl. mm_history
     and market_rhythm)
  6. Split/bonus integrity check (re-runs precompute if repairs land), then
     PIT market-cap refresh (dilution factor + pit_mcap features)
  7. Daily state file
  8. Forward-return grader (grade_decisions)
  9. S7 verdict (s7_verdict): per-scan forward-record read-out + decay tripwire
"""

import sys
import os
from datetime import date

from data_collection.kite.updater import run as run_updater, last_completed_session
from data_collection.nse.fii_dii import download_fii_dii
from data_collection.nse.bulk_deals import download_bulk_deals, update as update_bulk_deals
from data_collection.nse.stock_oi import update as update_stock_oi
from data_collection.nse.insider_trading import update as update_insider
from data_collection.nse.shareholding import update as update_shareholding
from data_collection.other.mf_holdings import update as update_mf_holdings
from data_collection.nse.delivery import update as update_delivery
from data_collection.nse.earnings_calendar import update as update_earnings_calendar
from data_collection.nse.announcements import get_announcements_for_universe
from data_collection.nse.fo import download_fo_list
from data_collection.nse.universe import get_all_nse_eq_symbols
from data_collection.kite.index_history import update as update_indices
from preprocessing.precompute import run as run_precompute
from data_collection.other.company_master import refresh as refresh_company_master
from data_collection.nse.bonus import build_bonus_events
from backtest.shares_history import refresh as refresh_pit_mcap
from pipeline.daily_state import run as run_daily_state
from backtest.integrity import repair_recent_breaks
from data_collection.nse.update_financials import run as run_financials
from evaluation.grade_decisions import run as run_grader
from evaluation.s7_verdict import run as run_s7_verdict
from magic_formula import auto_import as auto_import_magic_formula


def run():
    print("=" * 60)
    print("FULL EOD UPDATE")
    print("=" * 60)

    print("\n[1/9] Incremental OHLCV + Bhavcopy reconciliation...")
    try:
        run_updater()
    except RuntimeError as e:
        print(f"\nFATAL: {e}")
        sys.exit(1)

    print("\n[2/9] NSE supplementary data...")
    if last_completed_session() == date.today():
        download_fii_dii()
        download_bulk_deals()
    else:
        # Both NSE endpoints serve only the live day, and the files are named
        # by run date — a midday run would file stale data under today.
        print("  FII/DII + bulk-deal snapshots skipped until after the close")
    download_fo_list()  # cached monthly — no-op if already downloaded this month
    try:
        update_delivery()  # stock-level delivery %; idempotent, skips stored days
    except Exception as e:
        print(f"  WARNING: delivery % fetch failed: {e}")
    try:
        update_bulk_deals()  # rolling bulk/block deals parquet; forward-only, idempotent
    except Exception as e:
        print(f"  WARNING: bulk/block deals store update failed: {e}")
    try:
        update_stock_oi()  # per-stock options/futures OI + PCR; idempotent, skips stored days
    except Exception as e:
        print(f"  WARNING: stock OI fetch failed: {e}")
    try:
        update_insider()  # SEBI PIT insider/promoter buys+sells; keyed to disclosure date
    except Exception as e:
        print(f"  WARNING: insider trading fetch failed: {e}")
    try:
        update_shareholding()  # quarterly promoter/FII/DII/MF % + pledge; keyed to disclosure date
    except Exception as e:
        print(f"  WARNING: shareholding pattern fetch failed: {e}")
    try:
        update_mf_holdings()  # monthly MF portfolio holdings; idempotent, no-op until new month
    except Exception as e:
        print(f"  WARNING: MF holdings fetch failed: {e}")
    try:
        update_earnings_calendar()
    except Exception as e:
        # Rolling store keeps yesterday's dates usable when NSE hiccups.
        print(f"  WARNING: earnings calendar fetch failed: {e}")
    try:
        build_bonus_events()  # bonus factors that PIT mcap strips from dilution
    except Exception as e:
        print(f"  WARNING: bonus events fetch failed (PIT mcap reuses "
              f"previous bonus_events): {e}")

    print("\n[3/9] Corporate announcements...")
    symbols = get_all_nse_eq_symbols()
    ann = get_announcements_for_universe(symbols)
    if not ann.empty and "category" in ann.columns:
        print(ann["category"].value_counts().to_string())

    print("\n[4/9] Quarterly financials (new filings)...")
    try:
        run_financials()
    except Exception as e:
        # Results feed can be flaky — never block the price update over it.
        print(f"  WARNING: financials update failed: {e}")

    print("\n[5/9] Index closes + rebuilding dashboard summary...")
    try:
        # Before precompute: tonight's summary uses fresh shares_out for mcap.
        refresh_company_master()
    except Exception as e:
        print(f"  WARNING: company master refresh failed (mcap uses "
              f"previous shares_out): {e}")
    try:
        # Before precompute: mm_history (built inside precompute) consumes the
        # index files for TI65 analog features and index forward returns.
        update_indices()
    except Exception as e:
        print(f"  WARNING: index update failed (mm_history will reuse "
              f"yesterday's index files): {e}")
    run_precompute()
    try:
        # Recognizes a Screener export by its columns, imports it only when the
        # file content changes, then advances the local technical overlay.
        result = auto_import_magic_formula(
            os.environ.get("SCREENER_EXPORT_DIR", os.path.expanduser("~/Downloads")),
            as_of=last_completed_session().isoformat(),
        )
        if result.get("board_path"):
            action = "imported + refreshed" if result.get("auto_imported") else "refreshed"
            print(f"  Magic Formula board {action}")
        else:
            print(f"  Magic Formula: {result.get('message')}")
    except Exception as e:
        print(f"  WARNING: Magic Formula auto-import failed: {e}")

    print("\n[6/9] Split/bonus integrity check...")
    try:
        # Needs the close matrix precompute just rebuilt; when repairs land,
        # precompute runs again so tonight's summary uses the healed data.
        if repair_recent_breaks() > 0:
            print("  Repairs applied — rebuilding summary on clean data...")
            run_precompute()
    except Exception as e:
        print(f"  WARNING: integrity check failed: {e}")

    try:
        # PIT mcap: needs the healed close matrix + fresh shares_out/bonus feed.
        refresh_pit_mcap()
    except Exception as e:
        print(f"  WARNING: PIT mcap refresh failed (features keep previous "
              f"values): {e}")

    print("\n[7/9] Writing daily state file...")
    try:
        run_daily_state()
    except Exception as e:
        # State file is downstream convenience — never fail the data update over it.
        print(f"  WARNING: daily state failed: {e}")

    print("\n[8/9] Grading recorded decisions (forward returns)...")
    try:
        run_grader()
    except Exception as e:
        print(f"  WARNING: decision grader failed: {e}")

    print("\n[9/9] S7 verdict (forward-record read-out)...")
    try:
        run_s7_verdict()
    except Exception as e:
        # The record and its grading survive; only tonight's verdict misses.
        print(f"  WARNING: S7 verdict failed: {e}")

    print("\n" + "=" * 60)
    print("EOD update complete. Dashboard is ready.")
    print("=" * 60)


if __name__ == "__main__":
    run()
