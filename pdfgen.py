"""PDF banane ka engine (reportlab). Reports ka data reports.py me hai.
Font: system TTF mil jaaye to unicode, warna Helvetica (latin-1; baaki chars '?' ban jaate hain)."""
import io
from datetime import datetime, timezone

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

import cardimg

INK, TEAL, SOFT, LINE = colors.HexColor("#0b2530"), colors.HexColor("#0f6b7a"), colors.HexColor("#f3f8f9"), colors.HexColor("#d5e3e7")
GOOD, BAD, MUTED = colors.HexColor("#15803d"), colors.HexColor("#b91c1c"), colors.HexColor("#5b7380")
_F = {}


def _fonts():
    if _F:
        return _F
    reg, bold = cardimg._find(False), cardimg._find(True)
    try:
        if reg and bold:
            pdfmetrics.registerFont(TTFont("PdfBody", reg))
            pdfmetrics.registerFont(TTFont("PdfBold", bold))
            _F.update(body="PdfBody", bold="PdfBold", uni=True)
            return _F
    except Exception:
        pass
    _F.update(body="Helvetica", bold="Helvetica-Bold", uni=False)
    return _F


def safe(t):
    t = str(t).replace("₹", "Rs ")
    if _fonts()["uni"]:
        return t
    return t.encode("latin-1", "replace").decode("latin-1")


def utc(ts, fmt="%d/%m/%y %H:%M"):
    return datetime.fromtimestamp(ts, timezone.utc).strftime(fmt) if ts else "-"


def build(brand, title, subtitle, summary, sections, note=""):
    """summary  : [(label, value)]
    sections : [(heading, cols, rows)]  cols = [(header, rel_width, align 'l'|'r'|'c', wrap bool)]
               cell = "text" | ("text", 'good'|'bad'|'muted')"""
    f = _fonts()
    buf = io.BytesIO()
    W, H = A4
    margin = 12 * mm
    gen = datetime.now(timezone.utc).strftime("%d %b %Y %H:%M UTC")

    def deco(c, doc):
        c.saveState()
        c.setFillColor(INK)
        c.rect(0, H - 17 * mm, W, 17 * mm, stroke=0, fill=1)
        c.setFillColor(colors.HexColor("#22d3be"))
        c.rect(0, H - 17.8 * mm, W, 0.8 * mm, stroke=0, fill=1)
        c.setFillColor(colors.white)
        c.setFont(f["bold"], 13)
        c.drawString(margin, H - 11 * mm, safe(brand.upper())[:48])
        c.setFont(f["body"], 8.5)
        c.drawRightString(W - margin, H - 11 * mm, safe(title))
        c.setFillColor(MUTED)
        c.setFont(f["body"], 7.5)
        c.drawString(margin, 8 * mm, safe(f"Generated {gen} · Timezone: UTC · Private document"))
        c.drawRightString(W - margin, 8 * mm, f"Page {doc.page}")
        c.restoreState()

    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=margin, rightMargin=margin, topMargin=24 * mm,
                            bottomMargin=16 * mm, title=safe(title), author=safe(brand))
    sty = lambda **k: ParagraphStyle("x", fontName=k.pop("font", f["body"]), **k)
    flow = [Paragraph(safe(title), sty(font=f["bold"], fontSize=17, leading=21, textColor=INK)),
            Paragraph(safe(subtitle), sty(fontSize=9, leading=12, textColor=MUTED)), Spacer(1, 4 * mm)]
    if summary:
        pairs = [summary[i:i + 2] for i in range(0, len(summary), 2)]
        data = []
        for p in pairs:
            row = []
            for lab, val in p:
                row += [Paragraph(safe(lab).upper(), sty(font=f["bold"], fontSize=6.5, leading=8, textColor=MUTED)),
                        Paragraph(safe(val), sty(font=f["bold"], fontSize=10, leading=12, textColor=INK))]
            row += [""] * (4 - len(row))
            data.append(row)
        avail = W - 2 * margin
        t = Table(data, colWidths=[avail * .2, avail * .3, avail * .2, avail * .3])
        t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), SOFT), ("BOX", (0, 0), (-1, -1), .6, LINE),
                               ("INNERGRID", (0, 0), (-1, -1), .3, LINE), ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                               ("TOPPADDING", (0, 0), (-1, -1), 5), ("BOTTOMPADDING", (0, 0), (-1, -1), 5)]))
        flow += [t, Spacer(1, 5 * mm)]
    avail = W - 2 * margin
    for head, cols, rows in sections:
        flow.append(Paragraph(safe(head), sty(font=f["bold"], fontSize=11, leading=14, textColor=TEAL)))
        flow.append(Spacer(1, 1.5 * mm))
        if not rows:
            flow += [Paragraph("No records yet.", sty(fontSize=9, textColor=MUTED)), Spacer(1, 4 * mm)]
            continue
        tot = sum(c[1] for c in cols)
        widths = [avail * c[1] / tot for c in cols]
        cell = sty(fontSize=7.5, leading=9)
        data = [[Paragraph(safe(c[0]), sty(font=f["bold"], fontSize=7.5, leading=9, textColor=colors.white,
                                           alignment={"l": 0, "c": 1, "r": 2}[c[2]])) for c in cols]]
        cmds = [("BACKGROUND", (0, 0), (-1, 0), INK), ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("FONTNAME", (0, 1), (-1, -1), f["body"]), ("FONTSIZE", (0, 1), (-1, -1), 7.5),
                ("LINEBELOW", (0, 0), (-1, -1), .25, LINE), ("TOPPADDING", (0, 0), (-1, -1), 3),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3)]
        for ri, r in enumerate(rows, 1):
            line = []
            for ci, v in enumerate(r):
                txt, tone = (v if isinstance(v, tuple) else (v, None))
                if cols[ci][3]:
                    line.append(Paragraph(safe(txt), cell))
                else:
                    line.append(safe(txt))
                if tone:
                    cmds.append(("TEXTCOLOR", (ci, ri), (ci, ri), {"good": GOOD, "bad": BAD, "muted": MUTED}[tone]))
                if cols[ci][2] != "l":
                    cmds.append(("ALIGN", (ci, ri), (ci, ri), "RIGHT" if cols[ci][2] == "r" else "CENTER"))
            if ri % 2 == 0:
                cmds.append(("BACKGROUND", (0, ri), (-1, ri), SOFT))
            data.append(line)
        t = Table(data, colWidths=widths, repeatRows=1)
        t.setStyle(TableStyle(cmds))
        flow += [t, Spacer(1, 6 * mm)]
    if note:
        flow.append(Paragraph(safe(note), sty(fontSize=8, textColor=MUTED)))
    doc.build(flow, onFirstPage=deco, onLaterPages=deco)
    return buf.getvalue()
