"""Focused longitudinal study of SBI Contra Fund.

The study uses monthly full-portfolio disclosures and deliberately analyses
portfolio *weights*, not raw share-count changes across companies.  Weight changes
are still snapshot changes (not exact trades), and price effects begin only after
the conservative disclosure-availability date.

Run a five-year backfill::

    python src/fund_behavior_study.py collect 5
"""

from __future__ import annotations

import calendar
import io
import os
import sys
import zipfile
from datetime import date, timedelta
from functools import lru_cache

import numpy as np
import pandas as pd
import requests

from mf_holdings import HEADERS, _isin_symbol_map, _parse_sheet, _sbi_url, _scheme_name
from storage import read_daily


ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
STORE = os.path.join(ROOT, "data", "processed", "fund_study_sbi_contra.parquet")
BENCHMARK = os.path.join(ROOT, "data", "parquet", "indices", "nifty500.parquet")
FUND_ID = "mf:sbi:sbi-contra-fund"
FUND_NAME = "SBI Contra Fund"


def _month_end(year: int, month: int) -> pd.Timestamp:
    return pd.Timestamp(date(year, month, calendar.monthrange(year, month)[1]),
                        tz="Asia/Kolkata")


def download_month(year: int, month: int) -> pd.DataFrame:
    """Download only the SBI Contra sheet from a consolidated SBI workbook."""
    response = requests.get(_sbi_url(year, month), headers=HEADERS, timeout=60)
    if response.status_code != 200 or len(response.content) < 100_000:
        return pd.DataFrame()
    try:
        with zipfile.ZipFile(io.BytesIO(response.content)):
            pass
        book = pd.ExcelFile(io.BytesIO(response.content))
    except (zipfile.BadZipFile, ValueError):
        return pd.DataFrame()

    candidates = [sheet for sheet in book.sheet_names if sheet.upper() == "SCF"]
    if not candidates:
        for sheet in book.sheet_names:
            preview = book.parse(sheet, header=None, nrows=12)
            if "contra fund" in _scheme_name(preview, "").lower():
                candidates.append(sheet)
                break
    if not candidates:
        return pd.DataFrame()

    raw = book.parse(candidates[0], header=None)
    parsed = _parse_sheet(raw)
    if parsed.empty:
        return parsed
    parsed["symbol"] = parsed["isin"].map(_isin_symbol_map())
    parsed = parsed.dropna(subset=["symbol"])
    if parsed.empty:
        return parsed
    grouped = (parsed.groupby("symbol")
               .agg(holding_qty=("holding_qty", "sum"),
                    holding_value_cr=("value_lakh", lambda x: x.sum() / 100.0))
               .reset_index())
    month_end = _month_end(year, month)
    grouped.insert(0, "disclosure_date", month_end + pd.Timedelta(days=10))
    grouped.insert(0, "month", month_end)
    grouped["fund_id"] = FUND_ID
    grouped["fund_name"] = FUND_NAME
    return grouped


def collect(years: int = 5) -> pd.DataFrame:
    """Incrementally collect completed months, newest first."""
    os.makedirs(os.path.dirname(STORE), exist_ok=True)
    existing = pd.read_parquet(STORE) if os.path.exists(STORE) else pd.DataFrame()
    have = set(pd.to_datetime(existing.get("month", pd.Series(dtype="datetime64[ns]")))
               .dt.strftime("%Y-%m")) if not existing.empty else set()
    latest = date.today().replace(day=1) - timedelta(days=1)
    cursor = latest.replace(day=1)
    months = []
    for _ in range(max(1, years * 12)):
        months.append((cursor.year, cursor.month))
        cursor = (cursor - timedelta(days=1)).replace(day=1)
    frames = []
    for year, month in months:
        key = f"{year:04d}-{month:02d}"
        if key in have:
            continue
        try:
            frame = download_month(year, month)
        except Exception as exc:  # noqa: BLE001 - source month failures are non-fatal
            print(f"  {key}: failed ({type(exc).__name__})", flush=True)
            continue
        if frame.empty:
            print(f"  {key}: unavailable", flush=True)
            continue
        frames.append(frame)
        print(f"  {key}: {len(frame)} equities", flush=True)
    if frames:
        combined = pd.concat([existing] + frames, ignore_index=True) \
            if not existing.empty else pd.concat(frames, ignore_index=True)
        combined = (combined.drop_duplicates(["month", "symbol"], keep="last")
                    .sort_values(["month", "symbol"]).reset_index(drop=True))
        combined.to_parquet(STORE, compression="snappy")
    else:
        combined = existing
    print(f"  stored {combined['month'].nunique() if not combined.empty else 0} months", flush=True)
    return combined


def load() -> pd.DataFrame:
    if not os.path.exists(STORE):
        return pd.DataFrame()
    frame = pd.read_parquet(STORE)
    frame["month"] = pd.to_datetime(frame["month"])
    frame["disclosure_date"] = pd.to_datetime(frame["disclosure_date"])
    return frame.sort_values(["month", "symbol"]).reset_index(drop=True)


def panel(years: int | None = None) -> pd.DataFrame:
    """Complete month × stock panel with weights and snapshot changes."""
    raw = load()
    if raw.empty:
        return raw
    if years:
        cutoff = raw["month"].max() - pd.DateOffset(years=years) + pd.DateOffset(days=1)
        raw = raw[raw["month"] >= cutoff]
    months = raw[["month", "disclosure_date"]].drop_duplicates("month")
    grid = pd.MultiIndex.from_product(
        [months["month"], raw["symbol"].unique()], names=["month", "symbol"]
    ).to_frame(index=False)
    out = grid.merge(raw, on=["month", "symbol"], how="left")
    out["disclosure_date"] = out["month"].map(months.set_index("month")["disclosure_date"])
    out["holding_qty"] = out["holding_qty"].fillna(0.0)
    out["holding_value_cr"] = out["holding_value_cr"].fillna(0.0)
    totals = out.groupby("month")["holding_value_cr"].transform("sum")
    out["weight"] = np.where(totals > 0, out["holding_value_cr"] / totals, 0.0)
    out = out.sort_values(["symbol", "month"])
    grouped = out.groupby("symbol", sort=False)
    out["previous_weight"] = grouped["weight"].shift()
    out["delta_weight"] = out["weight"] - out["previous_weight"]
    out["previous_qty"] = grouped["holding_qty"].shift()
    out["change_kind"] = np.select(
        [out["previous_qty"].isna(),
         out["previous_qty"].eq(0) & out["holding_qty"].gt(0),
         out["previous_qty"].gt(0) & out["holding_qty"].eq(0),
         out["delta_weight"] > 0, out["delta_weight"] < 0],
        ["first_observed", "entry", "exit", "add", "trim"], default="unchanged",
    )
    return out.sort_values(["month", "symbol"]).reset_index(drop=True)


@lru_cache(maxsize=1000)
def _price_frame(symbol: str) -> pd.DataFrame:
    return read_daily(symbol, columns=["date", "close"])


def _return_after(symbol: str, disclosure: pd.Timestamp, horizons=(1, 5, 20, 60)) -> dict:
    prices = _price_frame(symbol).copy()
    if prices.empty:
        return {}
    prices = prices.sort_values("date").copy()
    prices["day"] = pd.to_datetime(prices["date"]).dt.tz_localize(None).dt.normalize()
    disclosed = pd.Timestamp(disclosure).tz_localize(None) if pd.Timestamp(disclosure).tzinfo \
        else pd.Timestamp(disclosure)
    # Month-end + 10 is a conservative end-of-day availability assumption.
    eligible = disclosed.normalize() + pd.Timedelta(days=1)
    future = prices[prices["day"] >= eligible]
    prior = prices[prices["day"] < eligible]
    if future.empty or prior.empty:
        return {}
    start = prices.index.get_loc(future.index[0])
    base = float(prior.iloc[-1]["close"])
    result = {"event_session": prices.iloc[start]["day"]}
    for horizon in horizons:
        end = start + horizon - 1
        result[f"return_{horizon}d"] = float(prices.iloc[end]["close"] / base - 1) \
            if end < len(prices) else np.nan
    return result


def event_study(years: int = 3, min_weight_change_bps: float = 10.0) -> pd.DataFrame:
    """Company-month events and Nifty 500-adjusted post-disclosure returns."""
    data = panel(years)
    if data.empty:
        return data
    threshold = min_weight_change_bps / 10_000.0
    events = data[
        data["previous_weight"].notna()
        & ((data["delta_weight"].abs() >= threshold)
           | data["change_kind"].isin(["entry", "exit"]))
    ]
    benchmark = pd.read_parquet(BENCHMARK) if os.path.exists(BENCHMARK) else pd.DataFrame()
    benchmark_cache = {}
    rows = []
    for event in events.itertuples(index=False):
        stock = _return_after(event.symbol, event.disclosure_date)
        if not stock:
            continue
        key = pd.Timestamp(event.disclosure_date)
        if key not in benchmark_cache and not benchmark.empty:
            b = benchmark.copy()
            b["date"] = pd.to_datetime(b["date"])
            # Inline benchmark equivalent; no filesystem mutation.
            disclosed = key.tz_localize(None) if key.tzinfo else key
            b["day"] = b["date"].dt.tz_localize(None).dt.normalize()
            eligible = disclosed.normalize() + pd.Timedelta(days=1)
            future, prior = b[b["day"] >= eligible], b[b["day"] < eligible]
            result = {}
            if not future.empty and not prior.empty:
                start = b.index.get_loc(future.index[0])
                base = float(prior.iloc[-1]["close"])
                for horizon in (1, 5, 20, 60):
                    end = start + horizon - 1
                    result[f"return_{horizon}d"] = float(b.iloc[end]["close"] / base - 1) \
                        if end < len(b) else np.nan
            benchmark_cache[key] = result
        bench = benchmark_cache.get(key, {})
        row = {
            "month": event.month, "disclosure_date": event.disclosure_date,
            "symbol": event.symbol, "change_kind": event.change_kind,
            "weight": event.weight, "delta_weight": event.delta_weight,
            "event_session": stock.get("event_session"),
        }
        direction = 1.0 if event.delta_weight > 0 else -1.0
        for horizon in (1, 5, 20, 60):
            abnormal = stock.get(f"return_{horizon}d", np.nan) \
                - bench.get(f"return_{horizon}d", np.nan)
            row[f"abnormal_{horizon}d"] = abnormal
            row[f"signed_abnormal_{horizon}d"] = direction * abnormal
        rows.append(row)
    return pd.DataFrame(rows)


def _current_tenure(group: pd.DataFrame) -> int:
    active = group.sort_values("month")["weight"].gt(0).tolist()
    count = 0
    for value in reversed(active):
        if not value:
            break
        count += 1
    return count


def build_study(years: int = 3) -> dict:
    """JSON-ready research dataset for the standalone dashboard."""
    years = int(np.clip(years, 1, 5))
    data = panel(years)
    if data.empty:
        return {"fund": FUND_NAME, "years": years, "error": "No study data collected"}
    observed_months = sorted(data["month"].drop_duplicates())
    latest_month = observed_months[-1]
    latest = data[data["month"].eq(latest_month)].copy()
    latest = latest[latest["weight"] > 0]

    monthly_rows = []
    for month, group in data.groupby("month", sort=True):
        comparable = group[group["previous_weight"].notna()]
        monthly_rows.append({
            "month": month,
            "equity_value_cr": group["holding_value_cr"].sum(),
            "stock_count": int((group["weight"] > 0).sum()),
            "hhi": float((group["weight"] ** 2).sum()),
            "positions_added": int((comparable["delta_weight"] > 0).sum()),
            "positions_trimmed": int((comparable["delta_weight"] < 0).sum()),
            "entries": int((comparable["change_kind"] == "entry").sum()),
            "exits": int((comparable["change_kind"] == "exit").sum()),
            "turnover_proxy": float(comparable["delta_weight"].abs().sum() / 2),
        })

    companies = []
    for symbol, group in data.groupby("symbol", sort=False):
        last = group.iloc[-1]
        comparable = group[group["previous_weight"].notna()]
        companies.append({
            "symbol": symbol,
            "latest_weight": float(last["weight"]),
            "delta_weight": float(last["delta_weight"]) if pd.notna(last["delta_weight"]) else None,
            "latest_value_cr": float(last["holding_value_cr"]),
            "active_months": int((group["weight"] > 0).sum()),
            "current_tenure_months": _current_tenure(group),
            "adds": int((comparable["delta_weight"] > 0).sum()),
            "trims": int((comparable["delta_weight"] < 0).sum()),
            "entries": int((comparable["change_kind"] == "entry").sum()),
            "exits": int((comparable["change_kind"] == "exit").sum()),
        })
    companies = sorted(companies, key=lambda row: row["latest_weight"], reverse=True)

    events = event_study(years)
    effects = []
    if not events.empty:
        for horizon in (1, 5, 20, 60):
            column = f"signed_abnormal_{horizon}d"
            values = events[column].dropna()
            n = len(values)
            std = values.std(ddof=1) if n > 1 else np.nan
            mean = values.mean() if n else np.nan
            effects.append({
                "horizon": horizon,
                "n": n,
                "mean": mean,
                "median": values.median() if n else np.nan,
                "positive_rate": (values > 0).mean() if n else np.nan,
                "t_stat": mean / (std / np.sqrt(n)) if n > 1 and std > 0 else np.nan,
            })
        company_effect = (events.groupby("symbol")
                          .agg(event_count=("symbol", "size"),
                               mean_signed_5d=("signed_abnormal_5d", "mean"),
                               mean_signed_20d=("signed_abnormal_20d", "mean"))
                          .reset_index())
        effect_map = company_effect.set_index("symbol").to_dict("index")
        for company in companies:
            company.update(effect_map.get(company["symbol"], {
                "event_count": 0, "mean_signed_5d": np.nan,
                "mean_signed_20d": np.nan,
            }))

    latest_active_tenures = [c["current_tenure_months"] for c in companies
                             if c["latest_weight"] > 0]
    latest_sorted = sorted(companies, key=lambda row: row["delta_weight"] or 0, reverse=True)
    return {
        "fund": FUND_NAME,
        "fund_id": FUND_ID,
        "years": years,
        "coverage": {
            "start": observed_months[0], "end": observed_months[-1],
            "months": len(observed_months),
        },
        "headline": {
            "equity_value_cr": float(latest["holding_value_cr"].sum()),
            "stock_count": len(latest),
            "hhi": float((latest["weight"] ** 2).sum()),
            "median_current_tenure_months": float(np.median(latest_active_tenures))
                if latest_active_tenures else np.nan,
            "latest_turnover_proxy": monthly_rows[-1]["turnover_proxy"],
        },
        "monthly": monthly_rows,
        "effects": effects,
        "companies": companies,
        "latest_additions": latest_sorted[:10],
        "latest_trims": list(reversed(latest_sorted[-10:])),
        "events": events.sort_values("disclosure_date", ascending=False).head(250)
            .to_dict("records") if not events.empty else [],
        "method": {
            "minimum_weight_change_bps": 10,
            "benchmark": "Nifty 500",
            "availability_lag_days": 10,
            "note": "Monthly snapshot changes are not exact dated trades. Price effects begin after disclosure availability.",
        },
    }


def company_study(symbol: str, years: int = 3) -> dict:
    symbol = symbol.strip().upper()
    data = panel(years)
    company = data[data["symbol"].eq(symbol)].copy()
    if company.empty:
        return {"symbol": symbol, "error": "Company not present in the selected window"}
    events = event_study(years)
    events = events[events["symbol"].eq(symbol)] if not events.empty else events
    return {
        "symbol": symbol,
        "history": company[["month", "weight", "delta_weight", "holding_value_cr",
                            "change_kind"]].to_dict("records"),
        "events": events.to_dict("records") if not events.empty else [],
    }


if __name__ == "__main__":
    if len(sys.argv) >= 2 and sys.argv[1] == "collect":
        collect(int(sys.argv[2]) if len(sys.argv) > 2 else 5)
    else:
        print(__doc__)
