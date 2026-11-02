"""Hiring teams add candidates and send them a personal portal link.

The link opens the candidate's portal straight away (no password). There they set their own password; from then on
the link stops working and they sign in normally. Links expire after invite.link_days (default 7).
"""
import hashlib
import secrets
from datetime import datetime, timedelta

from flask import Blueprint, g, request

from extensions import db
from models import Application, CandidateProfile, Company, InviteLink, Job, User
from routes.utils import body, err, ok, table
from services import ai
from services.audit import log, notify
from services.perms import can, can_any, deny, hash_password, make_token, staff_required
from services.pipeline import skill_match
from services.settings import resolve

bp = Blueprint("people", __name__, url_prefix="/api/candidates")


def cid():
    if g.user.is_superadmin and request.headers.get("X-Company-Id"):
        return int(request.headers["X-Company-Id"])
    return g.user.company_id


def hash_token(t):
    return hashlib.sha256(t.encode()).hexdigest()


def new_link(user, company_id, job_id=None, purpose="candidate"):
    """Revokes earlier unused links for this person and returns a fresh token (only ever shown once)."""
    InviteLink.query.filter_by(user_id=user.id, used_at=None, revoked=False).update({"revoked": True})
    days = int(resolve("invite.link_days", company_id=company_id)[0] or 7)
    token = secrets.token_urlsafe(24)
    link = InviteLink(token_hash=hash_token(token), user_id=user.id, company_id=company_id, job_id=job_id, purpose=purpose,
                      created_by=g.user.id if getattr(g, "user", None) else None, expires_at=datetime.utcnow() + timedelta(days=days))
    db.session.add(link)
    return token, link


def link_state(user):
    """invited | opened | active | expired for the candidate's account."""
    if user.password_hash and not user.must_change_password:
        return "active"
    last = InviteLink.query.filter_by(user_id=user.id).order_by(InviteLink.id.desc()).first()
    if not last or last.revoked:
        return "no_link"
    if last.expires_at < datetime.utcnow():
        return "expired"
    return "opened" if last.opened_at else "invited"


def _belongs(user):
    """The candidate is in this company's world: added by it or applied to one of its jobs."""
    p = CandidateProfile.query.filter_by(user_id=user.id).first()
    if p and p.source_company_id == cid():
        return True
    job_ids = [j.id for j in Job.query.filter_by(company_id=cid()).all()] or [0]
    return bool(Application.query.filter(Application.candidate_id == user.id, Application.job_id.in_(job_ids)).first())


def _add_one(c, job):
    email = (c.get("email") or "").strip().lower()
    name = (c.get("name") or "").strip()
    if not email or "@" not in email:
        return {"email": email, "error": "A valid email is needed."}
    u = User.query.filter_by(email=email).first()
    if u and u.kind != "candidate":
        return {"email": email, "error": "This email belongs to a hiring-team member."}
    existing = bool(u)
    if not u:
        u = User(email=email, name=name or email.split("@")[0], kind="candidate", password_hash=hash_password(secrets.token_urlsafe(16)),
                 must_change_password=True)
        db.session.add(u)
        db.session.flush()
    resume = c.get("resume_text") or ""
    p = CandidateProfile.query.filter_by(user_id=u.id).first()
    skills = [{"name": s.strip(), "level": 2, "verified": False, "source": "added"} for s in (c.get("skills") or []) if s and s.strip()]
    found = [{"name": s, "level": 2, "verified": False, "source": "resume"} for s in ai.extract_skills(resume)]
    if not p:
        merged, seen = [], set()
        for s in skills + found:
            if s["name"].lower() not in seen:
                seen.add(s["name"].lower())
                merged.append(s)
        p = CandidateProfile(user_id=u.id, headline=c.get("headline"), phone=c.get("phone"), location=c.get("location"),
                             experience_years=c.get("experience_years") or None, resume_text=resume, skills=merged,
                             source_company_id=cid(), added_by=g.user.id)
        db.session.add(p)
    else:
        if not p.source_company_id:
            p.source_company_id = cid()
        for k in ("headline", "phone", "location"):
            if c.get(k) and not getattr(p, k):
                setattr(p, k, c[k])
        if resume and not p.resume_text:
            p.resume_text = resume
    app_id = None
    if job:
        a = Application.query.filter_by(job_id=job.id, candidate_id=u.id).first()
        if not a:
            score, got, missing = skill_match(job, p.skills or [])
            a = Application(job_id=job.id, candidate_id=u.id, source="added", owner_id=g.user.id, match_score=score,
                            match_reasons={"matched": got, "missing": missing})
            db.session.add(a)
            db.session.flush()
        app_id = a.id
    out = {"user_id": u.id, "name": u.name, "email": u.email, "existing": existing, "application_id": app_id, "state": link_state(u)}
    if out["state"] != "active":
        token, link = new_link(u, cid(), job.id if job else None)
        out.update({"link": f"/welcome/{token}", "expires_at": link.expires_at.isoformat() + "Z", "state": "invited"})
    else:
        out["note"] = "Already has an account. They sign in with their own password."
        if job:
            notify(u.id, f"You've been added to {job.title}", "The hiring team added you to this job.", "/me/applications")
    log("candidate.add", "user", u.id, company_id=cid(), job_id=job.id if job else None, existing=existing)
    return out


@bp.post("")
@staff_required
def add():
    """Add one candidate or many ({candidates: [...]}) and get a personal portal link for each."""
    d = body()
    job = None
    if d.get("job_id"):
        job = Job.query.filter_by(id=int(d["job_id"]), company_id=cid()).first()
        if not job:
            return err("Job not found.", 404)
        if not can(g.user, "candidates.add", job=job):
            return deny("You can't add candidates to this job.")
    elif not can_any(g.user, "candidates.add", cid()):
        return deny()
    items = d.get("candidates") or [d]
    results = [_add_one(c, job) for c in items[:200]]
    db.session.commit()
    return ok({"results": results, "added": sum(1 for r in results if "error" not in r)})


@bp.get("")
@staff_required
def list_added():
    """Candidates your company added, with the state of their portal link."""
    if not can_any(g.user, "candidates.add", cid()) and not can_any(g.user, "candidates.view", cid()):
        return deny()
    sub = db.session.query(CandidateProfile.user_id).filter(CandidateProfile.source_company_id == cid())
    q = User.query.filter(User.id.in_(sub))
    if not can_any(g.user, "candidates.view", cid()):
        q = q.filter(User.id.in_(db.session.query(CandidateProfile.user_id).filter(CandidateProfile.added_by == g.user.id)))

    def ser(u):
        p = CandidateProfile.query.filter_by(user_id=u.id).first()
        by = db.session.get(User, p.added_by) if p and p.added_by else None
        jobs = [db.session.get(Job, a.job_id) for a in Application.query.filter_by(candidate_id=u.id).all()]
        return {"id": u.id, "name": u.name, "email": u.email, "phone": p.phone if p else None, "headline": p.headline if p else "",
                "added_by": by.name if by else "", "added_at": u.created_at.isoformat() + "Z", "state": link_state(u),
                "jobs": [j.title for j in jobs if j and j.company_id == cid()], "last_login_at": u.last_login_at.isoformat() + "Z" if u.last_login_at else None}
    return table(q, [User.name, User.email], {"name": User.name, "added": User.created_at}, "added", ser)


@bp.post("/<int:uid>/link")
@staff_required
def regenerate(uid):
    """A fresh link (the old one stops working). Not possible once the candidate has set their own password."""
    if not can_any(g.user, "candidates.add", cid()):
        return deny()
    u = db.session.get(User, uid)
    if not u or u.kind != "candidate" or not _belongs(u):
        return err("Not found", 404)
    if link_state(u) == "active":
        return err("This candidate already set a password. They sign in at the login page.", 409)
    token, link = new_link(u, cid(), body().get("job_id"))
    log("candidate.link", "user", uid, company_id=cid())
    db.session.commit()
    return ok({"link": f"/welcome/{token}", "expires_at": link.expires_at.isoformat() + "Z"})


# ---------------------------------------------------------------- public side of the link (no sign-in)

pub = Blueprint("invite", __name__, url_prefix="/api/auth/invite")


def _find(token):
    link = InviteLink.query.filter_by(token_hash=hash_token(token or "")).first()
    if not link or link.revoked:
        return None, "This link isn't valid any more. Ask the recruiter for a new one."
    if link.used_at:
        return None, "You've already set your password. Sign in with your email and password."
    if link.expires_at < datetime.utcnow():
        return None, "This link has expired. Ask the recruiter for a new one."
    return link, None


@pub.get("/<token>")
def peek(token):
    link, problem = _find(token)
    if not link:
        return err(problem, 410)
    u = db.session.get(User, link.user_id)
    c = db.session.get(Company, link.company_id) if link.company_id else None
    j = db.session.get(Job, link.job_id) if link.job_id else None
    by = db.session.get(User, link.created_by) if link.created_by else None
    return ok({"name": u.name, "email": u.email, "company": c.name if c and not (j and j.client_hidden) else None,
               "job": j.title if j else None, "added_by": by.name if by else None, "expires_at": link.expires_at.isoformat() + "Z",
               "require_password": bool(resolve("invite.require_password", company_id=link.company_id)[0])})


@pub.post("/<token>/open")
def open_link(token):
    """Signs the candidate straight into their portal. The session is marked as coming from the link."""
    from routes.auth import me_payload
    link, problem = _find(token)
    if not link:
        return err(problem, 410)
    u = db.session.get(User, link.user_id)
    if not u.active:
        return err("This account is switched off.", 403)
    link.opened_at = link.opened_at or datetime.utcnow()
    u.last_login_at = datetime.utcnow()
    log("candidate.link.open", "user", u.id, company_id=link.company_id)
    db.session.commit()
    return ok({"token": make_token(u, via="invite", lid=link.id), **me_payload(u),
               "require_password": bool(resolve("invite.require_password", company_id=link.company_id)[0])})
