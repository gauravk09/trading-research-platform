"""
gold_macro.py — the macro backdrop of every gold blow-off cycle, and a
macro-tilted probability for how the current cycle resolves.

For each cycle from gold_cycle_analogs.py it records, at the ANCHOR (the point
that matches today) using only data published by then:
  fed   — 6-month change in the effective fed funds rate (hiking / on hold / cutting)
  real  — 6-month change in the 10y real yield (TIPS from 2003, else 10y minus CPI YoY)
  infl  — 6-month change in CPI YoY
  usd   — 6-month change in the broad trade-weighted dollar
  cb    — official-sector gold flow (hand-labelled; no free series goes back to 1973)
and what those same series did over the NEXT 12 months (what actually decided it).

Probability = price-structure base rate blended 50/50 with a macro-similarity
weighting (analogs that looked like today at the anchor count more).

Output: output/studies/gold_cycle_analogs/macro.json (feeds the vlog artifact).
Run: ~/anaconda3/bin/python src/backtest/studies/gold_macro.py
"""

import json
import os

import pandas as pd

import gold_cycle_analogs as g

FRED = "https://fred.stlouisfed.org/graph/fredgraph.csv?id={}"
LAG = pd.DateOffset(months=1)              # monthly CPI/yields are published ~1 month later

# Official-sector flows at each anchor. Sources: IMF IFS / World Gold Council annual tallies.
CB_FLOW = {
    1973: ("none", "Post-Bretton Woods; no official buying, US/IMF sales about to start"),
    1980: ("selling", "US Treasury and IMF auctions (1975-80) had just ended"),
    2006: ("selling", "European banks selling ~400-500 t/yr under the gold agreement"),
    2008: ("selling", "European agreement sales still running (~230 t in 2008)"),
    2011: ("buying", "Emerging-market banks buying ~550-650 t/yr, but ETFs about to dump ~880 t"),
    2020: ("buying", "Record ~1,080 t bought in 2022 after Russia's reserves were frozen"),
    2026: ("buying", "Record Q2-2026: 289 t (World Gold Council), Poland and China leading"),
}

STORY = {
    1973: "Oil shock, inflation running ahead of a Fed that was hiking too slowly. Real rates collapsed and gold went on to new highs within months.",
    1980: "Volcker took the funds rate towards 19%. Real yields went from negative to +4% and the dollar surged. Gold lost 70% over 19 years.",
    2006: "The Fed stopped hiking in June 2006, a month after the top. Rates plateaued, the dip was bought, and new highs came in 16 months.",
    2008: "The Lehman liquidity crunch forced everything to be sold, gold included, as the dollar spiked. Then the Fed cut to zero and started QE, and gold went vertical.",
    2011: "The Fed was on hold, but the 2013 taper tantrum pushed real yields up 1.5 points, the dollar rallied and ETFs dumped ~880 t. That set off a 4-year bear.",
    2020: "The fastest hiking cycle in 40 years: real yields +2.7 points and a +15% dollar. Gold should have crashed, but record central-bank buying held it to -21%.",
}


def fred(series_id: str) -> pd.Series:
    df = pd.read_csv(FRED.format(series_id), index_col=0, parse_dates=True, na_values=".")
    return df.iloc[:, 0].dropna()


def load_macro() -> pd.DataFrame:
    """Month-start frame: fed funds, CPI YoY, 10y real yield, broad dollar."""
    ff = fred("DFF")
    cpi_yoy = fred("CPIAUCSL").pct_change(12, fill_method=None) * 100
    y10 = fred("GS10")
    tips = fred("DFII10").resample("MS").mean()
    real = (y10 - cpi_yoy).where(lambda x: x.index < "2003-01-01").combine_first(tips)
    old, new = fred("TWEXBMTH"), fred("DTWEXBGS").resample("MS").mean()
    usd = pd.concat([old[:"2005-12"], new["2006-01":] * old.loc["2006-01-01"] / new.loc["2006-01-01"]])
    m = pd.DataFrame({"fed": ff.resample("MS").first(), "infl": cpi_yoy, "real": real, "usd": usd}).loc["1970":]
    m.attrs["fed_daily"] = ff
    return m


def known_at(m: pd.DataFrame, d, col: str) -> float:
    """Latest value of `col` that was published by date d (fed funds is daily, no lag)."""
    if col == "fed":
        return m.attrs["fed_daily"][:d].iloc[-1]
    return m[col][:d - LAG].dropna().iloc[-1]


def trend(m, d, col, months=6) -> float:
    earlier = d - pd.DateOffset(months=months)
    now, then = known_at(m, d, col), known_at(m, earlier, col)
    return (now / then - 1) * 100 if col == "usd" else now - then


def direction(x: float, band: float) -> str:
    return "up" if x > band else "down" if x < -band else "flat"


def features(m, d) -> dict:
    f = dict(fed=trend(m, d, "fed"), real=trend(m, d, "real"), infl=trend(m, d, "infl"), usd=trend(m, d, "usd"))
    f["dirs"] = dict(fed=direction(f["fed"], 0.2), real=direction(f["real"], 0.25),
                     infl=direction(f["infl"], 0.3), usd=direction(f["usd"], 2))
    return f


def next_12m(m, d) -> dict:
    end = d + pd.DateOffset(months=12)
    if end > m.index[-1]:
        return {}
    return dict(fed=known_at(m, end, "fed") - known_at(m, d, "fed"),
                real=m.real[:end].dropna().iloc[-1] - known_at(m, d, "real"),
                usd=(m.usd[:end].dropna().iloc[-1] / known_at(m, d, "usd") - 1) * 100)


def similarity(a: dict, b: dict, cb_a: str, cb_b: str) -> float:
    """Count of matching macro directions at the anchor (0-5)."""
    return sum(a["dirs"][k] == b["dirs"][k] for k in a["dirs"]) + (cb_a == cb_b)


def weekly_window(series: pd.Series, start, end) -> list:
    w = series[start:end].resample("W-FRI").last().dropna()
    return [[d.strftime("%Y-%m-%d"), round(float(v), 2)] for d, v in w.items()]


def monthly_window(m: pd.DataFrame, col: str, start, end) -> list:
    x = m[col][start:end].dropna()
    return [[d.strftime("%Y-%m-%d"), round(float(v), 2)] for d, v in x.items()]


def main():
    gold = g.load_gold()
    m = load_macro()
    cycles = g.find_cycles(gold)
    for c in cycles:
        c["type"] = g.classify(c)
    blowoffs = [c for c in cycles if c["run12"] >= g.BLOWOFF]
    now_c = blowoffs[-1]
    now_f = features(m, gold.index[-1])
    now_cb = CB_FLOW[2026][0]

    out = []
    for c in blowoffs:
        yr = c["peak_d"].year
        is_now = c is now_c
        f = now_f if is_now else features(m, c["anchor"])
        start = c["peak_d"] - pd.DateOffset(months=12)
        end = gold.index[-1] if is_now else c["peak_d"] + pd.DateOffset(months=48)
        out.append(dict(
            year=yr, now=is_now, type=None if is_now else c["type"][0],
            peak_d=c["peak_d"].strftime("%Y-%m-%d"), peak=round(c["peak"], 1),
            l1_d=c["l1_d"].strftime("%Y-%m-%d"), l1=round(c["l1"], 1),
            b_d=c["b_d"].strftime("%Y-%m-%d"), b=round(c["b"], 1),
            anchor=(gold.index[-1] if is_now else c["anchor"]).strftime("%Y-%m-%d"),
            low_d=c["low_d"].strftime("%Y-%m-%d"), low=round(c["low"], 1),
            run12=round(c["run12"], 3), final_dd=None if is_now else round(c["final_dd"], 3),
            reclaim=c["reclaim"].strftime("%Y-%m-%d") if c["reclaim"] is not None else None,
            at_anchor={k: round(v, 2) for k, v in f.items() if k != "dirs"}, dirs=f["dirs"],
            next12={k: round(v, 2) for k, v in next_12m(m, c["anchor"]).items()} if not is_now else {},
            cb=CB_FLOW[yr][0], cb_note=CB_FLOW[yr][1], story=STORY.get(yr, ""),
            similarity=None if is_now else similarity(f, now_f, CB_FLOW[yr][0], now_cb),
            gold=weekly_window(gold, start, end),
            fed=monthly_window(m, "fed", start, end), real=monthly_window(m, "real", start, end),
            infl=monthly_window(m, "infl", start, end),
        ))

    hist = [o for o in out if not o["now"]]
    base = {k: sum(o["type"] == k for o in hist) / len(hist) for k in "ABC"}
    wsum = sum(o["similarity"] for o in hist)
    macro = {k: sum(o["similarity"] for o in hist if o["type"] == k) / wsum for k in "ABC"}
    blend = {k: round((base[k] + macro[k]) / 2, 3) for k in "ABC"}
    payload = dict(asof=gold.index[-1].strftime("%Y-%m-%d"), price=round(float(gold.iloc[-1]), 1),
                   base={k: round(v, 3) for k, v in base.items()},
                   macro={k: round(v, 3) for k, v in macro.items()}, blend=blend, cycles=out)
    path = os.path.join(g.OUT, "macro.json")
    json.dump(payload, open(path, "w"))

    for o in out:
        print(o["year"], o["type"], o["dirs"], o["cb"], "sim", o["similarity"], "next12", o["next12"])
    print("now at_anchor", out[-1]["at_anchor"])
    print("base", payload["base"], "\nmacro", payload["macro"], "\nblend", blend, "\n->", path)


if __name__ == "__main__":
    main()
