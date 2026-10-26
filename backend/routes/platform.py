"""Superadmin: companies, plans and credits, feature flags, platform settings, AI and voice keys, shared content, audit."""
import secrets
from datetime import datetime, timedelta

from flask import Blueprint, g, request

from extensions import db
from models import (Application, AuditLog, Certification, Company, HiringTemplate, Job, Question, Report,
                    RoleAssignment, RoundAttempt, Team, User)
from routes.utils import body, err, ok, table
from services import ai, speech
from services.audit import log, notify_roles
from services.perms import hash_password, superadmin_required
from services.policy import install_defaults
from services.settings import effective_table, platform_secret, reset_value, set_secret, set_value

bp = Blueprint("platform", __name__, url_prefix="/api/platform")

PLANS = {
    "trial": {"label": "Free trial", "credits": 500, "limits": {"seats": 5, "active_jobs": 3, "ai_minutes": 300, "isha_hours": 5, "storage_days": 30}},
    "employer": {"label": "Employer SaaS", "credits": 5000, "limits": {"seats": 25, "active_jobs": 25, "ai_minutes": 3000, "isha_hours": 60, "storage_days": 180}},
    "agency": {"label": "Agency (white-label)", "credits": 10000, "limits": {"seats": 50, "active_jobs": 100, "ai_minutes": 6000, "isha_hours": 150, "storage_days": 180}},
    "enterprise": {"label": "Enterprise", "credits": 50000, "limits": {"seats": 500, "active_jobs": 1000, "ai_minutes": 30000, "isha_hours": 1000, "storage_days": 365}},
}
DEFAULT_FLAGS = {"public_jobs": True, "ai_interviews": True, "isha": True, "coding": False, "white_label": False, "api": False,
                 "certifications": True}


@bp.get("/plans")
@superadmin_required
def plans():
    return ok(PLANS)


@bp.get("/overview")
@superadmin_required
def overview():
    by_status = {s: Company.query.filter_by(status=s).count() for s in ("trial", "active", "suspended")}
    reviewed = Report.query.filter(Report.verdict.isnot(None)).all()
    agree = sum(1 for r in reviewed if (r.recommendation == r.verdict) or (r.recommendation == "proceed" and r.verdict == "proceed"))
    burn = [{"id": c.id, "name": c.name, "used": c.credits_used, "total": c.credits_total,
             "pct": round(100 * c.credits_used / max(1, c.credits_total))} for c in Company.query.all()]
    burn.sort(key=lambda x: -x["pct"])
    return ok({
        "companies": by_status,
        "users": User.query.filter_by(kind="staff").count(),
        "candidates": User.query.filter_by(kind="candidate").count(),
        "jobs_live": Job.query.filter_by(status="live").count(),
        "assessments": RoundAttempt.query.filter_by(round_type="mcq").count(),
        "ai_interviews": RoundAttempt.query.filter_by(round_type="ai_interview").count(),
        "isha_sessions": RoundAttempt.query.filter_by(round_type="f2f_isha").count(),
        "reports": Report.query.count(),
        "disputes": Report.query.filter_by(disputed=True).count(),
        "ai_human_agreement": round(100 * agree / len(reviewed)) if reviewed else None,
        "pending_questions": Question.query.filter_by(status="pending", company_id=None).count(),
        "certs_in_review": Certification.query.filter_by(status="review").count(),
        "credit_burn": burn[:8],
        "ai_configured": ai.configured(), "voice_configured": speech.configured(),
    })


@bp.get("/companies")
@superadmin_required
def companies():
    def ser(c):
        d = c.to_dict()
        d["users"] = User.query.filter_by(company_id=c.id).count()
        d["jobs"] = Job.query.filter_by(company_id=c.id).count()
        return d
    return table(Company.query, [Company.name, Company.domain],
                 {"name": Company.name, "created": Company.created_at, "plan": Company.plan, "status": Company.status,
                  "credits": Company.credits_used}, "created", ser,
                 {"status": lambda q, v: q.filter(Company.status == v), "plan": lambda q, v: q.filter(Company.plan == v)})


@bp.post("/companies")
@superadmin_required
def onboard_company():
    d = body()
    if not d.get("name") or not d.get("admin_email"):
        return err("Company name and the Company Admin's email are required.")
    if User.query.filter_by(email=d["admin_email"].lower()).first():
        return err("A user with that admin email already exists.")
    plan = d.get("plan", "trial")
    p = PLANS.get(plan, PLANS["trial"])
    c = Company(name=d["name"], domain=d.get("domain"), country=d.get("country", "India"),
                timezone=d.get("timezone", "Asia/Kolkata"), gst=d.get("gst"), plan=plan,
                status="trial" if plan == "trial" else "active", credits_total=d.get("credits", p["credits"]),
                limits={**p["limits"], **(d.get("limits") or {})}, flags={**DEFAULT_FLAGS, **(d.get("flags") or {})},
                branding={"color": "#5B3FFF"})
    db.session.add(c)
    db.session.flush()
    db.session.add(Team(company_id=c.id, name="Hiring"))
    temp = d.get("admin_password") or secrets.token_urlsafe(9)
    admin = User(email=d["admin_email"].lower(), name=d.get("admin_name") or "Company Admin", kind="staff",
                 company_id=c.id, password_hash=hash_password(temp), must_change_password=not d.get("admin_password"))
    db.session.add(admin)
    db.session.flush()
    db.session.add(RoleAssignment(user_id=admin.id, company_id=c.id, role="company_admin", scope_type="company", scope_id=c.id))
    install_defaults(c.id)
    log("company.onboard", "company", c.id, company_id=c.id, plan=plan)
    db.session.commit()
    return ok({"company": c.to_dict(), "admin": admin.public(), "temporary_password": temp,
               "invite_expires": (datetime.utcnow() + timedelta(days=7)).isoformat() + "Z"})


@bp.get("/companies/<int:cid>")
@superadmin_required
def company_detail(cid):
    c = db.session.get(Company, cid)
    if not c:
        return err("Not found", 404)
    admins = [db.session.get(User, r.user_id).public() for r in RoleAssignment.query.filter_by(company_id=cid, role="company_admin").all()]
    return ok({"company": c.to_dict(), "admins": admins,
               "teams": [t.to_dict() for t in Team.query.filter_by(company_id=cid).all()],
               "counts": {"users": User.query.filter_by(company_id=cid).count(), "jobs": Job.query.filter_by(company_id=cid).count(),
                          "applications": Application.query.join(Job).filter(Job.company_id == cid).count()}})


@bp.patch("/companies/<int:cid>")
@superadmin_required
def company_update(cid):
    c = db.session.get(Company, cid)
    if not c:
        return err("Not found", 404)
    d = body()
    for f in ("name", "domain", "country", "timezone", "gst", "plan", "status"):
        if f in d:
            setattr(c, f, d[f])
    if "limits" in d:
        c.limits = {**(c.limits or {}), **d["limits"]}
    if "flags" in d:
        c.flags = {**(c.flags or {}), **d["flags"]}
    log("company.update", "company", cid, company_id=cid, changes=list(d.keys()))
    db.session.commit()
    return ok(c.to_dict())


@bp.post("/companies/<int:cid>/credits")
@superadmin_required
def adjust_credits(cid):
    c = db.session.get(Company, cid)
    d = body()
    if not d.get("reason"):
        return err("Give a reason for the credit change; it is logged.")
    c.credits_total = max(0, (c.credits_total or 0) + int(d.get("delta", 0)))
    log("company.credits", "company", cid, company_id=cid, delta=d.get("delta"), reason=d["reason"])
    db.session.commit()
    return ok(c.to_dict())


@bp.post("/companies/<int:cid>/support-access")
@superadmin_required
def support_access(cid):
    minutes = int(body().get("minutes", 30))
    log("support.access", "company", cid, company_id=cid, minutes=minutes)
    notify_roles(cid, ["company_admin"], "Code2Hire support is viewing your workspace",
                 f"Support access for {minutes} minutes by {g.user.name}. Every view is logged.", "/app/audit")
    db.session.commit()
    return ok({"company_id": cid, "until": (datetime.utcnow() + timedelta(minutes=minutes)).isoformat() + "Z"})


# ---------------------------------------------------------------- settings and keys

@bp.get("/settings")
@superadmin_required
def get_settings():
    return ok(effective_table("platform", 0))


@bp.put("/settings")
@superadmin_required
def put_settings():
    d = body()
    if d.get("reset"):
        reset_value("platform", 0, d["key"])
    else:
        set_value("platform", 0, d["key"], d.get("value"), d.get("locked", False))
    log("settings.platform", "setting", None, key=d.get("key"))
    db.session.commit()
    return ok(effective_table("platform", 0))


def _mask(v):
    return (v[:4] + "…" + v[-4:]) if v and len(v) > 10 else ("set" if v else "")


@bp.get("/integrations")
@superadmin_required
def integrations():
    from flask import current_app
    return ok({
        "anthropic_api_key": _mask(platform_secret("anthropic_api_key", current_app.config["ANTHROPIC_API_KEY"])),
        "azure_speech_key": _mask(platform_secret("azure_speech_key", current_app.config["AZURE_SPEECH_KEY"])),
        "azure_speech_region": platform_secret("azure_speech_region", current_app.config["AZURE_SPEECH_REGION"]),
        "anthropic_ok": ai.configured(), "azure_ok": speech.configured(),
    })


@bp.put("/integrations")
@superadmin_required
def put_integrations():
    d = body()
    for k in ("anthropic_api_key", "azure_speech_key", "azure_speech_region"):
        if d.get(k):
            set_secret(k, d[k].strip())
    log("integrations.update", "setting", None, keys=[k for k in d if d.get(k)])
    db.session.commit()
    return integrations()


@bp.post("/integrations/test")
@superadmin_required
def test_integrations():
    which = body().get("which")
    if which == "anthropic":
        if not ai.configured():
            return err("Add an Anthropic API key first.")
        res = ai.ask_json("connection test", 'Return JSON {"ok": true, "hello": "from Hira"}', {"ok": False})
        return ok(res)
    if which == "azure":
        try:
            t = speech.issue_token()
            return ok({"ok": bool(t), "region": t["region"] if t else None, "voices": len(speech.voices())})
        except Exception as e:
            return err(f"Azure Speech test failed: {e}")
    return err("Unknown integration")


# ---------------------------------------------------------------- shared content

@bp.get("/questions")
@superadmin_required
def global_questions():
    return table(Question.query.filter(Question.company_id.is_(None)), [Question.text, Question.skill],
                 {"skill": Question.skill, "level": Question.level, "created": Question.created_at}, "created",
                 None, {"status": lambda q, v: q.filter(Question.status == v), "skill": lambda q, v: q.filter(Question.skill == v)})


@bp.post("/questions/generate")
@superadmin_required
def generate_global_questions():
    d = body()
    items = ai.generate_mcq(d.get("skills") or ["Java"], int(d.get("level", 3)), int(d.get("n", 5)))
    for it in items:
        db.session.add(Question(company_id=None, skill=it.get("skill"), level=it.get("level", 3), text=it["text"],
                                code=it.get("code"), options=it["options"], answer=int(it.get("answer", 0)),
                                explanation=it.get("explanation"), status="pending", source="ai"))
    db.session.commit()
    return ok({"created": len(items)})


@bp.post("/questions/<int:qid>/review")
@superadmin_required
def review_question(qid):
    q = db.session.get(Question, qid)
    d = body()
    for f in ("text", "options", "answer", "skill", "level", "explanation", "code"):
        if f in d:
            setattr(q, f, d[f])
    q.status = d.get("status", "approved")
    log("question.review", "question", qid, status=q.status)
    db.session.commit()
    return ok(q.to_dict())


@bp.get("/templates")
@superadmin_required
def global_templates():
    return ok([t.to_dict() for t in HiringTemplate.query.filter(HiringTemplate.company_id.is_(None)).all()])


@bp.post("/templates")
@superadmin_required
def create_global_template():
    d = body()
    t = HiringTemplate(company_id=None, name=d["name"], description=d.get("description"), rounds=d.get("rounds", []),
                       rubric=d.get("rubric", []), created_by=g.user.id)
    db.session.add(t)
    db.session.commit()
    return ok(t.to_dict())


@bp.get("/certifications/review")
@superadmin_required
def certs_in_review():
    return ok([c.to_dict() for c in Certification.query.filter_by(status="review").all()])


@bp.post("/certifications/<int:cid>/decide")
@superadmin_required
def decide_cert(cid):
    c = db.session.get(Certification, cid)
    c.status = "published" if body().get("approve") else "draft"
    log("cert.review", "certification", cid, status=c.status)
    db.session.commit()
    return ok(c.to_dict())


@bp.get("/audit")
@superadmin_required
def audit():
    def ser(a):
        d = a.to_dict()
        u = db.session.get(User, a.actor_id) if a.actor_id else None
        d["actor"] = u.name if u else "System"
        return d
    return table(AuditLog.query, [AuditLog.action, AuditLog.target_type], {"created": AuditLog.created_at, "action": AuditLog.action},
                 "created", ser, {"company_id": lambda q, v: q.filter(AuditLog.company_id == int(v)),
                                  "action": lambda q, v: q.filter(AuditLog.action.ilike(f"%{v}%"))})


@bp.get("/users")
@superadmin_required
def all_users():
    return table(User.query, [User.name, User.email], {"name": User.name, "created": User.created_at}, "created",
                 lambda u: u.public(), {"kind": lambda q, v: q.filter(User.kind == v)})
