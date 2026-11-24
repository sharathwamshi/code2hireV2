"""V02.01.04: interview questions in the question bank.

Every interview question Claude writes (Isha's prepared questions, and the ones Ask Isha suggests) is saved to the
company's question bank as kind = "interview", status "pending" (a draft someone can approve), with the points a good
answer covers, a model answer and its follow-ups in `meta`. The same wording is never saved twice.

When Claude is down, Isha takes questions from here before falling back to her built-in templates: approved ones
first, then drafts. They're labelled "From the question bank". MCQ tests never draw these (kind = "mcq" only).
"""
from extensions import db
from models import Question, QuestionVersion

LEVEL_OF = {"fresher": 2, "mid": 3, "senior": 4, "lead": 5}


def _norm(t):
    from services.mcq import norm
    return norm(t)


def save(company_id, items, note="Written by Claude for a live interview"):
    """items: [{"q", "skill", "level", "type", "good", "model", "followups", "section", "simple"}]. Returns how many
    were saved. Never raises: saving to the bank must not stop an interview from being prepared."""
    if not items:
        return 0
    try:
        from services.mcq import _existing_texts
        taken = _existing_texts(company_id)
        made = 0
        for it in items:
            text = str(it.get("q") or "").strip()
            k = _norm(text)
            if not k or k in taken or len(text) < 12:
                continue
            taken.add(k)
            lvl = it.get("level")
            lvl = LEVEL_OF.get(lvl, lvl) if not isinstance(lvl, int) else lvl
            try:
                lvl = max(1, min(5, int(lvl or 3)))
            except (TypeError, ValueError):
                lvl = 3
            meta = {"type": it.get("type"), "good": [str(g)[:200] for g in it.get("good") or []][:6],
                    "model": (str(it.get("model") or "").strip()[:1200] or None),
                    "followups": [f if isinstance(f, dict) else {"q": str(f)} for f in it.get("followups") or []][:5],
                    "section": it.get("section"), "simple": (str(it.get("simple") or "").strip()[:400] or None)}
            q = Question(company_id=company_id, skill=str(it.get("skill") or "General")[:80], level=lvl, text=text[:4000],
                         options=[], answer=0, explanation=meta["model"], tags=["interview"], status="pending", source="ai",
                         kind="interview", meta=meta, version=1)
            db.session.add(q)
            db.session.flush()
            db.session.add(QuestionVersion(question_id=q.id, version=1, snapshot=q.snapshot(), note=note))
            made += 1
        return made
    except Exception:  # noqa: BLE001
        from flask import current_app
        current_app.logger.exception("saving interview questions to the bank")
        return 0


def find(company_id, skill, qtype=None, avoid=(), n=1):
    """Interview questions from the bank for this skill (and question type when given): approved first, then drafts.
    Returns Question rows."""
    from services.mcq import _canon
    want = _canon(skill) if skill else None
    taken = {_norm(t) for t in avoid or []}
    rows = (Question.query.filter(Question.kind == "interview", Question.status.in_(("approved", "pending")),
                                  (Question.company_id == company_id) | (Question.company_id.is_(None)))
            .order_by(Question.id.desc()).limit(500).all())
    out = []
    for status in ("approved", "pending"):
        for q in rows:
            if q.status != status or _norm(q.text) in taken:
                continue
            if want and _canon(q.skill) != want:
                continue
            if qtype and (q.meta or {}).get("type") not in (qtype, None):
                continue
            out.append(q)
            taken.add(_norm(q.text))
            if len(out) >= n:
                return out
    return out


def as_prep(q):
    """A bank question in the shape isha_prep._question expects."""
    m = q.meta or {}
    return {"q": q.text, "simple": m.get("simple") or q.text, "good": m.get("good") or [], "followups": m.get("followups") or [],
            "model": m.get("model") or q.explanation, "bank_id": q.id, "bank_status": q.status}
