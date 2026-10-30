"""
overnight_news.py — Rank material after-close filings for next-day EP/ORB trades

For a trade day T, pools every NSE filing broadcast between the previous
trading day's close (15:30) and T's open (09:15) — weekends included — and
scores each one deterministically (no LLM):

  results    joined to financials.parquet on filing time → actual YoY PAT
             swing decides direction and magnitude
  order wins ₹-crore value extracted from the filing text, sized against
             the company's annualized quarterly revenue
  the rest   signed keyword lexicon on subject + body text (approvals,
             buybacks, penalties, auditor exits, downgrades, fires, ...)

Positive score = expected up-move catalyst, negative = down. abs(score) is
the materiality rank. Run in the evening to get tomorrow's ORB watchlist:

    python src/overnight_news.py                # tonight → next trade day
    python src/overnight_news.py --date 2026-07-15   # historical morning
"""

import argparse
import os
import re

import pandas as pd

import announcements_store

BASE = os.path.join(os.path.dirname(__file__), "..")
FIN_PATH = os.path.join(BASE, "data", "processed", "financials.parquet")
SUMMARY_PATH = os.path.join(BASE, "data", "processed", "universe_summary.parquet")
OUT_DIR = os.path.join(BASE, "output", "overnight_news")

CLOSE_TIME = "15:30"
OPEN_TIME = "09:15"

SKIP_CATEGORIES = {"board_meeting", "analyst_meet", "insider_trade"}

# Routine paperwork — drop outright, whatever the category says
NOISE = re.compile(
    r"loss of share certificate|duplicate share|trading window|newspaper "
    r"(publication|advertisement)|book closure|record date for|postal ballot"
    r"|annual general meeting|extra-?ordinary general meeting|\bagm\b|\begm\b"
    r"|investor grievance|\bkyc\b|registrar and (share )?transfer|\besop\b"
    r"|employee stock option|compliance certificate|certificate under regulation"
    r"|reg(ulation)?\.? ?74|scrutinizer|voting results|proceedings of",
    re.I)

# (tag, pattern, weight) — matched once each against subject + body text
LEXICON = [
    ("order-win",      r"\bbagg?ed\b|\bsecured\b.{0,40}order|order.{0,30}(worth|valued)"
                       r"|letter of award|\bloa\b|work order|purchase order|contract award", 1.5),
    ("superlative",    r"largest[- ]ever|record (high|revenue|profit|order)|highest[- ]ever", 1.0),
    ("drug-approval",  r"usfda|us fda|who[- ]gmp|\bdcgi\b|cdsco.{0,30}approv"
                       r"|marketing authori[sz]ation|anda approval|final approval.{0,30}(fda|anda)", 2.0),
    ("approval",       r"\bapprov(al|ed)\b", 0.5),
    ("acquisition",    r"acquisition of|acquires?\b|stake purchase|scheme of amalgamation", 1.0),
    ("partnership",    r"joint venture|strategic (partnership|alliance|tie-?up)"
                       r"|collaboration with|mou with|memorandum of understanding", 1.0),
    ("buyback",        r"buy-?back", 1.5),
    ("bonus",          r"bonus (issue|shares)", 1.5),
    ("split",          r"stock split|sub-?division of.{0,20}shares", 0.75),
    ("capacity",       r"capacity expansion|commercial production|commissioned"
                       r"|new (plant|facility|manufacturing)", 1.0),
    ("rating-upgrade", r"rating.{0,40}upgrad|upgrad.{0,25}rating", 1.5),
    ("guidance-up",    r"rais(es?|ed) (its )?(guidance|outlook)|revis(es|ed).{0,20}upward", 2.0),
    ("fx-order",       r"(us ?\$|usd)\s*[\d,.]+\s*(million|billion|mn\b|bn\b)", 1.0),

    ("penalty",        r"penalt(y|ies)|show[- ]cause|demand notice|tax demand"
                       r"|gst.{0,30}(demand|notice)", -1.5),
    ("default",        r"\bdefault\b|delayed payment", -2.0),
    ("rating-cut",     r"rating.{0,40}downgrad|downgrad.{0,25}rating|outlook.{0,15}negative"
                       r"|watch.{0,10}negative", -2.0),
    ("key-exit",       r"resign(ation|ed|s)?\b.{0,60}(managing director|\bmd\b|chief"
                       r"|\bcfo\b|\bceo\b|auditor)", -1.5),
    ("mishap",         r"(fire|blaze|explosion|accident) (at|in|broke)", -2.0),
    ("shutdown",       r"shut ?down|suspension of (operations|production|work)"
                       r"|plant closure|operations.{0,25}halt", -2.0),
    ("insolvency",     r"insolvency|\bnclt\b|\bibc\b|liquidation|winding up", -2.5),
    ("enforcement",    r"\bfraud\b|search (and|&) seizure|\braids?\b|enforcement directorate"
                       r"|sebi.{0,40}(order|penalt|debar)", -2.0),
    ("pledge",         r"pledge[sd]?.{0,25}invoked|invocation of pledge", -1.5),
    ("fda-warning",    r"warning letter|form 483|\boai\b", -2.0),
    ("guidance-down",  r"lower(s|ed) (its )?(guidance|outlook)|cuts? guidance", -2.0),
    ("termination",    r"terminat(ed|ion) of (contract|agreement|order)", -1.5),
    ("recall",         r"\brecall\b", -1.0),
]
LEXICON = [(tag, re.compile(pat, re.I), w) for tag, pat, w in LEXICON]

AMOUNT_RE = re.compile(
    r"(?:rs\.?|inr|₹)\s*([\d,]+(?:\.\d+)?)\s*(crores?|cr\b|lakhs?|lacs?|million|mn\b|billion|bn\b)", re.I)
UNIT_CR = {"crore": 1, "cr": 1, "lakh": .01, "lac": .01,
           "million": .1, "mn": .1, "billion": 100, "bn": 100}


def load_financials() -> pd.DataFrame:
    fin = pd.read_parquet(FIN_PATH)
    fin["filing_dt"] = pd.to_datetime(fin["filing_date"], format="mixed", dayfirst=True, errors="coerce")
    fin["quarter_end"] = pd.to_datetime(fin["quarter_end"])
    return fin


def window_filings(prev_trade_date, trade_date) -> pd.DataFrame:
    """All filings broadcast in (prev close 15:30, trade-day open 09:15]."""
    start = pd.Timestamp(f"{prev_trade_date} {CLOSE_TIME}")
    end = pd.Timestamp(f"{trade_date} {OPEN_TIME}")

    df = announcements_store.load_range(          # weekend days included
        start=pd.Timestamp(prev_trade_date).date(),
        end=pd.Timestamp(trade_date).date())
    if df.empty:
        return pd.DataFrame()
    for col in ("subject", "desc", "attchmnttext", "category"):  # schema drifted over the years
        if col not in df.columns:
            df[col] = pd.NA
    df["an_ts"] = pd.to_datetime(df["an_dt"], format="%d-%b-%Y %H:%M:%S", errors="coerce")
    df = df[(df["an_ts"] > start) & (df["an_ts"] <= end)]
    df = df[df["symbol"].notna() & ~df["category"].isin(SKIP_CATEGORIES)]
    return df.drop_duplicates(subset=["symbol", "subject", "desc"]).reset_index(drop=True)


def results_score(symbol: str, start, end, fin: pd.DataFrame):
    """Direction and magnitude from the actual filed numbers, YoY."""
    mine = fin[fin["symbol"] == symbol]
    filed = mine[mine["filing_dt"].between(start, end)]
    if filed.empty:
        return None
    row = filed.sort_values("consolidated", ascending=False).iloc[0]

    prior_qe = row["quarter_end"] - pd.DateOffset(years=1)
    prior = mine[(mine["quarter_end"] == prior_qe) & (mine["consolidated"] == row["consolidated"])]
    if prior.empty:
        prior = mine[mine["quarter_end"] == prior_qe]
    if prior.empty:
        return None
    p = prior.iloc[0]

    cur = prev = None
    for col in ("pat_cr", "pbt_cr"):
        if pd.notna(row[col]) and pd.notna(p[col]):
            cur, prev = float(row[col]), float(p[col])
            break
    if cur is None:
        return None

    if prev <= 0 and cur > 0:
        score = 3.0
    elif prev > 0 and cur <= 0:
        score = -3.0
    elif prev <= 0 and cur <= 0:
        score = 0.0
    else:
        score = max(-3.0, min(3.0, (cur - prev) / abs(prev) / 0.25))  # ±75% YoY caps it

    detail = f"PAT ₹{cur:.0f}cr vs ₹{prev:.0f}cr YoY"
    if pd.notna(row["revenue_cr"]) and pd.notna(p["revenue_cr"]) and p["revenue_cr"] > 0:
        detail += f", rev {(row['revenue_cr'] / p['revenue_cr'] - 1) * 100:+.0f}%"
    return score, detail


def extract_order_cr(text: str):
    amounts = [float(m.group(1).replace(",", "")) * UNIT_CR[m.group(2).lower().rstrip("s")]
               for m in AMOUNT_RE.finditer(text)]
    return max(amounts) if amounts else None


def order_score(order_cr: float, symbol: str, asof, fin: pd.DataFrame):
    """Materiality of an order = its size vs annualized quarterly revenue."""
    mine = fin[(fin["symbol"] == symbol) & (fin["filing_dt"] < asof) & fin["revenue_cr"].notna()]
    if not mine.empty:
        annual_rev = float(mine.sort_values("filing_dt").iloc[-1]["revenue_cr"]) * 4
        if annual_rev > 0:
            ratio = order_cr / annual_rev
            return (max(0.3, min(3.0, ratio * 5)),
                    f"order ₹{order_cr:,.0f}cr ≈ {ratio * 100:.0f}% of ann. revenue")
    size = 2.0 if order_cr >= 500 else 1.5 if order_cr >= 100 else 1.0 if order_cr >= 25 else 0.5
    return size, f"order ₹{order_cr:,.0f}cr (no revenue base)"


def score_filings(filings: pd.DataFrame, fin: pd.DataFrame, start, end) -> pd.DataFrame:
    """One row per symbol: signed score, direction, and human-readable reasons."""
    if filings.empty:
        return pd.DataFrame()

    per_symbol = {}
    for row in filings.itertuples():
        text = " ".join(str(x) for x in (row.subject, row.desc, row.attchmnttext)
                        if isinstance(x, str))
        if NOISE.search(text):
            continue

        score, tags = 0.0, []
        for tag, pat, weight in LEXICON:
            if pat.search(text):
                score += weight
                tags.append(tag)

        if row.category == "results":
            res = results_score(row.symbol, start, end, fin)
            if res is not None:
                score, detail = res[0] + score, res[1]
                tags.insert(0, detail)
            else:
                tags.insert(0, "results (numbers not parsed — review)")
                score += 0.75
        elif row.category == "order_win" or "order-win" in tags:
            order_cr = extract_order_cr(text)
            if order_cr:
                extra, detail = order_score(order_cr, row.symbol, row.an_ts, fin)
                score += extra
                tags.insert(0, detail)

        if score == 0.0 and not tags:
            continue

        entry = per_symbol.setdefault(row.symbol, {
            "symbol": row.symbol, "score": 0.0, "categories": set(),
            "reasons": [], "headline": "", "best": 0.0, "last_filing": row.an_ts})
        entry["score"] += score
        entry["categories"].add(row.category)
        entry["reasons"].extend(tags)
        entry["last_filing"] = max(entry["last_filing"], row.an_ts)
        if abs(score) > abs(entry["best"]):
            entry["best"] = score
            entry["headline"] = str(row.desc if isinstance(row.desc, str) else row.subject)[:160]

    if not per_symbol:
        return pd.DataFrame()

    out = pd.DataFrame(per_symbol.values())
    out["direction"] = out["score"].apply(lambda s: "+" if s > 0 else "-" if s < 0 else "?")
    out["categories"] = out["categories"].apply(lambda c: ",".join(sorted(c)))
    out["reasons"] = out["reasons"].apply(lambda r: "; ".join(dict.fromkeys(r))[:200])
    return (out.drop(columns="best")
               .sort_values("score", key=abs, ascending=False)
               .reset_index(drop=True))


def scan(trade_date, prev_trade_date, min_score: float = 1.0,
         min_turnover_cr: float = 1.0) -> pd.DataFrame:
    start = pd.Timestamp(f"{prev_trade_date} {CLOSE_TIME}")
    end = pd.Timestamp(f"{trade_date} {OPEN_TIME}")

    filings = window_filings(prev_trade_date, trade_date)
    scored = score_filings(filings, load_financials(), start, end)
    if scored.empty:
        return scored

    summary = pd.read_parquet(SUMMARY_PATH)
    cols = ["symbol", "close", "avg_turnover_cr", "adr_pct", "ti65", "r6mo_pct"]
    scored = scored.merge(summary[cols], on="symbol", how="left")
    scored = scored[scored["avg_turnover_cr"].fillna(0) >= min_turnover_cr]
    scored = scored[scored["score"].abs() >= min_score]

    # same neglect notion as ep_checklist: flat names reprice hardest on real news
    scored["neglected"] = ((scored["ti65"].isna() | (scored["ti65"] < 1.02))
                           & (scored["r6mo_pct"] < 15))
    return scored.reset_index(drop=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", help="Trade date YYYY-MM-DD (default: next session from now)")
    parser.add_argument("--min-score", type=float, default=1.0)
    parser.add_argument("--min-turnover", type=float, default=1.0)
    parser.add_argument("--top", type=int, default=25)
    args = parser.parse_args()

    cm = pd.read_parquet(os.path.join(BASE, "data", "processed", "close_matrix.parquet"))
    sessions = cm.index.tz_localize(None).normalize()

    if args.date:
        trade_date = pd.Timestamp(args.date)
        prior = sessions[sessions < trade_date]
    else:
        now = pd.Timestamp.now()
        last = sessions[sessions <= now.normalize()][-1]
        after_close = now > pd.Timestamp(f"{last.date()} {CLOSE_TIME}")
        trade_date = (last + pd.offsets.BDay(1)).normalize() if after_close else last
        prior = sessions[sessions < trade_date]
    if prior.empty:
        raise SystemExit("No prior session in close_matrix for that date")
    prev_trade_date = prior[-1]

    print(f"Overnight window: {prev_trade_date.date()} {CLOSE_TIME} → {trade_date.date()} {OPEN_TIME}\n")
    result = scan(trade_date.date(), prev_trade_date.date(),
                  args.min_score, args.min_turnover)
    if result.empty:
        print("No material overnight filings.")
        return

    show = result.head(args.top)
    for row in show.itertuples():
        flag = "🔥" if row.neglected else "  "
        print(f"{row.direction} {abs(row.score):4.1f} {flag} {row.symbol:<12} "
              f"₹{row.avg_turnover_cr or 0:6.1f}cr/d  [{row.categories}]  {row.reasons}")

    os.makedirs(OUT_DIR, exist_ok=True)
    out_path = os.path.join(OUT_DIR, f"overnight_news_{trade_date.date()}.csv")
    result.to_csv(out_path, index=False)
    print(f"\n{len(result)} names → {out_path}")


if __name__ == "__main__":
    main()
