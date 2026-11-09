"""nse_news.py — poll the Pulse by Zerodha news feed into a daily archive.

Pulse (https://pulse.zerodha.com) aggregates ~30 Indian financial news sources
into one RSS feed. The feed is a rolling window of only the latest ~25 items
with NO archive and NO pagination — so the ONLY way to build history is to poll
it repeatedly and append. Run this often (an intraday cron every ~20 min during
market hours), not just once at EOD, or you capture only the day's last 25
headlines.

Each poll is idempotent: new items are deduped against the day's file on URL, so
calling it twice in a row adds nothing. Safe to over-poll.

Run manually / from cron:
    PYTHONPATH=src python -m data_collection.other.news
"""

import os

from data_collection.paths import ROOT_DIR
import email.utils
from datetime import datetime
from urllib.parse import urlparse
from xml.etree import ElementTree

import pandas as pd
import requests
from zoneinfo import ZoneInfo

RAW_DIR = os.path.join(ROOT_DIR, "data", "raw", "news")
os.makedirs(RAW_DIR, exist_ok=True)

FEED_URL = "https://pulse.zerodha.com/feed.php"
HEADERS = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"}
IST = ZoneInfo("Asia/Kolkata")

COLUMNS = ["fetched_at", "published", "source", "headline", "url", "description"]


def _source_from_url(url: str) -> str:
    """Human-readable source name from the article domain, e.g.
    'https://www.thehindu.com/...' -> 'thehindu'. Falls back to the netloc."""
    host = urlparse(url).netloc.lower().replace("www.", "")
    parts = host.split(".")
    return parts[0] if len(parts) >= 2 else host


def _parse_pubdate(raw: str) -> str:
    """RFC-822 'Mon, 13 Jul 2026 23:30:01 +0530' -> ISO string in IST.
    Returns the raw string unchanged if it cannot be parsed."""
    try:
        dt = email.utils.parsedate_to_datetime(raw)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=IST)
        return dt.astimezone(IST).isoformat(timespec="seconds")
    except (TypeError, ValueError):
        return raw or ""


def _today_path() -> str:
    return os.path.join(RAW_DIR, f"news_{datetime.now(IST).date().isoformat()}.csv")


def _parse_feed(xml_text: str) -> pd.DataFrame:
    root = ElementTree.fromstring(xml_text)
    fetched_at = datetime.now(IST).isoformat(timespec="seconds")
    rows = []
    for item in root.iter("item"):
        url = (item.findtext("link") or "").strip()
        if not url:
            continue
        rows.append({
            "fetched_at": fetched_at,
            "published": _parse_pubdate((item.findtext("pubDate") or "").strip()),
            "source": _source_from_url(url),
            "headline": (item.findtext("title") or "").strip(),
            "url": url,
            "description": (item.findtext("description") or "").strip(),
        })
    return pd.DataFrame(rows, columns=COLUMNS)


def poll_pulse() -> int:
    """Fetch the feed once and append any new items to today's CSV.
    Deduped on URL against what is already stored today. Returns the number of
    NEW items written this call."""
    resp = requests.get(FEED_URL, headers=HEADERS, timeout=20)
    resp.raise_for_status()
    fresh = _parse_feed(resp.text)
    if fresh.empty:
        print("Pulse feed returned no items.")
        return 0

    path = _today_path()
    if os.path.exists(path):
        existing = pd.read_csv(path)
        seen = set(existing["url"])
        new = fresh[~fresh["url"].isin(seen)]
        combined = pd.concat([existing, new], ignore_index=True)
    else:
        new = fresh
        combined = fresh

    combined.to_csv(path, index=False)
    print(f"Pulse: +{len(new)} new items ({len(combined)} total today) -> {path}")
    return len(new)


def load_recent_news(limit: int = 20) -> pd.DataFrame:
    """Newest stored news for the brief/state: most recent day's file, latest
    items first. Empty DataFrame if nothing archived yet."""
    import glob
    files = sorted(glob.glob(os.path.join(RAW_DIR, "news_*.csv")))
    if not files:
        return pd.DataFrame(columns=COLUMNS)
    df = pd.read_csv(files[-1])
    return df.sort_values("published", ascending=False).head(limit).reset_index(drop=True)


if __name__ == "__main__":
    poll_pulse()
