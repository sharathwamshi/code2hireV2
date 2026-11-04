"""Certifications: 8-step configuration, exams made of sections, grading bands, credentials, revocation."""
from datetime import datetime, timedelta

from flask import Blueprint, g, request

from extensions import db
from models import CandidateProfile, CertAttempt, Certification, Credential, RoundAttempt, User
from routes.utils import body, err, ok, table
from services.audit import log, notify
from services.perms import auth_required, can, deny, staff_required
from services.pipeline import issue_credential
from services.settings import resolve

bp = Blueprint("certs", __name__, url_prefix="/api")

FIELDS = ("name", "skills", "level", "issuer", "sections", "pass_rules", "proctoring", "id_check", "eligibility", "fee",
          "attempts_allowed", "cooldown_days", "validity_months", "output")


def cid():
    if g.user.is_superadmin and request.headers.get("X-Company-Id"):
        return int(request.headers["X-Company-Id"])
    return g.user.company_id


def _validate(c):
    problems = []
    if not c.sections:
        problems.append("Add at least one section.")
    total = sum(float(s.get("weight", 0)) for s in c.sections or [])
    if c.sections and abs(total - 100) > 0.5:
        problems.append(f"Section weights add up to {total:g}%, not 100%.")
    pr = c.pass_rules or {}
    if not (pr.get("cutoff", 0) <= pr.get("merit", 0) <= pr.get("distinction", 0)):
        problems.append("Grading bands must go cutoff ≤ merit ≤ distinction.")
    for s in c.sections or []:
        if s.get("type") not in ("mcq", "ai_interview"):
            problems.append(f"Section type {s.get('type')} isn't supported in exams yet.")
    return problems


@bp.get("/certs")
@staff_required
def list_certs():
    q = Certification.query.filter((Certification.company_id == cid()) | (Certification.company_id.is_(None)))

    def ser(c):
        d = c.to_dict()
        d["attempts"] = CertAttempt.query.filter_by(cert_id=c.id).count()
        d["holders"] = Credential.query.filter_by(cert_id=c.id, revoked=False).count()
        d["global"] = c.company_id is None
        d["problems"] = _validate(c)
        return d
    return table(q, [Certification.name], {"name": Certification.name, "created": Certification.created_at,
                                           "status": Certification.status}, "created", ser,
                 {"status": lambda q, v: q.filter(Certification.status == v)})


@bp.post("/certs")
@staff_required
def create_cert():
    if not can(g.user, "certs.manage", company_id=cid()):
        return deny()
    d = body()
    c = Certification(company_id=cid(), created_by=g.user.id, status="draft",
                      validity_months=resolve("cert.validity_months", company_id=cid())[0],
                      cooldown_days=resolve("cert.cooldown_days", company_id=cid())[0])
    for f in FIELDS:
        if f in d:
            setattr(c, f, d[f])
    c.name = c.name or "New certification"
    c.pass_rules = c.pass_rules or {"cutoff": 60, "merit": 75, "distinction": 90}
    c.output = c.output or {"verification_page": True, "linkedin": True, "badge": True, "revoke_on_integrity": True}
    db.session.add(c)
    log("cert.create", "cert", None, company_id=cid(), name=c.name)
    db.session.commit()
    return ok(c.to_dict())


@bp.get("/certs/<int:cert_id>")
@auth_required
def get_cert(cert_id):
    c = db.session.get(Certification, cert_id)
    if not c:
        return err("Not found", 404)
    d = c.to_dict()
    d["problems"] = _validate(c)
    if g.user.kind == "candidate":
        d["eligible"], d["why"] = _eligible(c, g.user)
        d["my_attempts"] = [a.to_dict() for a in CertAttempt.query.filter_by(cert_id=c.id, user_id=g.user.id).all()]
    return ok(d)


@bp.patch("/certs/<int:cert_id>")
@staff_required
def update_cert(cert_id):
    c = Certification.query.filter_by(id=cert_id, company_id=cid()).first()
    if not c or not can(g.user, "certs.manage", company_id=cid()):
        return deny()
    if c.status == "published" and CertAttempt.query.filter_by(cert_id=c.id).count():
        locked = {"sections", "pass_rules"} & set(body().keys())
        if locked:
            return err("Sections and grading are locked once people have taken the exam. Duplicate it to make a new version.")
    for f in FIELDS:
        if f in body():
            setattr(c, f, body()[f])
    log("cert.update", "cert", cert_id, company_id=cid())
    db.session.commit()
    return ok({**c.to_dict(), "problems": _validate(c)})


@bp.post("/certs/<int:cert_id>/publish")
@staff_required
def publish_cert(cert_id):
    c = Certification.query.filter_by(id=cert_id, company_id=cid()).first()
    if not c or not can(g.user, "certs.manage", company_id=cid()):
        return deny()
    problems = _validate(c)
    if problems:
        return err(" ".join(problems))
    # 'Code2Hire Verified' needs Superadmin review; company-issued certificates publish at once.
    c.status = "review" if body().get("request_verified") else "published"
    log("cert.publish", "cert", cert_id, company_id=cid(), status=c.status)
    db.session.commit()
    return ok(c.to_dict())


@bp.post("/certs/<int:cert_id>/retire")
@staff_required
def retire_cert(cert_id):
    c = Certification.query.filter_by(id=cert_id, company_id=cid()).first()
    if not c or not can(g.user, "certs.manage", company_id=cid()):
        return deny()
    c.status = "retired"
    db.session.commit()
    return ok(c.to_dict())


@bp.get("/certs/<int:cert_id>/attempts")
@staff_required
def cert_attempts(cert_id):
    c = db.session.get(Certification, cert_id)
    if not c or (c.company_id != cid() and not g.user.is_superadmin):
        return deny()
    q = CertAttempt.query.filter_by(cert_id=cert_id).join(User, User.id == CertAttempt.user_id)

    def ser(a):
        u = db.session.get(User, a.user_id)
        return {**a.to_dict(), "name": u.name, "email": u.email}
    return table(q, [User.name, User.email], {"created": CertAttempt.created_at, "score": CertAttempt.score}, "created", ser,
                 {"status": lambda q, v: q.filter(CertAttempt.status == v)})


@bp.post("/cert-attempts/<int:ca_id>/decide")
@staff_required
def decide_attempt(ca_id):
    """Human review for attempts held because of integrity events."""
    ca = db.session.get(CertAttempt, ca_id)
    c = db.session.get(Certification, ca.cert_id) if ca else None
    if not c or (c.company_id != cid() and not g.user.is_superadmin) or not can(g.user, "certs.manage", company_id=cid()):
        return deny()
    if ca.status != "review":
        return err("Nothing to decide.")
    if body().get("approve"):
        _grant(ca, c)
    else:
        ca.status = "completed"
        ca.passed = False
        notify(ca.user_id, f"{c.name}: result", "After review, this attempt could not be certified.", "/me/certifications")
    db.session.commit()
    return ok(ca.to_dict())


# ---------------------------------------------------------------- candidate side

@bp.get("/certs-catalog")
@auth_required
def catalog():
    rows = []
    for c in Certification.query.filter_by(status="published").all():
        d = {k: getattr(c, k) for k in ("id", "name", "skills", "level", "issuer", "fee", "validity_months", "attempts_allowed",
                                        "proctoring", "sections")}
        d["company_id"] = c.company_id
        d["verified"] = c.company_id is None
        d["eligible"], d["why"] = _eligible(c, g.user)
        d["minutes"] = sum(int(s.get("minutes", 0)) for s in c.sections or [])
        rows.append(d)
    return ok(rows)


def _eligible(c, user):
    el = c.eligibility or {}
    attempts = CertAttempt.query.filter_by(cert_id=c.id, user_id=user.id).order_by(CertAttempt.created_at.desc()).all()
    if any(a.passed for a in attempts):
        return False, "You already hold this certification."
    if len(attempts) >= (c.attempts_allowed or 99):
        return False, f"You've used all {c.attempts_allowed} attempts."
    if attempts and attempts[0].created_at > datetime.utcnow() - timedelta(days=c.cooldown_days or 0):
        when = attempts[0].created_at + timedelta(days=c.cooldown_days)
        return False, f"You can retake after {when:%d %b}."
    if attempts and attempts[0].status == "in_progress":
        return True, "Continue your attempt."
    if el.get("prerequisite_skill"):
        p = CandidateProfile.query.filter_by(user_id=user.id).first()
        lvl = next((s.get("level", 0) for s in (p.skills if p else []) or []
                    if s["name"].lower() == el["prerequisite_skill"].lower() and s.get("verified")), 0)
        if lvl < int(el.get("prerequisite_level", 1)):
            return False, f"Needs verified {el['prerequisite_skill']} L{el.get('prerequisite_level', 1)} first."
    return True, ""


def _section_attempt(ca, c, idx):
    s = c.sections[idx]
    cfg = {k: resolve(k)[0] for k in ("integrity.warnings_allowed", "integrity.instant_pause", "integrity.fullscreen",
                                      "integrity.face_check", "integrity.block_paste", "voice.name", "voice.allowed",
                                      "voice.rate", "voice.candidate_can_choose", "voice.silence_seconds", "voice.enabled")}
    if c.proctoring == "none":
        cfg.update({"integrity.fullscreen": False, "integrity.face_check": False, "integrity.instant_pause": [],
                    "integrity.warnings_allowed": 99})
    cfg.update({"title": f"{c.name} · Section {idx + 1}: {s.get('name') or s['type']}", "skills": [x["name"] if isinstance(x, dict) else x for x in c.skills or []], "level": c.level,
                "mcq.questions": int(s.get("questions", 10)), "mcq.minutes": int(s.get("minutes", 20)), "mcq.randomise": True,
                "mcq.negative_marking": bool(s.get("negative_marking")), "interview.questions": int(s.get("questions", 4)),
                "interview.minutes": int(s.get("minutes", 20)), "interview.difficulty": s.get("difficulty", "medium"),
                "interview.followup_depth": 1, "section_index": idx})
    att = RoundAttempt(cert_attempt_id=ca.id, round_index=idx, round_type=s["type"], config=cfg, status="invited",
                       deadline_at=datetime.utcnow() + timedelta(days=3))
    db.session.add(att)
    db.session.flush()
    return att


@bp.post("/certs/<int:cert_id>/start")
@auth_required
def start_exam(cert_id):
    c = Certification.query.filter_by(id=cert_id, status="published").first()
    if not c:
        return err("This certification isn't available.", 404)
    ok_, why = _eligible(c, g.user)
    if not ok_:
        return err(why, 403)
    ca = CertAttempt.query.filter_by(cert_id=c.id, user_id=g.user.id, status="in_progress").first()
    if ca:
        att = RoundAttempt.query.filter(RoundAttempt.cert_attempt_id == ca.id,
                                        RoundAttempt.status.notin_(["completed", "reviewed"])).first()
        if att:
            return ok({"cert_attempt_id": ca.id, "attempt_id": att.id})
    ca = CertAttempt(cert_id=c.id, user_id=g.user.id, status="in_progress", section_scores={})
    db.session.add(ca)
    db.session.flush()
    att = _section_attempt(ca, c, 0)
    log("cert.start", "cert", c.id, company_id=c.company_id)
    db.session.commit()
    return ok({"cert_attempt_id": ca.id, "attempt_id": att.id})


def on_section_done(att):
    """Called when a section's round finishes. Starts the next section or grades the exam."""
    ca = db.session.get(CertAttempt, att.cert_attempt_id)
    c = db.session.get(Certification, ca.cert_id)
    pct = att.score if att.round_type == "mcq" else (att.score or 0) * 20
    scores = dict(ca.section_scores or {})
    scores[str(att.round_index)] = {"pct": round(pct, 1), "warnings": att.warnings, "attempt_id": att.id}
    ca.section_scores = scores
    if att.round_index + 1 < len(c.sections or []):
        nxt = _section_attempt(ca, c, att.round_index + 1)
        return f"next_section:{nxt.id}"
    total = 0
    failed_min = False
    for i, s in enumerate(c.sections):
        sc = scores.get(str(i), {}).get("pct", 0)
        total += sc * float(s.get("weight", 0)) / 100
        if s.get("minimum") and sc < float(s["minimum"]):
            failed_min = True
    ca.score = round(total, 1)
    pr = c.pass_rules or {}
    grade = None
    if not failed_min and total >= pr.get("cutoff", 60):
        grade = "Distinction" if total >= pr.get("distinction", 90) else ("Merit" if total >= pr.get("merit", 75) else "Pass")
    ca.grade = grade
    warnings = sum(v.get("warnings", 0) for v in scores.values())
    allowed = int(resolve("integrity.warnings_allowed")[0])
    if grade and warnings > allowed and (c.output or {}).get("revoke_on_integrity", True):
        ca.status = "review"
        notify(ca.user_id, f"{c.name}: under review", "A reviewer will check the integrity events before issuing your certificate.",
               "/me/certifications")
        return "review"
    if grade:
        _grant(ca, c)
        return "certified"
    ca.status = "completed"
    ca.passed = False
    notify(ca.user_id, f"{c.name}: not this time", f"You scored {ca.score}%. You can retake after {c.cooldown_days} days.",
           "/me/certifications")
    return "not_passed"


def _grant(ca, c):
    ca.status = "completed"
    ca.passed = True
    ca.grade = ca.grade or "Pass"
    skill = (c.skills or [None])[0]
    skill = skill["name"] if isinstance(skill, dict) else skill
    issue_credential(ca.user_id, "certificate", c.name, skill, c.level, ca.grade,
                     issuer=c.issuer or "Code2Hire", cert_id=c.id, months=c.validity_months or 12)


@bp.get("/me/certifications")
@auth_required
def my_certs():
    out = []
    for ca in CertAttempt.query.filter_by(user_id=g.user.id).order_by(CertAttempt.created_at.desc()).all():
        c = db.session.get(Certification, ca.cert_id)
        nxt = RoundAttempt.query.filter(RoundAttempt.cert_attempt_id == ca.id,
                                        RoundAttempt.status.notin_(["completed", "reviewed"])).first()
        out.append({**ca.to_dict(), "cert": c.name, "sections": len(c.sections or []), "next_attempt_id": nxt.id if nxt else None,
                    **cert_breakdown(ca, c)})
    return ok(out)


def cert_breakdown(ca, c):
    """Score and progress as two separate things, with each section's score, weight and share of the total, so the
    overall score can be checked by hand: total = sum(section score x weight)."""
    scores = ca.section_scores or {}
    rows, done = [], 0
    for i, s in enumerate(c.sections or []):
        got = scores.get(str(i))
        w = float(s.get("weight", 0))
        if got is not None:
            done += 1
        rows.append({"name": s.get("name") or s.get("type"), "weight": w, "pct": got.get("pct") if got else None,
                     "points": round(got["pct"] * w / 100, 1) if got and got.get("pct") is not None else None,
                     "minimum": s.get("minimum"), "done": got is not None})
    total = len(c.sections or [])
    return {"breakdown": rows, "progress": {"done": done, "total": total},
            "final": ca.status in ("completed", "review") and done == total}


@bp.post("/credentials/<code>/revoke")
@staff_required
def revoke(code):
    cr = Credential.query.filter_by(code=code).first_or_404()
    c = db.session.get(Certification, cr.cert_id) if cr.cert_id else None
    if not g.user.is_superadmin and not (c and c.company_id == cid() and can(g.user, "certs.manage", company_id=cid())):
        return deny()
    cr.revoked = True
    cr.revoke_reason = body().get("reason") or "Revoked by issuer"
    log("credential.revoke", "credential", cr.id, reason=cr.revoke_reason)
    notify(cr.user_id, "A credential was revoked", f"{cr.title}: {cr.revoke_reason}", "/me/badges")
    db.session.commit()
    return ok(cr.to_dict())
