"""Ask Hira: the hiring team's assistant (V02.00.05).

Every answer is built from a database lookup made as the person asking, so Hira only ever shows what their role can
already see, never another company's data, and says "I don't know" when the data doesn't have the answer. When an
Anthropic key is set, Claude only works out what is being asked (which question, which job, which stage); the
answer itself always comes from the data. Without a key, a keyword reader handles the common questions.

In this version Hira answers and suggests. She does not add, move, shortlist or invite anyone.
"""
import re
from datetime import date, datetime, timedelta

from flask import g

from extensions import db
from models import (Application, CandidateProfile, Job, Notification, Report, RoundAttempt, SystemCheck, User)
from services import ai
from services.perms import can, visible_job_ids
from services.pipeline import ROUND_TYPES, skill_match

INTENTS = ["open_jobs", "job_status", "jobs_no_candidates", "jobs_closing", "stage", "final_round", "pending_reviews",
           "score_above", "suggest", "candidate", "attention", "help"]
STAGES = {"applied": "Applied", "shortlisted": "Shortlisted", "in_round": "In a round", "awaiting_review": "Waiting for review",
          "decision": "Waiting for a decision", "offer": "Offer", "hired": "Hired", "rejected": "Not selected",
          "on_hold": "On hold", "withdrawn": "Withdrawn"}
STAGE_WORDS = [("waiting for review", "awaiting_review"), ("awaiting review", "awaiting_review"), ("in review", "awaiting_review"),
               ("shortlist", "shortlisted"), ("rejected", "rejected"), ("not selected", "rejected"), ("hired", "hired"),
               ("offer", "offer"), ("on hold", "on_hold"), ("withdrawn", "withdrawn"), ("in a round", "in_round"),
               ("in progress", "in_round"), ("interviewing", "in_round"), ("applied", "applied"), ("new applicant", "applied"),
               ("decision", "decision")]
EXAMPLES = ["Which jobs are open?", "What's the status of this job?", "Which jobs have no candidates?",
            "Who is in the final round?", "Who is waiting for review?", "Who scored above 70%?",
            "Which candidates should I add to this job?", "What needs my attention today?"]
MAX_ITEMS = 12


def _cid():
    from routes.jobs import cid
    return cid()


def _jobs(status=None):
    q = Job.query.filter_by(company_id=_cid())
    ids = visible_job_ids(g.user, "candidates.view")
    if ids is not None:
        q = q.filter(Job.id.in_(ids or [0]))
    if status:
        q = q.filter(Job.status == status)
    return q.order_by(Job.created_at.desc()).all()


def _job_link(j):
    return f"/app/jobs/{j.id}"


def _app_link(a):
    return f"/app/applications/{a.id}"


def _pct(att):
    if att.score is None:
        return None
    return round(att.score) if att.round_type == "mcq" else round(att.score * 20)


def _find_job(text, page_job_id, jobs):
    """The job the question is about: named in the question, else the page the person is on."""
    t = text.lower()
    best = None
    for j in jobs:
        title = (j.title or "").lower()
        if title and title in t and (not best or len(title) > len(best.title)):
            best = j
    if best:
        return best
    words = {w for w in re.findall(r"[a-z0-9+#.]{3,}", t)} - {"job", "jobs", "the", "for", "what", "status", "which", "who", "this",
                                                               "candidates", "candidate", "show", "with", "about", "role"}
    scored = []
    for j in jobs:
        tw = set(re.findall(r"[a-z0-9+#.]{3,}", (j.title or "").lower()))
        hit = len(words & tw)
        if hit:
            scored.append((hit, j))
    if scored:
        scored.sort(key=lambda x: -x[0])
        if len(scored) == 1 or scored[0][0] > scored[1][0]:
            return scored[0][1]
    if page_job_id:
        return next((j for j in jobs if j.id == page_job_id), None)
    return None


def _rules(text):
    """Keyword reader: (intent, params). Used without an AI key, and as the check on what the AI says."""
    t = text.lower().strip()
    m = re.search(r"(?:above|over|more than|at least|>=?|scored)\s*(\d{1,3})\s*%?", t)
    if m and ("score" in t or "%" in t or "above" in t):
        return "score_above", {"threshold": int(m.group(1))}
    if re.search(r"attention|today|to.?do|my day|pending for me|what should i", t):
        return "attention", {}
    if re.search(r"suggest|recommend|should i add|who (?:can|should) i add|good fit|best fit|match(?:es|ing)? (?:for|this)|find candidates|talent pool", t):
        return "suggest", {}
    if re.search(r"no candidates|without candidates|empty jobs|zero candidates|no applicants|nobody applied", t):
        return "jobs_no_candidates", {}
    if re.search(r"clos|deadline|due (?:this|next)|ending", t):
        return "jobs_closing", {}
    if re.search(r"final round|last round", t):
        return "final_round", {}
    if re.search(r"review", t) and re.search(r"wait|pending|need|to review|awaiting", t):
        return "pending_reviews", {}
    for w, st in STAGE_WORDS:
        if w in t and re.search(r"who|which|show|list|candidates|people|how many", t):
            return "stage", {"stage": st}
    if re.search(r"status|how is|how's|progress|update on|pipeline", t):
        return "job_status", {}
    if re.search(r"(?:open|live|active|running) (?:jobs|roles|positions)|jobs (?:are )?(?:open|live)|which jobs|list (?:the )?jobs|my jobs|all jobs", t):
        return "open_jobs", {}
    m = re.search(r"(?:show|find|open|about|results? (?:of|for)|how did|how is|how's)\s+(?:me\s+)?([A-Za-z][A-Za-z .'’-]{1,60})", text, re.I)
    if m:
        name = re.split(r"['’]s\b", m.group(1))[0]
        tail = {"results", "result", "scores", "score", "profile", "details", "application", "report", "do", "doing", "progress"}
        parts = [w for w in name.split() if w.lower() not in tail]
        if parts:
            return "candidate", {"name": " ".join(parts).strip(" ?.")}
    return "help", {}


def _understand(text):
    intent, params = _rules(text)
    if intent != "help" or not ai.configured():
        return intent, params, "rules"
    out = ai.ask_json("assistant_intent",
                      "Classify this question from a recruiter using a hiring platform. Reply as JSON "
                      '{"intent": one of ' + ", ".join(INTENTS) + ', "stage": one of ' + ", ".join(STAGES) +
                      ' or null, "threshold": number or null, "name": candidate name or null}. Question: ' + text[:500],
                      lambda: {"intent": "help"}, company_id=_cid(), max_tokens=200)
    intent = out.get("intent") if out.get("intent") in INTENTS else "help"
    params = {"stage": out.get("stage") if out.get("stage") in STAGES else None, "name": (out.get("name") or "")[:60] or None}
    try:
        params["threshold"] = int(out.get("threshold")) if out.get("threshold") is not None else None
    except (TypeError, ValueError):
        params["threshold"] = None
    return intent, {k: v for k, v in params.items() if v is not None}, "ai"


def _counts(j):
    rows = db.session.query(Application.stage, db.func.count(Application.id)).filter(Application.job_id == j.id).group_by(Application.stage).all()
    return {s: n for s, n in rows}


def _cand_item(a, j, extra=""):
    u = db.session.get(User, a.candidate_id)
    return {"label": u.name if u else "Candidate", "sub": f"{j.title} · {STAGES.get(a.stage, a.stage)}" + (f" · {extra}" if extra else ""),
            "link": _app_link(a)}


# ---------------------------------------------------------------- answers

def a_open_jobs(text, job, jobs):
    live = [j for j in jobs if j.status == "live"]
    if not live:
        drafts = sum(1 for j in jobs if j.status in ("draft", "pending_approval"))
        return f"You have no open jobs right now{f' ({drafts} in draft or waiting for approval)' if drafts else ''}.", []
    items = []
    for j in live[:MAX_ITEMS]:
        c = _counts(j)
        total = sum(c.values())
        items.append({"label": j.title, "sub": f"{total} candidate{'s' if total != 1 else ''} · {c.get('awaiting_review', 0)} to review"
                      + (f" · closes {j.deadline:%d %b}" if j.deadline else ""), "link": _job_link(j)})
    return f"{len(live)} open job{'s' if len(live) != 1 else ''}." + (" Showing the newest 12." if len(live) > MAX_ITEMS else ""), items


def a_job_status(text, job, jobs):
    if not job:
        return "Which job do you mean? Name it in your question, or ask from the job's page.", \
            [{"label": j.title, "sub": j.status, "link": _job_link(j)} for j in jobs[:MAX_ITEMS]]
    c = _counts(job)
    total = sum(c.values())
    parts = [f"{STAGES.get(s, s)} {n}" for s, n in sorted(c.items(), key=lambda x: -x[1])]
    rounds = " → ".join(r.get("name") or ROUND_TYPES.get(r.get("type"), "") for r in (job.rounds or [])) or "no rounds yet"
    lines = [f"{job.title} is {job.status.replace('_', ' ')}, with {total} candidate{'s' if total != 1 else ''}"
             + (f": {', '.join(parts)}." if parts else ".")]
    lines.append(f"Rounds: {rounds}.")
    lines.append(f"Hired {c.get('hired', 0)} of {job.hires_target or 1}." + (f" Closes {job.deadline:%d %b %Y}." if job.deadline else ""))
    return " ".join(lines), [{"label": "Open the job", "sub": job.title, "link": _job_link(job)}]


def a_jobs_no_candidates(text, job, jobs):
    empty = [j for j in jobs if j.status in ("live", "draft", "pending_approval") and not Application.query.filter_by(job_id=j.id).first()]
    if not empty:
        return "Every job you can see has at least one candidate.", []
    return f"{len(empty)} job{'s have' if len(empty) != 1 else ' has'} no candidates yet.", \
        [{"label": j.title, "sub": j.status.replace("_", " "), "link": _job_link(j)} for j in empty[:MAX_ITEMS]]


def a_jobs_closing(text, job, jobs):
    today = date.today()
    soon = sorted([j for j in jobs if j.status == "live" and j.deadline and today <= j.deadline <= today + timedelta(days=7)],
                  key=lambda j: j.deadline)
    if not soon:
        return "No open job closes in the next 7 days.", []
    return f"{len(soon)} job{'s close' if len(soon) != 1 else ' closes'} in the next 7 days.", \
        [{"label": j.title, "sub": f"Closes {j.deadline:%a %d %b}", "link": _job_link(j)} for j in soon]


def _apps(jobs, job, **filt):
    ids = [job.id] if job else [j.id for j in jobs]
    q = Application.query.filter(Application.job_id.in_(ids or [0]))
    for k, v in filt.items():
        q = q.filter(getattr(Application, k) == v)
    return q.order_by(Application.updated_at.desc()).all()


def a_stage(text, job, jobs, stage=None):
    stage = stage or "in_round"
    apps = _apps(jobs, job, stage=stage)
    where = f" for {job.title}" if job else ""
    if not apps:
        return f"Nobody is at “{STAGES.get(stage, stage)}”{where}.", []
    byid = {j.id: j for j in jobs}
    return f"{len(apps)} candidate{'s' if len(apps) != 1 else ''} at “{STAGES.get(stage, stage)}”{where}.", \
        [_cand_item(a, byid.get(a.job_id) or db.session.get(Job, a.job_id)) for a in apps[:MAX_ITEMS]]


def a_final_round(text, job, jobs):
    out = []
    for j in ([job] if job else jobs):
        last = len(j.rounds or []) - 1
        if last < 0:
            continue
        for a in Application.query.filter(Application.job_id == j.id, Application.current_round == last,
                                          Application.stage.in_(("in_round", "awaiting_review", "decision", "shortlisted"))).all():
            out.append(_cand_item(a, j, (j.rounds[last].get("name") or ROUND_TYPES.get(j.rounds[last].get("type"), ""))))
    where = f" for {job.title}" if job else ""
    if not out:
        return f"Nobody is in the final round{where} yet.", []
    return f"{len(out)} candidate{'s are' if len(out) != 1 else ' is'} in the final round{where}.", out[:MAX_ITEMS]


def a_pending_reviews(text, job, jobs):
    ids = [job.id] if job else [j.id for j in jobs]
    rows = (db.session.query(Report, RoundAttempt, Application).join(RoundAttempt, RoundAttempt.id == Report.attempt_id)
            .join(Application, Application.id == RoundAttempt.application_id)
            .filter(Application.job_id.in_(ids or [0]), Report.status == "awaiting_review").order_by(Report.created_at.asc()).all())
    if not rows:
        return "No reports are waiting for review" + (f" for {job.title}." if job else "."), []
    byid = {j.id: j for j in jobs}
    items = []
    for r, att, a in rows[:MAX_ITEMS]:
        j = byid.get(a.job_id) or db.session.get(Job, a.job_id)
        u = db.session.get(User, a.candidate_id)
        waited = (datetime.utcnow() - r.created_at).days
        items.append({"label": u.name if u else "Candidate", "sub": f"{j.title} · {ROUND_TYPES.get(att.round_type, att.round_type)}"
                      + (f" · waiting {waited} day{'s' if waited != 1 else ''}" if waited else " · today"), "link": f"/app/reports/{att.id}"})
    return f"{len(rows)} report{'s are' if len(rows) != 1 else ' is'} waiting for review, oldest first.", items


def a_score_above(text, job, jobs, threshold=70):
    threshold = max(0, min(100, int(threshold if threshold is not None else 70)))
    ids = [job.id] if job else [j.id for j in jobs]
    rows = (db.session.query(RoundAttempt, Application).join(Application, Application.id == RoundAttempt.application_id)
            .filter(Application.job_id.in_(ids or [0]), RoundAttempt.score.isnot(None),
                    RoundAttempt.status.in_(("completed", "reviewed"))).all())
    best = {}
    for att, a in rows:
        p = _pct(att)
        if p is not None and p >= threshold and (a.id not in best or p > best[a.id][0]):
            best[a.id] = (p, att, a)
    if not best:
        return f"Nobody has scored {threshold}% or more" + (f" on {job.title}." if job else " in a finished round."), []
    byid = {j.id: j for j in jobs}
    items = [_cand_item(a, byid.get(a.job_id) or db.session.get(Job, a.job_id), f"{p}% in {ROUND_TYPES.get(att.round_type, att.round_type)}")
             for p, att, a in sorted(best.values(), key=lambda x: -x[0])[:MAX_ITEMS]]
    return f"{len(best)} candidate{'s' if len(best) != 1 else ''} scored {threshold}% or more" + (f" on {job.title}." if job else "."), items


def suggest_for(job, limit=MAX_ITEMS):
    """Candidates not yet on this job, ranked by skill match: this company's pool and past applicants, plus Disha
    candidates whose profile is open to everyone. Returns [(score, user, profile, matched, missing, source)]."""
    taken = {a.candidate_id for a in Application.query.filter_by(job_id=job.id).all()}
    cid = job.company_id
    job_ids = [j.id for j in Job.query.filter_by(company_id=cid).all()] or [0]
    mine = {a.candidate_id for a in Application.query.filter(Application.job_id.in_(job_ids)).all()}
    mine |= {p.user_id for p in CandidateProfile.query.filter_by(source_company_id=cid).all()}
    pool = CandidateProfile.query.filter((CandidateProfile.user_id.in_(mine or [0])) | (CandidateProfile.visibility == "everyone")).all()
    out = []
    for p in pool:
        if p.user_id in taken:
            continue
        u = db.session.get(User, p.user_id)
        if not u or u.kind != "candidate" or u.active is False:
            continue
        score, got, missing = skill_match(job, p.skills or [])
        if not got:
            continue
        out.append((score, u, p, got, missing, "company" if p.user_id in mine else "disha"))
    out.sort(key=lambda x: (-x[0], x[1].name or ""))
    return out[:limit]


def a_suggest(text, job, jobs):
    if not job:
        return "Which job should I find candidates for? Name it, or ask from the job's page.", \
            [{"label": j.title, "sub": j.status, "link": _job_link(j)} for j in jobs if j.status == "live"][:MAX_ITEMS]
    if not can(g.user, "candidates.add", job=job):
        return f"Your role can't add candidates to {job.title}, so I won't suggest any.", []
    ranked = suggest_for(job)
    if not ranked:
        return f"I found nobody in your talent pool or on Disha whose skills match {job.title}.", []
    items = []
    for score, u, p, got, missing, src in ranked:
        why = "Matches " + ", ".join(x.split(" L")[0] for x in got[:4]) + (f". Missing {', '.join(missing[:3])}" if missing else "")
        items.append({"label": u.name, "sub": f"{score}% match · {why}." + (" · Disha profile" if src == "disha" else " · your pool"),
                      "link": f"/app/jobs/{job.id}?add={u.id}", "user_id": u.id,
                      "pick": {"user_id": u.id, "name": u.name, "source": src, "email": u.email if src == "company" else None,
                               "headline": p.headline or "", "location": p.location or "",
                               "skills": [x["name"] if isinstance(x, dict) else x for x in (p.skills or [])][:6], "jobs": []}})
    return (f"{len(items)} candidate{'s' if len(items) != 1 else ''} who could fit {job.title}, best match first. "
            "Open one to add them to the job."), items


def a_candidate(text, job, jobs, name=None):
    name = (name or "").strip()
    if len(name) < 2:
        return "Whose results should I show? Give me their name.", []
    ids = [j.id for j in jobs] or [0]
    rows = (db.session.query(Application, User).join(User, User.id == Application.candidate_id)
            .filter(Application.job_id.in_(ids), User.name.ilike(f"%{name}%")).limit(MAX_ITEMS * 2).all())
    if not rows:
        return f"I couldn't find “{name}” on any job you can see.", []
    byid = {j.id: j for j in jobs}
    items = []
    for a, u in rows[:MAX_ITEMS]:
        j = byid.get(a.job_id)
        last = RoundAttempt.query.filter_by(application_id=a.id).order_by(RoundAttempt.round_index.desc()).first()
        extra = ""
        if last and _pct(last) is not None:
            extra = f"{_pct(last)}% in {ROUND_TYPES.get(last.round_type, last.round_type)}"
        items.append(_cand_item(a, j, extra))
    people = len({u.id for _, u in rows})
    return f"{people} candidate{'s' if people != 1 else ''} named like “{name}”, on {len(rows)} job{'s' if len(rows) != 1 else ''}.", items


def a_attention(text, job, jobs):
    ids = [j.id for j in jobs] or [0]
    items = []
    n_rev, rev_items = 0, []
    t, r_items = a_pending_reviews(text, None, jobs)
    if r_items:
        n_rev = len(r_items)
        items.append({"label": f"{n_rev}{'+' if n_rev >= MAX_ITEMS else ''} report{'s' if n_rev != 1 else ''} to review", "sub": r_items[0]["sub"],
                      "link": "/app/reports"})
    start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    today = (db.session.query(RoundAttempt, Application).join(Application, Application.id == RoundAttempt.application_id)
             .filter(Application.job_id.in_(ids), RoundAttempt.scheduled_at >= start, RoundAttempt.scheduled_at < start + timedelta(days=1),
                     RoundAttempt.status.in_(("invited", "scheduled", "in_progress"))).order_by(RoundAttempt.scheduled_at).all())
    for att, a in today[:6]:
        u = db.session.get(User, a.candidate_id)
        mine = att.interviewer_id == g.user.id
        items.append({"label": f"Interview {att.scheduled_at:%H:%M} UTC · {u.name if u else ''}", "sub": ("You interview" if mine else "Scheduled")
                      + f" · {db.session.get(Job, a.job_id).title}", "link": f"/app/isha/{att.id}" if mine else _app_link(a)})
    week = datetime.utcnow() - timedelta(days=7)
    helps = (db.session.query(SystemCheck, RoundAttempt, Application).join(RoundAttempt, RoundAttempt.id == SystemCheck.attempt_id)
             .join(Application, Application.id == RoundAttempt.application_id)
             .filter(Application.job_id.in_(ids), SystemCheck.help_step.isnot(None), SystemCheck.created_at > week).all())
    for c, att, a in helps[:6]:
        if (att.result or {}).get("syscheck", {}).get("passed"):
            continue
        u = db.session.get(User, a.candidate_id)
        from services.syscheck import HELP_ONLY, STEPS
        items.append({"label": f"{u.name if u else 'A candidate'} needs help with the system check", "sub": {**STEPS, **HELP_ONLY}.get(c.help_step, (c.help_step,))[0],
                      "link": _app_link(a)})
    declined = [x for x in RoundAttempt.query.join(Application, Application.id == RoundAttempt.application_id)
                .filter(Application.job_id.in_(ids), RoundAttempt.created_at > week).all() if (x.result or {}).get("recording_declined")]
    for att in declined[:4]:
        a = db.session.get(Application, att.application_id)
        u = db.session.get(User, a.candidate_id)
        items.append({"label": f"{u.name if u else 'A candidate'} declined recording", "sub": "The interview didn't start", "link": _app_link(a)})
    short = Notification.query.filter(Notification.user_id == g.user.id, Notification.title == "MCQ round is short of questions",
                                      Notification.created_at > week).first()
    if short:
        items.append({"label": "An MCQ round is short of questions", "sub": short.body[:120], "link": short.link})
    if not items:
        return "Nothing needs your attention right now: no reports waiting, no interviews today, and no candidates stuck.", []
    return f"{len(items)} thing{'s' if len(items) != 1 else ''} need{'s' if len(items) == 1 else ''} your attention.", items


def answer(text, page=None):
    """Returns {text, items, intent, job_id, engine}."""
    page = page or {}
    jobs = _jobs()
    intent, params, engine = _understand(text)
    try:
        page_job = int(page.get("job_id")) if page.get("job_id") else None
    except (TypeError, ValueError):
        page_job = None
    if not page_job and page.get("application_id"):
        a = db.session.get(Application, int(page["application_id"])) if str(page["application_id"]).isdigit() else None
        page_job = a.job_id if a else None
    job = _find_job(text, page_job, jobs)
    if intent == "open_jobs":
        t, items = a_open_jobs(text, job, jobs)
    elif intent == "job_status":
        t, items = a_job_status(text, job, jobs)
    elif intent == "jobs_no_candidates":
        t, items = a_jobs_no_candidates(text, job, jobs)
    elif intent == "jobs_closing":
        t, items = a_jobs_closing(text, job, jobs)
    elif intent == "stage":
        t, items = a_stage(text, job, jobs, params.get("stage"))
    elif intent == "final_round":
        t, items = a_final_round(text, job, jobs)
    elif intent == "pending_reviews":
        t, items = a_pending_reviews(text, job, jobs)
    elif intent == "score_above":
        t, items = a_score_above(text, job, jobs, params.get("threshold"))
    elif intent == "suggest":
        t, items = a_suggest(text, job, jobs)
    elif intent == "candidate":
        t, items = a_candidate(text, job, jobs, params.get("name"))
    elif intent == "attention":
        t, items = a_attention(text, job, jobs)
    else:
        t, items = ("I don't know that one yet. I answer from your live hiring data: jobs, candidates, stages, scores, reviews "
                    "and today's interviews. Try one of these:"), [{"label": q, "sub": "", "ask": q} for q in EXAMPLES]
    return {"text": t, "items": items, "intent": intent, "job_id": job.id if job else None, "engine": engine}
