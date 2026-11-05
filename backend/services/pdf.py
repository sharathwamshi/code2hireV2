"""PDF downloads (BUG-005): interview reports for the hiring team, feedback for candidates, and certificates.
Built with reportlab, so no browser or external service is needed on the server."""
import io
from datetime import datetime

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
from xml.sax.saxutils import escape

BRAND = colors.HexColor("#5B3FFF")
INK = colors.HexColor("#14213D")
MUTED = colors.HexColor("#5C6378")
SOFT = colors.HexColor("#F1F3F8")

_ss = getSampleStyleSheet()
H1 = ParagraphStyle("h1", parent=_ss["Heading1"], fontName="Helvetica-Bold", fontSize=18, textColor=INK, spaceAfter=4)
H2 = ParagraphStyle("h2", parent=_ss["Heading2"], fontName="Helvetica-Bold", fontSize=12.5, textColor=INK, spaceBefore=10, spaceAfter=4)
BODY = ParagraphStyle("b", parent=_ss["BodyText"], fontName="Helvetica", fontSize=9.5, leading=13.5, textColor=INK)
SMALL = ParagraphStyle("s", parent=BODY, fontSize=8, leading=11, textColor=MUTED)
CELL = ParagraphStyle("c", parent=BODY, fontSize=8.5, leading=11.5)


def P(text, style=BODY):
    return Paragraph(escape(str(text if text is not None else "")).replace("\n", "<br/>"), style)


def fmt_score(v, scale=5):
    """Same format as the screens: "3.0 / 5 · 60%". Report scores are stored out of 5."""
    if v is None:
        return "—"
    out5 = float(v)
    pct = round(out5 * 20)
    shown = out5 * scale / 5
    return f"{shown:.1f} / {scale} · {pct}%" if scale != 100 else f"{round(shown)} / 100"


def _footer(version):
    def draw(canvas, doc):
        canvas.saveState()
        canvas.setFont("Helvetica", 7.5)
        canvas.setFillColor(MUTED)
        canvas.drawString(18 * mm, 10 * mm, f"Code2Hire {version} · Powered by AcknowledgerFirst")
        canvas.drawRightString(doc.pagesize[0] - 18 * mm, 10 * mm, f"Page {doc.page} · generated {datetime.utcnow():%d %b %Y %H:%M} UTC")
        canvas.restoreState()
    return draw


def _table(rows, widths, header=True):
    t = Table([[c if not isinstance(c, str) else P(c, CELL) for c in r] for r in rows], colWidths=widths, repeatRows=1 if header else 0)
    style = [("VALIGN", (0, 0), (-1, -1), "TOP"), ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#DADDE6")),
             ("LEFTPADDING", (0, 0), (-1, -1), 5), ("RIGHTPADDING", (0, 0), (-1, -1), 5)]
    if header:
        style += [("BACKGROUND", (0, 0), (-1, 0), SOFT)]
    t.setStyle(TableStyle(style))
    return t


def report_pdf(v, version="", candidate=False):
    """v: the dict from routes.reports.view() for the chosen audience."""
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=18 * mm, rightMargin=18 * mm, topMargin=16 * mm, bottomMargin=18 * mm,
                            title=f"{v.get('round')} · {(v.get('candidate') or {}).get('name', '')}", author="Code2Hire")
    s = v.get("sections") or {}
    scale = v.get("scale") or 5
    mcq = v.get("type") == "mcq"
    out = [P("Code2Hire", ParagraphStyle("brand", parent=H2, textColor=BRAND, spaceBefore=0)),
           P(("Your feedback: " if candidate else "") + str(v.get("round") or "Interview report"), H1),
           P(f"{(v.get('candidate') or {}).get('name', '')} · {(v.get('job') or {}).get('title', '')}"
             + (f" · completed {v['completed_at'][:10]}" if v.get("completed_at") else ""), SMALL), Spacer(1, 6)]
    if candidate:
        res = v.get("result") or {}
        if res.get("cleared"):
            out.append(P("You cleared this round.", H2))
        if res.get("score") is not None:
            out.append(P(f"Your score: {fmt_score(res['score'], scale)}"))
        if res.get("next_step"):
            out.append(P(res["next_step"]))
    else:
        facts = [["Overall", fmt_score(v.get("overall"), scale)], ["Recommendation", str(v.get("recommendation") or "—").title()],
                 ["Decision", str(v.get("verdict") or "Not decided yet")], ["Integrity", "Clean" if not v.get("warnings") else f"{v['warnings']} warnings"],
                 ["Status", str(v.get("status") or "").replace("_", " ")], ["Interviewer", v.get("interviewer") or "—"]]
        out.append(_table(facts, [40 * mm, 134 * mm], header=False))
    if s.get("summary"):
        out += [P("Summary", H2), P(s["summary"])]
    for key, title in (("strengths", "Strengths"), ("gaps", "To work on"), ("next_steps", "Next steps"), ("learning_path", "Suggested learning")):
        items = s.get(key)
        if isinstance(items, list) and items:
            out.append(P(title, H2))
            for it in items[:12]:
                out.append(P("• " + (it if isinstance(it, str) else (it.get("title") or it.get("name") or str(it)))))
    comps = s.get("competencies") or []
    if comps and not candidate:
        out.append(P("Scores by competency", H2))
        rows = [["Competency", "Score", "Evidence"]] + [[c.get("name", ""), fmt_score(c.get("score"), scale), (c.get("evidence") or "")[:500]] for c in comps]
        out.append(_table(rows, [45 * mm, 32 * mm, 97 * mm]))
    qs = s.get("questions") or []
    if qs and not candidate:
        out.append(P("Question by question", H2))
        rows = [["#", "Question", "Answer", "Score"]]
        for i, q in enumerate(qs[:60]):
            ans = q.get("a") if not mcq else ("Correct" if q.get("correct") else "Skipped" if q.get("chosen") is None else "Wrong")
            rows.append([str(i + 1), (q.get("q") or "")[:400], (ans or "")[:700], fmt_score(q.get("score"), scale) if not mcq else ""])
        out.append(_table(rows, [8 * mm, 62 * mm, 82 * mm, 22 * mm]))
    integ = s.get("integrity")
    if isinstance(integ, dict) and integ.get("events") and not candidate:
        out.append(P("Integrity events", H2))
        rows = [["When", "Event", "Counted"]] + [[str(e.get("at", ""))[:19].replace("T", " "), e.get("label") or e.get("type", ""), "Yes" if e.get("counted") else "No"]
                                                 for e in integ["events"][:40]]
        out.append(_table(rows, [40 * mm, 104 * mm, 30 * mm]))
    if not candidate and v.get("history"):
        out.append(P("Review history", H2))
        for h in v["history"][:20]:
            out.append(P(f"v{h.get('version')} · {h.get('by', '')} · {str(h.get('at', ''))[:16].replace('T', ' ')}"
                         + (f" · verdict {h['verdict']}" if h.get("verdict") else "") + (f" · “{h['note']}”" if h.get("note") else ""), SMALL))
    out += [Spacer(1, 10), P("Confidential. Hira (AI) recommends; a named person reviews and decides." if not candidate else
                             "This feedback was reviewed by a person on the hiring team before it was shared with you.", SMALL)]
    doc.build(out, onFirstPage=_footer(version), onLaterPages=_footer(version))
    return buf.getvalue()


def certificate_pdf(c, holder, verify_url, version=""):
    """A one-page landscape certificate with the verification ID."""
    buf = io.BytesIO()
    page = landscape(A4)
    doc = SimpleDocTemplate(buf, pagesize=page, leftMargin=25 * mm, rightMargin=25 * mm, topMargin=28 * mm, bottomMargin=22 * mm,
                            title=f"{c.title} · {holder}", author="Code2Hire")
    center = lambda size, color=INK, bold=False, space=6: ParagraphStyle("x", parent=BODY, alignment=TA_CENTER, fontSize=size, leading=size * 1.3,  # noqa: E731
                                                                         textColor=color, fontName="Helvetica-Bold" if bold else "Helvetica", spaceAfter=space)
    out = [P("Code2Hire", center(14, BRAND, True)),
           P("CERTIFICATE" if c.kind == "certificate" else "SKILL BADGE", center(11, MUTED, True, 18)),
           P("This certifies that", center(11, MUTED)),
           P(holder, center(30, INK, True, 12)),
           P("has earned", center(11, MUTED)),
           P(c.title or c.skill or "Certification", center(20, INK, True, 6)),
           P(" · ".join(x for x in [f"Level {c.level}" if c.level else "", f"Grade {c.grade}" if c.grade else "", c.issuer or ""] if x), center(11, MUTED, False, 18)),
           P(f"Issued {c.created_at:%d %B %Y}" + (f" · valid until {c.expires_at:%d %B %Y}" if c.expires_at else ""), center(10, MUTED)),
           P(f"Verification ID: {c.code}", center(12, INK, True, 2)),
           P(f"Check it at {verify_url}", center(9, MUTED))]
    if c.revoked:
        out.insert(0, P("REVOKED: this credential is no longer valid.", center(12, colors.HexColor("#C5283D"), True)))

    def frame(canvas, d):
        canvas.saveState()
        canvas.setStrokeColor(BRAND)
        canvas.setLineWidth(3)
        canvas.rect(12 * mm, 12 * mm, page[0] - 24 * mm, page[1] - 24 * mm)
        canvas.setLineWidth(0.6)
        canvas.rect(15 * mm, 15 * mm, page[0] - 30 * mm, page[1] - 30 * mm)
        canvas.restoreState()
        _footer(version)(canvas, d)
    doc.build(out, onFirstPage=frame)
    return buf.getvalue()
