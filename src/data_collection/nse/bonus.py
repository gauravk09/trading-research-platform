"""
nse_bonus.py — bonus-issue events per NSE symbol, for PIT market cap.

A bonus issue inflates a company's paid-up equity capital without being real
dilution (it is market-cap-neutral, and Kite's adjusted prices already absorb
it). shares_history.py derives its dilution factor from paid-up capital, so it
needs to divide bonuses back out — this module supplies the (symbol, ex_date,
factor) events to do that.

Source: BSE's DefaultData corp-action feed, which returns the whole exchange for
a date range in one call (NSE's own corp-action API is Akamai bot-blocked, same
as its quote API). BSE scrip codes are mapped to NSE symbols via ISIN
(BSE ListofScripData -> ISIN -> NSE EQUITY_L). "Bonus issue A:B" means A new
shares per B held, so the share count multiplies by (A+B)/B.

Only bonuses inside the price-history window matter (earlier ones cancel in the
eqcap(t)/eqcap_today ratio), so the pull starts at START_YEAR.

Build/refresh:  PYTHONPATH=src ~/anaconda3/bin/python -m data_collection.nse.bonus
"""

import io
import os

from data_collection.paths import ROOT_DIR
import re
from datetime import date

import pandas as pd
import requests

from data_collection.nse.announcements import HEADERS

PROCESSED = os.path.join(ROOT_DIR, "data", "processed")
BONUS_PATH = os.path.join(PROCESSED, "bonus_events.parquet")

EQUITY_L_URL = "https://nsearchives.nseindia.com/content/equities/EQUITY_L.csv"
BSE_SCRIP_URL = ("https://api.bseindia.com/BseIndiaAPI/api/ListofScripData/w"
                 "?Group=&Scripcode=&industry=&segment=Equity&status=Active")
BSE_CA_URL = ("https://api.bseindia.com/BseIndiaAPI/api/DefaultData/w"
              "?ddlcategorys=E&ddlindustrys=&scripcode=&segment=0&strSearch=P"
              "&Fdate={year}-01-01&TDate={year}-12-31")
BSE_HEADERS = {"User-Agent": HEADERS["User-Agent"],
               "Referer": "https://www.bseindia.com/"}
START_YEAR = 2019


def _scripcode_to_symbol() -> dict:
    """BSE scrip_code -> NSE symbol, joined on ISIN."""
    bse = pd.DataFrame(requests.get(BSE_SCRIP_URL, headers=BSE_HEADERS,
                                    timeout=60).json())
    nse = pd.read_csv(io.StringIO(requests.get(EQUITY_L_URL, headers=HEADERS,
                                               timeout=30).text))
    nse.columns = [c.strip() for c in nse.columns]
    isin_to_symbol = dict(zip(nse["ISIN NUMBER"], nse["SYMBOL"]))
    return {int(row.SCRIP_CD): isin_to_symbol[row.ISIN_NUMBER]
            for row in bse.itertuples()
            if row.ISIN_NUMBER in isin_to_symbol}


def _bonus_factor(purpose: str):
    """'Bonus issue A:B' -> (A+B)/B share multiplier; None if no ratio."""
    m = re.search(r"(\d+)\s*:\s*(\d+)", purpose)
    if not m:
        return None
    a, b = int(m.group(1)), int(m.group(2))
    return (a + b) / b if b else None


def build_bonus_events() -> pd.DataFrame:
    """Pull every bonus since START_YEAR, map to NSE symbols, save the table."""
    code_to_symbol = _scripcode_to_symbol()
    rows = []
    for year in range(START_YEAR, date.today().year + 1):
        feed = requests.get(BSE_CA_URL.format(year=year), headers=BSE_HEADERS,
                            timeout=60).json()
        for item in feed:
            if "Bonus" not in item.get("Purpose", ""):
                continue
            symbol = code_to_symbol.get(int(item["scrip_code"]))
            factor = _bonus_factor(item["Purpose"])
            if symbol and factor:
                rows.append({"symbol": symbol,
                             "ex_date": pd.to_datetime(item["Ex_date"],
                                                       format="%d %b %Y"),
                             "factor": factor})

    events = (pd.DataFrame(rows).drop_duplicates(["symbol", "ex_date"])
              .sort_values(["symbol", "ex_date"]).reset_index(drop=True))
    events.to_parquet(BONUS_PATH, compression="snappy", index=False)
    print(f"nse_bonus: {len(events)} bonus events since {START_YEAR} for "
          f"{events['symbol'].nunique()} NSE symbols -> "
          f"{os.path.basename(BONUS_PATH)}")
    return events


if __name__ == "__main__":
    build_bonus_events()
