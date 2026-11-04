"""No sign-in needed: landing data, public job board, shared reports and credential verification."""
from datetime import datetime

from flask import Blueprint

from extensions import db
from models import Company, Credential, Job, Report, RoundAttempt, User
from routes.utils import err, ok

bp = Blueprint("public", __name__, url_prefix="/api/public")


@bp.get("/plans")
def plans():
    from routes.platform import PLANS
    return ok(PLANS)


@bp.get("/stats")
def stats():
    return ok({"companies": Company.query.count(), "jobs": Job.query.filter_by(status="live").count(),
               "credentials": Credential.query.filter_by(revoked=False).count(),
               "interviews": RoundAttempt.query.filter(RoundAttempt.completed_at.isnot(None)).count()})


def _job(j):
    c = db.session.get(Company, j.company_id)
    return {"id": j.id, "title": j.title, "company": None if j.client_hidden else c.name, "location": j.location,
            "work_mode": j.work_mode, "level": j.level, "skills": j.skills, "description": j.description,
            "salary": [j.salary_min, j.salary_max] if j.salary_visible else None, "posted": j.created_at.isoformat() + "Z",
            "rounds": [r.get("name") for r in j.rounds or []]}


@bp.get("/jobs")
def jobs():
    return ok([_job(j) for j in Job.query.filter_by(status="live", visibility="public").order_by(Job.created_at.desc()).limit(100)])


@bp.get("/jobs/invite/<token>")
def invite(token):
    j = Job.query.filter_by(invite_token=token, status="live").first()
    if not j:
        return err("This invite link has expired or the job is closed.", 404)
    return ok(_job(j))


@bp.get("/verify/<code>")
def verify(code):
    from services import throttle
    key = f"invite:verify:{throttle.client_ip()}"
    wait = throttle.locked(key)
    if wait:
        return err(throttle.message(wait), 429)
    c = Credential.query.filter_by(code=code.strip().upper()[:40]).first()
    if not c:
        throttle.fail(key)  # slows down anyone guessing IDs
        return err("No credential with that ID.", 404)
    u = db.session.get(User, c.user_id)
    state = "revoked" if c.revoked else ("expired" if c.expires_at and c.expires_at < datetime.utcnow() else "valid")
    return ok({"code": c.code, "state": state, "holder": u.name if u else "", "title": c.title, "kind": c.kind,
               "skill": c.skill, "level": c.level, "grade": c.grade, "issuer": c.issuer,
               "issued": c.created_at.isoformat() + "Z", "expires": c.expires_at.isoformat() + "Z" if c.expires_at else None,
               "revoke_reason": c.revoke_reason if c.revoked else None})


@bp.post("/hiring-plan")
def hiring_plan():
    """Landing page "Hira's hiring plan": drafts skills, rounds and first questions for ANY job title.
    Public, so it is rate limited per visitor (10 plans per 30 minutes) and capped in size."""
    from routes.utils import body
    from services import ai, throttle
    key = f"signup:plan:{throttle.client_ip()}"
    wait = throttle.locked(key)
    if wait:
        return err(throttle.message(wait), 429)
    title = " ".join(str(body().get("title") or "").split())[:120]
    if len(title) < 2:
        return err("Type a job title, for example “Cloud Architect”.")
    throttle.fail(key)
    plan = ai.draft_job(title)
    skills = [s for s in (plan.get("skills") or []) if isinstance(s, dict) and s.get("name")][:6]
    rounds = [r for r in (plan.get("rounds") or []) if isinstance(r, dict) and r.get("type")][:4]
    return ok({"title": plan.get("title") or title.title(), "level": plan.get("level") or "Mid",
               "skills": [{"name": str(s["name"])[:40], "level": int(s.get("level") or 3) if str(s.get("level") or 3).isdigit() else 3, "must": bool(s.get("must"))} for s in skills],
               "rounds": [{"type": r["type"], "name": str(r.get("name") or r["type"])[:60]} for r in rounds],
               "questions": [str(q)[:220] for q in (plan.get("questions") or [])][:3], "ai": ai.configured()})


@bp.get("/shared/<token>")
def shared(token):
    from routes.reports import view
    from services.pipeline import context
    r = Report.query.filter_by(share_token=token).first()
    if not r or (r.share_expires_at and r.share_expires_at < datetime.utcnow()):
        return err("This link has expired.", 404)
    att = db.session.get(RoundAttempt, r.attempt_id)
    _, job, _, _ = context(att)
    return ok(view(r, att, job, r.share_audience or "client"))
