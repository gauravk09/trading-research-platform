"""
pdf_human.py — render a study's markdown into a human-friendly PDF.

The division of labour (user decision 2026-07-26): markdown is the machine
artifact, the PDF is the human one — so headings are styled, pipe tables become
real ruled tables, bullets indent, **bold** renders, charts appear inline where
the markdown references them, and any charts passed separately land in a
captioned appendix. Parser is deliberately minimal: it only handles the
constructs our generators emit (#/##/### headings, pipe tables, - bullets,
![img](path), --- rules, **bold**, plain paragraphs).

Drop-in signature match for the old monospace renderer:
    build_pdf(md_path, charts, pdf_path)   # charts = [(png_path, caption), ...]
"""

import os
import re

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import (Image, PageBreak, Paragraph, SimpleDocTemplate,
                                Spacer, Table, TableStyle)

_ss = getSampleStyleSheet()
S = {
    "title": ParagraphStyle("t", parent=_ss["Title"], fontSize=16, leading=20,
                            spaceAfter=10),
    "h1": ParagraphStyle("h1", parent=_ss["Heading1"], fontSize=13, leading=16,
                         spaceBefore=12, spaceAfter=6,
                         textColor=colors.HexColor("#1a3d6e")),
    "h2": ParagraphStyle("h2", parent=_ss["Heading2"], fontSize=11, leading=14,
                         spaceBefore=9, spaceAfter=4,
                         textColor=colors.HexColor("#1a3d6e")),
    "body": ParagraphStyle("b", parent=_ss["BodyText"], fontSize=9, leading=12.5),
    "bullet": ParagraphStyle("bl", parent=_ss["BodyText"], fontSize=9,
                             leading=12.5, leftIndent=14, bulletIndent=4),
    "cell": ParagraphStyle("c", parent=_ss["BodyText"], fontSize=7.5, leading=9.5),
    "cellh": ParagraphStyle("ch", parent=_ss["BodyText"], fontSize=7.5,
                            leading=9.5, fontName="Helvetica-Bold"),
    "caption": ParagraphStyle("cap", parent=_ss["BodyText"], fontSize=8,
                              leading=11, textColor=colors.HexColor("#555555"),
                              spaceBefore=2, spaceAfter=10),
}
USABLE_W = A4[0] - 3 * cm


def _inline(text: str) -> str:
    """Escape + translate the two inline constructs our markdown uses."""
    text = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    text = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", text)
    text = re.sub(r"`(.+?)`", r"<font face='Courier'>\1</font>", text)
    return text


def _table(rows: list) -> Table:
    cells = [[Paragraph(_inline(c), S["cellh" if i == 0 else "cell"])
              for c in row] for i, row in enumerate(rows)]
    ncol = max(len(r) for r in cells)
    for r in cells:                                  # ragged rows -> pad
        r.extend([Paragraph("", S["cell"])] * (ncol - len(r)))
    # First column gets a third more width than the rest; total fits the page.
    first = min(USABLE_W * 0.30, USABLE_W / ncol * 1.6)
    rest = (USABLE_W - first) / max(ncol - 1, 1)
    t = Table(cells, colWidths=[first] + [rest] * (ncol - 1), repeatRows=1)
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e8edf5")),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#b8c2d0")),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1),
         [colors.white, colors.HexColor("#f5f7fa")]),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 2),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
    ]))
    return t


def _image(path: str) -> list:
    from reportlab.lib.utils import ImageReader
    iw, ih = ImageReader(path).getSize()
    w = min(USABLE_W, iw)
    return [Spacer(1, 4), Image(path, width=w, height=ih * w / iw), Spacer(1, 4)]


def _md_to_flowables(md_path: str) -> tuple:
    base = os.path.dirname(os.path.abspath(md_path))
    with open(md_path) as f:
        lines = f.read().splitlines()
    flow, para, table_rows, images_seen = [], [], [], set()

    def flush_para():
        if para:
            flow.append(Paragraph(_inline(" ".join(para)), S["body"]))
            flow.append(Spacer(1, 3))
            para.clear()

    def flush_table():
        if table_rows:
            flow.append(_table(table_rows))
            flow.append(Spacer(1, 6))
            table_rows.clear()

    for ln in lines:
        stripped = ln.strip()
        if stripped.startswith("|"):
            flush_para()
            cells = [c.strip() for c in stripped.strip("|").split("|")]
            if not all(re.fullmatch(r":?-{2,}:?", c) for c in cells):
                table_rows.append(cells)
            continue
        flush_table()
        m = re.match(r"!\[[^\]]*\]\(([^)]+)\)", stripped)
        if m:
            flush_para()
            path = os.path.join(base, m.group(1))
            if os.path.exists(path):
                flow.extend(_image(path))
                images_seen.add(os.path.basename(path))
            continue
        if stripped.startswith("### "):
            flush_para()
            flow.append(Paragraph(_inline(stripped[4:]), S["h2"]))
        elif stripped.startswith("## "):
            flush_para()
            flow.append(Paragraph(_inline(stripped[3:]), S["h1"]))
        elif stripped.startswith("# "):
            flush_para()
            flow.append(Paragraph(_inline(stripped[2:]), S["title"]))
        elif stripped.startswith(("- ", "* ")):
            flush_para()
            flow.append(Paragraph(_inline(stripped[2:]), S["bullet"],
                                  bulletText="•"))
        elif stripped in ("---", "***"):
            flush_para()
            flow.append(Spacer(1, 8))
        elif stripped.startswith("> "):
            flush_para()
            flow.append(Paragraph("<i>" + _inline(stripped[2:]) + "</i>", S["body"]))
        elif stripped == "":
            flush_para()
        else:
            para.append(stripped)
    flush_para()
    flush_table()
    return flow, images_seen


def build_pdf(md_path: str, charts: list, pdf_path: str) -> None:
    """Human-readable PDF: styled markdown body + captioned appendix for any
    chart not already embedded inline by the markdown itself."""
    flow, images_seen = _md_to_flowables(md_path)
    extra = [(p, cap) for p, cap in charts
             if os.path.exists(p) and os.path.basename(p) not in images_seen]
    if extra:
        flow.append(PageBreak())
        flow.append(Paragraph("Charts", S["h1"]))
        for path, caption in extra:
            flow.extend(_image(path))
            flow.append(Paragraph(_inline(caption), S["caption"]))
    SimpleDocTemplate(pdf_path, pagesize=A4,
                      leftMargin=1.5 * cm, rightMargin=1.5 * cm,
                      topMargin=1.5 * cm, bottomMargin=1.5 * cm).build(flow)
