"""Company Admin and managers: teams, users with stacked roles, custom roles, grants, policies, approvals, settings, audit."""
import secrets
from datetime import datetime, timedelta

from flask import Blueprint, g, request

from extensions import db
from models import (Application, Approval, AuditLog, Company, CustomRole, Grant, Job, JobAssignment, Policy,
                    RoleAssignment, Team, User)
from routes.utils import body, err, ok, parse_dt, table
from services.audit import log, notify
from services.perms import PERMISSIONS, ROLE_LABELS, ROLE_PERMS, can, deny, effective, hash_password, staff_required
from services.policy import ACTIONS, EVENTS, OPS, evaluate
from services.settings import effective_table, reset_value, set_value

bp = Blueprint("company", __name__, url_prefix="/api/company")


def cid():
    if g.user.is_superadmin and request.headers.get("X-Company-Id"):
        return int(request.headers["X-Company-Id"])
    return g.user.company_id


def need(perm):
    return can(g.user, perm, company_id=cid())


@bp.get("")
@staff_required
def company():
    c = db.session.get(Company, cid())
    return ok({"company": c.to_dict(), "teams": [t.to_dict() for t in Team.query.filter_by(company_id=c.id).all()],
               "usage": {"credits_used": c.credits_used, "credits_total": c.credits_total,
                         "seats_used": User.query.filter_by(company_id=c.id, active=True).count(),
                         "active_jobs": Job.query.filter_by(company_id=c.id, status="live").count()}})


@bp.patch("")
@staff_required
def update_company():
    if not need("company.manage"):
        return deny()
    c = db.session.get(Company, cid())
    d = body()
    for f in ("name", "domain", "timezone", "gst"):
        if f in d:
            setattr(c, f, d[f])
    if "branding" in d:
        c.branding = {**(c.branding or {}), **d["branding"]}
    log("company.profile", "company", c.id)
    db.session.commit()
    return ok(c.to_dict())


# ---------------------------------------------------------------- teams

@bp.get("/teams")
@staff_required
def teams():
    out = []
    for t in Team.query.filter_by(company_id=cid()).all():
        d = t.to_dict()
        d["members"] = RoleAssignment.query.filter_by(company_id=cid(), scope_type="team", scope_id=t.id).count()
        d["jobs"] = Job.query.filter_by(team_id=t.id).count()
        out.append(d)
    return ok(out)


@bp.post("/teams")
@staff_required
def create_team():
    if not need("teams.manage"):
        return deny()
    t = Team(company_id=cid(), name=body().get("name") or "New team")
    db.session.add(t)
    log("team.create", "team", None, name=t.name)
    db.session.commit()
    return ok(t.to_dict())


@bp.patch("/teams/<int:tid>")
@staff_required
def rename_team(tid):
    if not need("teams.manage"):
        return deny()
    t = Team.query.filter_by(id=tid, company_id=cid()).first_or_404()
    t.name = body().get("name", t.name)
    db.session.commit()
    return ok(t.to_dict())


# ---------------------------------------------------------------- users and stacked roles

def user_row(u):
    d = u.public()
    d["roles"] = [{"id": r.id, "role": r.role, "label": ROLE_LABELS.get(r.role) or _custom_label(r.role),
                   "scope_type": r.scope_type, "scope_id": r.scope_id, "scope_name": _scope_name(r.scope_type, r.scope_id)}
                  for r in RoleAssignment.query.filter_by(user_id=u.id).all()]
    d["grants"] = [gr.to_dict() for gr in Grant.query.filter_by(user_id=u.id, status="active").all()]
    d["last_login_at"] = u.last_login_at.isoformat() + "Z" if u.last_login_at else None
    d["skills_meta"] = u.skills_meta or {}
    return d


def _custom_label(role):
    if role.startswith("custom:"):
        cr = db.session.get(CustomRole, int(role.split(":")[1]))
        return cr.name if cr else role
    return role


def _scope_name(st, sid):
    if st == "team":
        t = db.session.get(Team, sid)
        return t.name if t else "Team"
    if st == "job":
        j = db.session.get(Job, sid)
        return j.title if j else "Job"
    return "Whole company"


@bp.get("/users")
@staff_required
def users():
    return table(User.query.filter_by(company_id=cid(), kind="staff"), [User.name, User.email],
                 {"name": User.name, "email": User.email, "created": User.created_at, "last_login": User.last_login_at},
                 "name", user_row, {"active": lambda q, v: q.filter(User.active == (v == "true"))})


@bp.post("/users")
@staff_required
def invite_user():
    if not need("users.manage"):
        return deny()
    d = body()
    email = (d.get("email") or "").strip().lower()
    if not email:
        return err("Email is required.")
    if User.query.filter_by(email=email).first():
        return err("Someone already uses that email.")
    temp = d.get("password") or secrets.token_urlsafe(9)
    u = User(email=email, name=d.get("name") or email.split("@")[0], kind="staff", company_id=cid(),
             password_hash=hash_password(temp), must_change_password=not d.get("password"),
             skills_meta=d.get("skills_meta") or {})
    db.session.add(u)
    db.session.flush()
    for r in d.get("roles") or [{"role": "recruiter", "scope_type": "company"}]:
        db.session.add(RoleAssignment(user_id=u.id, company_id=cid(), role=r["role"], scope_type=r.get("scope_type", "company"),
                                      scope_id=r.get("scope_id") or (cid() if r.get("scope_type", "company") == "company" else None)))
    log("user.invite", "user", u.id, roles=d.get("roles"))
    from routes.people import new_link
    token, _ = new_link(u, cid(), purpose="staff")
    db.session.commit()
    return ok({"user": user_row(u), "temporary_password": temp, "link": f"/welcome/{token}"})


@bp.patch("/users/<int:uid>")
@staff_required
def update_user(uid):
    if not need("users.manage"):
        return deny()
    u = User.query.filter_by(id=uid, company_id=cid()).first_or_404()
    d = body()
    for f in ("name", "active", "skills_meta"):
        if f in d:
            setattr(u, f, d[f])
    log("user.update", "user", uid, fields=list(d.keys()))
    db.session.commit()
    return ok(user_row(u))


@bp.put("/users/<int:uid>/roles")
@staff_required
def set_roles(uid):
    """Replace a person's role list. Roles stack; each has its own scope."""
    if not need("users.manage"):
        return deny()
    u = User.query.filter_by(id=uid, company_id=cid()).first_or_404()
    RoleAssignment.query.filter_by(user_id=uid).delete()
    for r in body().get("roles", []):
        st = r.get("scope_type", "company")
        db.session.add(RoleAssignment(user_id=uid, company_id=cid(), role=r["role"], scope_type=st,
                                      scope_id=r.get("scope_id") or (cid() if st == "company" else None)))
    log("user.roles", "user", uid, roles=body().get("roles"))
    db.session.commit()
    return ok(user_row(u))


@bp.post("/users/<int:uid>/reset-password")
@staff_required
def reset_password(uid):
    if not need("users.manage"):
        return deny()
    u = User.query.filter_by(id=uid, company_id=cid()).first_or_404()
    temp = secrets.token_urlsafe(9)
    u.password_hash = hash_password(temp)
    u.must_change_password = True
    log("user.reset_password", "user", uid)
    db.session.commit()
    return ok({"temporary_password": temp})


@bp.get("/permissions")
@staff_required
def permissions_catalog():
    return ok({"permissions": PERMISSIONS, "roles": ROLE_PERMS, "labels": ROLE_LABELS,
               "custom": [r.to_dict() for r in CustomRole.query.filter_by(company_id=cid()).all()],
               "mine": sorted(effective(g.user, cid()).keys())})


@bp.post("/roles")
@staff_required
def create_custom_role():
    if not need("users.manage"):
        return deny()
    d = body()
    base = d.get("base_role")
    perms = d.get("permissions") or list(ROLE_PERMS.get(base, []))
    r = CustomRole(company_id=cid(), name=d.get("name") or "Custom role", base_role=base,
                   permissions=[p for p in perms if p in PERMISSIONS])
    db.session.add(r)
    log("role.custom.create", "role", None, name=r.name)
    db.session.commit()
    return ok(r.to_dict())


@bp.patch("/roles/<int:rid>")
@staff_required
def update_custom_role(rid):
    if not need("users.manage"):
        return deny()
    r = CustomRole.query.filter_by(id=rid, company_id=cid()).first_or_404()
    d = body()
    if "name" in d:
        r.name = d["name"]
    if "permissions" in d:
        r.permissions = [p for p in d["permissions"] if p in PERMISSIONS]
    db.session.commit()
    return ok(r.to_dict())


# ---------------------------------------------------------------- grants, cover, access review

@bp.get("/grants")
@staff_required
def grants():
    out = []
    for gr in Grant.query.filter_by(company_id=cid()).order_by(Grant.created_at.desc()).all():
        d = gr.to_dict()
        u = db.session.get(User, gr.user_id)
        d["user"] = u.name if u else ""
        d["expired"] = bool(gr.expires_at and gr.expires_at < datetime.utcnow())
        out.append(d)
    return ok(out)


@bp.post("/grants")
@staff_required
def create_grant():
    if not need("users.manage"):
        return deny()
    d = body()
    if d.get("permission") not in PERMISSIONS:
        return err("Unknown permission.")
    gr = Grant(user_id=int(d["user_id"]), company_id=cid(), permission=d["permission"], scope_type=d.get("scope_type", "company"),
               scope_id=d.get("scope_id"), expires_at=parse_dt(d.get("expires_at")), reason=d.get("reason"), granted_by=g.user.id)
    db.session.add(gr)
    db.session.flush()
    res = evaluate(cid(), "grant.create", {"permission": gr.permission}, title=f"Grant {gr.permission} to user #{gr.user_id}",
                   ref_type="grant", ref_id=gr.id, requested_by=g.user.id)
    if res["blocked"]:
        db.session.rollback()
        return err(res["blocked"], 403)
    if res["approval"]:
        gr.status = "pending"
    log("grant.create", "grant", gr.id, permission=gr.permission, user_id=gr.user_id, expires=d.get("expires_at"))
    notify(gr.user_id, "You have a new permission" if gr.status == "active" else "A permission is waiting for approval",
           f"{PERMISSIONS[gr.permission]}", "/app/today")
    db.session.commit()
    return ok({**gr.to_dict(), "approval": res["approval"].id if res["approval"] else None})


@bp.delete("/grants/<int:gid>")
@staff_required
def revoke_grant(gid):
    if not need("users.manage"):
        return deny()
    gr = Grant.query.filter_by(id=gid, company_id=cid()).first_or_404()
    gr.status = "revoked"
    log("grant.revoke", "grant", gid)
    db.session.commit()
    return ok()


@bp.post("/cover")
@staff_required
def temporary_cover():
    """'Rahul covers Anita's jobs for 2 weeks': job-scoped grants that expire automatically."""
    if not need("users.manage"):
        return deny()
    d = body()
    src, dst = int(d["from_user_id"]), int(d["to_user_id"])
    until = parse_dt(d.get("until")) or datetime.utcnow() + timedelta(days=14)
    job_ids = {a.job_id for a in JobAssignment.query.filter_by(user_id=src).all()} | {j.id for j in Job.query.filter_by(created_by=src).all()}
    n = 0
    for jid in job_ids:
        for perm in ("candidates.view", "candidates.move", "interviews.run", "reports.view", "verdict.recommend", "jobs.edit"):
            db.session.add(Grant(user_id=dst, company_id=cid(), permission=perm, scope_type="job", scope_id=jid,
                                 expires_at=until, reason=f"Covering for user #{src}", granted_by=g.user.id))
            n += 1
    log("grant.cover", "user", dst, from_user=src, until=until.isoformat(), jobs=len(job_ids))
    notify(dst, "You're covering jobs", f"{len(job_ids)} jobs until {until:%d %b}", "/app/jobs")
    db.session.commit()
    return ok({"jobs": len(job_ids), "grants": n, "until": until.isoformat() + "Z"})


@bp.get("/access-review")
@staff_required
def access_review():
    """Hira's quarterly review: permissions that look unused or stale."""
    if not need("users.manage"):
        return deny()
    cutoff = datetime.utcnow() - timedelta(days=90)
    items = []
    for u in User.query.filter_by(company_id=cid(), kind="staff", active=True).all():
        if not u.last_login_at or u.last_login_at < cutoff:
            items.append({"type": "inactive_user", "user_id": u.id, "user": u.name,
                          "suggestion": "Not signed in for 90 days: switch off or remove roles"})
        for gr in Grant.query.filter_by(user_id=u.id, status="active").all():
            if gr.expires_at and gr.expires_at < datetime.utcnow():
                items.append({"type": "expired_grant", "grant_id": gr.id, "user": u.name, "suggestion": f"Expired grant {gr.permission}: revoke"})
            elif not gr.expires_at and gr.created_at < cutoff:
                items.append({"type": "old_grant", "grant_id": gr.id, "user": u.name,
                              "suggestion": f"{gr.permission} granted over 90 days ago with no expiry: confirm or revoke"})
    return ok(items)


# ---------------------------------------------------------------- policies

@bp.get("/policies")
@staff_required
def policies():
    return ok({"policies": [p.to_dict() for p in Policy.query.filter_by(company_id=cid()).all()],
               "events": EVENTS, "actions": ACTIONS, "ops": list(OPS.keys())})


@bp.post("/policies")
@staff_required
def create_policy():
    if not need("policies.manage"):
        return deny()
    d = body()
    if d.get("event") not in EVENTS or d.get("action") not in ACTIONS:
        return err("Choose a valid event and action.")
    p = Policy(company_id=cid(), name=d.get("name") or "New rule", event=d["event"], conditions=d.get("conditions", []),
               action=d["action"], params=d.get("params", {}), enabled=d.get("enabled", True))
    db.session.add(p)
    log("policy.create", "policy", None, name=p.name)
    db.session.commit()
    return ok(p.to_dict())


@bp.patch("/policies/<int:pid>")
@staff_required
def update_policy(pid):
    if not need("policies.manage"):
        return deny()
    p = Policy.query.filter_by(id=pid, company_id=cid()).first_or_404()
    for f in ("name", "event", "conditions", "action", "params", "enabled"):
        if f in body():
            setattr(p, f, body()[f])
    log("policy.update", "policy", pid)
    db.session.commit()
    return ok(p.to_dict())


@bp.delete("/policies/<int:pid>")
@staff_required
def delete_policy(pid):
    if not need("policies.manage"):
        return deny()
    Policy.query.filter_by(id=pid, company_id=cid()).delete()
    log("policy.delete", "policy", pid)
    db.session.commit()
    return ok()


# ---------------------------------------------------------------- approvals

@bp.get("/approvals")
@staff_required
def approvals():
    q = Approval.query.filter_by(company_id=cid())
    status = request.args.get("status", "pending")
    if status != "all":
        q = q.filter_by(status=status)
    out = []
    for a in q.order_by(Approval.created_at.desc()).all():
        d = a.to_dict()
        u = db.session.get(User, a.requested_by) if a.requested_by else None
        d["requested_by_name"] = u.name if u else ""
        out.append(d)
    return ok(out)


@bp.post("/approvals/<int:aid>/decide")
@staff_required
def decide(aid):
    if not need("approvals.decide"):
        return deny()
    a = Approval.query.filter_by(id=aid, company_id=cid()).first_or_404()
    if a.status != "pending":
        return err("Already decided.")
    if a.requested_by == g.user.id:
        return err("You can't approve your own request.", 403)
    d = body()
    if not d.get("approve"):
        a.status = "rejected"
        a.note = d.get("note") or a.note
        notify(a.requested_by, "Request not approved", a.title, "/app/approvals")
    else:
        approvers = list(a.approvers or [])
        if g.user.id in approvers:
            return err("You've already approved this.")
        approvers.append(g.user.id)
        a.approvers = approvers
        if len(approvers) >= (a.approvals_needed or 1):
            a.status = "approved"
            _apply(a)
            notify(a.requested_by, "Request approved", a.title, "/app/approvals")
    log("approval.decide", "approval", aid, approve=bool(d.get("approve")))
    db.session.commit()
    return ok(a.to_dict())


def _apply(a):
    if a.kind == "job.publish" and a.ref_id:
        j = db.session.get(Job, a.ref_id)
        if j:
            j.status = "live"
    elif a.kind == "offer.create" and a.ref_id:
        app_ = db.session.get(Application, a.ref_id)
        if app_:
            app_.stage = "offer"
            app_.verdict = "offer"
    elif a.kind == "grant.create" and a.ref_id:
        gr = db.session.get(Grant, a.ref_id)
        if gr:
            gr.status = "active"


# ---------------------------------------------------------------- settings (inheritance)

@bp.get("/settings")
@staff_required
def settings():
    scope = request.args.get("scope", "company")
    sid = int(request.args.get("id") or cid())
    team_id = sid if scope == "team" else None
    job_id = sid if scope == "job" else None
    if scope == "job":
        j = Job.query.filter_by(id=sid, company_id=cid()).first_or_404()
        team_id = j.team_id
    return ok(effective_table(scope, sid, company_id=cid(), team_id=team_id, job_id=job_id))


@bp.put("/settings")
@staff_required
def put_setting():
    d = body()
    scope = d.get("scope", "company")
    sid = int(d.get("id") or cid())
    job = Job.query.filter_by(id=sid, company_id=cid()).first() if scope == "job" else None
    allowed = need("settings.manage") or (job is not None and can(g.user, "jobs.edit", job=job))
    if not allowed:
        return deny()
    rows = {r["key"]: r for r in effective_table(scope, sid, company_id=cid(), team_id=sid if scope == "team" else (job.team_id if job else None),
                                                 job_id=sid if scope == "job" else None)}
    row = rows.get(d.get("key"))
    if not row:
        return err("Unknown setting.")
    if not row["editable"]:
        return err(f"This setting is locked at {row['locked_at']} level.", 403)
    if d.get("reset"):
        reset_value(scope, sid, d["key"])
    else:
        set_value(scope, sid, d["key"], d.get("value"), d.get("locked", False))
    log("settings.update", scope, sid, key=d["key"], value=d.get("value"), locked=d.get("locked"))
    db.session.commit()
    return settings_for(scope, sid, job)


def settings_for(scope, sid, job):
    return ok(effective_table(scope, sid, company_id=cid(), team_id=sid if scope == "team" else (job.team_id if job else None),
                              job_id=sid if scope == "job" else None))


# ---------------------------------------------------------------- audit and interviewers

@bp.get("/audit")
@staff_required
def audit():
    if not need("audit.view"):
        return deny()

    def ser(a):
        d = a.to_dict()
        u = db.session.get(User, a.actor_id) if a.actor_id else None
        d["actor"] = u.name if u else "System"
        return d
    return table(AuditLog.query.filter_by(company_id=cid()), [AuditLog.action, AuditLog.target_type],
                 {"created": AuditLog.created_at, "action": AuditLog.action}, "created", ser)


@bp.get("/interviewers")
@staff_required
def interviewers():
    ids = {r.user_id for r in RoleAssignment.query.filter(RoleAssignment.company_id == cid(),
                                                          RoleAssignment.role.in_(["interviewer", "manager", "recruiter", "hiring_manager"])).all()}
    return ok([{**db.session.get(User, i).public(), "skills_meta": db.session.get(User, i).skills_meta or {}} for i in ids])


# ---------------------------------------------------------------- company question bank

@bp.get("/questions")
@staff_required
def questions():
    from models import Question
    scope = request.args.get("scope", "company")
    q = Question.query.filter(Question.company_id.is_(None) if scope == "global" else Question.company_id == cid())
    return table(q, [Question.text, Question.skill], {"skill": Question.skill, "level": Question.level, "created": Question.created_at},
                 "created", None, {"status": lambda q, v: q.filter(Question.status == v), "skill": lambda q, v: q.filter(Question.skill == v),
                                   "source": lambda q, v: q.filter(Question.source == v)})


@bp.post("/questions")
@staff_required
def add_question():
    from models import Question
    if not can(g.user, "questions.manage", company_id=cid()) and not _any("questions.manage"):
        return deny()
    d = body()
    opts = [o for o in d.get("options", []) if str(o).strip()]
    if not d.get("text") or len(opts) < 2:
        return err("A question needs text and at least two options.")
    q = Question(company_id=cid(), skill=d.get("skill") or "General", level=int(d.get("level", 3)), text=d["text"], code=d.get("code"),
                 options=opts, answer=int(d.get("answer", 0)), explanation=d.get("explanation"), status="approved", source="manual")
    db.session.add(q)
    db.session.commit()
    return ok(q.to_dict())


@bp.post("/questions/generate")
@staff_required
def gen_questions():
    """Hira drafts questions; they wait as 'pending' until a person approves them."""
    from models import Question
    from services import ai
    if not _any("questions.manage"):
        return deny()
    d = body()
    items = ai.generate_mcq(d.get("skills") or ["General"], int(d.get("level", 3)), min(20, int(d.get("n", 5))), company_id=cid())
    for it in items:
        db.session.add(Question(company_id=cid(), skill=it.get("skill"), level=it.get("level", 3), text=it["text"], code=it.get("code") or None,
                                options=it["options"][:4], answer=int(it.get("answer", 0)), explanation=it.get("explanation"),
                                status="pending", source="ai"))
    log("question.generate", "question", None, n=len(items))
    db.session.commit()
    return ok({"created": len(items)})


@bp.patch("/questions/<int:qid>")
@staff_required
def edit_question(qid):
    from models import Question
    if not _any("questions.manage"):
        return deny()
    q = Question.query.filter_by(id=qid, company_id=cid()).first_or_404()
    for f in ("text", "options", "answer", "skill", "level", "explanation", "code", "status"):
        if f in body():
            setattr(q, f, body()[f])
    db.session.commit()
    return ok(q.to_dict())


def _any(perm):
    from services.perms import can_any
    return can_any(g.user, perm, cid())
