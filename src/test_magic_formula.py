import numpy as np
import pandas as pd
import magic_formula as mf

from magic_formula import (
    MagicFormulaConfig,
    build_snapshot,
    discover_latest_export,
    is_magic_formula_export,
    normalize_screener_export,
)


def _prices(start=100.0, end=200.0, periods=300):
    return pd.DataFrame({
        "date": pd.date_range("2024-01-01", periods=periods, freq="B"),
        "close": np.linspace(start, end, periods),
    })


def test_normalizes_screener_headings():
    raw = pd.DataFrame({
        "NSE Code": ["abc"],
        "Company": ["ABC Ltd"],
        "Industry": ["Engineering"],
        "Market Capitalization": [1500],
        "Enterprise Value to EBIT": [8.5],
        "Return on capital employed": [24.0],
    })
    result = normalize_screener_export(raw)
    assert result.loc[0, "symbol"] == "ABC"
    assert result.loc[0, "ev_ebit"] == 8.5
    assert result.loc[0, "roce"] == 24.0


def test_build_snapshot_ranks_and_applies_trend_gate():
    raw = pd.DataFrame({
        "NSE Code": ["CHEAP", "QUALITY", "BANK", "SMALL"],
        "Company": ["Cheap", "Quality", "Bank", "Small"],
        "Industry": ["Engineering", "Software", "Private Sector Bank", "Engineering"],
        "Market Capitalization": [2000, 3000, 5000, 500],
        "Enterprise Value to EBIT": [5, 10, 4, 3],
        "Return on capital employed": [20, 40, 50, 60],
    })
    price_map = {
        "CHEAP": _prices(100, 220),
        "QUALITY": _prices(220, 100),
    }
    config = MagicFormulaConfig(min_market_cap_cr=1000, min_avg_turnover_cr=0)
    board = build_snapshot(raw, "2025-03-01", lambda symbol: price_map.get(symbol, pd.DataFrame()), config)

    assert set(board["symbol"]) == {"CHEAP", "QUALITY"}
    cheap = board.set_index("symbol").loc["CHEAP"]
    quality = board.set_index("symbol").loc["QUALITY"]
    assert cheap["value_score"] > quality["value_score"]
    assert quality["quality_score"] > cheap["quality_score"]
    assert cheap["technical_state"] == "CONFIRMED"
    assert quality["technical_state"] == "WAITING_FOR_TREND"
    assert bool(cheap["is_candidate"])
    assert not bool(quality["is_candidate"])


def test_price_features_do_not_look_past_as_of():
    raw = pd.DataFrame({
        "NSE Code": ["REVERSAL"],
        "Market Capitalization": [2000],
        "Enterprise Value to EBIT": [7],
        "Return on capital employed": [30],
    })
    prices = _prices(100, 200, 300)
    future = pd.DataFrame({
        "date": pd.date_range(prices["date"].max() + pd.offsets.BDay(), periods=30, freq="B"),
        "close": np.linspace(200, 20, 30),
    })
    full = pd.concat([prices, future], ignore_index=True)
    cutoff = prices["date"].max()
    board = build_snapshot(raw, cutoff, lambda _: full, MagicFormulaConfig(min_avg_turnover_cr=0))
    row = board.iloc[0]
    assert row["price_as_of"] == cutoff.strftime("%Y-%m-%d")
    assert row["close"] == 200.0
    assert row["technical_state"] == "CONFIRMED"


def test_discovers_newest_matching_export(tmp_path):
    irrelevant = tmp_path / "other.csv"
    irrelevant.write_text("name,value\nfoo,1\n")
    older = tmp_path / "magic-old.csv"
    newer = tmp_path / "magic-new.csv"
    header = (
        "NSE Code,Market Capitalization,Enterprise Value to EBIT,"
        "Return on capital employed\n"
    )
    older.write_text(header + "OLD,2000,8,25\n")
    newer.write_text(header + "NEW,3000,9,30\n")
    older.touch()
    newer.touch()
    # Ensure a deterministic order even on coarse-mtime filesystems.
    import os
    os.utime(older, (1_700_000_000, 1_700_000_000))
    os.utime(newer, (1_800_000_000, 1_800_000_000))

    assert not is_magic_formula_export(irrelevant)
    assert is_magic_formula_export(older)
    assert discover_latest_export(tmp_path) == newer


def test_auto_import_only_archives_changed_content(tmp_path, monkeypatch):
    downloads = tmp_path / "downloads"
    raw_dir = tmp_path / "raw"
    processed_dir = tmp_path / "processed"
    downloads.mkdir()
    export = downloads / "screen.csv"
    export.write_text(
        "NSE Code,Company,Industry,Market Capitalization,"
        "Enterprise Value to EBIT,Return on capital employed\n"
        "TEST,Test Ltd,Engineering,2500,8,30\n"
    )
    monkeypatch.setattr(mf, "RAW_DIR", raw_dir)
    monkeypatch.setattr(mf, "PROCESSED_DIR", processed_dir)
    monkeypatch.setattr(mf, "LATEST_META", processed_dir / "latest.json")
    monkeypatch.setattr(mf, "UNIVERSE_SUMMARY", tmp_path / "missing.parquet")
    monkeypatch.setattr(mf, "read_daily", lambda *_args, **_kwargs: _prices())

    first = mf.auto_import(downloads, as_of="2025-03-01", config=MagicFormulaConfig(min_avg_turnover_cr=0))
    second = mf.auto_import(downloads, as_of="2025-03-01", config=MagicFormulaConfig(min_avg_turnover_cr=0))

    assert first["auto_imported"] is True
    assert second["auto_imported"] is False
    assert len(list(raw_dir.glob("*.csv"))) == 1
    assert (processed_dir / "latest.json").exists()
