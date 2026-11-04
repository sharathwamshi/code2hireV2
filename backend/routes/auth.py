from datetime import datetime

from flask import Blueprint, g

from extensions import db
from models import Application, CandidateProfile, Company, Job, User
from routes.utils import body, err, ok
from services import throttle
from services import validate as V
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


_DUMMY = []


def _dummy_hash():
    if not _DUMMY:
        _DUMMY.append(hash_password("not-a-real-password-0"))
    return _DUMMY[0]


@bp.post("/login")
def login():
    d = body()
    email = (d.get("email") or "").strip().lower()[:254]
    pw = d.get("password") or ""
    if not email or not pw:
        return err("Enter your email and password.", fields={k: "This is required." for k, v in (("email", email), ("password", pw)) if not v})
    ekey, ikey = f"email:{email}", f"ip:{throttle.client_ip()}"
    wait = throttle.locked(ekey, ikey)
    if wait:
        return err(throttle.message(wait), 429)
    u = User.query.filter_by(email=email).first()
    good = check_password(pw, u.password_hash) if u else (check_password(pw, _dummy_hash()) and False)  # same timing either way
    if not good:
        throttle.fail(ekey)
        throttle.fail(ikey)
        log("auth.login_failed", "user", u.id if u else None, company_id=u.company_id if u else None, email=email, ip=throttle.client_ip())
        db.session.commit()
        wait = throttle.locked(ekey, ikey)
        if wait:
            return err(throttle.message(wait), 429)
        return err("That email and password don't match.", 401)
    if not u.active:
        return err("This account is switched off. Contact your admin.", 403)
    throttle.clear(ekey)
    u.last_login_at = datetime.utcnow()
    db.session.commit()
    return ok({"token": make_token(u), **me_payload(u)})


@bp.post("/signup")
def signup():
    """Candidate self sign-up, optionally from a private job invite link."""
    d = body()
    ikey = f"signup:{throttle.client_ip()}"
    wait = throttle.locked(ikey)
    if wait:
        return err(throttle.message(wait), 429)
    c = V.Checker()
    email = c.add("email", *V.email(d.get("email")))
    name = c.add("name", *V.person_name(d.get("name"), required=False))
    c.add("password", d.get("password"), V.password(d.get("password"), email))
    if c:
        return c.response()
    if User.query.filter_by(email=email).first():
        throttle.fail(ikey)
        return err("An account with this email already exists. Sign in instead.", fields={"email": "An account with this email already exists."})
    throttle.fail(ikey)  # every sign-up counts toward the per-address limit (10 per 30 minutes)
    u = User(email=email, name=name or email.split("@")[0], kind="candidate",
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
    pkey = f"pw:{g.user.id}"
    if not via_link:
        wait = throttle.locked(pkey)
        if wait:
            return err(throttle.message(wait), 429)
        if not check_password(d.get("current", ""), g.user.password_hash):
            throttle.fail(pkey)
            return err("Your current password is not right.", fields={"current": "Your current password is not right."})
    pw = d.get("new") or ""
    problem = V.password(pw, g.user.email)
    if problem:
        return err(problem, fields={"new": problem})
    if check_password(pw, g.user.password_hash) and not via_link:
        return err("Choose a password different from your current one.", fields={"new": "Choose a different password."})
    throttle.clear(pkey)
    g.user.password_hash = hash_password(pw)
    g.user.must_change_password = False
    InviteLink.query.filter_by(user_id=g.user.id, used_at=None).update({"used_at": datetime.utcnow()})
    log("user.password_changed", "user", g.user.id, via_link=via_link)
    db.session.commit()
    return ok({"token": make_token(g.user), **me_payload(g.user), "link_session": False})
