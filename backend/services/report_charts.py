"""V02.00.08: charts for the PDF reports, drawn with reportlab's vector graphics (no browser, no image files).
The same pictures as the screens: score gauge, competency bars and radar, MCQ donut, answer map and skill bars,
answer quality per question, and coloured key-figure tiles."""
import math

from reportlab.graphics.shapes import Circle, Drawing, Line, Polygon, Rect, String, Wedge
from reportlab.lib import colors
from reportlab.lib.units import mm

GOOD = colors.HexColor("#12805C")
WARN = colors.HexColor("#E08A1E")
BAD = colors.HexColor("#C5283D")
INFO = colors.HexColor("#2F6FED")
BRAND = colors.HexColor("#5B3FFF")
ISHA = colors.HexColor("#FFC94A")
INK = colors.HexColor("#14213D")
MUTED = colors.HexColor("#5C6378")
SOFT = colors.HexColor("#EEF0F6")
LINE = colors.HexColor("#DADDE6")
NONE = colors.HexColor("#C9CEDA")
SOFTS = {"good": colors.HexColor("#E3F5EC"), "warn": colors.HexColor("#FFF1DE"), "bad": colors.HexColor("#FDE7EA"),
         "info": colors.HexColor("#E7EFFE"), "brand": colors.HexColor("#EFEBFF"), "none": colors.HexColor("#F1F3F8")}
TONE = {"good": GOOD, "warn": WARN, "bad": BAD, "info": INFO, "brand": BRAND, "none": NONE}
LEVEL_TONE = {"Strong": "good", "Meets": "info", "Weak": "bad"}


def band(pct):
    return "none" if pct is None else "good" if pct >= 70 else "warn" if pct >= 45 else "bad"


def level_of(score):
    return None if score is None else "Strong" if score >= 4 else "Meets" if score >= 3 else "Weak"


def _s(x, y, text, size=8, color=MUTED, anchor="start", bold=False):
    return String(x, y, str(text), fontSize=size, fillColor=color, textAnchor=anchor, fontName="Helvetica-Bold" if bold else "Helvetica")


def gauge(pct, sub="", tone=None, w=48 * mm):
    """Half-circle gauge; colour by band."""
    h = w * 0.6
    d = Drawing(w, h)
    cx, cy, r = w / 2, h * 0.22, w * 0.42
    t = TONE[tone or band(pct)]
    d.add(Wedge(cx, cy, r, 0, 180, fillColor=SOFT, strokeColor=None))
    if pct is not None and pct > 0:
        d.add(Wedge(cx, cy, r, 180 - 180 * min(100, pct) / 100, 180, fillColor=t, strokeColor=None))
    d.add(Wedge(cx, cy, r * 0.72, 0, 180, fillColor=colors.white, strokeColor=None))
    d.add(_s(cx, cy + r * 0.2, "—" if pct is None else f"{pct}%", 17, INK, "middle", True))
    if sub:
        d.add(_s(cx, cy - 1, sub, 7.5, MUTED, "middle"))
    return d


def competency_bars(comps, w=105 * mm):
    """Horizontal bars on a 0–5 scale, coloured by level; a diamond marks Isha's live score."""
    rows = comps[:14]
    name_w, val_w, row_h = 36 * mm, 22 * mm, 6.2 * mm
    h = row_h * len(rows) + 9 * mm
    d = Drawing(w, h)
    x0, x1 = name_w, w - val_w
    tw = x1 - x0
    top = h - 6 * mm
    for n in range(6):  # axis
        x = x0 + tw * n / 5
        d.add(Line(x, 4 * mm, x, top + 2, strokeColor=LINE, strokeWidth=0.4, strokeDashArray=[1, 2] if n not in (0, 5) else None))
        d.add(_s(x, top + 3, n, 6.5, MUTED, "middle"))
    for i, c in enumerate(rows):
        y = top - (i + 1) * row_h + 1.6 * mm
        name = str(c.get("name", ""))
        d.add(_s(0, y + 1.2 * mm, name[:24] + ("…" if len(name) > 24 else ""), 7.8, INK, "start", True))
        d.add(Rect(x0, y, tw, 3.4 * mm, fillColor=SOFT, strokeColor=None, rx=1.7 * mm, ry=1.7 * mm))
        sc = c.get("score")
        lvl = None if c.get("not_covered") or sc is None else (c.get("level") or level_of(float(sc)))
        if sc is not None and not c.get("not_covered"):
            d.add(Rect(x0, y, max(2, tw * float(sc) / 5), 3.4 * mm, fillColor=TONE[LEVEL_TONE.get(lvl, "brand")], strokeColor=None, rx=1.7 * mm, ry=1.7 * mm))
            d.add(_s(x1 + 2 * mm, y + 0.7 * mm, f"{float(sc):.1f}  {lvl or ''}", 7.5, TONE[LEVEL_TONE.get(lvl, "brand")], "start", True))
        else:
            d.add(_s(x1 + 2 * mm, y + 0.7 * mm, "Not covered", 7, MUTED))
        if c.get("ai_score") is not None:
            ax, ay, k = x0 + tw * float(c["ai_score"]) / 5, y + 1.7 * mm, 1.6 * mm
            d.add(Polygon([ax, ay + k, ax + k, ay, ax, ay - k, ax - k, ay], fillColor=ISHA, strokeColor=colors.white, strokeWidth=0.6))
    # legend
    lx = 0
    items = [("Strong (4–5)", GOOD), ("Meets (3)", INFO), ("Weak (below 3)", BAD)]
    if any(c.get("ai_score") is not None for c in rows):
        items.append(("Isha's live score", ISHA))
    for label, col in items:
        d.add(Rect(lx, 0.6 * mm, 2.4 * mm, 2.4 * mm, fillColor=col, strokeColor=None))
        d.add(_s(lx + 3.4 * mm, 0.9 * mm, label, 6.8))
        lx += 4.5 * mm + len(label) * 1.45 * mm
    return d


def radar(comps, w=62 * mm):
    items = [c for c in comps if c.get("score") is not None][:10]
    if len(items) < 3:
        return None
    d = Drawing(w, w * 0.92)
    cx, cy, R, n = w / 2, w * 0.46, w * 0.25, len(items)

    def pt(i, v):
        a = math.pi / 2 - 2 * math.pi * i / n
        return cx + math.cos(a) * R * v, cy + math.sin(a) * R * v
    for k in (0.2, 0.4, 0.6, 0.8, 1.0):
        pts = [c for i in range(n) for c in pt(i, k)]
        d.add(Polygon(pts, fillColor=SOFT if k == 1 else None, strokeColor=LINE, strokeWidth=0.5))
    for i in range(n):
        x, y = pt(i, 1)
        d.add(Line(cx, cy, x, y, strokeColor=LINE, strokeWidth=0.5))
    d.add(Polygon([c for i in range(n) for c in pt(i, 0.6)], fillColor=None, strokeColor=MUTED, strokeWidth=0.5, strokeDashArray=[2, 2]))
    if any(c.get("ai_score") is not None for c in items):
        d.add(Polygon([c for i, it in enumerate(items) for c in pt(i, float(it.get("ai_score") or it["score"]) / 5)],
                      fillColor=colors.Color(1, 0.79, 0.29, 0.18), strokeColor=ISHA, strokeWidth=1))
    d.add(Polygon([c for i, it in enumerate(items) for c in pt(i, float(it["score"]) / 5)],
                  fillColor=colors.Color(0.36, 0.25, 1, 0.22), strokeColor=BRAND, strokeWidth=1.3))
    for i, it in enumerate(items):
        x, y = pt(i, float(it["score"]) / 5)
        d.add(Circle(x, y, 1.3, fillColor=BRAND, strokeColor=None))
        lx, ly = pt(i, 1.18)
        anchor = "middle" if abs(lx - cx) < 4 else "start" if lx > cx else "end"
        name = str(it.get("name", ""))
        d.add(_s(lx, ly - 2, (name[:13] + ("…" if len(name) > 13 else "")) + f" {float(it['score']):.1f}", 6.6, INK, anchor, True))
    return d


def donut(parts, center, sub="", w=40 * mm):
    """parts: [(label, value, tone)]"""
    d = Drawing(w, w + 10 * mm)
    cx, cy, r = w / 2, 10 * mm + w / 2, w * 0.42
    total = sum(v for _, v, _ in parts) or 1
    start = 90
    d.add(Circle(cx, cy, r, fillColor=SOFT, strokeColor=None))
    for _, v, t in parts:
        if not v:
            continue
        ext = 360 * v / total
        d.add(Wedge(cx, cy, r, start - ext, start, fillColor=TONE[t], strokeColor=colors.white, strokeWidth=0.8))
        start -= ext
    d.add(Circle(cx, cy, r * 0.62, fillColor=colors.white, strokeColor=None))
    d.add(_s(cx, cy + 1, center, 13, INK, "middle", True))
    if sub:
        d.add(_s(cx, cy - 4 * mm, sub, 6.8, MUTED, "middle"))
    x = 0
    for label, v, t in parts:
        d.add(Rect(x, 3 * mm, 2.4 * mm, 2.4 * mm, fillColor=TONE[t], strokeColor=None))
        txt = f"{label} {v}"
        d.add(_s(x + 3.3 * mm, 3.3 * mm, txt, 6.6))
        x += 5 * mm + len(txt) * 1.25 * mm
    return d


def answer_map(questions, w=120 * mm):
    """One square per MCQ question."""
    size, gap = 6.2 * mm, 1.4 * mm
    per = max(1, int((w + gap) // (size + gap)))
    rows = math.ceil(len(questions) / per)
    d = Drawing(w, rows * (size + gap))
    for i, q in enumerate(questions):
        r_, c_ = divmod(i, per)
        x, y = c_ * (size + gap), (rows - 1 - r_) * (size + gap)
        skipped = q.get("chosen") in (None, "")
        t = "good" if q.get("correct") else "none" if skipped else "bad"
        d.add(Rect(x, y, size, size, fillColor=TONE[t], strokeColor=None, rx=1.3 * mm, ry=1.3 * mm))
        d.add(_s(x + size / 2, y + size / 2 - 2.2, i + 1, 7, colors.white if t != "none" else INK, "middle", True))
    return d


def skill_stack(questions, w=120 * mm):
    by = {}
    for q in questions:
        k = q.get("skill") or "General"
        v = by.setdefault(k, [0, 0, 0])
        if q.get("correct"):
            v[0] += 1
        elif q.get("chosen") in (None, ""):
            v[2] += 1
        else:
            v[1] += 1
    rows = sorted(by.items(), key=lambda kv: -kv[1][0] / max(1, sum(kv[1])))[:12]
    row_h = 6 * mm
    d = Drawing(w, row_h * len(rows))
    name_w, val_w = 30 * mm, 18 * mm
    tw = w - name_w - val_w
    for i, (k, (rt, wr, sk)) in enumerate(rows):
        n = rt + wr + sk
        y = (len(rows) - 1 - i) * row_h + 1.3 * mm
        d.add(_s(0, y + 0.8 * mm, k[:20], 7.6, INK, "start", True))
        x = name_w
        d.add(Rect(x, y, tw, 3.2 * mm, fillColor=SOFT, strokeColor=None))
        for v, t in ((rt, "good"), (wr, "bad"), (sk, "none")):
            if v:
                d.add(Rect(x, y, tw * v / n, 3.2 * mm, fillColor=TONE[t], strokeColor=None))
                x += tw * v / n
        d.add(_s(name_w + tw + 2 * mm, y + 0.6 * mm, f"{round(100 * rt / n)}%  {rt}/{n}", 7.2, INK, "start", True))
    return d


def question_columns(questions, w=174 * mm):
    """Answer quality per question: share of a good answer's points covered, or the score when nothing was matched."""
    cov_mode = any(any(q.get("covered") or []) for q in questions)
    vals = []
    for q in questions[:30]:
        pts = len(q.get("good_answer") or [])
        if cov_mode and pts:
            vals.append(round(100 * sum(1 for x in (q.get("covered") or []) if x) / pts))
        elif q.get("score") is not None:
            vals.append(round(float(q["score"]) * 20))
        else:
            vals.append(0)
    if not any(vals) and not any(q.get("score") is not None for q in questions):
        return None, cov_mode
    H = 34 * mm
    d = Drawing(w, H + 8 * mm)
    x0 = 9 * mm
    for g in (0, 50, 100):
        y = 6 * mm + H * g / 100
        d.add(Line(x0, y, w, y, strokeColor=LINE, strokeWidth=0.4, strokeDashArray=[1, 2] if g else None))
        d.add(_s(x0 - 1.5 * mm, y - 2, f"{g}%", 6.4, MUTED, "end"))
    bw = min(12 * mm, (w - x0) / max(1, len(vals)) - 2 * mm)
    for i, v in enumerate(vals):
        x = x0 + 1.5 * mm + i * (bw + 2 * mm)
        h = max(0.8, H * v / 100)
        d.add(Rect(x, 6 * mm, bw, h, fillColor=TONE[band(v)], strokeColor=None, rx=1, ry=1))
        d.add(_s(x + bw / 2, 1.5 * mm, f"Q{i + 1}", 6.4, MUTED, "middle"))
        if bw >= 6 * mm:
            d.add(_s(x + bw / 2, 6 * mm + h + 1.2, f"{v}%", 6.4, INK, "middle", True))
    return d, cov_mode
