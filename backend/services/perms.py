"""Authentication and the permission engine.

Roles stack: a user can hold several roles, each limited to a scope (company, team or job).
Effective permissions = union of role permissions + active, unexpired grants.
"""
from datetime import datetime
from functools import wraps

import bcrypt
import jwt
from flask import current_app, g, jsonify, request

from extensions import db
from models import CustomRole, Grant, Job, JobAssignment, RoleAssignment, User

PERMISSIONS = {
    "company.manage": "Edit company profile, branding and SSO",
    "users.manage": "Invite users, assign roles and grants",
    "policies.manage": "Create and edit policies",
    "settings.manage": "Change inherited settings",
    "billing.view": "See plan and credit usage",
    "teams.manage": "Create teams and assign people",
    "templates.manage": "Create and edit hiring templates",
    "jobs.create": "Create jobs",
    "jobs.edit": "Edit jobs",
    "jobs.publish": "Publish jobs publicly",
    "candidates.view": "See candidates and applications",
    "candidates.move": "Move, shortlist and reject candidates",
    "interviews.run": "Invite to rounds and schedule interviews",
    "interviews.join": "Join live interviews and submit scorecards",
    "verdict.recommend": "Recommend a verdict",
    "verdict.final": "Give the final decision",
    "reports.view": "Read interview reports",
    "reports.share": "Share reports with candidates or clients",
    "analytics.view": "See team analytics and build reports",
    "export": "Export data",
    "salary.view": "See salary bands",
    "approvals.decide": "Approve or reject requests",
    "certs.manage": "Create and publish certifications",
    "questions.manage": "Manage the company question bank",
    "audit.view": "Read the audit log",
}

ROLE_PERMS = {
    "company_admin": list(PERMISSIONS.keys()),
    "manager": [p for p in PERMISSIONS if p not in ("company.manage", "billing.view")],
    "recruiter": ["jobs.create", "jobs.edit", "candidates.view", "candidates.move", "interviews.run",
                  "verdict.recommend", "reports.view", "reports.share", "analytics.view", "questions.manage"],
    "interviewer": ["interviews.join", "reports.view"],
    "hiring_manager": ["candidates.view", "reports.view", "verdict.final", "analytics.view"],
}
ROLE_LABELS = {"company_admin": "Company Admin", "manager": "Super Recruiter / Manager", "recruiter": "Recruiter",
               "interviewer": "Interviewer", "hiring_manager": "Hiring Manager"}


# ---------------------------------------------------------------- passwords and tokens

def hash_password(pw):
    return bcrypt.hashpw(pw.encode(), bcrypt.gensalt()).decode()


def check_password(pw, hashed):
    try:
        return bcrypt.checkpw(pw.encode(), hashed.encode())
    except Exception:
        return False


def make_token(user):
    payload = {"sub": str(user.id), "exp": datetime.utcnow() + current_app.config["TOKEN_TTL"]}
    return jwt.encode(payload, current_app.config["SECRET_KEY"], algorithm="HS256")


def _load_user():
    header = request.headers.get("Authorization", "")
    token = header[7:] if header.startswith("Bearer ") else request.args.get("token")
    if not token:
        return None
    try:
        data = jwt.decode(token, current_app.config["SECRET_KEY"], algorithms=["HS256"])
    except jwt.PyJWTError:
        return None
    u = db.session.get(User, int(data["sub"]))
    return u if u and u.active else None


def auth_required(fn):
    @wraps(fn)
    def wrapper(*a, **kw):
        u = _load_user()
        if not u:
            return jsonify({"error": "Please sign in again."}), 401
        g.user = u
        return fn(*a, **kw)
    return wrapper


def superadmin_required(fn):
    @wraps(fn)
    @auth_required
    def wrapper(*a, **kw):
        if not g.user.is_superadmin:
            return jsonify({"error": "Superadmin only."}), 403
        return fn(*a, **kw)
    return wrapper


def staff_required(fn):
    @wraps(fn)
    @auth_required
    def wrapper(*a, **kw):
        if g.user.kind != "staff" and not g.user.is_superadmin:
            return jsonify({"error": "This area is for hiring teams."}), 403
        return fn(*a, **kw)
    return wrapper


# ---------------------------------------------------------------- permission engine

def _role_perms(role, company_id):
    if role.startswith("custom:"):
        cr = db.session.get(CustomRole, int(role.split(":")[1]))
        return list(cr.permissions or []) if cr and cr.company_id == company_id else []
    return ROLE_PERMS.get(role, [])


def effective(user, company_id=None):
    """{perm: [(scope_type, scope_id), ...]} for the user inside a company."""
    company_id = company_id or user.company_id
    out = {}
    if user.is_superadmin:
        return {p: [("company", company_id)] for p in PERMISSIONS}
    for ra in RoleAssignment.query.filter_by(user_id=user.id, company_id=company_id).all():
        for p in _role_perms(ra.role, company_id):
            out.setdefault(p, []).append((ra.scope_type, ra.scope_id))
    now_ = datetime.utcnow()
    for gr in Grant.query.filter_by(user_id=user.id, company_id=company_id, status="active").all():
        if gr.expires_at and gr.expires_at < now_:
            continue
        out.setdefault(gr.permission, []).append((gr.scope_type, gr.scope_id))
    return out


def roles_of(user):
    return [{"role": r.role, "label": ROLE_LABELS.get(r.role, r.role), "scope_type": r.scope_type, "scope_id": r.scope_id}
            for r in RoleAssignment.query.filter_by(user_id=user.id).all()]


def can(user, perm, job=None, team_id=None, company_id=None):
    if user.is_superadmin:
        return True
    company_id = company_id or (job.company_id if job else user.company_id)
    if user.company_id != company_id:
        return False
    scopes = effective(user, company_id).get(perm, [])
    for st, sid in scopes:
        if st == "company":
            return True
        if st == "team" and ((job and job.team_id == sid) or (team_id and team_id == sid)):
            return True
        if st == "job" and job and job.id == sid:
            return True
    if job is not None:
        # people assigned to a job get the job-level permissions of their assignment role
        a = JobAssignment.query.filter_by(job_id=job.id, user_id=user.id).first()
        if a and perm in ROLE_PERMS.get(a.role, []):
            return True
        if job.created_by == user.id and perm in ROLE_PERMS["recruiter"]:
            return True
    return False


def visible_job_ids(user, perm="candidates.view"):
    """Jobs the user can see; None means all jobs in the company."""
    if user.is_superadmin:
        return None
    scopes = effective(user).get(perm, [])
    if any(st == "company" for st, _ in scopes):
        return None
    team_ids = [sid for st, sid in scopes if st == "team"]
    ids = {sid for st, sid in scopes if st == "job"}
    if team_ids:
        ids |= {j.id for j in Job.query.filter(Job.team_id.in_(team_ids)).all()}
    ids |= {a.job_id for a in JobAssignment.query.filter_by(user_id=user.id).all()}
    ids |= {j.id for j in Job.query.filter_by(created_by=user.id).all()}
    return ids


def deny(msg="You don't have permission to do that.", code=403):
    return jsonify({"error": msg}), code


def can_any(user, perm, company_id=None):
    """True if the user holds the permission at any scope (used for screens that then filter to what they can see)."""
    if user.is_superadmin:
        return True
    return perm in effective(user, company_id or user.company_id)
