"""MCQ papers (V02.00.11, CAN-015 / CAN-016).

A hiring MCQ round's questions are drawn when the candidate is INVITED, not when they press Start, so the hiring team
can review them first. Two choices, made by whoever sets up the round (Rounds and rules):
  mcq.paper             "random" - each candidate gets their own draw from the pool (unseen questions first)
                        "same"   - everyone gets the same paper, picked and checked once in round setup (mcq.fixed_ids)
  mcq.review_before_start  True - the candidate can't start until someone approves their paper (default)
A reviewer can swap single questions or redraw the whole paper until the candidate starts; then it's locked.
Practice, skill checks and certification sections have no hiring team, so they keep drawing at Start."""
import random
from datetime import datetime

from extensions import db
from models import Question

PENDING, APPROVED, EMPTY = "pending_review", "approved", "empty"


def applies(att):
    return att.round_type == "mcq" and bool(att.application_id)


def _state(att):
    return (att.result or {}).get("paper") or {}


def state(att):
    return _state(att).get("state")


def ready(att):
    """True when the candidate may start: no paper step, or the paper is approved."""
    if not applies(att):
        return True
    st = state(att)
    if st is None:  # invited before V02.00.11, or the bank was empty at invite: drawn at Start as before
        return True
    return st != PENDING


def _questions(ids):
    live = {q.id: q for q in Question.query.filter(Question.id.in_([i for i in ids if i > 0] or [0])).all()}
    return live


def _snap(att, ids):
    res = dict(att.result or {})
    old = res.get("qsnap") or {}
    live = _questions(ids)
    snap = {}
    for i in ids:
        if i in live:
            snap[str(i)] = {**live[i].snapshot(), "version": live[i].version or 1}
        elif str(i) in old:
            snap[str(i)] = old[str(i)]
    return snap


def _put(att, ids, st, by=None, note=None, snap_extra=None):
    res = dict(att.result or {})
    paper = dict(res.get("paper") or {})
    hist = list(paper.get("history") or [])
    if note:
        hist.append({"at": datetime.utcnow().isoformat() + "Z", "by": by, "note": note})
    cfg = att.config or {}
    paper.update({"state": st, "mode": cfg.get("mcq.paper", "random"), "history": hist[-30:]})
    if st == APPROVED and by is not None:
        paper.update({"approved_by": by, "approved_at": datetime.utcnow().isoformat() + "Z"})
    res["paper"] = paper
    res["question_ids"] = ids
    snap = (res.get("qsnap") or {}) | (snap_extra or {})
    res["qsnap"] = snap
    att.result = res
    att.result = {**res, "qsnap": _snap(att, ids)}


def prepare(att, job):
    """Called when the candidate is invited to an MCQ round. Returns the paper state."""
    if not applies(att):
        return None
    from routes.rounds import _pick_questions
    cfg = att.config or {}
    n = int(cfg.get("mcq.questions", 10))
    review = cfg.get("mcq.review_before_start", True)
    fixed = [int(i) for i in (cfg.get("mcq.fixed_ids") or []) if str(i).lstrip("-").isdigit()]
    if cfg.get("mcq.paper") == "same" and fixed:
        # checked once in round setup, so it's ready at once
        _put(att, fixed, APPROVED, note="Same paper for everyone (checked in round setup)")
        return APPROVED
    try:
        ids = _pick_questions(att, job, n)
    except Exception:  # noqa: BLE001 - the AI or the bank failing must never stop the invite; Start draws again
        ids = []
    if not ids:
        res = dict(att.result or {})
        res["paper"] = {"state": EMPTY, "mode": cfg.get("mcq.paper", "random")}
        att.result = res
        return EMPTY
    extra = (att.result or {}).pop("pick_snap", None) or {}
    st = PENDING if review else APPROVED
    _put(att, ids, st, note="Drawn at invite", snap_extra=extra)
    if st == PENDING:
        from services.audit import notify_roles
        from models import User
        cand = db.session.get(User, db.session.get(__import__("models").Application, att.application_id).candidate_id)
        notify_roles(job.company_id, ["recruiter", "manager"], "Review an MCQ paper",
                     f"{cand.name if cand else 'A candidate'}'s questions for {job.title} are ready to check. They can start once you approve.",
                     f"/app/applications/{att.application_id}?paper={att.id}")
    return st


def view(att, staff=True):
    res = att.result or {}
    ids = res.get("question_ids") or []
    snap = res.get("qsnap") or {}
    live = _questions(ids)
    qs = []
    for i in ids:
        q = live.get(i)
        data = snap.get(str(i)) or (q.snapshot() if q else None)
        if not data:
            continue
        row = {"id": i, "text": data.get("text"), "code": data.get("code"), "options": data.get("options") or [],
               "skill": data.get("skill"), "level": data.get("level")}
        if staff:
            row.update({"answer": data.get("answer"), "explanation": data.get("explanation"),
                        "source": getattr(q, "source", None) if q else "ai", "draft": bool(q and q.status == "pending") or i < 0,
                        "version": data.get("version") or 1})
        qs.append(row)
    p = _state(att)
    locked = att.status not in ("invited", "scheduled")
    return {"state": p.get("state"), "mode": p.get("mode") or (att.config or {}).get("mcq.paper", "random"), "questions": qs,
            "approved_at": p.get("approved_at"), "history": list(reversed(p.get("history") or []))[:10], "locked": locked,
            "wanted": int((att.config or {}).get("mcq.questions", 10))}


def _pool(att, job, exclude):
    from services.mcq import _skills, base_pool, unique
    cfg = att.config or {}
    pool = unique(base_pool(att, job, cfg.get("mcq.folder_ids") or [], _skills(att, job), cfg.get("level")).all())
    return [q for q in pool if q.id not in exclude]


def swap(att, job, qid, by):
    ids = list((att.result or {}).get("question_ids") or [])
    if qid not in ids:
        return "That question isn't in this paper."
    cur = (att.result or {}).get("qsnap", {}).get(str(qid)) or {}
    pool = _pool(att, job, set(ids))
    same_skill = [q for q in pool if (q.skill or "") == (cur.get("skill") or "")]
    choice = random.choice(same_skill or pool) if (same_skill or pool) else None
    if not choice:
        return "There are no other approved questions for this round. Add questions to the question bank first."
    ids[ids.index(qid)] = choice.id
    _put(att, ids, state(att) or PENDING, by=by, note=f"Swapped one question ({cur.get('skill') or 'question'})")
    return None


def redraw(att, job, by):
    from services.mcq import _skills, base_pool, unique
    cfg = att.config or {}
    n = int(cfg.get("mcq.questions", 10))
    pool = unique(base_pool(att, job, cfg.get("mcq.folder_ids") or [], _skills(att, job), cfg.get("level")).all())
    old = set((att.result or {}).get("question_ids") or [])
    fresh = [q for q in pool if q.id not in old]
    random.shuffle(fresh)
    rest = [q for q in pool if q.id in old]
    random.shuffle(rest)
    chosen = (fresh + rest)[:n]
    if not chosen:
        return "There are no approved questions for this round. Add questions to the question bank first."
    _put(att, [q.id for q in chosen], PENDING if cfg.get("mcq.review_before_start", True) else APPROVED, by=by, note="Redrew the whole paper")
    return None


def approve(att, by, by_name):
    if not (att.result or {}).get("question_ids"):
        return "There are no questions to approve."
    _put(att, list(att.result["question_ids"]), APPROVED, by=by, note=f"Approved by {by_name}")
    from services.audit import notify
    from models import Application
    a = db.session.get(Application, att.application_id)
    if a:
        notify(a.candidate_id, "Your test is ready", "The hiring team has prepared your test. You can start it from your home page.", "/me#upcoming")
    return None


def sample(job, cfg, n):
    """Round setup: a sample paper from the pool the round draws from. Nothing is saved; nothing is written by AI."""
    from types import SimpleNamespace
    from services.mcq import _skills, base_pool, unique
    fake = SimpleNamespace(config=cfg, practice_user_id=None, application_id=None, id=None, cert_attempt_id=None)
    pool = unique(base_pool(fake, job, cfg.get("mcq.folder_ids") or [], _skills(fake, job), cfg.get("level")).all())
    fixed = [int(i) for i in (cfg.get("mcq.fixed_ids") or []) if str(i).isdigit()]
    if fixed:
        live = {q.id: q for q in Question.query.filter(Question.id.in_(fixed)).all()}
        chosen = [live[i] for i in fixed if i in live]
    else:
        random.shuffle(pool)
        pool.sort(key=lambda q: 1 if q.source == "ai" else 0)
        chosen = pool[:n]
    return {"available": len(pool), "fixed": bool(fixed), "questions": [{"id": q.id, "text": q.text, "code": q.code, "options": q.options or [], "answer": q.answer,
                                                                         "explanation": q.explanation, "skill": q.skill, "level": q.level, "source": q.source} for q in chosen]}
