"""Candidates with Disha: profile, resume, job board and matching, applications, practice, skill checks, badges, learning, privacy."""
import io
from datetime import datetime, timedelta

from flask import Blueprint, g, request

from extensions import db
from models import (Application, CandidateProfile, Company, Credential, Job, LearningPath, Notification, Report, RoundAttempt,
                    User)
from routes.utils import body, err, ok, table
from services import validate as V
from services import ai, files
from services.audit import log
from services.perms import auth_required
from services.pipeline import ROUND_TYPES, join_window, round_name, skill_match
from services.settings import resolve

bp = Blueprint("candidate", __name__, url_prefix="/api/me")


def profile():
    p = CandidateProfile.query.filter_by(user_id=g.user.id).first()
    if not p:
        p = CandidateProfile(user_id=g.user.id, skills=[])
        db.session.add(p)
        db.session.flush()
    return p


@bp.get("")
@auth_required
def home():
    p = profile()
    apps = Application.query.filter_by(candidate_id=g.user.id).all()
    invites = []
    for a in apps:
        for att in RoundAttempt.query.filter(RoundAttempt.application_id == a.id,
                                             RoundAttempt.status.in_(["invited", "scheduled", "in_progress", "paused"])).all():
            j = db.session.get(Job, a.job_id)
            can_join, opens = join_window(att)
            invites.append({"attempt_id": att.id, "type": att.round_type, "name": round_name(att, j), "job": j.title,
                            "status": att.status, "deadline_at": att.deadline_at.isoformat() + "Z" if att.deadline_at else None,
                            "scheduled_at": att.scheduled_at.isoformat() + "Z" if att.scheduled_at else None,
                            "can_join": can_join, "opens_at": opens.isoformat() + "Z" if opens else None})
    badges = Credential.query.filter_by(user_id=g.user.id, revoked=False).count()
    goal = (p.target_roles or [None])[0]
    db.session.commit()
    return ok({"user": g.user.public(), "profile": p.to_dict(), "invites": invites,
               "stats": {"applications": len(apps), "badges": badges,
                         "verified_skills": sum(1 for s in p.skills or [] if s.get("verified")),
                         "practice": RoundAttempt.query.filter_by(practice_user_id=g.user.id).count()},
               "goal": goal, "completeness": _completeness(p)})


def _completeness(p):
    checks = [bool(p.headline), bool(p.resume_text), bool(p.skills), bool(p.location), bool(p.target_roles),
              any(s.get("verified") for s in p.skills or [])]
    return {"pct": int(100 * sum(checks) / len(checks)),
            "missing": [n for n, c in zip(["headline", "resume", "skills", "location", "goal", "a verified skill"], checks) if not c]}


@bp.patch("/profile")
@auth_required
def update_profile():
    p = profile()
    d = body()
    c = V.Checker()
    if "name" in d:
        name = c.add("name", *V.person_name(d.get("name")))
    if "phone" in d:
        d["phone"] = c.add("phone", *V.phone(d.get("phone")))
    for k, label in (("headline", "Headline"), ("location", "City")):
        if k in d:
            d[k] = c.add(k, *V.text(d.get(k), 120, label=label))
    if "experience_years" in d:
        d["experience_years"] = c.add("experience_years", *V.integer(d.get("experience_years"), 0, 60, label="Years of experience"))
    if "visibility" in d and d["visibility"] not in ("everyone", "applied", "nobody"):
        c.add("visibility", None, "Choose who can see your profile.")
    if "target_roles" in d and not isinstance(d["target_roles"], list):
        c.add("target_roles", None, "Target roles must be a list.")
    if "skills" in d and (not isinstance(d["skills"], list) or any(not isinstance(s, dict) or not str(s.get("name") or "").strip() for s in d["skills"])):
        c.add("skills", None, "Each skill needs a name.")
    if c:
        return c.response()
    for f in ("headline", "location", "phone", "experience_years", "target_roles", "visibility"):
        if f in d:
            setattr(p, f, d[f] if f != "target_roles" else [str(x)[:120] for x in d[f]][:5])
    if "name" in d:
        g.user.name = name
    if "skills" in d:
        verified = {s["name"].lower(): s for s in p.skills or [] if s.get("verified")}
        new = []
        for s in d["skills"]:
            v = verified.get(s["name"].lower())
            new.append(v if v else {"name": s["name"], "level": int(s.get("level", 2)), "verified": False, "source": "self"})
        for k, v in verified.items():  # verified skills can't be removed by editing
            if k not in {s["name"].lower() for s in new}:
                new.append(v)
        p.skills = new
    db.session.commit()
    return ok(p.to_dict())


@bp.post("/resume")
@auth_required
def resume():
    p = profile()
    if "file" in request.files:
        try:
            text = files.resume_text(request.files["file"])
        except files.FileProblem as e:
            return err(str(e))
    else:
        text = body().get("text") or ""
    if len(text.strip()) < 20:
        return err("That resume looks empty.")
    p.resume_text = text[:30000]
    have = {s["name"].lower() for s in p.skills or []}
    found = [s for s in ai.extract_skills(text) if s.lower() not in have]
    p.skills = (p.skills or []) + [{"name": s, "level": 2, "verified": False, "source": "resume"} for s in found]
    log("candidate.resume", "user", g.user.id)
    db.session.commit()
    return ok({"profile": p.to_dict(), "found_skills": found})


@bp.post("/path")
@auth_required
def path():
    p = profile()
    goal = body().get("goal") or (p.target_roles or ["your next role"])[0]
    p.target_roles = [goal]
    db.session.commit()
    return ok(ai.disha_path(goal, p.skills or []))


# ---------------------------------------------------------------- jobs

def _job_public(j, p):
    c = db.session.get(Company, j.company_id)
    score, got, missing = skill_match(j, p.skills or [])
    return {"id": j.id, "title": j.title, "company": None if j.client_hidden else (c.name if c else ""),
            "location": j.location, "work_mode": j.work_mode, "level": j.level, "skills": j.skills,
            "salary": [j.salary_min, j.salary_max] if j.salary_visible else None,
            "description": j.description, "posted": j.created_at.isoformat() + "Z",
            "match": score, "matched": got, "missing": missing,
            "applied": bool(Application.query.filter_by(job_id=j.id, candidate_id=g.user.id).first()),
            "rounds": [{"type": r["type"], "name": r.get("name") or ROUND_TYPES[r["type"]]} for r in j.rounds or []]}


@bp.get("/jobs")
@auth_required
def jobs():
    p = profile()
    q = Job.query.filter_by(status="live", visibility="public")
    if request.args.get("mode"):
        q = q.filter(Job.work_mode == request.args["mode"])
    rows = [_job_public(j, p) for j in q.all()]
    text = (request.args.get("q") or "").lower()
    if text:
        rows = [r for r in rows if text in (r["title"] + " " + (r["company"] or "") + " " + (r["location"] or "")
                                            + " " + " ".join(s["name"] if isinstance(s, dict) else s for s in r["skills"] or [])).lower()]
    sort = request.args.get("sort", "match")
    rows.sort(key=lambda r: -(r["match"] or 0) if sort == "match" else r["posted"], reverse=sort == "posted")
    page, size = int(request.args.get("page", 1)), int(request.args.get("size", 12))
    return ok({"items": rows[(page - 1) * size: page * size], "total": len(rows), "page": page, "size": size,
               "pages": max(1, (len(rows) + size - 1) // size)})


@bp.get("/jobs/<int:jid>")
@auth_required
def job(jid):
    j = Job.query.filter_by(id=jid, status="live").first()
    if not j or (j.visibility != "public" and not Application.query.filter_by(job_id=jid, candidate_id=g.user.id).first()):
        return err("This job isn't open.", 404)
    return ok(_job_public(j, profile()))


@bp.post("/jobs/<int:jid>/apply")
@auth_required
def apply(jid):
    j = Job.query.filter_by(id=jid, status="live").first()
    tok = body().get("invite")
    if not j or (j.visibility != "public" and j.invite_token != tok):
        return err("This job isn't open for applications.", 404)
    if Application.query.filter_by(job_id=jid, candidate_id=g.user.id).first():
        return err("You've already applied.")
    p = profile()
    if not p.resume_text:
        return err("Add your resume first so the team can see your experience.")
    score, got, missing = skill_match(j, p.skills or [])
    a = Application(job_id=jid, candidate_id=g.user.id, source="applied", match_score=score,
                    match_reasons={"matched": got, "missing": missing})
    db.session.add(a)
    log("application.apply", "job", jid, company_id=j.company_id)
    db.session.commit()
    return ok({"id": a.id, "match": score})


@bp.get("/applications")
@auth_required
def applications():
    out = []
    for a in Application.query.filter_by(candidate_id=g.user.id).order_by(Application.created_at.desc()).all():
        j = db.session.get(Job, a.job_id)
        c = db.session.get(Company, j.company_id)
        steps = []
        # latest attempt per round wins (a re-interview replaces the earlier one on screen)
        atts = {att.round_index: att for att in RoundAttempt.query.filter_by(application_id=a.id).order_by(RoundAttempt.id.asc()).all()}
        for i, r in enumerate(j.rounds or []):
            att = atts.get(i)
            can_join, opens = join_window(att) if att else (False, None)
            steps.append({"name": r.get("name") or ROUND_TYPES.get(r["type"], r["type"]), "type": r["type"],
                          "status": att.status if att else ("upcoming" if i > a.current_round else "skipped"),
                          "attempt_id": att.id if att else None,
                          "deadline_at": att.deadline_at.isoformat() + "Z" if att and att.deadline_at else None,
                          "scheduled_at": att.scheduled_at.isoformat() + "Z" if att and att.scheduled_at else None,
                          "can_join": can_join, "opens_at": opens.isoformat() + "Z" if opens else None})
        stage = {"applied": "Applied", "shortlisted": "Shortlisted", "in_round": "In progress", "awaiting_review": "Being reviewed",
                 "decision": "Being reviewed", "on_hold": "Being reviewed", "offer": "Offer", "hired": "Hired",
                 "rejected": "Not selected", "withdrawn": "Withdrawn"}.get(a.stage, a.stage)
        out.append({"id": a.id, "job": {"id": j.id, "title": j.title, "company": None if j.client_hidden else c.name},
                    "stage": stage, "raw_stage": a.stage, "applied": a.created_at.isoformat() + "Z", "steps": steps,
                    "match": a.match_score})
    return ok(out)


@bp.post("/applications/<int:aid>/withdraw")
@auth_required
def withdraw(aid):
    a = Application.query.filter_by(id=aid, candidate_id=g.user.id).first_or_404()
    a.stage = "withdrawn"
    log("application.withdraw", "application", aid)
    db.session.commit()
    return ok()


# ---------------------------------------------------------------- practice and skill checks

PRACTICE_CFG = {"integrity.warnings_allowed": 99, "integrity.instant_pause": [], "integrity.fullscreen": False,
                "integrity.face_check": False, "integrity.block_paste": False, "pass.auto": False}


@bp.post("/practice")
@auth_required
def practice():
    """Mock interview or practice MCQ. Never seen by employers."""
    d = body()
    rtype = d.get("type", "ai_interview")
    if rtype not in ("ai_interview", "mcq"):
        return err("Practice is available for AI interviews and MCQs.")
    skills = d.get("skills") or [s["name"] for s in (profile().skills or [])[:3]] or ["Communication"]
    cfg = dict(PRACTICE_CFG)
    keys = ["voice.name", "voice.allowed", "voice.rate", "voice.candidate_can_choose", "voice.silence_seconds", "voice.enabled",
            "interview.followup_depth", "ai.language"]
    for k in keys:
        cfg[k] = resolve(k)[0]
    cfg.update({"title": d.get("title") or f"Practice: {d.get('role') or ', '.join(skills)}", "skills": skills,
                "level": int(d.get("level", 3)), "role_level": d.get("role_level", "Mid"),
                "interview.questions": int(d.get("questions", 4)), "interview.difficulty": d.get("difficulty", "medium"),
                "interview.minutes": int(d.get("minutes", 20)), "mcq.questions": int(d.get("questions", 8)),
                "mcq.minutes": int(d.get("minutes", 12)), "mcq.randomise": True})
    att = RoundAttempt(practice_user_id=g.user.id, round_type=rtype, config=cfg, status="invited",
                       deadline_at=datetime.utcnow() + timedelta(days=7))
    db.session.add(att)
    db.session.commit()
    return ok({"attempt_id": att.id})


@bp.post("/skill-check")
@auth_required
def skill_check():
    """A short proctored MCQ. Pass it and the skill becomes verified with a badge."""
    d = body()
    skill = d.get("skill")
    level = int(d.get("level", 2))
    if not skill:
        return err("Choose a skill.")
    recent = Credential.query.filter_by(user_id=g.user.id, skill=skill, level=level, revoked=False).first()
    if recent:
        return err(f"You already hold {skill} L{level}. Try the next level.")
    cfg = {k: resolve(k)[0] for k in ("integrity.warnings_allowed", "integrity.instant_pause", "integrity.fullscreen",
                                      "integrity.face_check", "integrity.block_paste")}
    cfg.update({"title": f"{skill} skill check · L{level}", "skills": [skill], "level": level, "skill_check": True,
                "pass_pct": 70, "mcq.questions": 8, "mcq.minutes": 12, "mcq.randomise": True, "mcq.negative_marking": False})
    att = RoundAttempt(practice_user_id=g.user.id, round_type="mcq", config=cfg, status="invited",
                       deadline_at=datetime.utcnow() + timedelta(days=2))
    db.session.add(att)
    db.session.commit()
    return ok({"attempt_id": att.id})


@bp.get("/practice")
@auth_required
def practice_list():
    out = []
    for att in RoundAttempt.query.filter_by(practice_user_id=g.user.id).order_by(RoundAttempt.created_at.desc()).all():
        r = Report.query.filter_by(attempt_id=att.id).first()
        out.append({"id": att.id, "type": att.round_type, "title": (att.config or {}).get("title"), "status": att.status,
                    "score": att.score, "skill_check": bool((att.config or {}).get("skill_check")),
                    "created_at": att.created_at.isoformat() + "Z", "report": r.sections if r else None})
    return ok(out)


@bp.get("/badges")
@auth_required
def badges():
    return ok([c.to_dict() for c in Credential.query.filter_by(user_id=g.user.id).order_by(Credential.created_at.desc()).all()])


# ---------------------------------------------------------------- learning

@bp.get("/learning")
@auth_required
def learning():
    return ok([lp.to_dict() for lp in LearningPath.query.filter_by(user_id=g.user.id).all()])


@bp.post("/learning")
@auth_required
def new_learning():
    d = body()
    p = profile()
    skill = d.get("skill") or "Communication"
    cur = next((s.get("level", 1) for s in p.skills or [] if s["name"].lower() == skill.lower()), 1)
    goal = d.get("goal") or (p.target_roles or ["your next role"])[0]
    data = ai.learning_path(goal, skill, cur)
    lp = LearningPath(user_id=g.user.id, title=data.get("title") or f"{skill} path", skill=skill, topics=data.get("topics", []),
                      reason=d.get("reason") or f"Towards {goal}")
    db.session.add(lp)
    db.session.commit()
    return ok(lp.to_dict())


@bp.patch("/learning/<int:lid>/topics/<int:i>")
@auth_required
def toggle_topic(lid, i):
    lp = LearningPath.query.filter_by(id=lid, user_id=g.user.id).first_or_404()
    topics = [dict(t) for t in lp.topics or []]
    if 0 <= i < len(topics):
        topics[i]["done"] = bool(body().get("done", not topics[i].get("done")))
    lp.topics = topics
    db.session.commit()
    return ok(lp.to_dict())


@bp.delete("/learning/<int:lid>")
@auth_required
def delete_learning(lid):
    LearningPath.query.filter_by(id=lid, user_id=g.user.id).delete()
    db.session.commit()
    return ok()


# ---------------------------------------------------------------- feedback shared by employers

@bp.get("/feedback")
@auth_required
def feedback():
    from routes.reports import view
    out = []
    for a in Application.query.filter_by(candidate_id=g.user.id).all():
        j = db.session.get(Job, a.job_id)
        for att in RoundAttempt.query.filter_by(application_id=a.id).all():
            r = Report.query.filter_by(attempt_id=att.id, shared_with_candidate=True).first()
            if r:
                out.append(view(r, att, j, "candidate"))
    return ok(out)


@bp.post("/feedback/<int:rid>/dispute")
@auth_required
def dispute(rid):
    r = db.session.get(Report, rid)
    att = db.session.get(RoundAttempt, r.attempt_id) if r else None
    a = db.session.get(Application, att.application_id) if att else None
    if not a or a.candidate_id != g.user.id or not r.shared_with_candidate:
        return err("Not found", 404)
    note = (body().get("note") or "").strip()
    if len(note) < 10:
        return err("Tell the team what went wrong in at least a sentence (10+ characters).", fields={"note": "At least 10 characters."})
    if r.dispute_status == "open" or (r.disputed and not r.dispute_status):
        return err("You've already raised a concern about this round. The team will answer it.", 409)
    r.disputed = True
    r.dispute_note = note[:2000]
    r.disputed_at = datetime.utcnow()
    r.dispute_status = "open"
    r.dispute_resolution = r.dispute_resolved_at = r.dispute_resolved_by = None
    j = db.session.get(Job, a.job_id)
    from services.audit import notify_roles
    notify_roles(j.company_id, ["recruiter", "manager"], "A candidate raised a concern", f"{g.user.name}, {j.title}",
                 f"/app/reports/{att.id}")
    log("report.dispute", "report", rid, company_id=j.company_id)
    db.session.commit()
    return ok()


# ---------------------------------------------------------------- privacy

@bp.get("/export")
@auth_required
def export():
    p = profile()
    return ok({"user": g.user.public(), "profile": p.to_dict(),
               "applications": [a.to_dict() for a in Application.query.filter_by(candidate_id=g.user.id).all()],
               "credentials": [c.to_dict() for c in Credential.query.filter_by(user_id=g.user.id).all()],
               "learning": [lp.to_dict() for lp in LearningPath.query.filter_by(user_id=g.user.id).all()]})


@bp.delete("")
@auth_required
def delete_me():
    """Right to erasure: anonymise the account. Reports stay for employers' records without personal data."""
    if body().get("confirm") != "DELETE":
        return err('Type DELETE to confirm.')
    u = g.user
    p = profile()
    p.resume_text, p.phone, p.headline, p.location = None, None, None, None
    u.name = "Deleted user"
    u.email = f"deleted-{u.id}@deleted.code2hire"
    u.active = False
    Notification.query.filter_by(user_id=u.id).delete()
    log("candidate.delete", "user", u.id)
    db.session.commit()
    return ok()
