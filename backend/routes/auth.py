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
    if u.kind == "staff" and "analytics.view" not in perms:  # V02.00.09: a hiring manager on a job sees its analytics
        from services.perms import assigned_job_ids
        if assigned_job_ids(u, "analytics.view"):
            perms = sorted(perms + ["analytics.view"])
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


# ---------------------------------------------------------------- V02.00.10 (CP-010): forgot password by email

RESET_MINUTES = 60


def _site_url():
    import os
    from flask import request
    return (os.environ.get("C2H_PUBLIC_URL") or request.host_url).rstrip("/")


@bp.post("/forgot")
def forgot():
    """Sends a one-time reset link (valid 60 minutes) when the address belongs to an active account. The answer is the
    same either way, so this can't be used to find out who has an account."""
    import secrets
    from datetime import timedelta
    from models import InviteLink
    from routes.people import hash_token
    from services import mailer
    email = str(body().get("email") or "").strip().lower()
    if V.email(email)[1]:
        return err("Enter the email address you sign in with.", fields={"email": "Enter a valid email address."})
    ip = throttle.client_ip()
    wait = throttle.locked(f"forgot:{email}", f"ip:{ip}")
    if wait:
        return err(throttle.message(wait), 429)
    throttle.fail(f"forgot:{email}")  # at most 5 reset emails per address per 15 minutes
    same = {"sent": True, "message": "If that address has a Code2Hire account, we've emailed a link to reset the password. It works for 60 minutes."}
    if not mailer.configured():
        return err("Password reset by email isn't set up yet. Ask your recruiter or the Code2Hire admin to help you sign in.", 503)
    u = User.query.filter(db.func.lower(User.email) == email).first()
    if not u or not u.active or u.archived_at:
        db.session.commit()
        return ok(same)
    InviteLink.query.filter_by(user_id=u.id, purpose="reset", used_at=None, revoked=False).update({"revoked": True})
    token = secrets.token_urlsafe(32)
    db.session.add(InviteLink(token_hash=hash_token(token), user_id=u.id, purpose="reset",
                              expires_at=datetime.utcnow() + timedelta(minutes=RESET_MINUTES)))
    url = f"{_site_url()}/reset/{token}"
    first = (u.name or "").split(" ")[0] or "there"
    try:
        mailer.send(u.email, "Reset your Code2Hire password",
                    f"Hi {first},\n\nSomeone (hopefully you) asked to reset the password for your Code2Hire account.\n"
                    f"Open this link within {RESET_MINUTES} minutes to choose a new password:\n{url}\n\n"
                    "If you didn't ask for this, ignore this email; your password stays the same.\n\nCode2Hire",
                    mailer.layout("Reset your password", [f"Hi {first},", "Someone (hopefully you) asked to reset the password for your Code2Hire account.",
                                                         f"The link works for {RESET_MINUTES} minutes and only once."],
                                  "Choose a new password", url, "If you didn't ask for this, ignore this email. Your password stays the same."))
    except mailer.MailError as e:
        db.session.rollback()
        log("user.password_reset_failed", "user", u.id, reason=str(e)[:200])
        db.session.commit()
        return err("We couldn't send the email just now. Try again in a few minutes, or ask your recruiter or admin for help.", 502)
    log("user.password_reset_sent", "user", u.id)
    db.session.commit()
    return ok(same)


def _reset_link(token):
    from models import InviteLink
    from routes.people import hash_token
    link = InviteLink.query.filter_by(token_hash=hash_token(token or ""), purpose="reset").first()
    if not link or link.revoked or link.used_at or link.expires_at < datetime.utcnow():
        return None, None
    u = db.session.get(User, link.user_id)
    if not u or not u.active or u.archived_at:
        return None, None
    return link, u


@bp.get("/reset/<token>")
def reset_check(token):
    link, u = _reset_link(token)
    if not link:
        return err("This reset link has expired or was already used. Ask for a new one.", 410)
    return ok({"email": u.email, "expires_at": link.expires_at.isoformat() + "Z"})


@bp.post("/reset/<token>")
def reset_password(token):
    ip = throttle.client_ip()
    wait = throttle.locked(f"ip:{ip}")
    if wait:
        return err(throttle.message(wait), 429)
    link, u = _reset_link(token)
    if not link:
        throttle.fail(f"ip:{ip}")
        db.session.commit()
        return err("This reset link has expired or was already used. Ask for a new one.", 410)
    pw = body().get("new") or ""
    problem = V.password(pw, u.email)
    if problem:
        return err(problem, fields={"new": problem})
    u.password_hash = hash_password(pw)
    u.must_change_password = False
    link.used_at = datetime.utcnow()
    from models import InviteLink
    InviteLink.query.filter(InviteLink.user_id == u.id, InviteLink.purpose == "reset", InviteLink.used_at.is_(None)).update({"revoked": True})
    throttle.clear(f"email:{u.email.lower()}")
    log("user.password_reset", "user", u.id)
    db.session.commit()
    return ok({"token": make_token(u), **me_payload(u)})


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
