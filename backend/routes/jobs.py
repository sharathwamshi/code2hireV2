"""Recruiters and managers: jobs, applications, Hira screening, rounds, verdicts, talent pool."""
import secrets
from datetime import datetime, timedelta

from flask import Blueprint, g, request
from sqlalchemy import func

from extensions import db
from models import (Application, CandidateProfile, HiringTemplate, Job, JobAssignment, Report, RoundAttempt, SavedView,
                    Team, User)
from routes.utils import body, copy_name, err, ok, parse_dt, table
from services import validate as V
from services import ai
from services.audit import log, notify
from services.perms import can, can_any, deny, hash_password, staff_required, visible_job_ids
from services.pipeline import CREDIT_COST, ROUND_TYPES, active_attempt, invite_to_round, reschedule, round_config, round_name, skill_match, spend
from services.policy import evaluate
from services.settings import report_scale, resolve

bp = Blueprint("jobs", __name__, url_prefix="/api")


def cid():
    if g.user.is_superadmin and request.headers.get("X-Company-Id"):
        return int(request.headers["X-Company-Id"])
    return g.user.company_id


def get_job(jid, perm="candidates.view"):
    j = Job.query.filter_by(id=jid, company_id=cid()).first()
    if not j or not can(g.user, perm, job=j):
        return None
    return j


def job_row(j):
    d = j.to_dict()
    d["applications"] = Application.query.filter_by(job_id=j.id).count()
    d["in_review"] = Application.query.filter_by(job_id=j.id, stage="awaiting_review").count()
    d["hired"] = Application.query.filter_by(job_id=j.id, stage="hired").count()
    t = db.session.get(Team, j.team_id) if j.team_id else None
    d["team"] = t.name if t else ""
    u = db.session.get(User, j.created_by) if j.created_by else None
    d["owner"] = u.name if u else ""
    if not can(g.user, "salary.view", job=j):
        d["salary_min"] = d["salary_max"] = None
    return d


# ---------------------------------------------------------------- jobs

@bp.get("/jobs")
@staff_required
def jobs():
    q = Job.query.filter_by(company_id=cid())
    ids = visible_job_ids(g.user, "candidates.view")
    if ids is not None:
        q = q.filter(Job.id.in_(ids or [0]))
    return table(q, [Job.title, Job.location, Job.client_name],
                 {"title": Job.title, "created": Job.created_at, "status": Job.status, "deadline": Job.deadline},
                 "created", job_row,
                 {"status": lambda q, v: q.filter(Job.status == v), "visibility": lambda q, v: q.filter(Job.visibility == v),
                  "team_id": lambda q, v: q.filter(Job.team_id == int(v)),
                  "mine": lambda q, v: q.filter(Job.created_by == g.user.id) if v == "true" else q})


@bp.post("/jobs/draft")
@staff_required
def draft():
    """Hira turns pasted text (a JD, an email, a few lines) into a full job plan."""
    if not can_any(g.user, "jobs.create", cid()):
        return deny()
    text = body().get("text") or ""
    if len(text.strip()) < 5:
        return err("Paste a job description or describe the role in a few words.")
    return ok(ai.draft_job(text, company_id=cid()))


@bp.get("/templates")
@staff_required
def templates():
    q = HiringTemplate.query.filter((HiringTemplate.company_id == cid()) | (HiringTemplate.company_id.is_(None)))
    q = q.filter((HiringTemplate.archived.is_(None)) | (HiringTemplate.archived.is_(False)))
    return ok([{**t.to_dict(), "global": t.company_id is None} for t in q.order_by(HiringTemplate.name).all()])


@bp.post("/templates")
@staff_required
def save_template():
    if not can(g.user, "templates.manage", company_id=cid()):
        return deny()
    d = body()
    t = HiringTemplate(company_id=cid(), team_id=d.get("team_id"), name=d.get("name") or "Template",
                       description=d.get("description"), rounds=d.get("rounds", []), rubric=d.get("rubric", []),
                       created_by=g.user.id)
    db.session.add(t)
    log("template.create", "template", None, name=t.name)
    db.session.commit()
    return ok(t.to_dict())


LEVELS = ("Junior", "Mid", "Senior", "Lead")
WORK_MODES = ("onsite", "hybrid", "remote")
VISIBILITY = ("private", "public", "internal")


def _job_fields(d, j=None):
    """Checks every job field that is present (all of them on create). Returns (clean_dict, Checker)."""
    c, out, creating = V.Checker(), {}, j is None
    if creating or "title" in d:
        out["title"] = c.add("title", *V.text(d.get("title"), 120, required=True, label="Job title"))
        if out["title"] and len(out["title"]) < 2:
            c.add("title", None, "Job title needs at least 2 characters.")
    if "description" in d:
        out["description"] = c.add("description", *V.text(d.get("description"), 20000, label="Description"))
    for k, allowed, label in (("level", LEVELS, "Level"), ("work_mode", WORK_MODES, "Work mode"), ("visibility", VISIBILITY, "Visibility")):
        if k in d and d[k] not in (None, ""):
            if d[k] not in allowed:
                c.add(k, None, f"{label} must be one of: {', '.join(allowed)}.")
            out[k] = d[k]
    for k, label in (("location", "Location"), ("client_name", "Client name")):
        if k in d:
            out[k] = c.add(k, *V.text(d.get(k), 120, label=label))
    if creating or "hires_target" in d:
        out["hires_target"] = c.add("hires_target", *V.integer(d.get("hires_target", 1), 1, 1000, required=True, label="Hires needed"))
    for k, label in (("salary_min", "Minimum salary"), ("salary_max", "Maximum salary")):
        if k in d:
            out[k] = c.add(k, *V.integer(d.get(k), 0, 1_000_000_000, label=label))
    lo = out.get("salary_min", j.salary_min if j else None) if "salary_min" not in c.fields else None
    hi = out.get("salary_max", j.salary_max if j else None) if "salary_max" not in c.fields else None
    if lo is not None and hi is not None and lo > hi:
        c.add("salary_min", None, "Minimum salary can't be more than the maximum.")
    if "credit_budget" in d:
        out["credit_budget"] = c.add("credit_budget", *V.integer(d.get("credit_budget"), 0, 10_000_000, label="Credit budget"))
    if "deadline" in d:
        if d.get("deadline") in (None, ""):
            out["deadline"] = None
        else:
            dt = parse_dt(d.get("deadline"))
            if not dt:
                c.add("deadline", None, "Enter a valid date.")
            else:
                out["deadline"] = dt.date()
                if (creating or dt.date() != j.deadline) and dt.date() < datetime.utcnow().date():
                    c.add("deadline", None, "The deadline can't be in the past.")
    if "team_id" in d:
        tid = d.get("team_id")
        if tid in (None, ""):
            out["team_id"] = None
        else:
            t = db.session.get(Team, int(tid)) if str(tid).isdigit() else None
            if not t or t.company_id != cid():
                c.add("team_id", None, "Choose a team from your company.")
            out["team_id"] = t.id if t else None
    if "skills" in d:
        skills, seen = [], set()
        for s in d.get("skills") or []:
            if not isinstance(s, dict) or not str(s.get("name") or "").strip():
                continue
            name = str(s["name"]).strip()[:60]
            if name.lower() in seen:
                continue
            seen.add(name.lower())
            lvl = s.get("level", 3)
            skills.append({**s, "name": name, "level": min(5, max(1, int(lvl) if str(lvl).lstrip("-").isdigit() else 3))})
        if len(skills) > 40:
            c.add("skills", None, "Add at most 40 skills.")
        out["skills"] = skills[:40]
    for k in ("salary_visible", "client_hidden"):
        if k in d:
            out[k] = bool(d[k])
    if "rubric" in d:
        out["rubric"] = d.get("rubric") or []
    return out, c


def _rounds_clean(rounds):
    out = []
    for r in rounds or []:
        if r.get("type") in ROUND_TYPES:
            out.append({"type": r["type"], "name": r.get("name") or ROUND_TYPES[r["type"]], "config": r.get("config") or {}})
    return out


@bp.post("/jobs")
@staff_required
def create_job():
    d = body()
    if not can(g.user, "jobs.create", team_id=d.get("team_id"), company_id=cid()):
        return deny("You can create jobs only in your own team." if can_any(g.user, "jobs.create", cid()) else
                    "You don't have permission to do that.")
    if d.get("template_id"):
        t = db.session.get(HiringTemplate, int(d["template_id"])) if str(d["template_id"]).isdigit() else None
        if t and t.company_id in (None, cid()):
            d.setdefault("rounds", t.rounds)
            d.setdefault("rubric", t.rubric)
    f, chk = _job_fields(d)
    if chk:
        return chk.response()
    rubric = d.get("rubric") or [{"name": s["name"], "weight": 2 if s.get("must") else 1} for s in f.get("skills", [])][:6]
    j = Job(company_id=cid(), team_id=f.get("team_id"), title=f["title"], description=f.get("description"),
            skills=f.get("skills", []), level=f.get("level"), location=f.get("location"), work_mode=f.get("work_mode") or "hybrid",
            salary_min=f.get("salary_min"), salary_max=f.get("salary_max"), salary_visible=f.get("salary_visible", False),
            visibility=f.get("visibility") or "private", rounds=_rounds_clean(d.get("rounds")) or
            [{"type": "mcq", "name": "Skill screen", "config": {}}, {"type": "ai_interview", "name": "AI interview with Hira", "config": {}}],
            rubric=rubric, plan={"summary": d.get("summary"), "questions": d.get("questions", [])},
            client_name=f.get("client_name"), client_hidden=f.get("client_hidden", False),
            hires_target=f["hires_target"], deadline=f.get("deadline"),
            credit_budget=f.get("credit_budget"), created_by=g.user.id)
    db.session.add(j)
    db.session.flush()
    db.session.add(JobAssignment(job_id=j.id, user_id=g.user.id, role="recruiter"))
    log("job.create", "job", j.id, title=j.title)
    db.session.commit()
    return ok(job_row(j))


@bp.get("/jobs/<int:jid>")
@staff_required
def job_detail(jid):
    j = get_job(jid)
    if not j:
        return deny("You can't see this job.")
    d = job_row(j)
    d["rounds_resolved"] = [{**r, "index": i, "resolved": round_config(j, i)} for i, r in enumerate(j.rounds or [])]
    d["assignments"] = [{**a.to_dict(), "name": (db.session.get(User, a.user_id) or User(name="?")).name}
                        for a in JobAssignment.query.filter_by(job_id=j.id).all()]
    stages = dict(db.session.query(Application.stage, func.count()).filter_by(job_id=j.id).group_by(Application.stage).all())
    d["funnel"] = stages
    d["invite_link"] = f"/signup?invite={j.invite_token}"
    d["can"] = {p: can(g.user, p, job=j) for p in ("jobs.create", "jobs.edit", "jobs.publish", "candidates.move", "interviews.run",
                                                  "verdict.final", "reports.share", "salary.view")}
    return ok(d)


@bp.patch("/jobs/<int:jid>")
@staff_required
def update_job(jid):
    j = get_job(jid, "jobs.edit")
    if not j:
        return deny()
    d = body()
    f, chk = _job_fields(d, j)
    if chk:
        return chk.response()
    if "team_id" in f and f["team_id"] != j.team_id and not can(g.user, "jobs.create", team_id=f["team_id"], company_id=cid()):
        return deny("You can move jobs only into your own team.")
    for k, v in f.items():
        setattr(j, k, v)
    if "rounds" in d:
        rounds = _rounds_clean(d["rounds"])
        if not rounds:
            return err("A job needs at least one round.", fields={"rounds": "Add at least one round."})
        j.rounds = rounds
    log("job.update", "job", jid, fields=list(d.keys()))
    db.session.commit()
    return ok(job_row(j))


@bp.post("/jobs/<int:jid>/publish")
@staff_required
def publish(jid):
    j = get_job(jid, "jobs.edit")
    if not j:
        return deny()
    if j.visibility == "public" and not can(g.user, "jobs.publish", job=j):
        return deny("You need the 'publish jobs publicly' permission. Make it private or ask a manager.")
    res = evaluate(cid(), "job.publish", {"visibility": j.visibility, "salary_max": j.salary_max, "team_id": j.team_id},
                   title=f"Publish {j.title} ({j.visibility})", ref_type="job", ref_id=j.id, requested_by=g.user.id)
    if res["blocked"]:
        return err(res["blocked"], 403)
    j.status = "pending_approval" if res["approval"] else "live"
    log("job.publish", "job", jid, status=j.status, policies=res["matched"])
    db.session.commit()
    return ok({**job_row(j), "approval": bool(res["approval"]), "policies": res["matched"]})


@bp.post("/jobs/<int:jid>/close")
@staff_required
def close(jid):
    j = get_job(jid, "jobs.edit")
    if not j:
        return deny()
    j.status = "closed"
    log("job.close", "job", jid)
    db.session.commit()
    return ok(job_row(j))


@bp.post("/jobs/<int:jid>/duplicate")
@staff_required
def duplicate(jid):
    j = get_job(jid, "jobs.create")
    if not j:
        return deny()
    n = Job(**{c.name: getattr(j, c.name) for c in Job.__table__.columns if c.name not in ("id", "created_at", "invite_token")})
    n.title = copy_name(j.title, lambda t: Job.query.filter_by(company_id=j.company_id, title=t).first() is not None)
    n.status = "draft"
    n.created_by = g.user.id
    n.invite_token = secrets.token_urlsafe(12)
    db.session.add(n)
    db.session.flush()
    db.session.add(JobAssignment(job_id=n.id, user_id=g.user.id, role="recruiter"))
    db.session.commit()
    return ok(job_row(n))


@bp.put("/jobs/<int:jid>/assignments")
@staff_required
def assignments(jid):
    j = get_job(jid, "jobs.edit")
    if not j:
        return deny()
    JobAssignment.query.filter_by(job_id=jid).delete()
    for a in body().get("assignments", []):
        db.session.add(JobAssignment(job_id=jid, user_id=int(a["user_id"]), role=a.get("role", "recruiter")))
        notify(int(a["user_id"]), "You were added to a job", f"{j.title} as {a.get('role', 'recruiter')}", f"/app/jobs/{jid}")
    log("job.assign", "job", jid, assignments=body().get("assignments"))
    db.session.commit()
    return job_detail(jid)


# ---------------------------------------------------------------- applications

def app_row(a, job=None):
    u = db.session.get(User, a.candidate_id)
    p = CandidateProfile.query.filter_by(user_id=a.candidate_id).first()
    d = a.to_dict()
    d["candidate"] = {"id": u.id, "name": u.name, "email": u.email, "headline": p.headline if p else "",
                      "location": p.location if p else "", "experience_years": p.experience_years if p else None,
                      "skills": (p.skills or [])[:8] if p else []}
    last = RoundAttempt.query.filter_by(application_id=a.id).order_by(RoundAttempt.round_index.desc()).first()
    job = job or db.session.get(Job, a.job_id)
    d["last_round"] = {"id": last.id, "type": last.round_type, "status": last.status, "score": last.score,
                       "warnings": last.warnings or 0, "scale": report_scale(job)} if last else None
    d["round_name"] = (job.rounds[a.current_round].get("name") if job and 0 <= a.current_round < len(job.rounds or []) else None)
    d["job_title"] = job.title if job else ""
    return d


def _app_query(job_id):
    q = Application.query.filter_by(job_id=job_id)
    return q.join(User, User.id == Application.candidate_id)


@bp.get("/jobs/<int:jid>/applications")
@staff_required
def applications(jid):
    j = get_job(jid)
    if not j:
        return deny()
    return table(_app_query(jid), [User.name, User.email],
                 {"name": User.name, "match": Application.match_score, "applied": Application.created_at,
                  "stage": Application.stage, "updated": Application.updated_at},
                 "match", lambda a: app_row(a, j),
                 {"stage": lambda q, v: q.filter(Application.stage.in_(v.split(","))),
                  "min_match": lambda q, v: q.filter(Application.match_score >= int(v)),
                  "max_match": lambda q, v: q.filter(Application.match_score <= int(v)),
                  "source": lambda q, v: q.filter(Application.source == v)})


@bp.post("/jobs/<int:jid>/ask")
@staff_required
def ask_hira(jid):
    """'Show strong Python people above 70 not yet invited' -> filter chips the table applies."""
    if not get_job(jid):
        return deny()
    fields = {"stage": ["applied", "shortlisted", "in_round", "awaiting_review", "decision", "offer", "hired", "rejected", "on_hold"],
              "match_score": "0-100", "q": "free text search on name/email/skills"}
    return ok(ai.nl_filter(body().get("text", ""), fields, company_id=cid()))


def _get_or_create_candidate(name, email, resume_text=""):
    email = (email or "").strip().lower()
    u = User.query.filter_by(email=email).first()
    if u and u.kind != "candidate":
        return None
    if not u:
        u = User(email=email, name=name or email.split("@")[0], kind="candidate",
                 password_hash=hash_password(secrets.token_urlsafe(12)), must_change_password=True)
        db.session.add(u)
        db.session.flush()
    p = CandidateProfile.query.filter_by(user_id=u.id).first()
    if not p:
        p = CandidateProfile(user_id=u.id, resume_text=resume_text,
                             skills=[{"name": s, "level": 2, "verified": False, "source": "resume"} for s in ai.extract_skills(resume_text)])
        db.session.add(p)
    elif resume_text and not p.resume_text:
        p.resume_text = resume_text
    return u


@bp.post("/jobs/<int:jid>/applications")
@staff_required
def add_candidates(jid):
    """Add one candidate or a batch: {candidates: [{name, email, resume_text}]}."""
    j = get_job(jid, "candidates.move")
    if not j:
        return deny()
    items = body().get("candidates") or [body()]
    added, skipped = [], []
    for c in items[:200]:
        email, bad = V.email(c.get("email"))
        if bad:
            skipped.append(c.get("email") or "")
            continue
        c = {**c, "email": email}
        u = _get_or_create_candidate(c.get("name"), c["email"], c.get("resume_text") or "")
        if not u or Application.query.filter_by(job_id=jid, candidate_id=u.id).first():
            skipped.append(c["email"])
            continue
        p = CandidateProfile.query.filter_by(user_id=u.id).first()
        score, got, missing = skill_match(j, p.skills if p else [])
        a = Application(job_id=jid, candidate_id=u.id, source="bulk" if len(items) > 1 else "invited", owner_id=g.user.id,
                        match_score=score, match_reasons={"matched": got, "missing": missing})
        db.session.add(a)
        added.append(c["email"])
    log("application.add", "job", jid, added=len(added))
    db.session.commit()
    return ok({"added": added, "skipped": skipped})


@bp.post("/jobs/<int:jid>/shortlist")
@staff_required
def shortlist(jid):
    """Hira scores every new application against the JD and explains why."""
    j = get_job(jid, "candidates.move")
    if not j:
        return deny()
    apps = Application.query.filter_by(job_id=jid, stage="applied").all()
    threshold = int(body().get("threshold") or 0)
    out = []
    for a in apps[:100]:
        p = CandidateProfile.query.filter_by(user_id=a.candidate_id).first()
        res = ai.score_resume(j, p.resume_text if p else "", company_id=cid())
        a.match_score = int(res.get("score") or 0)
        a.match_reasons = {"reasons": res.get("reasons", []), "matched": res.get("matched", []), "missing": res.get("missing", [])}
        if threshold and a.match_score >= threshold:
            a.stage = "shortlisted"
        out.append({"id": a.id, "score": a.match_score, "reasons": a.match_reasons["reasons"]})
    log("hira.shortlist", "job", jid, scored=len(out), threshold=threshold)
    db.session.commit()
    return ok({"scored": len(out), "items": out})


@bp.post("/jobs/<int:jid>/bulk")
@staff_required
def bulk(jid):
    j = get_job(jid, "candidates.move")
    if not j:
        return deny()
    d = body()
    ids = [int(i) for i in d.get("ids", [])]
    action = d.get("action")
    done, failed = 0, []
    for a in Application.query.filter(Application.job_id == jid, Application.id.in_(ids or [0])).all():
        if action == "shortlist":
            a.stage = "shortlisted"
        elif action == "hold":
            a.stage = "on_hold"
        elif action == "reject":
            r = _reject(a, j, d.get("note"))
            if r:
                failed.append({"id": a.id, "error": r})
                continue
        elif action == "invite":
            r = _invite(a, j, d.get("round_index"), d.get("interviewer_id"), parse_dt(d.get("scheduled_at")))
            if isinstance(r, str):
                failed.append({"id": a.id, "error": r})
                continue
        else:
            return err("Unknown action.")
        done += 1
    log(f"application.bulk.{action}", "job", jid, n=done)
    db.session.commit()
    return ok({"done": done, "failed": failed})


def _invite(a, job, idx=None, interviewer_id=None, scheduled_at=None):
    if not can(g.user, "interviews.run", job=job):
        return "You can't invite to rounds on this job."
    idx = a.current_round + 1 if idx is None else int(idx)
    if idx >= len(job.rounds or []):
        return "There are no more rounds."
    if idx < 0:
        return "Choose a round."
    rtype = job.rounds[idx]["type"]
    if a.stage in ("rejected", "withdrawn", "hired"):
        return f"This candidate is {a.stage}; they can't be invited."
    if rtype in ("f2f_isha", "f2f_human") and not interviewer_id:
        return "Pick an interviewer for a face-to-face round."
    if interviewer_id:
        iv = db.session.get(User, int(interviewer_id)) if str(interviewer_id).isdigit() else None
        if not iv or iv.kind != "staff" or iv.company_id != job.company_id or not iv.active:
            return "Choose an interviewer from your company."
    if scheduled_at and scheduled_at < datetime.utcnow() - timedelta(minutes=5):
        return "The interview time is in the past. Pick a time in the future."
    existing = active_attempt(a.id, idx)
    if existing:
        if existing.status in ("in_progress", "paused"):
            return "This candidate is already taking this round."
        return reschedule(existing, job, interviewer_id, scheduled_at)  # no second invite and no second charge
    if not spend(job.company_id, CREDIT_COST.get(rtype, 0), f"{rtype} for application {a.id}"):
        return "Not enough credits. Ask your admin to top up."
    return invite_to_round(a, idx, g.user.id, int(interviewer_id) if interviewer_id else None, scheduled_at)


def _reject(a, job, note=None):
    last = RoundAttempt.query.filter_by(application_id=a.id).order_by(RoundAttempt.round_index.desc()).first()
    res = evaluate(job.company_id, "candidate.reject", {"stage": a.stage, "round_type": last.round_type if last else None},
                   title=f"Rejected for {job.title}", ref_type="application", ref_id=a.id, requested_by=g.user.id)
    if res["blocked"]:
        return res["blocked"]
    a.stage = "rejected"
    a.verdict = "reject"
    a.verdict_by = g.user.id
    a.verdict_note = note
    notify(a.candidate_id, f"Update on {job.title}", "Thank you for your time. The team has decided not to move forward.",
           "/me/applications")
    return None


@bp.get("/applications/<int:aid>")
@staff_required
def application(aid):
    a = db.session.get(Application, aid)
    j = get_job(a.job_id) if a else None
    if not j:
        return deny()
    d = app_row(a, j)
    p = CandidateProfile.query.filter_by(user_id=a.candidate_id).first()
    d["profile"] = p.to_dict() if p else {}
    attempts = []
    for att in RoundAttempt.query.filter_by(application_id=aid).order_by(RoundAttempt.round_index).all():
        r = Report.query.filter_by(attempt_id=att.id).first()
        iv = db.session.get(User, att.interviewer_id) if att.interviewer_id else None
        attempts.append({**att.to_dict(exclude=("result", "brief")), "name": round_name(att, j), "interviewer": iv.name if iv else None,
                         "report": {"id": r.id, "status": r.status, "overall": r.overall, "recommendation": r.recommendation,
                                    "verdict": r.verdict} if r else None})
    d["attempts"] = attempts
    d["scale"] = report_scale(db.session.get(Job, a.job_id))
    d["rounds"] = j.rounds
    d["reinterviews"] = sum(1 for n in (a.notes or []) if n.get("kind") == "reinterview")
    d["can"] = {p_: can(g.user, p_, job=j) for p_ in ("candidates.move", "interviews.run", "verdict.recommend", "verdict.final")}
    others = Application.query.filter(Application.candidate_id == a.candidate_id, Application.id != aid).all()
    d["other_applications"] = [{"id": o.id, "job_id": o.job_id, "stage": o.stage, "job": db.session.get(Job, o.job_id).title}
                               for o in others if db.session.get(Job, o.job_id).company_id == cid()]
    return ok(d)


@bp.post("/applications/<int:aid>/invite")
@staff_required
def invite(aid):
    a = db.session.get(Application, aid)
    j = get_job(a.job_id) if a else None
    if not j:
        return deny()
    d = body()
    r = _invite(a, j, d.get("round_index"), d.get("interviewer_id"), parse_dt(d.get("scheduled_at")))
    if isinstance(r, str):
        return err(r)
    db.session.commit()
    return ok({"attempt_id": r.id if r else None, "stage": a.stage})


@bp.post("/applications/<int:aid>/notes")
@staff_required
def add_note(aid):
    a = db.session.get(Application, aid)
    if not a or not get_job(a.job_id):
        return deny()
    notes = list(a.notes or [])
    notes.append({"by": g.user.name, "by_id": g.user.id, "text": body().get("text", ""), "at": datetime.utcnow().isoformat() + "Z",
                  "kind": "note"})
    a.notes = notes
    db.session.commit()
    return ok(notes)


@bp.post("/applications/<int:aid>/verdict")
@staff_required
def verdict(aid):
    """proceed | hold | reject (move permission) and offer | hired (final decision permission)."""
    a = db.session.get(Application, aid)
    j = get_job(a.job_id) if a else None
    if not j:
        return deny()
    d = body()
    v = d.get("verdict")
    final = v in ("offer", "hired")
    if final and not can(g.user, "verdict.final", job=j):
        return deny("Only someone with final-decision permission can make an offer or hire.")
    if not final and not can(g.user, "candidates.move", job=j):
        return deny()
    sod, _, _ = resolve("policy.separation_of_duties", company_id=j.company_id, team_id=j.team_id, job_id=j.id)
    if sod and (final or v == "reject"):
        interviewed = RoundAttempt.query.filter_by(application_id=aid, interviewer_id=g.user.id).first()
        if interviewed:
            return err("Separation of duties: you interviewed this candidate, so someone else must give the final verdict.", 403)
    if v == "proceed":
        r = _invite(a, j, None, d.get("interviewer_id"), parse_dt(d.get("scheduled_at")))
        if isinstance(r, str):
            return err(r)
        if r is None:
            a.stage = "decision"
    elif v == "hold":
        a.stage = "on_hold"
    elif v == "reject":
        r = _reject(a, j, d.get("note"))
        if r:
            return err(r, 403)
    elif v == "offer":
        salary = d.get("salary")
        over = bool(salary and j.salary_max and float(salary) > j.salary_max)
        res = evaluate(j.company_id, "offer.create", {"salary": salary, "salary_max": j.salary_max, "over_band": over},
                       title=f"Offer for {db.session.get(User, a.candidate_id).name}, {j.title}" + (f" at {salary}" if salary else ""),
                       ref_type="application", ref_id=a.id, requested_by=g.user.id, payload={"salary": salary})
        if res["blocked"]:
            return err(res["blocked"], 403)
        if res["approval"]:
            a.stage = "decision"
            a.verdict = "offer_pending"
        else:
            a.stage = "offer"
            a.verdict = "offer"
            notify(a.candidate_id, f"Good news about {j.title}", "The team would like to make you an offer.", "/me/applications")
    elif v == "hired":
        a.stage = "hired"
        a.verdict = "hired"
    else:
        return err("Unknown verdict.")
    if v not in ("offer",):
        a.verdict = a.verdict if v == "proceed" else v
    a.verdict_by = g.user.id
    a.verdict_note = d.get("note")
    log("application.verdict", "application", aid, company_id=j.company_id, verdict=v, note=d.get("note"))
    db.session.commit()
    return ok(app_row(a, j))


@bp.post("/applications/<int:aid>/reinterview")
@staff_required
def reinterview(aid):
    a = db.session.get(Application, aid)
    j = get_job(a.job_id, "interviews.run") if a else None
    if not j:
        return deny()
    prev = sum(1 for n in (a.notes or []) if n.get("kind") == "reinterview")
    mx, _, _ = resolve("policy.reinterview_max", company_id=j.company_id, team_id=j.team_id, job_id=j.id)
    if prev >= mx:
        return err(f"Re-interviews are limited to {mx} per candidate per job.", 403)
    res = evaluate(j.company_id, "reinterview.request", {"previous_reinterviews": prev},
                   title="Re-interview", ref_type="application", ref_id=aid, requested_by=g.user.id)
    if res["blocked"]:
        return err(res["blocked"], 403)
    d = body()
    try:
        idx = int(d.get("round_index", max(0, a.current_round)))
        j.rounds[idx]
    except (TypeError, ValueError, IndexError):
        return err("Choose a round.")
    if idx < 0:
        return err("Choose a round.")
    if active_attempt(a.id, idx):
        return err("This candidate already has an open invite for this round. Reschedule it instead.", 409)
    if not spend(j.company_id, CREDIT_COST.get(j.rounds[idx]["type"], 0), "reinterview"):
        return err("Not enough credits.")
    att = invite_to_round(a, idx, g.user.id, d.get("interviewer_id"), parse_dt(d.get("scheduled_at")))
    notes = list(a.notes or [])
    notes.append({"kind": "reinterview", "by": g.user.name, "text": d.get("reason") or "Re-interview",
                  "at": datetime.utcnow().isoformat() + "Z"})
    a.notes = notes
    log("application.reinterview", "application", aid, company_id=j.company_id, reason=d.get("reason"))
    db.session.commit()
    return ok({"attempt_id": att.id if att else None})


@bp.get("/jobs/<int:jid>/compare")
@staff_required
def compare(jid):
    j = get_job(jid)
    if not j:
        return deny()
    ids = [int(i) for i in (request.args.get("ids") or "").split(",") if i]
    out = []
    for a in Application.query.filter(Application.job_id == jid, Application.id.in_(ids or [0])).all():
        row = app_row(a, j)
        comps = {}
        for att in RoundAttempt.query.filter_by(application_id=a.id).all():
            r = Report.query.filter_by(attempt_id=att.id).first()
            for c in ((r.sections or {}).get("competencies") or []) if r else []:
                comps.setdefault(c["name"], []).append(c.get("score") or 0)
        row["competencies"] = {k: round(sum(v) / len(v), 1) for k, v in comps.items()}
        out.append(row)
    return ok(out)


@bp.get("/applications/<int:aid>/packet")
@staff_required
def packet(aid):
    """Hiring packet: everything a decision maker needs on one page."""
    a = db.session.get(Application, aid)
    j = get_job(a.job_id, "reports.view") if a else None
    if not j:
        return deny()
    reports = []
    for att in RoundAttempt.query.filter_by(application_id=aid).order_by(RoundAttempt.round_index).all():
        r = Report.query.filter_by(attempt_id=att.id).first()
        if r:
            reports.append({"round": round_name(att, j), "type": att.round_type, "overall": r.overall,
                            "recommendation": r.recommendation, "verdict": r.verdict, "summary": (r.sections or {}).get("summary"),
                            "strengths": (r.sections or {}).get("strengths"), "gaps": (r.sections or {}).get("gaps"),
                            "warnings": att.warnings})
    return ok({"application": app_row(a, j), "job": {"title": j.title, "level": j.level}, "reports": reports,
               "notes": a.notes or []})


@bp.get("/talent-pool")
@staff_required
def talent_pool():
    """Everyone who has applied to this company, searchable and re-usable for new jobs."""
    if not can_any(g.user, "candidates.view", cid()):
        return deny()
    job_ids = [j.id for j in Job.query.filter_by(company_id=cid()).all()] or [0]
    sub = db.session.query(Application.candidate_id).filter(Application.job_id.in_(job_ids)).distinct()
    added = db.session.query(CandidateProfile.user_id).filter(CandidateProfile.source_company_id == cid())
    q = User.query.filter(User.id.in_(sub) | User.id.in_(added))

    def ser(u):
        p = CandidateProfile.query.filter_by(user_id=u.id).first()
        apps = Application.query.filter(Application.candidate_id == u.id, Application.job_id.in_(job_ids)).all()
        from routes.people import link_state
        return {"id": u.id, "name": u.name, "email": u.email, "headline": p.headline if p else "", "account": link_state(u),
                "skills": (p.skills or [])[:8] if p else [], "applications": len(apps),
                "best_stage": max((x.stage for x in apps), key=lambda s: ["rejected", "applied", "shortlisted", "in_round",
                                                                           "awaiting_review", "on_hold", "decision", "offer", "hired"].index(s) if s in
                                  ["rejected", "applied", "shortlisted", "in_round", "awaiting_review", "on_hold", "decision", "offer", "hired"] else 0)
                if apps else ""}
    return table(q, [User.name, User.email], {"name": User.name, "created": User.created_at}, "created", ser)


@bp.post("/talent-pool/add-to-job")
@staff_required
def pool_to_job():
    d = body()
    j = get_job(int(d["job_id"]) if str(d.get("job_id") or "").isdigit() else 0, "candidates.move")
    if not j:
        return deny()
    if j.status != "live":
        return err("You can add people only to a live job.")
    job_ids = [x.id for x in Job.query.filter_by(company_id=cid()).all()] or [0]
    in_pool = {r[0] for r in db.session.query(Application.candidate_id).filter(Application.job_id.in_(job_ids)).all()}
    in_pool |= {r[0] for r in db.session.query(CandidateProfile.user_id).filter(CandidateProfile.source_company_id == cid()).all()}
    n = skipped = 0
    for uid in d.get("user_ids", [])[:500]:
        if not str(uid).isdigit() or int(uid) not in in_pool:
            continue
        if Application.query.filter_by(job_id=j.id, candidate_id=int(uid)).first():
            skipped += 1
            continue
        p = CandidateProfile.query.filter_by(user_id=int(uid)).first()
        score, got, missing = skill_match(j, p.skills if p else [])
        db.session.add(Application(job_id=j.id, candidate_id=int(uid), source="pool", owner_id=g.user.id, match_score=score,
                                   match_reasons={"matched": got, "missing": missing}))
        n += 1
    log("application.add", "job", j.id, added=n, source="pool")
    db.session.commit()
    return ok({"added": n, "skipped": skipped})


# ---------------------------------------------------------------- my interviews (interviewer)

@bp.get("/interviews")
@staff_required
def my_interviews():
    q = RoundAttempt.query.filter(RoundAttempt.interviewer_id == g.user.id)

    def ser(att):
        a = db.session.get(Application, att.application_id)
        j = db.session.get(Job, a.job_id) if a else None
        u = db.session.get(User, a.candidate_id) if a else None
        return {**att.to_dict(exclude=("result", "brief", "config")), "job": j.title if j else "", "candidate": u.name if u else "",
                "name": round_name(att, j), "report": bool(Report.query.filter_by(attempt_id=att.id).first())}
    return table(q, [], {"scheduled": RoundAttempt.scheduled_at, "created": RoundAttempt.created_at, "status": RoundAttempt.status},
                 "scheduled", ser, {"status": lambda q, v: q.filter(RoundAttempt.status.in_(v.split(",")))})


# ---------------------------------------------------------------- saved views (every table)

@bp.get("/views/<table_name>")
@staff_required
def views(table_name):
    q = SavedView.query.filter_by(table=table_name).filter((SavedView.user_id == g.user.id) | (SavedView.shared_team_id.isnot(None)))
    return ok([v.to_dict() for v in q.all()])


@bp.post("/views/<table_name>")
@staff_required
def save_view(table_name):
    d = body()
    v = SavedView(user_id=g.user.id, table=table_name, name=d.get("name") or "My view", params=d.get("params", {}),
                  shared_team_id=d.get("shared_team_id"))
    db.session.add(v)
    db.session.commit()
    return ok(v.to_dict())


@bp.delete("/views/<int:vid>")
@staff_required
def delete_view(vid):
    SavedView.query.filter_by(id=vid, user_id=g.user.id).delete()
    db.session.commit()
    return ok()
