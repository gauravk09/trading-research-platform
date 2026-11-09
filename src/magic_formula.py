"""Magic Formula fundamental import and technical-ranking pipeline.

Screener.in is the source of slow-moving fundamentals.  Local daily parquet
files are the source of point-in-time prices.  Every import is retained so a
current export is never silently treated as historical fundamental data.

Examples
--------
Import a fresh Screener export and build today's board::

    python src/magic_formula.py --input ~/Downloads/screener.csv

Refresh technicals from the most recent saved fundamental snapshot::

    python src/magic_formula.py --refresh
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
from dataclasses import asdict, dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Callable

import numpy as np
import pandas as pd

from data_collection.storage import read_daily


ROOT = Path(__file__).resolve().parents[1]
RAW_DIR = ROOT / "data" / "raw" / "magic_formula"
PROCESSED_DIR = ROOT / "data" / "processed" / "magic_formula"
LATEST_META = PROCESSED_DIR / "latest.json"
UNIVERSE_SUMMARY = ROOT / "data" / "processed" / "universe_summary.parquet"
DEFAULT_EXPORT_DIR = Path.home() / "Downloads"


@dataclass(frozen=True)
class MagicFormulaConfig:
    min_market_cap_cr: float = 1_000.0
    min_avg_turnover_cr: float = 1.0
    fundamental_weight: float = 0.60
    momentum_weight: float = 0.40
    min_price_sessions: int = 253


COLUMN_ALIASES = {
    "symbol": ("nse_code", "nsecode", "symbol", "ticker"),
    "name": ("company", "company_name", "name"),
    "industry": ("industry", "sector"),
    "market_cap_cr": ("market_capitalization", "market_cap", "mcap", "mcap_cr"),
    "ev_ebit": (
        "enterprise_value_to_ebit",
        "enterprise_value_ebit",
        "ev_ebit",
        "ev_to_ebit",
    ),
    "roce": ("return_on_capital_employed", "roce", "roce_percent"),
    "roce_3y": (
        "average_return_on_capital_employed_3years",
        "average_3years_return_on_capital_employed",
        "roce_3yr",
        "roce_3y",
    ),
    "debt_equity": ("debt_to_equity", "debt_equity"),
}

FINANCIAL_PATTERNS = (
    "bank",
    "finance",
    "financial",
    "insurance",
    "asset management",
    "stockbroking",
    "investment services",
    "housing finance",
)
UTILITY_PATTERNS = (
    "utility",
    "electricity generation",
    "electricity distribution",
    "power generation",
    "power distribution",
    "gas distribution",
)


def _slug(value: object) -> str:
    text = str(value).strip().lower().replace("%", " percent ")
    return re.sub(r"[^a-z0-9]+", "_", text).strip("_")


def _resolve_columns(frame: pd.DataFrame) -> dict[str, str]:
    available = {_slug(column): column for column in frame.columns}
    resolved: dict[str, str] = {}
    for canonical, aliases in COLUMN_ALIASES.items():
        for alias in aliases:
            if alias in available:
                resolved[canonical] = available[alias]
                break
    required = {"symbol", "market_cap_cr", "ev_ebit", "roce"}
    missing = sorted(required - resolved.keys())
    if missing:
        expected = ", ".join(sorted(required))
        raise ValueError(
            f"Screener export is missing required fields: {', '.join(missing)}. "
            f"Required canonical fields are: {expected}."
        )
    return resolved


def normalize_screener_export(frame: pd.DataFrame) -> pd.DataFrame:
    """Normalize the flexible column headings produced by Screener exports."""
    resolved = _resolve_columns(frame)
    out = pd.DataFrame(index=frame.index)
    for canonical, source in resolved.items():
        out[canonical] = frame[source]
    for optional in ("name", "industry", "roce_3y", "debt_equity"):
        if optional not in out:
            out[optional] = np.nan if optional not in {"name", "industry"} else ""

    out["symbol"] = (
        out["symbol"].fillna("").astype(str).str.strip().str.upper()
        .str.replace(r"\.0$", "", regex=True)
    )
    out["name"] = out["name"].fillna("").astype(str).str.strip()
    out["industry"] = out["industry"].fillna("").astype(str).str.strip()
    for column in ("market_cap_cr", "ev_ebit", "roce", "roce_3y", "debt_equity"):
        out[column] = pd.to_numeric(out[column], errors="coerce")
    return out.drop_duplicates("symbol", keep="first").reset_index(drop=True)


def _is_excluded_industry(industry: object) -> bool:
    value = str(industry).strip().lower()
    return any(pattern in value for pattern in FINANCIAL_PATTERNS + UTILITY_PATTERNS)


def _price_features(prices: pd.DataFrame, as_of: pd.Timestamp, minimum: int) -> dict:
    if prices.empty or "date" not in prices or "close" not in prices:
        return {"price_sessions": 0, "technical_state": "NO_PRICE_DATA"}
    data = prices[["date", "close"]].copy()
    data["date"] = pd.to_datetime(data["date"]).dt.tz_localize(None)
    data = data[data["date"] <= as_of.tz_localize(None)].dropna().sort_values("date")
    data = data.drop_duplicates("date", keep="last")
    if data.empty:
        return {"price_sessions": 0, "technical_state": "NO_PRICE_DATA"}

    closes = data["close"].astype(float)
    result = {
        "price_sessions": int(len(closes)),
        "price_as_of": data["date"].iloc[-1].strftime("%Y-%m-%d"),
        "close": float(closes.iloc[-1]),
        "sma50": float(closes.tail(50).mean()) if len(closes) >= 50 else np.nan,
        "sma200": float(closes.tail(200).mean()) if len(closes) >= 200 else np.nan,
        "momentum_12_1_pct": np.nan,
        "technical_state": "INSUFFICIENT_HISTORY",
    }
    if len(closes) >= minimum:
        # 12-1 momentum: performance from ~12 months ago to ~1 month ago.
        result["momentum_12_1_pct"] = float((closes.iloc[-22] / closes.iloc[-253] - 1) * 100)
        trend = closes.iloc[-1] > result["sma200"] and result["sma50"] > result["sma200"]
        result["technical_state"] = "CONFIRMED" if trend else "WAITING_FOR_TREND"
    return result


def _rank_score(values: pd.Series, higher_is_better: bool) -> pd.Series:
    if values.notna().sum() == 0:
        return pd.Series(np.nan, index=values.index)
    # Scores are intuitive: 100 is best, 0 is worst.
    ranks = values.rank(method="average", ascending=higher_is_better, na_option="keep")
    count = values.notna().sum()
    if count == 1:
        return ranks.where(values.isna(), 100.0)
    return ((ranks - 1) / (count - 1) * 100).round(1)


def build_snapshot(
    fundamentals: pd.DataFrame,
    as_of: str | date | pd.Timestamp,
    price_loader: Callable[[str], pd.DataFrame] | None = None,
    config: MagicFormulaConfig | None = None,
    universe_summary: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Blend one dated fundamental snapshot with prices available at ``as_of``."""
    config = config or MagicFormulaConfig()
    price_loader = price_loader or (lambda symbol: read_daily(symbol, columns=["date", "close"]))
    as_of_ts = pd.Timestamp(as_of)
    frame = normalize_screener_export(fundamentals)

    if universe_summary is not None and not universe_summary.empty:
        attach = [column for column in ("symbol", "avg_turnover_cr", "sector") if column in universe_summary]
        if "symbol" in attach:
            local = universe_summary[attach].drop_duplicates("symbol")
            frame = frame.merge(local, on="symbol", how="left", suffixes=("", "_local"))
            if "sector" in frame and "industry" in frame:
                frame["industry"] = frame["industry"].mask(frame["industry"].eq(""), frame["sector"])
    if "avg_turnover_cr" not in frame:
        frame["avg_turnover_cr"] = np.nan

    frame["excluded_industry"] = frame["industry"].map(_is_excluded_industry)
    frame = frame[
        frame["symbol"].ne("")
        & frame["market_cap_cr"].ge(config.min_market_cap_cr)
        & frame["ev_ebit"].gt(0)
        & frame["roce"].gt(0)
        & ~frame["excluded_industry"]
    ].copy()

    features = []
    for symbol in frame["symbol"]:
        item = {"symbol": symbol}
        item.update(_price_features(price_loader(symbol), as_of_ts, config.min_price_sessions))
        features.append(item)
    feature_frame = pd.DataFrame(features) if features else pd.DataFrame(columns=[
        "symbol", "price_sessions", "technical_state", "price_as_of", "close",
        "sma50", "sma200", "momentum_12_1_pct",
    ])
    frame = frame.merge(feature_frame, on="symbol", how="left")

    frame["value_score"] = _rank_score(frame["ev_ebit"], higher_is_better=False)
    frame["quality_score"] = _rank_score(frame["roce"], higher_is_better=True)
    frame["magic_score"] = frame[["value_score", "quality_score"]].mean(axis=1).round(1)
    frame["momentum_score"] = _rank_score(frame["momentum_12_1_pct"], higher_is_better=True)
    frame["blend_score"] = (
        config.fundamental_weight * frame["magic_score"]
        + config.momentum_weight * frame["momentum_score"]
    ).round(1)
    liquid = frame["avg_turnover_cr"].isna() | frame["avg_turnover_cr"].ge(config.min_avg_turnover_cr)
    frame["is_candidate"] = frame["technical_state"].eq("CONFIRMED") & liquid
    frame["candidate_rank"] = np.nan
    candidate_mask = frame["is_candidate"] & frame["blend_score"].notna()
    frame.loc[candidate_mask, "candidate_rank"] = (
        frame.loc[candidate_mask, "blend_score"].rank(method="first", ascending=False).astype(int)
    )
    frame["as_of"] = as_of_ts.strftime("%Y-%m-%d")
    return frame.sort_values(
        ["is_candidate", "blend_score", "magic_score"], ascending=[False, False, False], na_position="last"
    ).reset_index(drop=True)


def _load_universe_summary() -> pd.DataFrame | None:
    return pd.read_parquet(UNIVERSE_SUMMARY) if UNIVERSE_SUMMARY.exists() else None


def _latest_raw_path() -> Path:
    files = sorted(RAW_DIR.glob("*.csv"))
    if not files:
        raise FileNotFoundError(
            f"No saved Screener snapshots in {RAW_DIR}. Import a CSV with --input first."
        )
    return files[-1]


def file_sha256(path: str | os.PathLike) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def is_magic_formula_export(path: str | os.PathLike) -> bool:
    """Return True when a CSV exposes the minimum Screener columns we need."""
    candidate = Path(path)
    if candidate.suffix.lower() != ".csv" or not candidate.is_file():
        return False
    try:
        header = pd.read_csv(candidate, nrows=0)
        _resolve_columns(header)
        return True
    except (OSError, UnicodeError, pd.errors.ParserError, ValueError):
        return False


def discover_latest_export(watch_dir: str | os.PathLike = DEFAULT_EXPORT_DIR) -> Path | None:
    """Find the newest CSV whose header matches a Magic Formula export."""
    directory = Path(watch_dir).expanduser()
    if not directory.is_dir():
        return None
    candidates = sorted(
        directory.glob("*.csv"),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    return next((path for path in candidates if is_magic_formula_export(path)), None)


def run_pipeline(
    input_path: str | os.PathLike | None = None,
    as_of: str | None = None,
    refresh: bool = False,
    config: MagicFormulaConfig | None = None,
    snapshot_date: str | None = None,
    source_sha256: str | None = None,
) -> dict:
    """Import/refresh the board, persist it, and return dashboard metadata."""
    config = config or MagicFormulaConfig()
    as_of = as_of or date.today().isoformat()
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)

    if input_path:
        source = Path(input_path).expanduser().resolve()
        if not source.exists():
            raise FileNotFoundError(source)
        fundamentals_as_of = snapshot_date or as_of
        raw_path = RAW_DIR / f"{fundamentals_as_of}.csv"
        if source != raw_path:
            shutil.copy2(source, raw_path)
        source_sha256 = source_sha256 or file_sha256(source)
    elif refresh:
        raw_path = _latest_raw_path()
        fundamentals_as_of = raw_path.stem
        source_sha256 = source_sha256 or file_sha256(raw_path)
    else:
        raise ValueError("Provide --input CSV or use --refresh.")

    raw = pd.read_csv(raw_path)
    board = build_snapshot(raw, as_of, config=config, universe_summary=_load_universe_summary())
    board_path = PROCESSED_DIR / f"{as_of}.parquet"
    board.to_parquet(board_path, index=False)
    meta = {
        "fundamentals_as_of": fundamentals_as_of,
        "technicals_as_of": as_of,
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "raw_path": str(raw_path),
        "board_path": str(board_path),
        "source_sha256": source_sha256,
        "universe_count": int(len(board)),
        "candidate_count": int(board["is_candidate"].sum()),
        "confirmed_count": int(board["technical_state"].eq("CONFIRMED").sum()),
        "waiting_count": int(board["technical_state"].eq("WAITING_FOR_TREND").sum()),
        "insufficient_count": int(board["technical_state"].isin(["INSUFFICIENT_HISTORY", "NO_PRICE_DATA"]).sum()),
        "config": asdict(config),
    }
    LATEST_META.write_text(json.dumps(meta, indent=2) + "\n")
    return meta


def auto_import(
    watch_dir: str | os.PathLike = DEFAULT_EXPORT_DIR,
    as_of: str | None = None,
    config: MagicFormulaConfig | None = None,
) -> dict:
    """Import the newest changed Screener CSV, or refresh the saved snapshot.

    The export's filesystem modification date becomes its fundamental snapshot
    date.  The technical cutoff remains ``as_of`` (normally the latest EOD
    session), keeping those two clocks explicit.
    """
    as_of = as_of or date.today().isoformat()
    candidate = discover_latest_export(watch_dir)
    previous = {}
    if LATEST_META.exists():
        try:
            previous = json.loads(LATEST_META.read_text())
        except (OSError, json.JSONDecodeError):
            previous = {}

    if candidate is None:
        if any(RAW_DIR.glob("*.csv")):
            result = run_pipeline(refresh=True, as_of=as_of, config=config)
            return {**result, "auto_imported": False, "auto_source": None}
        return {
            "auto_imported": False,
            "auto_source": None,
            "message": f"No matching Screener CSV found in {Path(watch_dir).expanduser()}",
        }

    digest = file_sha256(candidate)
    if digest == previous.get("source_sha256") and Path(previous.get("raw_path", "")).exists():
        result = run_pipeline(refresh=True, as_of=as_of, config=config, source_sha256=digest)
        return {**result, "auto_imported": False, "auto_source": str(candidate)}

    snapshot_date = datetime.fromtimestamp(candidate.stat().st_mtime).astimezone().date().isoformat()
    previous_date = previous.get("fundamentals_as_of")
    if previous_date and snapshot_date < previous_date and any(RAW_DIR.glob("*.csv")):
        # An old matching CSV left in Downloads must never roll the fundamental
        # snapshot backwards after a newer file was imported elsewhere.
        result = run_pipeline(refresh=True, as_of=as_of, config=config)
        return {
            **result,
            "auto_imported": False,
            "auto_source": str(candidate),
            "auto_skip_reason": "older_than_current_snapshot",
        }
    result = run_pipeline(
        input_path=candidate,
        as_of=as_of,
        config=config,
        snapshot_date=snapshot_date,
        source_sha256=digest,
    )
    return {**result, "auto_imported": True, "auto_source": str(candidate)}


def load_latest_board() -> tuple[pd.DataFrame, dict]:
    if not LATEST_META.exists():
        raise FileNotFoundError("Magic Formula board has not been built yet.")
    meta = json.loads(LATEST_META.read_text())
    board_path = Path(meta["board_path"])
    if not board_path.exists():
        raise FileNotFoundError(board_path)
    return pd.read_parquet(board_path), meta


def main() -> None:
    parser = argparse.ArgumentParser(description="Blend a Screener Magic Formula export with local technicals.")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--input", help="Screener CSV export to import and retain")
    source.add_argument("--refresh", action="store_true", help="Reuse the newest retained Screener export")
    source.add_argument("--auto-import", action="store_true", help="Find and import the newest matching CSV")
    parser.add_argument("--as-of", help="Technical cutoff date (YYYY-MM-DD); defaults to today")
    parser.add_argument(
        "--watch-dir",
        default=os.environ.get("SCREENER_EXPORT_DIR", str(DEFAULT_EXPORT_DIR)),
        help="Folder scanned by --auto-import (default: ~/Downloads or SCREENER_EXPORT_DIR)",
    )
    parser.add_argument("--min-market-cap", type=float, default=1_000.0, help="Minimum market cap, ₹ crore")
    parser.add_argument("--min-turnover", type=float, default=1.0, help="Minimum average turnover, ₹ crore")
    args = parser.parse_args()
    config = MagicFormulaConfig(
        min_market_cap_cr=args.min_market_cap,
        min_avg_turnover_cr=args.min_turnover,
    )
    if args.auto_import:
        result = auto_import(args.watch_dir, args.as_of, config)
    else:
        result = run_pipeline(args.input, args.as_of, args.refresh, config)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
