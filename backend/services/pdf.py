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
LINE_C = colors.HexColor("#DADDE6")

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


def _band_page(title):
    """First page: a coloured band across the top with the brand and the report title (V02.00.08)."""
    def draw(canvas, doc):
        canvas.saveState()
        w, h = doc.pagesize
        canvas.setFillColor(BRAND)
        canvas.rect(0, h - 14 * mm, w, 14 * mm, stroke=0, fill=1)
        canvas.setFillColor(colors.HexColor("#8A6BFF"))
        canvas.rect(w * 0.55, h - 14 * mm, w * 0.45, 14 * mm, stroke=0, fill=1)
        canvas.setFillColor(colors.HexColor("#2F6FED"))
        canvas.rect(w * 0.8, h - 14 * mm, w * 0.2, 14 * mm, stroke=0, fill=1)
        canvas.setFillColor(colors.white)
        canvas.setFont("Helvetica-Bold", 13)
        canvas.drawString(18 * mm, h - 9.2 * mm, "Code2Hire")
        canvas.setFont("Helvetica", 9)
        canvas.drawRightString(w - 18 * mm, h - 9 * mm, title[:80])
        canvas.restoreState()
    return draw


def _tiles(tiles, width=174 * mm):
    """Key figures as coloured tiles: [(label, value, sub, tone)]."""
    from services.report_charts import SOFTS, TONE
    n = len(tiles)
    cw = width / n
    cells = [[[P(l.upper(), ParagraphStyle("tl", parent=SMALL, fontName="Helvetica-Bold", fontSize=6.8, textColor=MUTED)),
               P(v, ParagraphStyle("tv", parent=BODY, fontName="Helvetica-Bold", fontSize=13, leading=16, textColor=TONE.get(t, INK) if t != "none" else INK)),
               P(sub or "", SMALL)] for l, v, sub, t in tiles]]
    t = Table(cells, colWidths=[cw] * n)
    st = [("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 8), ("TOPPADDING", (0, 0), (-1, -1), 5), ("BOTTOMPADDING", (0, 0), (-1, -1), 6)]
    for i, (_, _, _, tone) in enumerate(tiles):
        st += [("BACKGROUND", (i, 0), (i, 0), SOFTS.get(tone, SOFT)), ("LINEBEFORE", (i, 0), (i, 0), 3, TONE.get(tone, BRAND))]
    t.setStyle(TableStyle(st))
    return t


def _two_lists(cols, width=174 * mm):
    """Coloured list boxes side by side: [(title, items, tone)]."""
    from services.report_charts import SOFTS, TONE
    cw = width / len(cols)
    cells = [[]]
    for title, items, tone in cols:
        body = [P(f"{title}  ({len(items)})", ParagraphStyle("lh", parent=BODY, fontName="Helvetica-Bold", textColor=TONE[tone]))]
        body += [P("• " + (x if isinstance(x, str) else (x.get("title") or x.get("name") or str(x))), CELL) for x in items[:12]] or [P("None recorded.", SMALL)]
        cells[0].append(body)
    t = Table(cells, colWidths=[cw] * len(cols))
    st = [("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 8), ("RIGHTPADDING", (0, 0), (-1, -1), 8), ("TOPPADDING", (0, 0), (-1, -1), 6), ("BOTTOMPADDING", (0, 0), (-1, -1), 8)]
    for i, (_, _, tone) in enumerate(cols):
        st += [("BACKGROUND", (i, 0), (i, 0), SOFTS[tone]), ("LINEABOVE", (i, 0), (i, 0), 3, TONE[tone])]
    t.setStyle(TableStyle(st))
    return t


def report_pdf(v, version="", candidate=False):
    """v: the dict from routes.reports.view() for the chosen audience. V02.00.08: charts and colour, like the screens."""
    from reportlab.platypus import KeepTogether
    from services import report_charts as RC
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=18 * mm, rightMargin=18 * mm, topMargin=20 * mm, bottomMargin=18 * mm,
                            title=f"{v.get('round')} · {(v.get('candidate') or {}).get('name', '')}", author="Code2Hire")
    s = v.get("sections") or {}
    scale = v.get("scale") or 5
    mcq = v.get("type") == "mcq" or s.get("kind") == "mcq"
    qs = s.get("questions") or []
    comps = s.get("competencies") or []
    pct = None if v.get("overall") is None else max(0, min(100, round(float(v["overall"]) * 20)))
    rec = {"proceed": ("Proceed", "good"), "hold": ("Hold", "warn"), "reject": ("Do not proceed", "bad")}.get(v.get("recommendation"))
    name = (v.get("candidate") or {}).get("name", "")
    tk = v.get("taken") or {}   # V02.01.08: when it was taken, in IST (the company's zone), and how long
    meta = " · ".join(x for x in [(v.get("job") or {}).get("title", ""),
                                  f"taken {tk['date']}, {tk['time']} · {tk['length']}" if tk.get("date") else (f"completed {v['completed_at'][:10]}" if v.get("completed_at") else ""),
                                  f"interviewer {v['interviewer']}" if v.get("interviewer") and not candidate else ""] if x)
    out = []
    # ---- hero: gauge + who, what, verdict
    if candidate:
        res = v.get("result") or {}
        cpct = None if res.get("score") is None else max(0, min(100, round(float(res["score"]) * 20)))
        right = [P("Your feedback", SMALL), P(str(v.get("round") or "Interview"), H1), P(meta, SMALL)]
        if res.get("cleared"):
            right.append(P("You cleared this round.", ParagraphStyle("ok", parent=H2, textColor=RC.GOOD)))
        if res.get("next_step"):
            right.append(P(res["next_step"]))
        hero = Table([[RC.gauge(cpct, "your score", "good" if res.get("cleared") else None) if cpct is not None else "", right]], colWidths=[52 * mm, 122 * mm])
    else:
        right = [P(name, H1), P(f"{v.get('round') or ''}" + (f"  ·  {meta}" if meta else ""), SMALL)]
        if rec:
            who = "Interviewer" if str(v.get("type", "")).startswith("f2f") else "Hira"
            right.append(Spacer(1, 3))
            pill = Table([[Paragraph(f"{who} recommends: <b>{escape(rec[0])}</b>" + (f"  ·  confidence {escape(str(v['confidence']))}" if v.get("confidence") else ""),
                                     ParagraphStyle("rec", parent=BODY, textColor=RC.TONE[rec[1]]))]])
            pill.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), RC.SOFTS[rec[1]]), ("LEFTPADDING", (0, 0), (-1, -1), 7), ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 4)]))
            right.append(pill)
        if v.get("verdict"):
            right.append(Paragraph(f"Decision: <b>{escape(str(v['verdict']))}</b>", BODY))
        hero = Table([[RC.gauge(pct, fmt_score(v.get("overall"), scale).split(" · ")[0]), right]], colWidths=[52 * mm, 122 * mm])
    hero.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "MIDDLE"), ("LEFTPADDING", (0, 0), (-1, -1), 0)]))
    out += [hero, Spacer(1, 4)]
    if s.get("summary") and not candidate:
        out += [P(s["summary"], ParagraphStyle("sum", parent=BODY, fontSize=10.5, leading=15)), Spacer(1, 6)]
    # ---- key figures
    if not candidate:
        tiles = [("Overall", "—" if pct is None else f"{pct}%", fmt_score(v.get("overall"), scale).split(" · ")[0], RC.band(pct))]
        if mcq and qs:
            right_n = sum(1 for q in qs if q.get("correct"))
            skipped = sum(1 for q in qs if q.get("chosen") in (None, ""))
            tiles.append(("Correct", f"{right_n} / {len(qs)}", f"{skipped} skipped", RC.band(round(100 * right_n / len(qs)))))
        elif comps:
            lv = [None if c.get("not_covered") or c.get("score") is None else (c.get("level") or RC.level_of(float(c["score"]))) for c in comps]
            tiles.append(("Competencies", f"{lv.count('Strong')} strong", f"{lv.count('Meets')} meets · {lv.count('Weak')} weak", "good" if lv.count("Strong") >= lv.count("Weak") else "warn"))
        integ = s.get("integrity") if isinstance(s.get("integrity"), dict) else None
        if integ is not None:
            w_ = integ.get("warnings") or 0
            tiles.append(("Integrity", "Clean" if not w_ else f"{w_} warning{'s' if w_ > 1 else ''}", f"{len(integ.get('events') or [])} events logged", "good" if not w_ else "bad" if w_ > 2 else "warn"))
        if rec:
            tiles.append(("Recommendation", rec[0], f"Decision: {v['verdict']}" if v.get("verdict") else "Awaiting a decision", rec[1]))
        out += [_tiles(tiles), Spacer(1, 4)]
    # ---- charts
    if mcq and qs:
        right_n = sum(1 for q in qs if q.get("correct"))
        skipped = sum(1 for q in qs if q.get("chosen") in (None, ""))
        chart = Table([[RC.donut([("Correct", right_n, "good"), ("Wrong", len(qs) - right_n - skipped, "bad"), ("Skipped", skipped, "none")],
                                 f"{round(100 * right_n / len(qs))}%", "correct"),
                        [P("EVERY QUESTION", ParagraphStyle("k", parent=SMALL, fontName="Helvetica-Bold", fontSize=6.8)), RC.answer_map(qs, 118 * mm), Spacer(1, 6),
                         P("BY SKILL", ParagraphStyle("k2", parent=SMALL, fontName="Helvetica-Bold", fontSize=6.8)), RC.skill_stack(qs, 118 * mm)]]],
                      colWidths=[50 * mm, 124 * mm])
        chart.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "MIDDLE"), ("BOX", (0, 0), (-1, -1), 0.4, LINE_C), ("TOPPADDING", (0, 0), (-1, -1), 6), ("BOTTOMPADDING", (0, 0), (-1, -1), 6)]))
        out += [KeepTogether([P("Your answers at a glance" if candidate else "Results at a glance", H2), chart])]
    elif comps and not candidate:
        rad = RC.radar(comps)
        row = [RC.competency_bars(comps, 110 * mm if rad else 170 * mm)] + ([rad] if rad else [])
        chart = Table([row], colWidths=[112 * mm, 62 * mm] if rad else [174 * mm])
        chart.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "MIDDLE"), ("BOX", (0, 0), (-1, -1), 0.4, LINE_C), ("TOPPADDING", (0, 0), (-1, -1), 8), ("BOTTOMPADDING", (0, 0), (-1, -1), 6)]))
        out += [KeepTogether([P("Scores by competency", H2), chart])]
    # ---- strengths / gaps (or the candidate's three lists)
    if candidate:
        cols = [("What went well", s.get("strengths") or [], "good"), ("What to work on", s.get("gaps") or [], "warn"), ("Next steps", s.get("next_steps") or [], "info")]
        out += [Spacer(1, 6), _two_lists(cols)]
        if s.get("learning_path"):
            out.append(P("Suggested learning", H2))
            for it in s["learning_path"][:10]:
                out.append(P("• " + (it if isinstance(it, str) else (it.get("title") or it.get("name") or str(it)))))
    elif s.get("strengths") or s.get("gaps"):
        out += [Spacer(1, 8), _two_lists([("Strengths", s.get("strengths") or [], "good"), ("Gaps", s.get("gaps") or [], "bad")])]
        if s.get("handoff"):
            out.append(P("Next round should probe: " + "; ".join(s["handoff"][:8]), SMALL))
    # ---- competency table, colour-coded
    if comps and not candidate:
        out.append(P("Score by skill" if mcq else "Competency details", H2))
        rows = [["Competency" if not mcq else "Skill", "Score", "Level", "Evidence"]]
        tones = []
        for c in comps:
            sc = c.get("score")
            lvl = None if c.get("not_covered") or sc is None else (c.get("level") or RC.level_of(float(sc)))
            tones.append(RC.LEVEL_TONE.get(lvl, "none"))
            rows.append([c.get("name", ""), fmt_score(sc, scale), lvl or "Not covered", (c.get("evidence") or c.get("reason") or "")[:500]])
        t = _table(rows, [40 * mm, 30 * mm, 22 * mm, 82 * mm])
        st = []
        for i, tone in enumerate(tones, start=1):
            st += [("LINEBEFORE", (0, i), (0, i), 3, RC.TONE[tone]), ("BACKGROUND", (2, i), (2, i), RC.SOFTS[tone]), ("TEXTCOLOR", (2, i), (2, i), RC.TONE[tone])]
        t.setStyle(TableStyle(st + [("BACKGROUND", (0, 0), (-1, 0), RC.SOFTS["brand"])]))
        out.append(t)
    # ---- answer quality per question (interviews)
    if qs and not mcq:
        d, cov = RC.question_columns(qs)
        if d is not None:
            out += [KeepTogether([P("Answer quality by question", H2),
                                  P("Share of a good answer's points covered." if cov else "Score for each answer, as a percentage.", SMALL), d])]
    # ---- question by question
    if qs:
        out.append(P("Questions and answers" if mcq else "Question by question", H2))
        letter = lambda i: chr(65 + i) if isinstance(i, int) and i >= 0 else "—"  # noqa: E731
        if mcq:
            rows = [["#", "Question", "Correct answer", "Candidate chose" if not candidate else "Your answer"]]
            marks = []
            for i, q in enumerate(qs[:100]):
                opts = q.get("options") or []
                right = q.get("answer")
                ch = q.get("chosen")
                ch = int(ch) if isinstance(ch, (int, str)) and str(ch).isdigit() else None
                marks.append("none" if ch is None else "good" if ch == right else "bad")
                rows.append([str(i + 1), (q.get("q") or "")[:400],
                             f"{letter(right)}. {opts[right]}"[:300] if isinstance(right, int) and right < len(opts) else "—",
                             ("Skipped" if ch is None else f"{letter(ch)}. {opts[ch] if ch < len(opts) else ''}"[:300] + ("  (correct)" if ch == right else "  (wrong)"))])
            t = _table(rows, [8 * mm, 74 * mm, 46 * mm, 46 * mm])
            st = [("BACKGROUND", (0, 0), (-1, 0), RC.SOFTS["brand"])]
            for i, m in enumerate(marks, start=1):
                st += [("BACKGROUND", (3, i), (3, i), RC.SOFTS[m]), ("BACKGROUND", (0, i), (0, i), RC.TONE[m]), ("TEXTCOLOR", (0, i), (0, i), colors.white if m != "none" else INK),
                       ("BACKGROUND", (2, i), (2, i), RC.SOFTS["good"])]
            t.setStyle(TableStyle(st))
            out.append(t)
        else:
            for i, q in enumerate(qs[:60]):
                good = q.get("good_answer") or []
                cov = q.get("covered") or []
                hit = sum(1 for k in range(len(good)) if k < len(cov) and cov[k])
                head = f"{i + 1}. {q.get('q') or ''}" + (f"  ·  {fmt_score(q.get('score'), scale)}" if q.get("score") is not None and not candidate else "") \
                    + (f"  ·  {q['time']}" if q.get("time") and not candidate else "")
                exp = [P(f"A GOOD ANSWER COVERS  ({hit} of {len(good)})", ParagraphStyle("eh", parent=SMALL, fontName="Helvetica-Bold", fontSize=6.8, textColor=RC.GOOD))]
                exp += [Paragraph(('<font color="#12805C"><b>• covered</b></font>  ' if (k < len(cov) and cov[k]) else '<font color="#8A93A6">• not covered</font>  ') + escape(g), CELL)
                        for k, g in enumerate(good)] or [P("No expected points were set.", SMALL)]
                ans = [P("YOUR ANSWER" if candidate else "CANDIDATE'S ANSWER", ParagraphStyle("ah", parent=SMALL, fontName="Helvetica-Bold", fontSize=6.8, textColor=RC.INFO)),
                       P((q.get("a") or "").strip()[:1500] or "(no answer)", CELL)]
                if q.get("interviewer_said") and not candidate:
                    ans.append(P("Interviewer also said: " + " / ".join(q["interviewer_said"])[:600], SMALL))
                tone = RC.band(round(float(q["score"]) * 20)) if q.get("score") is not None and not candidate else "brand"
                t = Table([[P(head, ParagraphStyle("qh", parent=CELL, fontName="Helvetica-Bold")), ""], [exp, ans]], colWidths=[72 * mm, 102 * mm])
                t.setStyle(TableStyle([("SPAN", (0, 0), (1, 0)), ("BOX", (0, 0), (-1, -1), 0.4, LINE_C), ("BACKGROUND", (0, 0), (-1, 0), RC.SOFTS[tone]),
                                       ("LINEBEFORE", (0, 0), (0, -1), 3, RC.TONE[tone]), ("BACKGROUND", (0, 1), (0, 1), RC.SOFTS["good"]),
                                       ("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 6), ("RIGHTPADDING", (0, 0), (-1, -1), 6)]))
                out += [KeepTogether([t]), Spacer(1, 4)]
    integ = s.get("integrity")
    if isinstance(integ, dict) and integ.get("events") and not candidate:
        out.append(P("Integrity events", H2))
        rows = [["When", "Event", "Counted"]] + [[str(e.get("at", ""))[:19].replace("T", " "), e.get("label") or e.get("type", ""), "Yes" if e.get("counted") else "No"]
                                                 for e in integ["events"][:40]]
        t = _table(rows, [40 * mm, 104 * mm, 30 * mm])
        st = [("BACKGROUND", (0, 0), (-1, 0), RC.SOFTS["brand"])]
        for i, e in enumerate(integ["events"][:40], start=1):
            tone = ("bad" if e.get("severity") == "high" else "warn") if e.get("counted") else "none"
            st += [("BACKGROUND", (2, i), (2, i), RC.SOFTS[tone]), ("LINEBEFORE", (0, i), (0, i), 3, RC.TONE[tone])]
        t.setStyle(TableStyle(st))
        out.append(t)
    if not candidate and v.get("history"):
        out.append(P("Review history", H2))
        for h in v["history"][:20]:
            out.append(P(f"v{h.get('version')} · {h.get('by', '')} · {str(h.get('at', ''))[:16].replace('T', ' ')}"
                         + (f" · verdict {h['verdict']}" if h.get("verdict") else "") + (f" · “{h['note']}”" if h.get("note") else ""), SMALL))
    isha_ = s.get("kind") == "f2f_isha"   # V02.01.07: Isha scores; the interviewer recommends
    out += [Spacer(1, 10), P(("Confidential. Isha scores the interview; the interviewer recommends; a named person reviews and decides." if isha_
                              else "Confidential. Hira (AI) recommends; a named person reviews and decides.") if not candidate else
                             "This feedback was reviewed by a person on the hiring team before it was shared with you.", SMALL)]
    first = _band_page(("Your feedback · " if candidate else "Interview report · ") + str(v.get("round") or ""))
    foot = _footer(version)
    doc.build(out, onFirstPage=lambda c, d: (first(c, d), foot(c, d)), onLaterPages=foot)
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


def instructions_pdf(d, version=""):
    """The candidate instructions for one round (V02.00.05)."""
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=18 * mm, rightMargin=18 * mm, topMargin=16 * mm, bottomMargin=18 * mm,
                            title=f"Instructions · {d.get('title', '')}", author="Code2Hire")
    out = [P("Code2Hire", ParagraphStyle("brand", parent=H2, textColor=BRAND, spaceBefore=0)),
           P(f"Before your round: {d.get('title') or 'Interview'}", H1),
           P(f"{d.get('job', '')} · {d.get('kind', '')}" + (f" · about {d['minutes']} minutes" if d.get("minutes") else ""), SMALL), Spacer(1, 6)]
    for sec in d.get("sections") or []:
        out.append(P(sec.get("heading", ""), H2))
        for it in sec.get("items") or []:
            out.append(P("• " + it))
    if d.get("extra"):
        out += [P("From the hiring team", H2), P(d["extra"])]
    out += [Spacer(1, 10), P("Before the round starts, a short system check tests your device, camera, microphone, speaker and "
                             "internet. Every step except the internet test must pass.", SMALL)]
    doc.build(out, onFirstPage=_footer(version), onLaterPages=_footer(version))
    return buf.getvalue()
