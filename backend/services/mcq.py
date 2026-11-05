"""Choosing MCQ questions (BUG-004).

Rules, for job rounds, certification sections and practice tests alike:
  1. Never the same question twice in one test, compared by its text (not just its id), so copies can't slip in.
  2. Questions the candidate saw in earlier attempts come last; unseen ones first.
  3. When the bank is short, Hira writes new questions and is told which ones to avoid. A new question whose text
     already exists is never saved. New questions are saved to the bank as drafts for review (company setting
     mcq.ai_review, on by default); they are used in this one test, and in others only once a person approves them.
  4. If there still aren't enough, the test is shorter rather than padded with copies, and the recruiter is told.
"""
import random
import re
from datetime import datetime, timedelta

from extensions import db
from models import Notification, Question, QuestionVersion, RoundAttempt

_PUNCT = re.compile(r"[^\w\s]", re.UNICODE)


def norm(text):
    """The text a person would call 'the same question': case, spacing and punctuation ignored."""
    return " ".join(_PUNCT.sub(" ", (text or "").lower()).split())


def _skills(att, job):
    return [s["name"] if isinstance(s, dict) else s for s in (job.skills if job else [])] or (att.config or {}).get("skills", [])


def base_pool(att, job, folder_ids=None, skills=None, level=None):
    company_id = job.company_id if job else None
    pool = Question.query.filter(Question.status == "approved",
                                 (Question.company_id == company_id) | (Question.company_id.is_(None)))
    if folder_ids:
        from routes.qbank import descendants
        ids = descendants(folder_ids, company_id) | descendants(folder_ids, None)
        return pool.filter(Question.folder_id.in_(ids or [0]))
    if skills:
        pool = pool.filter(Question.skill.in_(skills))
    if level:
        pool = pool.filter(Question.level >= max(1, int(level) - 1), Question.level <= int(level) + 1)
    return pool


def unique(questions):
    """Drops questions whose text repeats another's. Keeps the newest version (highest id) of each text."""
    out, seen = [], set()
    for q in sorted(questions, key=lambda q: -(q.id or 0)):
        k = norm(q.text)
        if k and k not in seen:
            seen.add(k)
            out.append(q)
    return out


def seen_before(att):
    """(ids, texts) of questions this candidate was shown in their other MCQ attempts."""
    from services.pipeline import context
    _, _, cand, _ = context(att)
    if not cand:
        return set(), set()
    from models import Application, CertAttempt
    app_ids = [a.id for a in Application.query.filter_by(candidate_id=cand.id).all()]
    cert_ids = [c.id for c in CertAttempt.query.filter_by(user_id=cand.id).all()]
    q = RoundAttempt.query.filter(RoundAttempt.round_type == "mcq", RoundAttempt.id != att.id,
                                  (RoundAttempt.application_id.in_(app_ids or [0])) | (RoundAttempt.practice_user_id == cand.id) |
                                  (RoundAttempt.cert_attempt_id.in_(cert_ids or [0])))
    ids, texts = set(), set()
    for prev in q.all():
        res = prev.result or {}
        ids.update(int(i) for i in res.get("question_ids") or [])
        texts.update(norm(v.get("text")) for v in (res.get("qsnap") or {}).values())
    return ids, texts


def _existing_texts(company_id):
    rows = db.session.query(Question.text).filter((Question.company_id == company_id) | (Question.company_id.is_(None)),
                                                  Question.status != "archived").all()
    return {norm(t) for (t,) in rows}


def save_generated(items, company_id, skills, review=True, folder_id=None, tags=None, note="Drafted by Hira"):
    """Saves AI-written questions, skipping any whose text is already in the bank (or repeats another in this batch)."""
    taken = _existing_texts(company_id)
    out = []
    for it in items or []:
        text = str(it.get("text") or "").strip()
        opts = [str(o) for o in (it.get("options") or []) if str(o).strip()][:6]
        k = norm(text)
        if not k or k in taken or len(opts) < 2 or len({norm(o) for o in opts}) < len(opts):
            continue
        taken.add(k)
        try:
            ans = int(it.get("answer", 0))
        except (TypeError, ValueError):
            continue
        if not 0 <= ans < len(opts):
            continue
        q = Question(company_id=company_id, folder_id=folder_id, skill=(it.get("skill") or (skills[0] if skills else "General"))[:80],
                     level=max(1, min(5, int(it.get("level") or 3))), text=text[:4000], code=it.get("code") or None, options=opts,
                     answer=ans, explanation=it.get("explanation"), tags=tags or [], status="pending" if review else "approved",
                     source="ai", version=1)
        db.session.add(q)
        db.session.flush()
        db.session.add(QuestionVersion(question_id=q.id, version=1, snapshot=q.snapshot(), note=note))
        out.append(q)
    return out


def pick(att, job, n):
    """Returns (questions, info). info = {"wanted", "got", "short", "generated", "repeats"}."""
    from services import ai
    from services.settings import resolve
    cfg = att.config or {}
    skills, level = _skills(att, job), cfg.get("level")
    company_id = job.company_id if job else None
    folder_ids = cfg.get("mcq.folder_ids") or []
    pool = unique(base_pool(att, job, folder_ids, skills, level).all())
    seen_ids, seen_texts = seen_before(att)
    fresh = [q for q in pool if q.id not in seen_ids and norm(q.text) not in seen_texts]
    repeat = [q for q in pool if q not in fresh]
    random.shuffle(fresh)
    random.shuffle(repeat)
    generated = []
    if len(fresh) < n and not folder_ids:  # chosen folders are used as they are; never generate into them
        avoid = [q.text for q in pool][:60]
        items = ai.generate_mcq(skills or ["General aptitude"], int(level or 3), n - len(fresh), company_id=company_id, avoid=avoid)
        review = bool(resolve("mcq.ai_review", company_id=company_id, team_id=job.team_id if job else None,
                              job_id=job.id if job else None)[0]) if job else False
        generated = save_generated(items, company_id, skills, review=review)
        texts = {norm(q.text) for q in fresh + repeat}
        generated = [q for q in generated if norm(q.text) not in texts]
    chosen = (fresh + generated + repeat)[:n]
    info = {"wanted": n, "got": len(chosen), "short": len(chosen) < n, "generated": len(generated),
            "repeats": sum(1 for q in chosen if q in repeat)}
    if generated and job and any(q.status == "pending" for q in generated):
        _tell(job, "New questions to review", f"Hira wrote {len(generated)} new question{'s' if len(generated) != 1 else ''} for {job.title}. "
              "They were used once and wait in the question bank as drafts until someone approves them.", f"/app/questions?status=pending&job={job.id}")
    if info["short"] and job:
        _tell(job, "MCQ round is short of questions",
              f"{job.title}: a candidate got {len(chosen)} of {n} questions because the question bank doesn't have enough different ones. "
              "Add or approve questions, or lower the number of questions.", f"/app/jobs/{job.id}")
    return chosen, info


def _tell(job, title, body, link):
    """Once a day per job and message, so a busy round doesn't flood anyone."""
    from services.audit import notify_roles
    since = datetime.utcnow() - timedelta(hours=24)
    if Notification.query.filter(Notification.title == title, Notification.link == link, Notification.created_at > since).first():
        return
    notify_roles(job.company_id, ["recruiter", "manager"], title, body, link)


def coverage(job, cfg, n):
    """For round setup: how many different questions the bank has for this round."""
    folder_ids = cfg.get("mcq.folder_ids") or []
    skills = [s["name"] if isinstance(s, dict) else s for s in (job.skills or [])]
    pool = unique(base_pool(None, job, folder_ids, None if folder_ids else skills, None).all())
    by = {}
    for q in pool:
        by[q.skill or "General"] = by.get(q.skill or "General", 0) + 1
    pending = Question.query.filter(Question.status == "pending",
                                    (Question.company_id == job.company_id) | (Question.company_id.is_(None))).count()
    have = len(pool)
    parts = ", ".join(f"{k} {v}" for k, v in sorted(by.items(), key=lambda x: -x[1])[:6])
    if have >= n * 2:
        msg = f"{n} questions per test from {have} available ({parts}). Retakes can get different questions."
    elif have >= n:
        msg = f"{n} questions per test from {have} available ({parts}). Retakes will repeat some questions; add more for variety."
    elif folder_ids:
        msg = f"Only {have} questions in the chosen folders, so tests will have {have} instead of {n}. Add questions or choose more folders."
    else:
        msg = f"Only {have} approved questions for this job's skills{f' ({parts})' if parts else ''}. Hira will write the rest; they are saved as drafts for review."
    if pending:
        msg += f" {pending} draft question{'s' if pending != 1 else ''} wait for review."
    return {"available": have, "by_skill": by, "wanted": n, "short": have < n, "pending": pending, "message": msg}
