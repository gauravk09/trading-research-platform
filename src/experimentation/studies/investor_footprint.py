"""Point-in-time investor holdings, accumulation, and disclosure-impact metrics.

This module deliberately separates three dates/concepts that are often mixed up:

* ``as_of_date``: when the reported position was measured;
* ``disclosure_date``: when the market could first know the position;
* ``delta_qty``: a change between two snapshots, not a dated trade.

Named public shareholders come from NSE Regulation 31 XBRL filings.  Mutual-fund
schemes come from the full monthly AMC workbooks collected by ``mf_holdings.py``.
The analytics accept either source after normalization to the schema documented in
``REQUIRED_COLUMNS``.

CLI examples::

    PYTHONPATH=src python -m experimentation.studies.investor_footprint collect-named 40
    PYTHONPATH=src python -m experimentation.studies.investor_footprint report "Ashish Kacholia"
    PYTHONPATH=src python -m experimentation.studies.investor_footprint report "Vijay Kedia"

The output is research data, not a reconstruction of exact trades.  Regulation 31
filings can omit a holder below the applicable reporting threshold, so first/last
appearances are explicitly marked as left/right censored.
"""

from __future__ import annotations

import math
import os

from data_collection.paths import ROOT_DIR
import re
import sys
import time
import unicodedata
import xml.etree.ElementTree as ET
from datetime import date, timedelta
from typing import Iterable

import numpy as np
import pandas as pd
import requests

from data_collection.nse.shareholding import HEADERS, download_master, _session
from data_collection.storage import read_daily


PROCESSED = os.path.join(ROOT_DIR, "data", "processed")
NAMED_HOLDINGS_STORE = os.path.join(PROCESSED, "named_investor_holdings.parquet")
NAMED_FILINGS_STORE = os.path.join(PROCESSED, "named_holdings_filings.parquet")
MF_SCHEME_STORE = os.path.join(PROCESSED, "mf_scheme_holdings.parquet")

REQUIRED_COLUMNS = [
    "investor_id", "investor_name", "investor_type", "symbol", "as_of_date",
    "disclosure_date", "holding_qty", "holding_pct", "source_type",
]

# Aliases are intentionally conservative.  A related person or family vehicle is
# not silently attributed to the headline investor.  Add audited aliases here as
# the source data reveals spelling variants.
INVESTOR_ALIASES = {
    "ASHISH KACHOLIA": ("ashish-kacholia", "Ashish Kacholia"),
    "KACHOLIA ASHISH": ("ashish-kacholia", "Ashish Kacholia"),
    "VIJAY KEDIA": ("vijay-kedia", "Vijay Kedia"),
    "VIJAY KISHANLAL KEDIA": ("vijay-kedia", "Vijay Kedia"),
    # Kept as its own investor/entity; reports can later roll it into a group.
    "KEDIA SECURITIES PRIVATE LIMITED": (
        "kedia-securities-private-limited", "Kedia Securities Private Limited"
    ),
    "KEDIA SECURITIES PVT LTD": (
        "kedia-securities-private-limited", "Kedia Securities Private Limited"
    ),
}


def normalize_name(value: str) -> str:
    """Upper-case, punctuation-insensitive shareholder name for stable matching."""
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(c for c in text if not unicodedata.combining(c))
    text = re.sub(r"[^A-Za-z0-9]+", " ", text.upper()).strip()
    return re.sub(r"\s+", " ", text)


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", normalize_name(value).lower()).strip("-")


def canonical_investor(value: str) -> tuple[str, str]:
    normalized = normalize_name(value)
    return INVESTOR_ALIASES.get(normalized, (_slug(normalized), normalized.title()))


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1].rsplit(":", 1)[-1]


def _context_values(root: ET.Element) -> dict[str, dict[str, str]]:
    out: dict[str, dict[str, str]] = {}
    for node in root.iter():
        context = node.attrib.get("contextRef")
        value = (node.text or "").strip()
        if context and value:
            out.setdefault(context, {})[_local_name(node.tag)] = value
    return out


def _matching_data_context(name_context: str, contexts: dict[str, dict[str, str]]) -> str | None:
    """Map XBRL's dimensional name context to the corresponding numeric context."""
    candidates = [name_context]
    if name_context.startswith("D_"):
        candidates.append(name_context[2:])
    # Some issuers add more than one dimensional marker.
    candidates.append(re.sub(r"^(?:D_)+", "", name_context))
    for candidate in candidates:
        values = contexts.get(candidate, {})
        if "NumberOfShares" in values or "NumberOfFullyPaidUpEquityShares" in values:
            return candidate
    # Last-resort suffix match keeps the row but remains deterministic.
    suffix = re.search(r"_Context\d+$", name_context)
    if suffix:
        matches = [c for c, v in contexts.items()
                   if c.endswith(suffix.group()) and "NumberOfShares" in v]
        if len(matches) == 1:
            return matches[0]
    return None


def _investor_type(holder_category: str) -> str:
    category = normalize_name(holder_category).replace(" ", "")
    if "NONPROMOTERNONPUBLIC" in category:
        return "non_promoter_non_public"
    if "PROMOTER" in category:
        return "promoter_or_promoter_group"
    if "SIGNIFICANTBENEFICIAL" in category:
        return "significant_beneficial_owner"
    return "named_public_shareholder"


def parse_named_holdings_xbrl(xml_text: str) -> pd.DataFrame:
    """Extract all explicitly named shareholders from one NSE/BSE taxonomy XBRL.

    Percentages in this taxonomy are stored as fractions (``0.0322`` = 3.22%).
    Aggregate category contexts do not contain ``NameOfTheShareholder`` and are
    therefore excluded.
    """
    columns = ["investor_id", "investor_name", "raw_investor_name", "investor_type",
               "holding_qty", "holding_pct", "holder_category"]
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return pd.DataFrame(columns=columns)
    contexts = _context_values(root)
    rows = []
    for name_context, values in contexts.items():
        raw_name = values.get("NameOfTheShareholder")
        if not raw_name:
            continue
        data_context = _matching_data_context(name_context, contexts)
        if not data_context:
            continue
        numeric = contexts[data_context]
        qty = pd.to_numeric(
            numeric.get("NumberOfShares", numeric.get("NumberOfFullyPaidUpEquityShares")),
            errors="coerce",
        )
        pct = pd.to_numeric(
            numeric.get("ShareholdingAsAPercentageOfTotalNumberOfShares"), errors="coerce"
        )
        investor_id, investor_name = canonical_investor(raw_name)
        holder_category = re.sub(r"_Context\d+$", "", data_context)
        rows.append({
            "investor_id": investor_id,
            "investor_name": investor_name,
            "raw_investor_name": raw_name.strip(),
            "investor_type": _investor_type(holder_category),
            "holding_qty": float(qty) if pd.notna(qty) else np.nan,
            "holding_pct": float(pct) * 100.0 if pd.notna(pct) else np.nan,
            "holder_category": holder_category,
        })
    if not rows:
        return pd.DataFrame(columns=columns)
    return pd.DataFrame(rows).drop_duplicates(
        subset=["investor_id", "holding_qty", "holding_pct", "holder_category"]
    ).reset_index(drop=True)


def _read_parquet(path: str) -> pd.DataFrame:
    return pd.read_parquet(path) if os.path.exists(path) else pd.DataFrame()


def collect_named_holdings(days: int = 40, pause: float = 0.15,
                           symbols: Iterable[str] | None = None) -> None:
    """Fetch new NSE filings and append their explicitly named shareholders.

    The filings ledger records successfully parsed filings even when no named holder
    exists.  This makes updates idempotent without interpreting absence as zero.
    """
    os.makedirs(PROCESSED, exist_ok=True)
    session = _session()
    master = download_master(date.today() - timedelta(days=days), date.today(), session)
    if symbols:
        wanted = {str(symbol).strip().upper() for symbol in symbols}
        master = master[master["symbol"].astype(str).str.upper().isin(wanted)]
    existing = _read_parquet(NAMED_HOLDINGS_STORE)
    filings = _read_parquet(NAMED_FILINGS_STORE)
    have = set(filings.get("record_id", pd.Series(dtype=str)).astype(str))
    fresh = master[~master["record_id"].astype(str).isin(have)].copy()
    if fresh.empty:
        print("  named investor holdings: up to date")
        return

    holding_frames, filing_rows = [], []
    failures = 0
    for row in fresh.itertuples(index=False):
        try:
            response = session.get(row.xbrl, headers=HEADERS, timeout=40)
            response.raise_for_status()
            parsed = parse_named_holdings_xbrl(response.text)
        except Exception:  # noqa: BLE001 - individual filing failure is retried next run
            failures += 1
            continue
        if not parsed.empty:
            parsed["symbol"] = str(row.symbol).strip().upper()
            parsed["as_of_date"] = row.as_of_date
            parsed["disclosure_date"] = row.disclosure_date
            parsed["source_type"] = "nse_reg31_xbrl"
            parsed["source_url"] = row.xbrl
            parsed["record_id"] = str(row.record_id)
            holding_frames.append(parsed)
        filing_rows.append({
            "record_id": str(row.record_id), "symbol": str(row.symbol).strip().upper(),
            "as_of_date": row.as_of_date, "disclosure_date": row.disclosure_date,
            "source_url": row.xbrl,
        })
        if pause:
            time.sleep(pause)

    if holding_frames:
        new_holdings = pd.concat(holding_frames, ignore_index=True)
        combined = pd.concat([existing, new_holdings], ignore_index=True) \
            if not existing.empty else new_holdings
        combined = combined.drop_duplicates(
            subset=["record_id", "investor_id", "holding_qty", "holder_category"],
            keep="last",
        ).sort_values(["as_of_date", "symbol", "investor_id"]).reset_index(drop=True)
        combined.to_parquet(NAMED_HOLDINGS_STORE, compression="snappy")
    if filing_rows:
        new_filings = pd.DataFrame(filing_rows)
        filings = pd.concat([filings, new_filings], ignore_index=True) \
            if not filings.empty else new_filings
        filings.drop_duplicates("record_id", keep="last") \
            .sort_values(["as_of_date", "symbol"]) \
            .to_parquet(NAMED_FILINGS_STORE, compression="snappy")
    print(f"  named investor holdings: parsed {len(filing_rows)} filings, "
          f"{sum(len(x) for x in holding_frames)} named rows, {failures} failures")


def load_normalized_holdings(include_named: bool = True, include_funds: bool = True) -> pd.DataFrame:
    """Load named investors and scheme-level mutual funds into one tidy schema."""
    frames = []
    if include_named:
        named = _read_parquet(NAMED_HOLDINGS_STORE)
        if not named.empty:
            # Reclassify older local rows created before holder categories were
            # separated; the XBRL category is the source of truth.
            if "holder_category" in named:
                named["investor_type"] = named["holder_category"].map(_investor_type)
            frames.append(named)
    if include_funds:
        funds = _read_parquet(MF_SCHEME_STORE)
        if not funds.empty:
            funds = funds.copy()
            funds["investor_id"] = "mf:" + funds["amc"].map(_slug) + ":" + funds["scheme"].map(_slug)
            funds["investor_name"] = funds["amc"] + " — " + funds["scheme"]
            funds["investor_type"] = "mutual_fund_scheme"
            funds["as_of_date"] = funds["month"]
            funds["holding_pct"] = np.nan
            funds["source_type"] = "amc_monthly_portfolio"
            frames.append(_complete_fund_panel(funds))
    if not frames:
        return pd.DataFrame(columns=REQUIRED_COLUMNS)
    out = pd.concat(frames, ignore_index=True, sort=False)
    for col in ("as_of_date", "disclosure_date"):
        out[col] = pd.to_datetime(out[col])
    return out.sort_values(["investor_id", "symbol", "as_of_date"]).reset_index(drop=True)


def _complete_fund_panel(funds: pd.DataFrame) -> pd.DataFrame:
    """Fill absent securities with zero inside each fully disclosed fund-month.

    Unlike named Regulation 31 shareholders, AMC workbooks disclose the complete
    scheme portfolio.  Absence in a month therefore means zero and allows genuine
    entry/exit detection.
    """
    frames = []
    for investor_id, group in funds.groupby("investor_id", sort=False):
        dates = group[["as_of_date", "disclosure_date"]].drop_duplicates("as_of_date")
        symbols = group["symbol"].dropna().unique()
        grid = pd.MultiIndex.from_product(
            [dates["as_of_date"], symbols], names=["as_of_date", "symbol"]
        ).to_frame(index=False)
        merged = grid.merge(group, on=["as_of_date", "symbol"], how="left",
                            suffixes=("", "_reported"))
        disclosure = dates.set_index("as_of_date")["disclosure_date"]
        merged["disclosure_date"] = merged["as_of_date"].map(disclosure)
        static = group.iloc[0]
        for col in ("investor_id", "investor_name", "investor_type", "source_type",
                    "amc", "scheme"):
            if col in group:
                merged[col] = merged[col].fillna(static[col]) if col in merged else static[col]
        for col in ("holding_qty", "holding_value_cr"):
            if col in merged:
                merged[col] = merged[col].fillna(0.0)
        if "holding_pct" not in merged:
            merged["holding_pct"] = np.nan
        frames.append(merged)
    return pd.concat(frames, ignore_index=True, sort=False) if frames else funds


def holding_changes(holdings: pd.DataFrame) -> pd.DataFrame:
    """Add snapshot deltas and inference flags without inventing exact trade dates."""
    missing = set(REQUIRED_COLUMNS) - set(holdings.columns)
    if missing:
        raise ValueError(f"holdings missing required columns: {sorted(missing)}")
    df = holdings.copy()
    df["as_of_date"] = pd.to_datetime(df["as_of_date"])
    df["disclosure_date"] = pd.to_datetime(df["disclosure_date"])
    df = df.sort_values(["investor_id", "symbol", "as_of_date", "disclosure_date"])
    # Revisions and alternate XBRL tables can repeat the same investor snapshot.
    # Prefer the largest explicitly reported position within a filing, then the
    # latest revision for a given as-of date.
    df = (df.sort_values(["holding_qty", "disclosure_date"], na_position="first")
          .drop_duplicates(["investor_id", "symbol", "as_of_date", "disclosure_date"],
                           keep="last")
          .sort_values("disclosure_date")
          .drop_duplicates(["investor_id", "symbol", "as_of_date"], keep="last")
          .sort_values(["investor_id", "symbol", "as_of_date", "disclosure_date"]))
    group = df.groupby(["investor_id", "symbol"], sort=False)
    df["previous_qty"] = group["holding_qty"].shift()
    df["previous_pct"] = group["holding_pct"].shift()
    df["previous_as_of_date"] = group["as_of_date"].shift()
    df["delta_qty"] = df["holding_qty"] - df["previous_qty"]
    df["delta_pct_points"] = df["holding_pct"] - df["previous_pct"]
    comparable = df["previous_qty"].notna()
    df["change_kind"] = np.select(
        [~comparable,
         comparable & df["previous_qty"].eq(0) & df["holding_qty"].gt(0),
         comparable & df["previous_qty"].gt(0) & df["holding_qty"].eq(0),
         df["delta_qty"] > 0, df["delta_qty"] < 0],
        ["first_observed", "entry", "exit", "add", "trim"], default="unchanged",
    )
    # A first observed position may have existed below the reporting threshold.
    df["trade_date_precision"] = np.where(comparable, "snapshot_interval", "left_censored")
    return df.reset_index(drop=True)


def _scatter_score(positive_deltas: pd.Series, possible_periods: int) -> tuple[float, float]:
    """Return normalized buying scatter [0,1] and entropy effective periods.

    Equal buying in every observable interval scores 1; one lump scores 0.  The
    denominator is all comparable intervals, so buying in two of eight quarters is
    less "scattered" than buying in two of two quarters.
    """
    values = positive_deltas[positive_deltas > 0].astype(float).to_numpy()
    if len(values) == 0:
        return np.nan, 0.0
    weights = values / values.sum()
    effective = float(np.exp(-(weights * np.log(weights)).sum()))
    if possible_periods <= 1:
        return np.nan, effective
    return float(np.clip((effective - 1.0) / (possible_periods - 1.0), 0, 1)), effective


def accumulation_summary(holdings: pd.DataFrame) -> pd.DataFrame:
    """One row per investor-company with cadence, scatter, and tenure estimates."""
    changes = holding_changes(holdings)
    rows = []
    for (investor_id, symbol), group in changes.groupby(["investor_id", "symbol"]):
        comparable = group[group["previous_qty"].notna()]
        adds = comparable[comparable["delta_qty"] > 0]
        trims = comparable[comparable["delta_qty"] < 0]
        scatter, effective = _scatter_score(adds["delta_qty"], len(comparable))
        first, last = group.iloc[0], group.iloc[-1]
        span = (adds["as_of_date"].max() - adds["as_of_date"].min()).days \
            if len(adds) >= 2 else 0
        rows.append({
            "investor_id": investor_id,
            "investor_name": last["investor_name"],
            "investor_type": last["investor_type"],
            "symbol": symbol,
            "n_snapshots": len(group),
            "n_comparable_intervals": len(comparable),
            "n_add_intervals": len(adds),
            "n_trim_intervals": len(trims),
            "n_entries": int((comparable["change_kind"] == "entry").sum()),
            "n_exits": int((comparable["change_kind"] == "exit").sum()),
            "buy_consistency": len(adds) / len(comparable) if len(comparable) else np.nan,
            "buy_scatter_score": scatter,
            "effective_buy_periods": effective,
            "accumulation_span_days": span,
            "gross_reported_add_qty": adds["delta_qty"].sum(min_count=1),
            "net_reported_change_qty": comparable["delta_qty"].sum(min_count=1),
            "first_observed_date": first["as_of_date"],
            "last_observed_date": last["as_of_date"],
            "observed_tenure_days": (last["as_of_date"] - first["as_of_date"]).days,
            "tenure_is_lower_bound": True,
            "latest_holding_qty": last["holding_qty"],
            "latest_holding_pct": last["holding_pct"],
        })
    return pd.DataFrame(rows)


def investor_style_summary(holdings: pd.DataFrame) -> pd.DataFrame:
    """Aggregate company-level behavior into an interpretable investor style card.

    HHI is calculated only when comparable market values are supplied (the mutual-
    fund scheme table has ``holding_value_cr``).  Share counts from different
    companies are never summed as if they were economically comparable.
    """
    company = accumulation_summary(holdings)
    if company.empty:
        return pd.DataFrame()
    latest_idx = (holdings.sort_values(["investor_id", "symbol", "as_of_date"])
                  .groupby(["investor_id", "symbol"])["as_of_date"].idxmax())
    latest = holdings.loc[latest_idx].copy()
    rows = []
    for investor_id, group in company.groupby("investor_id"):
        source = latest[latest["investor_id"].eq(investor_id)]
        hhi = np.nan
        if "holding_value_cr" in source and source["holding_value_cr"].notna().any():
            values = source["holding_value_cr"].dropna().clip(lower=0)
            if values.sum() > 0:
                weights = values / values.sum()
                hhi = float((weights ** 2).sum())
        tenure = group["observed_tenure_days"].median()
        scatter = group.loc[group["n_add_intervals"] > 0, "buy_scatter_score"].median()
        consistency = group.loc[group["n_comparable_intervals"] > 0, "buy_consistency"].median()
        turnover = (group["n_trim_intervals"].sum()
                    / group["n_comparable_intervals"].sum()) \
            if group["n_comparable_intervals"].sum() else np.nan
        descriptors = []
        descriptors.append("patient" if tenure >= 365 else "short-observed-history")
        if group["n_add_intervals"].sum() == 0:
            descriptors.append("no-observed-adds")
        elif pd.notna(scatter):
            descriptors.append("gradual-accumulator" if scatter >= 0.35 else "lumpy-accumulator")
        else:
            descriptors.append("insufficient-accumulation-history")
        if pd.notna(hhi):
            descriptors.append("concentrated" if hhi >= 0.15 else "diversified")
        rows.append({
            "investor_id": investor_id,
            "investor_name": group.iloc[-1]["investor_name"],
            "n_companies": group["symbol"].nunique(),
            "median_observed_tenure_days": tenure,
            "median_latest_holding_pct": group["latest_holding_pct"].median(),
            "median_buy_consistency": consistency,
            "median_buy_scatter_score": scatter,
            "trim_interval_rate": turnover,
            "latest_value_hhi": hhi,
            "style_label": ", ".join(descriptors),
        })
    return pd.DataFrame(rows)


def _event_window(prices: pd.DataFrame, disclosure_date: pd.Timestamp,
                  horizons: Iterable[int]) -> dict[str, float]:
    prices = prices.sort_values("date").copy()
    prices["date"] = pd.to_datetime(prices["date"])
    if prices["date"].dt.tz is not None:
        prices["date"] = prices["date"].dt.tz_localize(None)
    disclosed = pd.Timestamp(disclosure_date)
    if disclosed.tzinfo is not None:
        disclosed = disclosed.tz_localize(None)
    # Daily bars cannot isolate an intraday reaction.  If a filing arrives after
    # the 09:15 open, start at the next full session so the return contains no
    # pre-disclosure hours.  A pre-open filing can use the same day's session.
    market_open = disclosed.normalize() + pd.Timedelta(hours=9, minutes=15)
    eligible_date = disclosed.normalize() if disclosed <= market_open \
        else disclosed.normalize() + pd.Timedelta(days=1)
    sessions = prices[prices["date"].dt.normalize() >= eligible_date].index
    prior = prices[prices["date"].dt.normalize() < eligible_date].index
    if len(sessions) == 0 or len(prior) == 0:
        return {}
    event_idx = prices.index.get_loc(sessions[0])
    base = float(prices.loc[prior[-1], "close"])
    out = {"event_session": prices.iloc[event_idx]["date"]}
    for horizon in horizons:
        end = event_idx + int(horizon) - 1
        out[f"return_{horizon}d"] = (
            float(prices.iloc[end]["close"]) / base - 1.0 if end < len(prices) else np.nan
        )
    trailing = prices.iloc[max(0, event_idx - 20):event_idx]
    out["adv20"] = float(trailing["volume"].mean()) if "volume" in trailing else np.nan
    return out


def disclosure_events(holdings: pd.DataFrame, horizons: Iterable[int] = (1, 5, 20, 60),
                      benchmark: pd.DataFrame | None = None) -> pd.DataFrame:
    """Measure post-publication price reaction for reported adds/trims.

    ``delta_qty`` is used only for direction/intensity.  The return clock starts on
    the first session on/after public disclosure, never at the quarter/month end.
    """
    changes = holding_changes(holdings)
    events = changes[changes["change_kind"].isin(["entry", "add", "trim", "exit"])].copy()
    rows = []
    benchmark_windows: dict[pd.Timestamp, dict[str, float]] = {}
    for row in events.itertuples(index=False):
        prices = read_daily(row.symbol, columns=["date", "close", "volume"])
        if prices.empty:
            continue
        window = _event_window(prices, row.disclosure_date, horizons)
        if not window:
            continue
        result = {
            "investor_id": row.investor_id, "investor_name": row.investor_name,
            "symbol": row.symbol, "as_of_date": row.as_of_date,
            "disclosure_date": row.disclosure_date, "change_kind": row.change_kind,
            "delta_qty": row.delta_qty, **window,
        }
        result["flow_to_adv20"] = row.delta_qty / window["adv20"] \
            if window.get("adv20") and window["adv20"] > 0 else np.nan
        if benchmark is not None and not benchmark.empty:
            key = pd.Timestamp(row.disclosure_date)
            if key not in benchmark_windows:
                benchmark_windows[key] = _event_window(benchmark, key, horizons)
            bench = benchmark_windows[key]
            for horizon in horizons:
                result[f"abnormal_return_{horizon}d"] = (
                    result.get(f"return_{horizon}d", np.nan)
                    - bench.get(f"return_{horizon}d", np.nan)
                )
        rows.append(result)
    return pd.DataFrame(rows)


def impact_summary(events: pd.DataFrame, horizon: int = 20) -> pd.DataFrame:
    """Aggregate disclosure reactions by investor with sample size and uncertainty."""
    column = f"abnormal_return_{horizon}d" if f"abnormal_return_{horizon}d" in events \
        else f"return_{horizon}d"
    if events.empty or column not in events:
        return pd.DataFrame()
    rows = []
    for (investor_id, investor_name), group in events.groupby(["investor_id", "investor_name"]):
        signed = np.where(group["change_kind"].isin(["entry", "add"]), 1.0, -1.0) \
            * group[column]
        values = pd.Series(signed).dropna()
        n = len(values)
        mean = values.mean() if n else np.nan
        std = values.std(ddof=1) if n > 1 else np.nan
        rows.append({
            "investor_id": investor_id, "investor_name": investor_name,
            "n_events": n, "mean_signed_reaction": mean,
            "median_signed_reaction": values.median() if n else np.nan,
            "positive_reaction_rate": (values > 0).mean() if n else np.nan,
            "t_stat": mean / (std / math.sqrt(n)) if n > 1 and std > 0 else np.nan,
            "horizon_days": horizon,
        })
    return pd.DataFrame(rows).sort_values("mean_signed_reaction", ascending=False)


def investor_report(query: str) -> None:
    holdings = load_normalized_holdings()
    if holdings.empty:
        print("No holdings data. Run the named and/or mutual-fund collectors first.")
        return
    q = normalize_name(query)
    mask = holdings["investor_name"].map(normalize_name).str.contains(q, regex=False) \
        | holdings["investor_id"].map(normalize_name).str.contains(q, regex=False)
    selected = holdings[mask]
    if selected.empty:
        matches = holdings[["investor_id", "investor_name"]].drop_duplicates()
        print(f"No investor matched {query!r}. Available examples:\n"
              f"{matches.head(20).to_string(index=False)}")
        return
    style = investor_style_summary(selected)
    summary = accumulation_summary(selected).sort_values(
        ["latest_holding_pct", "latest_holding_qty"], ascending=False, na_position="last"
    )
    print("STYLE\n" + style.to_string(index=False))
    print("\nCOMPANIES\n" + summary.to_string(index=False))


def fund_sample_report(n: int = 20) -> pd.DataFrame:
    """Compare the largest ``n`` funds having at least two collected months."""
    holdings = load_normalized_holdings(include_named=False, include_funds=True)
    if holdings.empty:
        return pd.DataFrame()
    month_counts = holdings.groupby("investor_id")["as_of_date"].nunique()
    eligible_ids = month_counts[month_counts >= 2].index
    eligible = holdings[holdings["investor_id"].isin(eligible_ids)]
    latest_month = eligible.groupby("investor_id")["as_of_date"].transform("max")
    latest = eligible[eligible["as_of_date"].eq(latest_month)]
    size = (latest.groupby(["investor_id", "investor_name"])
            .agg(latest_equity_value_cr=("holding_value_cr", "sum"),
                 latest_stock_count=("holding_qty", lambda x: int((x > 0).sum())))
            .reset_index()
            .sort_values("latest_equity_value_cr", ascending=False)
            .head(n))
    selected = eligible[eligible["investor_id"].isin(size["investor_id"])]
    style = investor_style_summary(selected)
    changes = holding_changes(selected)
    activity = (changes[changes["previous_qty"].notna()]
                .groupby("investor_id")
                .agg(positions_added=("delta_qty", lambda x: int((x > 0).sum())),
                     positions_trimmed=("delta_qty", lambda x: int((x < 0).sum())),
                     new_positions=("change_kind", lambda x: int((x == "entry").sum())),
                     exited_positions=("change_kind", lambda x: int((x == "exit").sum())))
                .reset_index())
    benchmark_path = os.path.join(ROOT_DIR, "data", "parquet",
                                  "indices", "nifty500.parquet")
    benchmark = pd.read_parquet(benchmark_path) if os.path.exists(benchmark_path) else None
    events = disclosure_events(selected, horizons=(1, 5), benchmark=benchmark)
    reaction = impact_summary(events, horizon=5)
    if not reaction.empty:
        reaction = reaction[["investor_id", "n_events", "mean_signed_reaction",
                             "positive_reaction_rate", "t_stat"]].rename(columns={
                                 "n_events": "reaction_events_5d",
                                 "mean_signed_reaction": "mean_signed_abnormal_5d",
                                 "positive_reaction_rate": "positive_reaction_rate_5d",
                                 "t_stat": "reaction_t_stat_5d",
                             })
    out = size.merge(style, on=["investor_id", "investor_name"], how="left") \
              .merge(activity, on="investor_id", how="left")
    if not reaction.empty:
        out = out.merge(reaction, on="investor_id", how="left")
    return out.sort_values("latest_equity_value_cr", ascending=False).reset_index(drop=True)


if __name__ == "__main__":
    command = sys.argv[1] if len(sys.argv) > 1 else ""
    if command == "collect-named":
        days = int(sys.argv[2]) if len(sys.argv) > 2 else 40
        symbols = sys.argv[3].split(",") if len(sys.argv) > 3 else None
        collect_named_holdings(days, symbols=symbols)
    elif command == "report" and len(sys.argv) > 2:
        investor_report(" ".join(sys.argv[2:]))
    elif command == "sample-funds":
        sample = fund_sample_report(int(sys.argv[2]) if len(sys.argv) > 2 else 20)
        print(sample.to_string(index=False) if not sample.empty else "No comparable fund data.")
    else:
        print(__doc__)
