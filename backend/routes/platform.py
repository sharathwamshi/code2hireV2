"""Superadmin: companies, plans and credits, feature flags, platform settings, AI and voice keys, shared content, audit."""
import re
import secrets
from datetime import datetime, timedelta

from flask import Blueprint, g, request

from extensions import db
from models import (Application, AuditLog, Certification, Company, HiringTemplate, Job, Question, Report,
                    RoleAssignment, RoundAttempt, Team, User)
from routes.utils import body, copy_name, err, ok, table
from services import validate as V
from services import ai, disputes, speech
from services.audit import log, notify_roles
from services.perms import hash_password, superadmin_required
from services.policy import install_defaults
from services.settings import check_change, effective_table, platform_secret, reset_value, set_secret, set_value

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
        "disputes": disputes.query("open").count(),
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
    c = V.Checker()
    name = c.add("name", *V.text(d.get("name"), 160, required=True, label="Company name"))
    if name and len(name) < 2:
        c.add("name", None, "Company name needs at least 2 characters.")
    admin_email = c.add("admin_email", *V.email(d.get("admin_email")))
    admin_name = c.add("admin_name", *V.person_name(d.get("admin_name")))
    domain = (d.get("domain") or "").strip().lower() or None
    if domain and not re.match(r"^([a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,24}$", domain):
        c.add("domain", None, "Enter a domain like acme.com (no https:// or slashes).")
    if d.get("plan") and d["plan"] not in PLANS:
        c.add("plan", None, "Choose a plan from the list.")
    if d.get("credits") not in (None, ""):
        c.add("credits", *V.integer(d.get("credits"), 0, 10_000_000, label="Credits"))
    gst = (d.get("gst") or "").strip().upper() or None
    if gst and not re.match(r"^\d{2}[A-Z]{5}\d{4}[A-Z][A-Z\d]Z[A-Z\d]$", gst):
        c.add("gst", None, "Enter a valid 15-character GSTIN, like 29ABCDE1234F1Z5.")
    if d.get("admin_password"):
        c.add("admin_password", None, V.password(d["admin_password"], admin_email))
    if not c.fields.get("admin_email") and User.query.filter_by(email=admin_email).first():
        c.add("admin_email", None, "A user with this email already exists.")
    if not c.fields.get("name") and Company.query.filter(db.func.lower(Company.name) == name.lower()).first():
        c.add("name", None, "A company with this name already exists.")
    if c:
        return c.response()
    d = {**d, "name": name, "admin_email": admin_email, "admin_name": admin_name, "domain": domain, "gst": gst}
    if d.get("credits") not in (None, ""):
        d["credits"] = int(float(d["credits"]))
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
    admin = User(email=admin_email, name=admin_name, kind="staff",
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
        value, e = check_change(d.get("key"), d.get("value"))
        if e:
            return err(e, fields={d.get("key") or "key": e})
        set_value("platform", 0, d["key"], value, d.get("locked", False))
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
    """Tests the key typed in the box when one is sent (without saving it), otherwise the saved key.
    Always answers with a plain sentence, and names which key was tested by its last 4 characters."""
    from flask import current_app
    d = body()
    which = d.get("which")
    if which == "anthropic":
        typed = (d.get("key") or "").strip()
        key = typed or platform_secret("anthropic_api_key", current_app.config["ANTHROPIC_API_KEY"])
        if not key:
            return err("Paste an Anthropic API key first.")
        hint, source = "…" + key[-4:], "typed" if typed else "saved"
        model = current_app.config.get("ANTHROPIC_MODEL")
        try:
            import anthropic
            cl = anthropic.Anthropic(api_key=key, max_retries=0, timeout=20)
            cl.messages.create(model=model, max_tokens=5, messages=[{"role": "user", "content": "Reply with OK."}])
            return ok({"ok": True, "message": f"Connected · {model} is responding.", "key": hint, "source": source})
        except Exception as e:
            return err(_explain_ai_error(e, model) + f" (tested the {source} key {hint})", 400)
    if which == "azure":
        typed_key = (d.get("key") or "").strip()
        typed_region = (d.get("region") or "").strip().lower()
        key, region = speech._creds()
        key, region = typed_key or key, typed_region or region
        if not key:
            return err("Paste an Azure Speech key first.")
        if not re.match(r"^[a-z0-9]{3,40}$", region or ""):
            return err("Enter a region like centralindia or eastus.")
        hint, source = "…" + key[-4:], "typed" if typed_key else "saved"
        try:
            import requests
            r = requests.post(f"https://{region}.api.cognitive.microsoft.com/sts/v1.0/issueToken",
                              headers={"Ocp-Apim-Subscription-Key": key}, timeout=10)
            if r.status_code in (401, 403):
                return err(f"Azure rejected this key for region {region}. Check the key and that it belongs to {region}. (tested the {source} key {hint})")
            r.raise_for_status()
            return ok({"ok": True, "message": f"Connected · Azure Speech is ready in {region}.", "key": hint, "source": source})
        except Exception as e:
            return err(f"Can't reach Azure Speech in {region}: {type(e).__name__}. Check the region name and the server's internet access. (tested the {source} key {hint})")
    return err("Unknown integration.")


def _explain_ai_error(e, model):
    name = type(e).__name__
    if name == "AuthenticationError":
        return "Invalid API key: Anthropic didn't accept it."
    if name == "PermissionDeniedError":
        return "This key isn't allowed to use the API. Check its workspace and permissions."
    if name == "NotFoundError":
        return f"The key works, but the model {model} isn't available to it."
    if name == "RateLimitError":
        return "The key works, but it's over its rate limit right now. Try again in a minute."
    if name in ("APIConnectionError", "APITimeoutError", "ConnectError"):
        return "Can't reach Anthropic from the server. Check its internet access."
    return f"The test failed: {name}."


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
    from services.mcq import save_generated
    skills = d.get("skills") or ["Java"]
    items = save_generated(ai.generate_mcq(skills, int(d.get("level", 3)), min(20, int(d.get("n", 5)))), None, skills, review=True)
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


@bp.get("/disputes")
@superadmin_required
def platform_disputes():
    st = request.args.get("status") or "open"
    q = disputes.query(st if st in ("open", "resolved") else None)
    rows = [disputes.row(r) for r in q.limit(300).all()]
    return ok({"items": rows, "total": len(rows)})


@bp.get("/disputes/<int:rid>")
@superadmin_required
def platform_dispute(rid):
    from routes.reports import view
    from services.pipeline import context
    r = db.session.get(Report, rid)
    if not r:
        return err("Not found", 404)
    att = db.session.get(RoundAttempt, r.attempt_id)
    app, job, cand, _ = context(att)
    if not job:
        return err("This dispute isn't linked to a job.", 404)
    out = view(r, att, job, "internal")
    from models import Company
    out["company"] = (db.session.get(Company, job.company_id) or Company(name="")).name
    out["transcript"] = [{"q": q.get("q"), "a": q.get("a")} for q in (r.sections or {}).get("questions", [])]
    return ok(out)


@bp.post("/disputes/<int:rid>/resolve")
@superadmin_required
def platform_resolve_dispute(rid):
    from services.pipeline import context
    r = db.session.get(Report, rid)
    if not r:
        return err("Not found", 404)
    att = db.session.get(RoundAttempt, r.attempt_id)
    app, job, cand, _ = context(att)
    d = body()
    good, msg = disputes.resolve(r, att, job, d.get("action"), d.get("note"), g.user)
    return ok({"message": msg}) if good else err(msg, 409 if "already" in msg else 400)


def _template_fields(d, t=None):
    from services.pipeline import ROUND_TYPES
    c = V.Checker()
    out = {}
    if t is None or "name" in d:
        out["name"] = c.add("name", *V.text(d.get("name"), 160, required=True, label="Name"))
        if out["name"] and len(out["name"]) < 2:
            c.add("name", None, "Name needs at least 2 characters.")
        if out.get("name") and not c.fields.get("name"):
            clash = HiringTemplate.query.filter(HiringTemplate.company_id.is_(None), db.func.lower(HiringTemplate.name) == out["name"].lower())
            if t is not None:
                clash = clash.filter(HiringTemplate.id != t.id)
            if clash.first():
                c.add("name", None, "A template with this name already exists.")
    if "description" in d:
        out["description"] = c.add("description", *V.text(d.get("description"), 2000, label="Description"))
    if t is None or "rounds" in d:
        from services.pipeline import clean_rounds
        rounds, rerr = clean_rounds(d.get("rounds"))
        if rerr:
            c.add("rounds", None, rerr)
        if not rounds:
            c.add("rounds", None, "Add at least one round.")
        if len(rounds) > 10:
            c.add("rounds", None, "A template can have at most 10 rounds.")
        out["rounds"] = rounds
    if "rubric" in d:
        out["rubric"] = d.get("rubric") or []
    return out, c


@bp.get("/templates")
@superadmin_required
def global_templates():
    q = HiringTemplate.query.filter(HiringTemplate.company_id.is_(None))
    if request.args.get("archived") != "true":
        q = q.filter((HiringTemplate.archived.is_(None)) | (HiringTemplate.archived.is_(False)))
    return ok([t.to_dict() for t in q.order_by(HiringTemplate.name).all()])


@bp.post("/templates")
@superadmin_required
def create_global_template():
    f, c = _template_fields(body())
    if c:
        return c.response()
    t = HiringTemplate(company_id=None, created_by=g.user.id, updated_by=g.user.id, updated_at=datetime.utcnow(), archived=False,
                       rubric=f.pop("rubric", []), **f)
    db.session.add(t)
    db.session.flush()
    log("template.create", "template", t.id, name=t.name)
    db.session.commit()
    return ok(t.to_dict())


def _global_template(tid):
    t = db.session.get(HiringTemplate, tid)
    return t if t and t.company_id is None else None


@bp.patch("/templates/<int:tid>")
@superadmin_required
def update_global_template(tid):
    t = _global_template(tid)
    if not t:
        return err("Template not found.", 404)
    d = body()
    f, c = _template_fields(d, t)
    if c:
        return c.response()
    for k, v in f.items():
        setattr(t, k, v)
    if "archived" in d:
        t.archived = bool(d["archived"])
    t.updated_by, t.updated_at = g.user.id, datetime.utcnow()
    log("template.update", "template", t.id, fields=list(d.keys()))
    db.session.commit()
    return ok(t.to_dict())


@bp.post("/templates/<int:tid>/duplicate")
@superadmin_required
def duplicate_global_template(tid):
    t = _global_template(tid)
    if not t:
        return err("Template not found.", 404)
    name = copy_name(t.name, lambda n: HiringTemplate.query.filter(HiringTemplate.company_id.is_(None), HiringTemplate.name == n).first() is not None)
    n = HiringTemplate(company_id=None, name=name, description=t.description, rounds=t.rounds, rubric=t.rubric,
                       created_by=g.user.id, updated_by=g.user.id, updated_at=datetime.utcnow(), archived=False)
    db.session.add(n)
    db.session.flush()
    log("template.duplicate", "template", n.id, source=t.id)
    db.session.commit()
    return ok(n.to_dict())


@bp.delete("/templates/<int:tid>")
@superadmin_required
def delete_global_template(tid):
    """Removes the template. Jobs already created from it keep their own copy of the rounds, so nothing else changes."""
    t = _global_template(tid)
    if not t:
        return err("Template not found.", 404)
    log("template.delete", "template", t.id, name=t.name)
    db.session.delete(t)
    db.session.commit()
    return ok()


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
