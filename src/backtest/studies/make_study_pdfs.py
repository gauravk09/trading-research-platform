"""
make_study_pdfs.py — Render every study write-up + charts into a PDF.

For each output/studies/<slug>_study.md with a matching <slug>_events.csv,
produces output/studies/<slug>_study.pdf containing:
  - the full write-up text (wrapped, monospace so pasted tables line up)
  - a standard chart page built from the event log: forward returns by
    horizon, regime split, RS-quintile split, D+5 return distribution,
    and signal frequency per year

Usage:
    ~/anaconda3/bin/python src/backtest/studies/make_study_pdfs.py [slug ...]
(no args = all studies with both files present, plus MASTER_SUMMARY)
"""

import os
import sys
import textwrap

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.backends.backend_pdf import PdfPages

STUDIES_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "..", "output", "studies")

PAGE = (8.27, 11.69)  # A4 portrait
LINES_PER_PAGE = 88
WRAP_COLS = 108


def text_pages(pdf: PdfPages, md_path: str) -> None:
    with open(md_path) as f:
        raw = f.read()
    lines = []
    for line in raw.splitlines():
        if len(line) <= WRAP_COLS:
            lines.append(line)
        else:
            lines.extend(textwrap.wrap(line, WRAP_COLS,
                                       subsequent_indent="  ",
                                       break_long_words=False) or [""])
    for start in range(0, len(lines), LINES_PER_PAGE):
        fig = plt.figure(figsize=PAGE)
        fig.text(0.05, 0.97, "\n".join(lines[start:start + LINES_PER_PAGE]),
                 family="monospace", fontsize=6.5, va="top")
        pdf.savefig(fig)
        plt.close(fig)


def chart_page(pdf: PdfPages, events: pd.DataFrame, title: str) -> None:
    ev = events.copy()
    ev["regime"] = pd.cut(ev["breadth_score"], [-np.inf, -2, 0, np.inf],
                          labels=["bad", "neutral", "good"])
    ev["rs_bucket"] = pd.cut(ev["rs_rank"], [0, 20, 40, 60, 80, 100],
                             labels=["0-20", "20-40", "40-60", "60-80", "80-100"])
    horizons = [n for n in [1, 2, 3, 5, 10, 20, 40, 60] if f"ret_o{n}" in ev.columns]

    fig, axes = plt.subplots(3, 2, figsize=PAGE)
    fig.suptitle(title, fontsize=11, fontweight="bold")

    ax = axes[0][0]
    med = [ev[f"ret_o{n}"].median() for n in horizons]
    mean = [ev[f"ret_o{n}"].mean() for n in horizons]
    x = np.arange(len(horizons))
    ax.bar(x - 0.2, med, 0.4, label="median")
    ax.bar(x + 0.2, mean, 0.4, label="mean")
    ax.set_xticks(x, [f"D+{n}" for n in horizons])
    ax.axhline(0, color="k", lw=0.5)
    ax.set_title("Forward return from D+1 open (%)", fontsize=8)
    ax.legend(fontsize=6)

    ax = axes[0][1]
    pick = [n for n in (5, 20) if n in horizons] or horizons[-1:]
    reg = ev.groupby("regime", observed=True)[[f"ret_o{n}" for n in pick]].median()
    reg.plot.bar(ax=ax, rot=0, legend=True)
    ax.axhline(0, color="k", lw=0.5)
    ax.set_title("Median return by market regime (%)", fontsize=8)
    ax.legend([f"D+{n}" for n in pick], fontsize=6)
    ax.set_xlabel("")

    ax = axes[1][0]
    n_seg = pick[-1]
    good = ev[ev["regime"] == "good"]
    rs = good.groupby("rs_bucket", observed=True)[f"ret_o{n_seg}"].median()
    rs.plot.bar(ax=ax, rot=0, color="tab:green")
    ax.axhline(0, color="k", lw=0.5)
    ax.set_title(f"Good market: median D+{n_seg} return by RS rank (%)", fontsize=8)
    ax.set_xlabel("")

    ax = axes[1][1]
    n_hist = 5 if 5 in horizons else horizons[0]
    r = ev[f"ret_o{n_hist}"].dropna().clip(-30, 30)
    ax.hist(r, bins=60, color="tab:blue")
    ax.axvline(0, color="k", lw=0.5)
    ax.axvline(r.median(), color="r", lw=1, label=f"median {r.median():+.2f}%")
    ax.set_title(f"D+{n_hist} return distribution (clipped ±30%)", fontsize=8)
    ax.legend(fontsize=6)

    ax = axes[2][0]
    per_year = pd.to_datetime(ev["date"], utc=True).dt.year.value_counts().sort_index()
    per_year.plot.bar(ax=ax, rot=45, color="tab:gray")
    ax.set_title("Signals per year", fontsize=8)
    ax.set_xlabel("")

    ax = axes[2][1]
    win = [(ev[f"ret_o{n}"].dropna() > 0).mean() * 100 for n in horizons]
    ax.plot([f"D+{n}" for n in horizons], win, marker="o")
    ax.axhline(50, color="k", lw=0.5, ls="--")
    ax.set_title("Win rate by horizon (%)", fontsize=8)

    for row in axes:
        for a in row:
            a.tick_params(labelsize=6)
    fig.tight_layout(rect=[0, 0, 1, 0.97])
    pdf.savefig(fig)
    plt.close(fig)


def build_pdf(slug: str) -> None:
    md = os.path.join(STUDIES_DIR, f"{slug}_study.md")
    csv = os.path.join(STUDIES_DIR, f"{slug}_events.csv")
    out = os.path.join(STUDIES_DIR, f"{slug}_study.pdf")
    with PdfPages(out) as pdf:
        text_pages(pdf, md)
        if os.path.exists(csv):
            events = pd.read_csv(csv, parse_dates=["date"])
            if {"breadth_score", "rs_rank"}.issubset(events.columns):
                chart_page(pdf, events, f"{slug} — event-log charts")
        png = os.path.join(STUDIES_DIR, f"{slug}_equity.png")
        if os.path.exists(png):
            fig, ax = plt.subplots(figsize=PAGE)
            ax.imshow(plt.imread(png))
            ax.axis("off")
            pdf.savefig(fig)
            plt.close(fig)
    print(f"  {os.path.basename(out)}")


def build_master() -> None:
    md = os.path.join(STUDIES_DIR, "MASTER_SUMMARY.md")
    if not os.path.exists(md):
        return
    out = os.path.join(STUDIES_DIR, "MASTER_SUMMARY.pdf")
    with PdfPages(out) as pdf:
        text_pages(pdf, md)
    print(f"  {os.path.basename(out)}")


def main():
    slugs = sys.argv[1:]
    if not slugs:
        slugs = sorted(f[:-len("_study.md")] for f in os.listdir(STUDIES_DIR)
                       if f.endswith("_study.md"))
    print("Rendering study PDFs...")
    for slug in slugs:
        build_pdf(slug)
    if not sys.argv[1:]:
        build_master()


if __name__ == "__main__":
    main()
