"""Build point-in-time market-cap matrices for the large-cap / F&O-proxy cohort.

mcap(date, symbol) = latest_shares_out[symbol] * close[date, symbol] / 1e7  (in cr)

shares_out_history is only a 3-day snapshot, so we use the latest shares per
symbol and let the ranking move over history with PRICE only. This is the
documented PIT-mcap proxy (see memory fno-mover-anatomy). Two caveats, both
conservative: (1) only currently-listed symbols get a share count -> survivorship;
(2) share count is today's, so pre-dilution years are slightly overstated.

Writes into the engine's lookup cache:
  mcap_cr.parquet    date x symbol market cap in crore
  mcap_rank.parquet  date x symbol rank per day (1 = largest)
"""
import os
import pandas as pd

BASE = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
CACHE = os.path.join(BASE, "output", "studies", "cache")
SHARES = os.path.join(BASE, "data", "processed", "shares_out_history.parquet")


def build():
    close = pd.read_parquet(os.path.join(CACHE, "close.parquet"))
    sh = pd.read_parquet(SHARES).sort_values("date")
    shares = sh.groupby("symbol")["shares_out"].last()

    shares = shares.reindex(close.columns)          # align to matrix columns
    mcap_cr = close.mul(shares, axis=1) / 1e7       # ₹ -> ₹ crore
    mcap_rank = mcap_cr.rank(axis=1, ascending=False, method="min")

    mcap_cr.to_parquet(os.path.join(CACHE, "mcap_cr.parquet"))
    mcap_rank.to_parquet(os.path.join(CACHE, "mcap_rank.parquet"))

    last = mcap_cr.iloc[-1].dropna().sort_values(ascending=False)
    print(f"symbols with shares: {shares.notna().sum()} of {len(close.columns)}")
    print(f"top-5 by mcap on {close.index[-1].date()}:")
    print((last.head() / 1e5).round(2).to_string(), "(lakh cr)")
    print(f"mcap floor at rank 150: "
          f"{mcap_rank.iloc[-1][mcap_rank.iloc[-1] <= 150].index.map(last).min():.0f} cr")


if __name__ == "__main__":
    build()
