from datetime import datetime

from flask import Blueprint, g

from extensions import db
from models import Application, CandidateProfile, Company, Job, User
from routes.utils import body, err, ok
from services import ai
from services.audit import log
from services.perms import auth_required, check_password, effective, hash_password, make_token, roles_of
from services.pipeline import skill_match

bp = Blueprint("auth", __name__, url_prefix="/api/auth")


def me_payload(u):
    company = db.session.get(Company, u.company_id) if u.company_id else None
    perms = sorted(effective(u).keys()) if u.kind == "staff" or u.is_superadmin else []
    return {"user": u.public(), "roles": roles_of(u), "permissions": perms,
            "company": company.to_dict() if company else None,
            "must_change_password": u.must_change_password,
            "home": "/admin" if u.is_superadmin else ("/me" if u.kind == "candidate" else "/app/today")}


@bp.post("/login")
def login():
    d = body()
    u = User.query.filter_by(email=(d.get("email") or "").strip().lower()).first()
    if not u or not check_password(d.get("password", ""), u.password_hash):
        return err("That email and password don't match.", 401)
    if not u.active:
        return err("This account is switched off. Contact your admin.", 403)
    u.last_login_at = datetime.utcnow()
    db.session.commit()
    return ok({"token": make_token(u), **me_payload(u)})


@bp.post("/signup")
def signup():
    """Candidate self sign-up, optionally from a private job invite link."""
    d = body()
    email = (d.get("email") or "").strip().lower()
    if not email or "@" not in email or len(d.get("password") or "") < 8:
        return err("Enter a valid email and a password of at least 8 characters.")
    if User.query.filter_by(email=email).first():
        return err("An account with this email already exists. Sign in instead.")
    u = User(email=email, name=d.get("name") or email.split("@")[0], kind="candidate",
             password_hash=hash_password(d["password"]))
    db.session.add(u)
    db.session.flush()
    resume = d.get("resume_text") or ""
    skills = [{"name": s, "level": 2, "verified": False, "source": "resume"} for s in ai.extract_skills(resume)]
    db.session.add(CandidateProfile(user_id=u.id, resume_text=resume, skills=skills, headline=d.get("headline"),
                                    target_roles=[d["goal"]] if d.get("goal") else []))
    if d.get("invite"):
        job = Job.query.filter_by(invite_token=d["invite"]).first()
        if job and job.status == "live":
            score, got, missing = skill_match(job, skills)
            db.session.add(Application(job_id=job.id, candidate_id=u.id, source="invited", match_score=score,
                                       match_reasons={"matched": got, "missing": missing}))
    log("candidate.signup", "user", u.id)
    db.session.commit()
    return ok({"token": make_token(u), **me_payload(u)})


@bp.get("/me")
@auth_required
def me():
    claims = getattr(g, "claims", {}) or {}
    return ok({**me_payload(g.user), "link_session": claims.get("via") == "invite"})


@bp.post("/change-password")
@auth_required
def change_password():
    """Normal change needs the current password. Someone who opened their personal link and hasn't set one yet doesn't."""
    from models import InviteLink
    d = body()
    claims = getattr(g, "claims", {}) or {}
    via_link = claims.get("via") == "invite" and g.user.must_change_password
    if not via_link and not check_password(d.get("current", ""), g.user.password_hash):
        return err("Your current password is not right.")
    pw = d.get("new") or ""
    if len(pw) < 8:
        return err("Use at least 8 characters.")
    if pw.lower() == g.user.email.split("@")[0].lower() or pw.isdigit():
        return err("Pick something harder to guess: mix letters and numbers.")
    g.user.password_hash = hash_password(pw)
    g.user.must_change_password = False
    InviteLink.query.filter_by(user_id=g.user.id, used_at=None).update({"used_at": datetime.utcnow()})
    log("user.password_changed", "user", g.user.id, via_link=via_link)
    db.session.commit()
    return ok({"token": make_token(g.user), **me_payload(g.user), "link_session": False})
