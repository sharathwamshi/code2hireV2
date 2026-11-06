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
from services import files, throttle
from services import validate as V
from services.validate import iso
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
    """active | not_sent | sent | opened | expired | no_link for the candidate's account.
    not_sent: a link exists but the team hasn't copied or sent it yet, so we never claim "sent" too early."""
    if user.password_hash and not user.must_change_password:
        return "active"
    last = InviteLink.query.filter_by(user_id=user.id).order_by(InviteLink.id.desc()).first()
    if not last or last.revoked:
        return "no_link"
    if last.used_at:
        return "active"
    if last.expires_at < datetime.utcnow():
        return "expired"
    if last.opened_at:
        return "opened"
    return "sent" if last.shared_at else "not_sent"


def _belongs(user):
    """The candidate is in this company's world: added by it or applied to one of its jobs."""
    p = CandidateProfile.query.filter_by(user_id=user.id).first()
    if p and p.source_company_id == cid():
        return True
    job_ids = [j.id for j in Job.query.filter_by(company_id=cid()).all()] or [0]
    return bool(Application.query.filter(Application.candidate_id == user.id, Application.job_id.in_(job_ids)).first())


def _clean(c, country):
    """Checks one person. Returns (clean, field_errors)."""
    chk = V.Checker()
    out = {
        "name": chk.add("name", *V.person_name(c.get("name"))),
        "email": chk.add("email", *V.email(c.get("email"))),
        "phone": chk.add("phone", *V.phone(c.get("phone"), default_country=country)),
        "location": chk.add("location", *V.text(c.get("location"), 120, label="City")),
        "headline": chk.add("headline", *V.text(c.get("headline"), 120, label="Headline")),
        "experience_years": chk.add("experience_years", *V.integer(c.get("experience_years"), 0, 60, label="Years of experience")),
        "skills": chk.add("skills", *V.skills(c.get("skills"), 20)),
        "resume_text": (c.get("resume_text") or "")[:30000],
    }
    if len(c.get("resume_text") or "") > 30000:
        chk.add("resume_text", None, "The resume text is too long (30,000 characters at most).")
    return out, chk.fields


def _existing(email, phone):
    """What already exists for this email/phone, from this company's point of view."""
    u = User.query.filter_by(email=email).first() if email else None
    if u and u.kind != "candidate":
        return {"kind": "staff"}
    if u:
        return {"kind": "in_company" if _belongs(u) else "account", "user_id": u.id, "name": u.name, "email": u.email}
    if phone:
        p = CandidateProfile.query.filter_by(phone=phone, source_company_id=cid()).first()
        if p:
            other = db.session.get(User, p.user_id)
            return {"kind": "same_phone", "user_id": other.id, "name": other.name, "email": other.email}
    return None


def _add_one(c, job, country="91", dry=False, picked=False):
    """picked: chosen from the search dropdown (V02.00.05). A Disha candidate picked for a job keeps their own
    profile: it isn't claimed by this company, and they're told they can decline."""
    clean, fields = _clean(c, country)
    row = {"name": clean["name"], "email": clean["email"], "phone": clean["phone"]}
    if fields:
        return {**row, "status": "invalid", "fields": fields, "error": next(iter(fields.values()))}
    ex = _existing(clean["email"], clean["phone"])
    if ex and ex["kind"] == "staff":
        return {**row, "status": "invalid", "fields": {"email": "This email belongs to a hiring-team member."},
                "error": "This email belongs to a hiring-team member."}
    if ex and ex["kind"] == "same_phone":
        msg = f"{ex['name']} ({ex['email']}) already uses this phone number."
        return {**row, "status": "duplicate", "fields": {"phone": msg}, "error": msg, "existing": ex}
    u = db.session.get(User, ex["user_id"]) if ex else None
    already_applied = bool(u and job and Application.query.filter_by(job_id=job.id, candidate_id=u.id).first())
    if ex and ex["kind"] == "in_company" and (not job or already_applied):
        msg = "Already in your talent pool" + (f" and on {job.title}." if job else ".")
        return {**row, "status": "duplicate", "error": msg, "existing": ex, "user_id": u.id, "reason": "in_job" if already_applied else "in_pool"}
    if already_applied:
        return {**row, "status": "duplicate", "error": f"Already on {job.title}.", "existing": ex, "user_id": u.id, "reason": "in_job"}
    if dry:
        kind = "new" if not ex else "in_pool" if ex["kind"] == "in_company" else "account"
        note = {"new": "", "in_pool": "Already in your talent pool: they'll be added to this job.",
                "account": "Has a Code2Hire account already; they keep their own sign-in."}[kind]
        return {**row, "status": "ok", "kind": kind, "note": note}
    existing = bool(u)
    if not u:
        u = User(email=clean["email"], name=clean["name"], kind="candidate", password_hash=hash_password(secrets.token_urlsafe(16)),
                 must_change_password=True)
        db.session.add(u)
        db.session.flush()
    resume = clean["resume_text"]
    p = CandidateProfile.query.filter_by(user_id=u.id).first()
    skills = [{"name": s, "level": 2, "verified": False, "source": "added"} for s in clean["skills"]]
    found = [{"name": s, "level": 2, "verified": False, "source": "resume"} for s in ai.extract_skills(resume)]
    if not p:
        merged, seen = [], set()
        for s in skills + found:
            if s["name"].lower() not in seen:
                seen.add(s["name"].lower())
                merged.append(s)
        p = CandidateProfile(user_id=u.id, headline=clean["headline"], phone=clean["phone"], location=clean["location"],
                             experience_years=clean["experience_years"], resume_text=resume, skills=merged,
                             source_company_id=cid(), added_by=g.user.id)
        db.session.add(p)
    else:
        if not p.source_company_id and not picked:
            p.source_company_id, p.added_by = cid(), g.user.id
        for k in ("headline", "phone", "location", "experience_years"):
            if clean.get(k) and not getattr(p, k):
                setattr(p, k, clean[k])
        if resume and not p.resume_text:
            p.resume_text = resume
    app_id = None
    if job:
        a = Application.query.filter_by(job_id=job.id, candidate_id=u.id).first()
        if not a:
            score, got, missing = skill_match(job, p.skills or [])
            a = Application(job_id=job.id, candidate_id=u.id, source="picked" if picked else "added", owner_id=g.user.id, match_score=score,
                            match_reasons={"matched": got, "missing": missing})
            db.session.add(a)
            db.session.flush()
        app_id = a.id
    out = {**row, "status": "added", "user_id": u.id, "name": u.name, "email": u.email, "existing": existing,
           "application_id": app_id, "phone": p.phone}
    if link_state(u) != "active":
        token, link = new_link(u, cid(), job.id if job else None)
        out.update({"link": f"/welcome/{token}", "expires_at": iso(link.expires_at), "state": "not_sent"})
    else:
        out.update({"state": "active", "note": "Already has an account. They sign in with their own password."})
        if job:
            notify(u.id, f"You've been added to {job.title}", "The hiring team added you to this job. If you're not interested, "
                   "you can withdraw from My applications.", "/me/applications")
    log("candidate.add", "user", u.id, company_id=cid(), job_id=job.id if job else None, existing=existing)
    return out


def _job_for_add(d):
    if d.get("job_id") in (None, ""):
        return None, None if can_any(g.user, "candidates.add", cid()) else deny()
    job = Job.query.filter_by(id=int(d["job_id"]) if str(d["job_id"]).isdigit() else 0, company_id=cid()).first()
    if not job:
        return None, err("Job not found.", 404)
    if job.status == "closed":
        return None, err("This job is closed. Reopen it or add the candidate to your talent pool only.")
    if not can(g.user, "candidates.add", job=job):
        return None, deny("You can't add candidates to this job.")
    return job, None


@bp.post("")
@staff_required
def add():
    """Add one candidate or many ({candidates: [...]}) and get a personal portal link for each.
    {dry_run: true} checks every row and returns what would happen, without saving (the list preview)."""
    d = body()
    job, problem = _job_for_add(d)
    if problem:
        return problem
    items = d.get("candidates") if isinstance(d.get("candidates"), list) else [d]
    if not items:
        return err("Add at least one person.")
    if len(items) > 200:
        return err("Add at most 200 people at a time.")
    country = str(d.get("country") or "91")
    country = country if country.isdigit() and 1 <= len(country) <= 3 else "91"
    dry = bool(d.get("dry_run"))
    results, seen = [], {}
    for i, c in enumerate(items):
        c = c if isinstance(c, dict) else {}
        picked = False
        if c.get("user_id"):
            u, why = _pickable(c.get("user_id"), job)
            if not u:
                results.append({"name": c.get("name"), "email": None, "status": "invalid", "row": i + 1, "error": why, "fields": {"name": why}})
                continue
            p = CandidateProfile.query.filter_by(user_id=u.id).first()
            c = {"name": u.name, "email": u.email, "phone": (p.phone if p else "") or "", "skills": []}
            picked = not _belongs(u)
        key = (c.get("email") or "").strip().lower()
        if key and key in seen:
            results.append({"name": c.get("name"), "email": key, "status": "duplicate", "row": i + 1,
                            "error": f"Same email as row {seen[key]} in this list."})
            continue
        if key:
            seen[key] = i + 1
        r = _add_one(c, job, country, dry, picked=picked)
        if picked:  # a Disha candidate's email stays hidden until they're on the job
            r["email"] = r["email"] if r["status"] == "added" else None
        r["row"] = i + 1
        results.append(r)
        if not dry and r["status"] == "added":
            db.session.flush()
    if dry:
        db.session.rollback()
    else:
        db.session.commit()
    count = lambda st: sum(1 for r in results if r["status"] == st)  # noqa: E731
    return ok({"results": results, "added": count("added"), "ready": count("ok"), "invalid": count("invalid"),
               "duplicates": count("duplicate"), "dry_run": dry})


def _pickable(user_id, job):
    """(user, None) when this company may pick the person from the dropdown, else (None, reason)."""
    u = db.session.get(User, int(user_id)) if str(user_id).isdigit() else None
    if not u or u.kind != "candidate" or u.active is False:
        return None, "That candidate no longer exists."
    if _belongs(u):
        return u, None
    p = CandidateProfile.query.filter_by(user_id=u.id).first()
    if not p or p.visibility != "everyone":
        return None, "This candidate's profile isn't open to companies."
    if not job:
        return None, "Pick a job to add a Disha candidate to. They're added to that job, not to your talent pool."
    return u, None


def _skill_names(p, n=6):
    return [s["name"] if isinstance(s, dict) else s for s in (p.skills or [])][:n] if p else []


@bp.get("/search")
@staff_required
def search():
    """Type-ahead for "Add candidate" (V02.00.05): your company's candidates and Disha candidates whose profile is open
    to everyone. Disha candidates who aren't yours show name, headline and skills only, never email or phone."""
    if not can_any(g.user, "candidates.add", cid()):
        return deny()
    q = (request.args.get("q") or "").strip()
    if len(q) < 2:
        return ok({"items": []})
    job = None
    if str(request.args.get("job_id") or "").isdigit():
        job = Job.query.filter_by(id=int(request.args["job_id"]), company_id=cid()).first()
    like = f"%{q}%"
    company_job_ids = [j.id for j in Job.query.filter_by(company_id=cid()).all()] or [0]
    mine = {a.candidate_id for a in Application.query.filter(Application.job_id.in_(company_job_ids)).all()}
    mine |= {p.user_id for p in CandidateProfile.query.filter_by(source_company_id=cid()).all()}
    users = (User.query.filter(User.kind == "candidate", User.active.isnot(False), User.id.in_(mine or [0]),
                               (User.name.ilike(like)) | (User.email.ilike(like))).order_by(User.name).limit(10).all())
    out = []
    for u in users:
        p = CandidateProfile.query.filter_by(user_id=u.id).first()
        apps = Application.query.filter(Application.candidate_id == u.id, Application.job_id.in_(company_job_ids)).all()
        jobs = []
        here = None
        for a in apps:
            j = db.session.get(Job, a.job_id)
            jobs.append({"title": j.title, "stage": a.stage, "application_id": a.id})
            if job and a.job_id == job.id:
                here = {"stage": a.stage, "application_id": a.id}
        out.append({"user_id": u.id, "name": u.name, "email": u.email, "headline": p.headline if p else "", "skills": _skill_names(p),
                    "location": p.location if p else "", "source": "company", "jobs": jobs[:5], "in_this_job": here})
    if len(out) < 10:
        email_q = q.lower() if "@" in q else None
        disha = (db.session.query(User, CandidateProfile).join(CandidateProfile, CandidateProfile.user_id == User.id)
                 .filter(User.kind == "candidate", User.active.isnot(False), CandidateProfile.visibility == "everyone",
                         ~User.id.in_(mine or [0]), (User.name.ilike(like)) | (User.email == email_q if email_q else False))
                 .order_by(User.name).limit(10 - len(out)).all())
        for u, p in disha:
            here = None
            if job:
                a = Application.query.filter_by(job_id=job.id, candidate_id=u.id).first()
                here = {"stage": a.stage, "application_id": a.id} if a else None
            out.append({"user_id": u.id, "name": u.name, "email": None, "headline": p.headline or "", "skills": _skill_names(p),
                        "location": p.location or "", "source": "disha", "jobs": [], "in_this_job": here})
    return ok({"items": out})


@bp.get("/check")
@staff_required
def check():
    """While typing: is there already someone with this email or phone? Format problems come back too."""
    if not can_any(g.user, "candidates.add", cid()):
        return deny()
    email, e_bad = V.email(request.args.get("email"), required=False)
    phone, p_bad = V.phone(request.args.get("phone"), default_country=request.args.get("country") or "91")
    ex = None if (e_bad and p_bad) else _existing(None if e_bad else email, None if p_bad else phone)
    if ex and ex["kind"] == "account":
        ex = {"kind": "account"}  # another company's candidate: don't show their details
    jid = request.args.get("job_id")
    if ex and ex.get("user_id") and str(jid or "").isdigit():
        a = Application.query.filter_by(job_id=int(jid), candidate_id=ex["user_id"]).first()
        job = db.session.get(Job, int(jid))
        if a and job and job.company_id == cid():
            ex["in_job"] = {"stage": a.stage, "application_id": a.id, "job": job.title}
    similar = []
    name = " ".join((request.args.get("name") or "").split()).lower()
    if len(name) >= 3:
        company_job_ids = [j.id for j in Job.query.filter_by(company_id=cid()).all()] or [0]
        mine = {a.candidate_id for a in Application.query.filter(Application.job_id.in_(company_job_ids)).all()}
        mine |= {p.user_id for p in CandidateProfile.query.filter_by(source_company_id=cid()).all()}
        for u in User.query.filter(User.id.in_(mine or [0]), db.func.lower(User.name) == name).limit(5).all():
            if e_bad or u.email != email:
                similar.append({"user_id": u.id, "name": u.name, "email": u.email})
    return ok({"existing": ex, "similar": similar})


@bp.post("/parse-resume")
@staff_required
def parse_resume():
    """Upload a PDF, DOCX or TXT resume; returns the details to fill in the form (nothing is saved)."""
    if not can_any(g.user, "candidates.add", cid()):
        return deny()
    if "file" not in request.files:
        return err("Choose a resume file.")
    try:
        text = files.resume_text(request.files["file"])
    except files.FileProblem as e:
        return err(str(e))
    f = ai.resume_fields(text, company_id=cid())
    phone, bad = V.phone(f.get("phone"))
    return ok({**f, "phone": phone if not bad else (f.get("phone") or ""), "resume_text": text})


@bp.post("/parse-file")
@staff_required
def parse_file():
    """Upload a CSV or XLSX list; returns rows mapped to our fields (nothing is saved). Columns are matched by name."""
    if not can_any(g.user, "candidates.add", cid()):
        return deny()
    if "file" not in request.files:
        return err("Choose a CSV or Excel file.")
    try:
        rows, total = files.sheet_rows(request.files["file"], 200)
    except files.FileProblem as e:
        return err(str(e))
    alias = {"name": ("name", "full name", "candidate", "candidate name"), "email": ("email", "email address", "e-mail", "mail"),
             "phone": ("phone", "mobile", "phone number", "mobile number", "whatsapp", "contact"),
             "skills": ("skills", "skill", "key skills"), "location": ("city", "location"), "headline": ("headline", "title", "current role", "designation"),
             "experience_years": ("experience", "experience years", "years", "years of experience", "exp")}
    out = []
    for r in rows:
        m = {}
        for field, names in alias.items():
            for n in names:
                if r.get(n):
                    m[field] = r[n]
                    break
        if "skills" in m:
            m["skills"] = [s.strip() for s in str(m["skills"]).replace("|", ";").replace(",", ";").split(";") if s.strip()]
        out.append(m)
    if not any(r.get("email") for r in out):
        return err("We couldn't find an Email column. Use the template's headers: Name, Email, Phone, Skills, City.")
    return ok({"rows": out, "total": total, "truncated": total > 200})


@bp.get("/template.csv")
@staff_required
def template():
    from flask import Response
    csv_text = ("Name,Email,Phone,Skills,City,Headline,Experience\n"
                "Asha Rao,asha.rao@example.com,+91 98450 00001,Python; Django; SQL,Bengaluru,Backend developer,4\n"
                "Vikas Nair,vikas.nair@example.com,,React; TypeScript,Pune,Frontend developer,2\n")
    return Response("\ufeff" + csv_text, mimetype="text/csv",
                    headers={"Content-Disposition": "attachment; filename=code2hire-candidates-template.csv"})


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
        last = InviteLink.query.filter_by(user_id=u.id).order_by(InviteLink.id.desc()).first()
        return {"id": u.id, "name": u.name, "email": u.email, "phone": p.phone if p else None, "headline": p.headline if p else "",
                "added_by": by.name if by else "", "added_at": iso(u.created_at), "state": link_state(u),
                "link_expires_at": iso(last.expires_at) if last else None, "link_shared_via": last.shared_via if last else None,
                "jobs": [j.title for j in jobs if j and j.company_id == cid()], "last_login_at": iso(u.last_login_at)}
    return table(q, [User.name, User.email], {"name": User.name, "added": User.created_at}, "added", ser,
                 {"state": lambda q, v: q.filter(User.id.in_([u.id for u in q.all() if link_state(u) == v] or [0]))})


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
    jid = body().get("job_id")
    job = Job.query.filter_by(id=int(jid), company_id=cid()).first() if str(jid or "").isdigit() else None
    token, link = new_link(u, cid(), job.id if job else None)
    log("candidate.link", "user", uid, company_id=cid())
    db.session.commit()
    return ok({"link": f"/welcome/{token}", "expires_at": iso(link.expires_at), "state": "not_sent"})


@bp.post("/<int:uid>/link/shared")
@staff_required
def mark_shared(uid):
    """The team copied, emailed or messaged the link: from now on it shows as sent."""
    if not can_any(g.user, "candidates.add", cid()):
        return deny()
    u = db.session.get(User, uid)
    if not u or u.kind != "candidate" or not _belongs(u):
        return err("Not found", 404)
    via = body().get("via") if body().get("via") in ("copy", "message", "email", "manual") else "manual"
    link = InviteLink.query.filter_by(user_id=uid, revoked=False, used_at=None).order_by(InviteLink.id.desc()).first()
    if not link or link.expires_at < datetime.utcnow():
        return err("There's no active link to send. Create a new link first.", 409)
    link.shared_at = link.shared_at or datetime.utcnow()
    link.shared_via = via
    log("candidate.link.shared", "user", uid, company_id=cid(), via=via)
    db.session.commit()
    return ok({"state": link_state(u)})


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


def _guarded_find(token):
    """Like _find, but a burst of bad tokens from one address is slowed down (20 per 15 minutes)."""
    key = f"invite:{throttle.client_ip()}"
    wait = throttle.locked(key)
    if wait:
        return None, (throttle.message(wait), 429)
    link, problem = _find(token)
    if not link:
        throttle.fail(key)
        return None, (problem, 410)
    return link, None


@pub.get("/<token>")
def peek(token):
    link, problem = _guarded_find(token)
    if not link:
        return err(*problem)
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
    link, problem = _guarded_find(token)
    if not link:
        return err(*problem)
    u = db.session.get(User, link.user_id)
    if not u.active:
        return err("This account is switched off.", 403)
    link.opened_at = link.opened_at or datetime.utcnow()
    u.last_login_at = datetime.utcnow()
    log("candidate.link.open", "user", u.id, company_id=link.company_id)
    db.session.commit()
    return ok({"token": make_token(u, via="invite", lid=link.id), **me_payload(u),
               "require_password": bool(resolve("invite.require_password", company_id=link.company_id)[0])})
