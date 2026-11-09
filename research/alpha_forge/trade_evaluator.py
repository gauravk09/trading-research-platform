"""trade_evaluator.py — ingest a trades Excel/CSV (from our engine or quantstats
export) and explore it: all trades, biggest winners/losers, worst loss period,
and summary statistics.

Run:  streamlit run trade_evaluator.py
Reuses quantstats for the returns-side metrics; trade stats follow vectorbt's
standard definitions (win rate, profit factor, expectancy).
"""

import io

import numpy as np
import pandas as pd
import streamlit as st

st.set_page_config(page_title="Trade Evaluator", layout="wide", page_icon="📊")

ALIASES = {
    "asset": ["asset", "symbol", "instrument", "ticker", "stock", "name"],
    "side": ["side", "direction", "type"],
    "entry": ["entry", "entry_date", "entrytime", "open_date", "opened"],
    "exit": ["exit", "exit_date", "close_date", "closed"],
    "pnl": ["pnl", "return", "returns", "ret", "profit", "pl", "r"],
}


def find_col(cols, keys):
    low = {c.lower(): c for c in cols}
    for k in keys:
        if k in low:
            return low[k]
    return None


@st.cache_data(show_spinner=False)
def read_any(data, filename):
    if filename.endswith(".csv"):
        return {"CSV": pd.read_csv(io.BytesIO(data))}
    xl = pd.ExcelFile(io.BytesIO(data))
    return {s: xl.parse(s) for s in xl.sheet_names}


def normalize(df):
    cols = df.columns
    m = {std: find_col(cols, keys) for std, keys in ALIASES.items()}
    if m["pnl"] is None or m["asset"] is None:
        return None, m
    out = pd.DataFrame({"asset": df[m["asset"]].astype(str),
                        "pnl": pd.to_numeric(df[m["pnl"]], errors="coerce")})
    out["side"] = df[m["side"]].astype(str).str.upper() if m["side"] else "LONG"
    for c in ("entry", "exit"):
        out[c] = pd.to_datetime(df[m[c]], errors="coerce") if m[c] else pd.NaT
    out = out.dropna(subset=["pnl"])
    if out["exit"].notna().any():
        out["year"] = out["exit"].dt.year
        out["days"] = (out["exit"] - out["entry"]).dt.days
    return out, m


def worst_loss_period(eq):
    """Peak-to-trough of the cumulative-P&L curve: start, end, depth."""
    peak = eq.cummax()
    dd = eq - peak
    trough = dd.idxmin()
    start = eq.loc[:trough].idxmax()
    return start, trough, dd.min()


st.title("📊 Trade Evaluator")
st.caption("Ingest a trades Excel/CSV and inspect every trade, the biggest moves, and the worst loss stretch.")

import glob
import os

HERE = os.path.dirname(os.path.abspath(__file__))
up = st.file_uploader("Upload a trades file (.xlsx / .csv)", type=["xlsx", "csv"])
samples = sorted(glob.glob(os.path.join(HERE, "backtest_reports", "*_eval.xlsx")))
if up is None:
    st.info("Upload a trades file, or load a bundled sample below. Our engine writes one via "
            "`python export_excel.py <factor>` → `backtest_reports/<factor>_eval.xlsx`.")
    if samples and st.button(f"Load sample: {os.path.basename(samples[0])}"):
        st.session_state["sample"] = samples[0]
    if "sample" not in st.session_state:
        st.stop()
    data, fname = open(st.session_state["sample"], "rb").read(), st.session_state["sample"]
else:
    data, fname = up.getvalue(), up.name

sheets = read_any(data, fname)
sheet = st.selectbox("Sheet", list(sheets)) if len(sheets) > 1 else list(sheets)[0]
raw = sheets[sheet]
trades, mapping = normalize(raw)
if trades is None:
    st.error(f"Couldn't find an asset + return/pnl column. Detected: {mapping}. "
             "Rename columns or pick another sheet.")
    st.stop()

# ---- controls ----
with st.sidebar:
    st.header("Filters")
    cap = st.slider("Cap |return| at (%)", 10, 2000, 100, 10,
                    help="Guards against unadjusted corporate-action glitches "
                         "(e.g. an un-split price showing +374,600%).")
    capf = cap / 100
    sides = st.multiselect("Side", sorted(trades["side"].unique()),
                           default=sorted(trades["side"].unique()))
    st.caption(f"column mapping: {mapping}")

df = trades[trades["side"].isin(sides)].copy()
n_glitch = int((df["pnl"].abs() > capf).sum())
df["pnl"] = df["pnl"].clip(-capf, capf)

# ---- KPIs (vectorbt-standard trade stats) ----
wins, losses = df[df.pnl > 0], df[df.pnl < 0]
win_rate = len(wins) / len(df) if len(df) else 0
avg_w, avg_l = wins.pnl.mean(), losses.pnl.mean()
pf = wins.pnl.sum() / -losses.pnl.sum() if losses.pnl.sum() else np.inf
expectancy = df.pnl.mean()

st.subheader(f"{sheet} — {len(df):,} trades")
if n_glitch:
    st.warning(f"{n_glitch} trade(s) exceeded ±{cap}% and were capped "
               f"(likely unadjusted splits/bonuses, not real P&L).")
k = st.columns(6)
k[0].metric("Trades", f"{len(df):,}")
k[1].metric("Win rate", f"{win_rate*100:.1f}%")
k[2].metric("Avg win", f"{avg_w*100:+.2f}%")
k[3].metric("Avg loss", f"{avg_l*100:+.2f}%")
k[4].metric("Profit factor", f"{pf:.2f}")
k[5].metric("Expectancy", f"{expectancy*100:+.3f}%")
st.caption("`pnl` is market-neutral (leg return minus the equal-weight universe over "
           "the same window). Note: these are quintile *stints* held entry→exit; a "
           "cross-sectional factor actually rebalances daily on a 5-day-forward signal, "
           "so per-stint stats under-state it — the factor's true edge is the daily L/S "
           "in the quantstats/Alphalens reports. For a real swing/discretionary trade "
           "log, these stats are exactly right.")

tab_trades, tab_hi, tab_stats, tab_eq = st.tabs(
    ["All trades", "Biggest & worst period", "Statistics", "Equity"])

with tab_trades:
    st.caption("Sortable — click any column header. P&L shown as a fraction "
               "(0.05 = +5%). Styler is skipped on the full table for speed; the "
               "Biggest & worst tab colour-codes the extremes.")
    show = df.sort_values("exit" if df["exit"].notna().any() else "pnl", ascending=False)
    st.dataframe(show, use_container_width=True, height=520)

with tab_hi:
    c1, c2 = st.columns(2)
    c1.markdown("**🏆 Biggest winners**")
    c1.dataframe(df.nlargest(10, "pnl")[["asset", "side", "entry", "exit", "pnl"]]
                 .style.format({"pnl": "{:+.2%}"}), use_container_width=True)
    c2.markdown("**💀 Biggest losers**")
    c2.dataframe(df.nsmallest(10, "pnl")[["asset", "side", "entry", "exit", "pnl"]]
                 .style.format({"pnl": "{:+.2%}"}), use_container_width=True)

    if df["exit"].notna().any():
        seq = df.sort_values("exit")
        eq = seq["pnl"].cumsum().reset_index(drop=True)
        eq.index = seq["exit"].values
        s, t, depth = worst_loss_period(eq)
        st.markdown("---")
        st.markdown(f"**📉 Worst loss period:** {pd.Timestamp(s).date()} → {pd.Timestamp(t).date()}  "
                    f"· drawdown **{depth*100:.1f}%** of cumulative per-trade P&L")
        window = seq[(seq["exit"] >= s) & (seq["exit"] <= t)]
        st.caption(f"{len(window)} trades closed in that stretch; "
                   f"{(window.pnl<0).mean()*100:.0f}% were losers.")
        st.line_chart(pd.DataFrame({"cumulative P&L": eq}))

with tab_stats:
    st.markdown("**By side**")
    g = df.groupby("side").agg(trades=("pnl", "size"), win_rate=("pnl", lambda x: (x > 0).mean()),
                               avg=("pnl", "mean"), total=("pnl", "sum"))
    st.dataframe(g.style.format({"win_rate": "{:.1%}", "avg": "{:+.2%}", "total": "{:+.1%}"}),
                 use_container_width=True)
    if "year" in df:
        st.markdown("**By exit year**")
        gy = df.groupby("year").agg(trades=("pnl", "size"), win_rate=("pnl", lambda x: (x > 0).mean()),
                                    avg=("pnl", "mean"), total=("pnl", "sum"))
        st.dataframe(gy.style.format({"win_rate": "{:.1%}", "avg": "{:+.2%}", "total": "{:+.1%}"}),
                     use_container_width=True)
    st.markdown("**Return distribution**")
    st.bar_chart(np.histogram(df.pnl, bins=40)[0])

with tab_eq:
    if df["exit"].notna().any():
        seq = df.sort_values("exit")
        eq = pd.Series(seq["pnl"].cumsum().values, index=seq["exit"].values)
        dd = eq - eq.cummax()
        c1, c2 = st.columns(2)
        c1.markdown("**Cumulative per-trade P&L**"); c1.line_chart(eq)
        c2.markdown("**Drawdown**"); c2.area_chart(dd)
    else:
        st.info("No exit dates in this file — equity curve needs dated trades.")
