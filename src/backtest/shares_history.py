"""
shares_history.py — point-in-time (PIT) market cap for the backtest universe.

`mcap = current_shares x close` is already correct through splits and bonuses
(Kite prices are split/bonus-adjusted, so both effects cancel in the product).
The one thing it gets wrong is REAL dilution / buybacks — a stock that raised
capital has more shares today than in the past, so today's share count
overstates its old market cap (SUZLON ~3.7x, IDEA ~30x).

The fix is a per-stock dilution factor D(t) = eqcap(t) / eqcap_today, built from
the annual paid-up Equity Share Capital series on each stock's cached screener
page. Paid-up capital is split-invariant, so D handles splits and real dilution
correctly with no historical face value needed. Bonus issues DO inflate paid-up
capital while being market-cap-neutral, so each annual eqcap is first restated
into today's share basis by multiplying it by the bonus factors that took effect
after that fiscal-year end (bonus_events.parquet from nse_bonus.py); that leaves
only real dilution in D. If bonus_events is absent, D falls back to raw eqcap
(bonus-givers' past mcap then slightly understated — benign for size buckets).

Each annual figure steps in on the date it became public (the Q4 filing date
from financials.parquet, else fiscal-year-end + 75 days) so D(t) is causal.

Outputs (wide date x symbol float32 matrices, close_matrix layout):
    features/dilution_factor.parquet   D(t), 1.0 where unknown (no correction)
    features/pit_mcap.parquet          current_shares x close x D, in Rs Cr
    features/mcap_decile.parquet       cross-sectional pct-rank of pit_mcap
and the raw long series equity_capital_history.parquet [symbol, fy_end, eqcap_cr].

Build:  ~/anaconda3/bin/python src/backtest/shares_history.py
"""

import glob
import gzip
import os
import re

import pandas as pd

_ROOT = os.path.join(os.path.dirname(__file__), "..", "..")
PROCESSED = os.path.join(_ROOT, "data", "processed")
SCREENER_DIR = os.path.join(_ROOT, "data", "raw", "screener")
FEATURES_DIR = os.path.join(PROCESSED, "features")
CLOSE_MATRIX = os.path.join(PROCESSED, "close_matrix.parquet")
MASTER = os.path.join(PROCESSED, "company_master.parquet")
FINANCIALS = os.path.join(PROCESSED, "financials.parquet")
EQCAP_HISTORY = os.path.join(PROCESSED, "equity_capital_history.parquet")
BONUS_EVENTS = os.path.join(PROCESSED, "bonus_events.parquet")

REPORTING_LAG = pd.Timedelta(days=75)  # fallback when no Q4 filing date is known


def _parse_equity_capital(symbol: str) -> pd.DataFrame:
    """Annual paid-up Equity Share Capital (Rs Cr) from a cached screener page.

    Returns [fy_end, eqcap_cr] aligned via the table's data-date-key headers,
    or None if the page or the row is absent."""
    path = os.path.join(SCREENER_DIR, f"{symbol}.html.gz")
    if not os.path.exists(path):
        return None
    text = gzip.open(path, "rt", encoding="utf-8").read()
    start = text.find('id="balance-sheet"')
    if start < 0:
        return None
    section = text[start:text.find("</section>", start)]
    dates = re.findall(r'data-date-key="(\d{4}-\d\d-\d\d)"',
                       section[:section.find("</thead>")])
    row = re.search(r"Equity Capital.*?</tr>", section, re.S)
    if not row or not dates:
        return None
    cells = [re.sub(r"<[^>]+>", "", c).replace(",", "").strip()
             for c in re.findall(r"<td[^>]*>(.*?)</td>", row.group(0), re.S)]
    values = [float(c) for c in cells if re.match(r"^-?[0-9.]+$", c)]
    if len(values) != len(dates):
        return None  # misaligned table — skip rather than guess
    return pd.DataFrame({"symbol": symbol,
                         "fy_end": pd.to_datetime(dates),
                         "eqcap_cr": values})


def build_equity_capital_history() -> pd.DataFrame:
    """Parse every cached screener page into one long equity-capital table."""
    frames = []
    for path in sorted(glob.glob(os.path.join(SCREENER_DIR, "*.html.gz"))):
        symbol = os.path.basename(path)[:-len(".html.gz")]
        df = _parse_equity_capital(symbol)
        if df is not None and (df["eqcap_cr"] > 0).all():
            frames.append(df)
    history = pd.concat(frames, ignore_index=True)
    history.to_parquet(EQCAP_HISTORY, compression="snappy", index=False)
    print(f"shares_history: equity capital parsed for {history['symbol'].nunique()} "
          f"symbols -> {os.path.basename(EQCAP_HISTORY)}")
    return history


def _public_dates() -> dict:
    """(symbol, fy_end) -> earliest Q4 filing date, i.e. when the annual paid-up
    capital first became public. Missing pairs fall back to fy_end + 75 days."""
    fin = pd.read_parquet(FINANCIALS, columns=["symbol", "quarter_end",
                                               "relating_to", "filing_date"])
    q4 = fin[fin["relating_to"].str.contains("Fourth", na=False)].copy()
    q4["filed"] = pd.to_datetime(q4["filing_date"].str.slice(0, 11),
                                 format="%d-%b-%Y", errors="coerce")
    q4 = q4.dropna(subset=["filed"])
    first = q4.groupby(["symbol", "quarter_end"])["filed"].min()
    return {(s, pd.Timestamp(q)): d for (s, q), d in first.items()}


def _bonus_map() -> dict:
    """symbol -> DataFrame[ex_date, factor], or empty if no feed collected."""
    if not os.path.exists(BONUS_EVENTS):
        return {}
    events = pd.read_parquet(BONUS_EVENTS)
    return {sym: g for sym, g in events.groupby("symbol")}


def build_dilution_matrix(close: pd.DataFrame) -> pd.DataFrame:
    """Causal D(t) = eqcap_as_of(t) / eqcap_today per symbol, on close's grid.

    Each annual eqcap is restated into today's share basis by the bonus factors
    that took effect after its fiscal-year end, so only real dilution survives.
    eqcap steps in on its public date; before the first known figure it is
    back-filled (constant) so early history is corrected as best we can. Symbols
    with no equity-capital history get D = 1.0 (identical to today's behaviour)."""
    history = (pd.read_parquet(EQCAP_HISTORY) if os.path.exists(EQCAP_HISTORY)
               else build_equity_capital_history())
    public = _public_dates()
    bonuses = _bonus_map()
    grid = close.index.tz_localize(None).normalize()  # naive dates for merge_asof

    columns = {}
    for symbol, g in history.groupby("symbol"):
        if symbol not in close.columns:
            continue
        g = g.sort_values("fy_end")
        bex = bonuses.get(symbol)
        if bex is not None:
            factor_after = g["fy_end"].apply(
                lambda fy: bex.loc[bex["ex_date"] > fy, "factor"].prod())
            eqcap = (g["eqcap_cr"].to_numpy() * factor_after.to_numpy())
        else:
            eqcap = g["eqcap_cr"].to_numpy()
        eqcap_today = eqcap[-1]
        avail = [public.get((symbol, fy), fy + REPORTING_LAG) for fy in g["fy_end"]]
        steps = (pd.DataFrame({"avail": avail, "eqcap": eqcap})
                 .sort_values("avail").drop_duplicates("avail", keep="last"))
        merged = pd.merge_asof(pd.DataFrame({"avail": grid}), steps, on="avail")
        eqcap_asof = merged["eqcap"].bfill().to_numpy()  # constant before first
        columns[symbol] = eqcap_asof / eqcap_today

    D = pd.DataFrame(columns, index=close.index).reindex(columns=close.columns)
    D = D.fillna(1.0).astype("float32")
    D.to_parquet(os.path.join(FEATURES_DIR, "dilution_factor.parquet"),
                 compression="snappy")
    print(f"shares_history: dilution_factor built for {len(columns)} symbols "
          f"({(D.min() < 0.5).sum()} with >2x historical dilution)")
    return D


def build_pit_mcap(close: pd.DataFrame, D: pd.DataFrame) -> None:
    """PIT mcap (Rs Cr) = current_shares x close x D(t), plus its daily decile."""
    shares = (pd.read_parquet(MASTER, columns=["symbol", "shares_out"])
              .set_index("symbol")["shares_out"])
    shares = shares.reindex(close.columns)
    pit_mcap = (close.mul(shares, axis=1) * D / 1e7).astype("float32")
    pit_mcap.to_parquet(os.path.join(FEATURES_DIR, "pit_mcap.parquet"),
                        compression="snappy")
    decile = pit_mcap.rank(axis=1, pct=True).astype("float32")
    decile.to_parquet(os.path.join(FEATURES_DIR, "mcap_decile.parquet"),
                      compression="snappy")
    print(f"shares_history: pit_mcap + mcap_decile written "
          f"({int(pit_mcap.iloc[-1].notna().sum())} symbols priced today)")


def refresh() -> None:
    """Nightly entry: rebuild D(t) + PIT mcap from the fresh close matrix and
    the cached equity-capital / bonus tables (no screener re-parse)."""
    close = pd.read_parquet(CLOSE_MATRIX)
    D = build_dilution_matrix(close)
    build_pit_mcap(close, D)


def main() -> None:
    """Full rebuild: re-parse the screener cache, then refresh the matrices.
    Run after the screener cache or bonus feed is refreshed."""
    build_equity_capital_history()
    refresh()


if __name__ == "__main__":
    main()
