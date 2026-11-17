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
from services.profile import apply_resume, next_steps, read_resume, resume_plan, strength
from services.settings import resolve
from services.skills import LEVELS, canon, find, options, role_skills, same

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
            iv = db.session.get(User, att.interviewer_id) if att.interviewer_id else None
            invites.append({"attempt_id": att.id, "type": att.round_type, "name": round_name(att, j), "job": j.title,
                            "company": (db.session.get(Company, j.company_id).name if j.company_id else None),
                            "interviewer": iv.name if iv else None, "rescheduled": bool((att.result or {}).get("rescheduled_at")),
                            "minutes": (att.config or {}).get("interview.minutes") or (att.config or {}).get("mcq.minutes"),
                            "status": att.status, "deadline_at": att.deadline_at.isoformat() + "Z" if att.deadline_at else None,
                            "scheduled_at": att.scheduled_at.isoformat() + "Z" if att.scheduled_at else None,
                            "can_join": can_join, "opens_at": opens.isoformat() + "Z" if opens else None,
                            "setup_ok": bool(((att.result or {}).get("syscheck") or {}).get("passed")),
                            "instructions": syscheck_short(att),
                            "paper_pending": not _papers().ready(att)})
    badges = Credential.query.filter_by(user_id=g.user.id, revoked=False).count()
    goal = (p.target_roles or [None])[0]
    db.session.commit()
    from models import SystemCheck
    tested = SystemCheck.query.filter(SystemCheck.user_id == g.user.id, SystemCheck.passed.is_(True),
                                      SystemCheck.created_at > datetime.utcnow() - timedelta(days=7)).first()
    practice_n = RoundAttempt.query.filter(RoundAttempt.practice_user_id == g.user.id,
                                           RoundAttempt.status.in_(("completed", "reviewed"))).count()
    ranked = _ranked_jobs(p, {})
    from services import resumes
    return ok({"user": g.user.public(), "profile": p.to_dict(), "invites": invites, "setup_tested": bool(tested),
               "resume_file": resumes.info(resumes.current(g.user.id)), "resume_history": resumes.history(g.user.id, 5),
               "stats": {"applications": len([a for a in apps if a.stage not in ("withdrawn", "removed")]), "badges": badges,
                         "verified_skills": sum(1 for s in p.skills or [] if s.get("verified")),
                         "practice": RoundAttempt.query.filter_by(practice_user_id=g.user.id).count()},
               "goal": goal, "completeness": strength(p, g.user), "next_steps": next_steps(p, g.user, practice_n),
               "top_skills": _top_skills(p, apps), "skills_total": len(p.skills or []),
               "jobs_preview": ranked[:3], "activity": _activity(apps), "role_chips": _role_chips(p, apps, ranked),
               "tip": _tip(p, ranked)})


def _top_skills(p, apps, n=6):
    """HOM-10: verified first, then level, then how many of the candidate's applied jobs ask for it."""
    asked = {}
    for a in apps:
        j = db.session.get(Job, a.job_id)
        for s in (j.skills or []) if j else []:
            for o in options(s["name"] if isinstance(s, dict) else s):
                asked[o.lower()] = asked.get(o.lower(), 0) + 1
    rows = sorted(p.skills or [], key=lambda s: (not s.get("verified"), -(s.get("level") or 0), -asked.get((s.get("name") or "").lower(), 0)))
    return rows[:n]


def _activity(apps, n=6):
    """HOM-12: latest practice scores, skill checks, badges and application updates."""
    out = []
    for att in (RoundAttempt.query.filter(RoundAttempt.practice_user_id == g.user.id, RoundAttempt.status.in_(("completed", "reviewed")))
                .order_by(RoundAttempt.completed_at.desc()).limit(n).all()):
        cfg = att.config or {}
        out.append({"kind": "skill_check" if cfg.get("skill_check") else "practice", "title": cfg.get("title") or "Practice",
                    "score": att.score, "type": att.round_type, "at": (att.completed_at or att.created_at).isoformat() + "Z",
                    "link": "/me/skills" if cfg.get("skill_check") else "/me/practice"})
    for c in Credential.query.filter_by(user_id=g.user.id, revoked=False).order_by(Credential.created_at.desc()).limit(n).all():
        out.append({"kind": "badge", "title": c.title, "at": c.created_at.isoformat() + "Z", "link": "/me/skills"})
    for a in apps:
        j = db.session.get(Job, a.job_id)
        out.append({"kind": "application", "title": f"{j.title}: {STAGE_LABEL.get(a.stage, a.stage)}", "at": (a.updated_at or a.created_at).isoformat() + "Z",
                    "link": "/me/applications"})
    return sorted(out, key=lambda x: x["at"], reverse=True)[:n]


def _role_chips(p, apps, ranked):
    """HOM-04: roles from the candidate's applications and goal first, then the titles of their best-matching jobs."""
    chips = []
    titles = [db.session.get(Job, a.job_id).title for a in apps if db.session.get(Job, a.job_id)]
    for t in titles + list(p.target_roles or []) + [r["title"] for r in ranked[:6]]:
        t = canon(t)
        if t and t.lower() != "your next role" and not any(same(t, c) for c in chips):
            chips.append(t)
    return chips[:6]


def _tip(p, ranked):
    """One short tip from Disha for the Home panel."""
    sk = p.skills or []
    if not p.resume_text:
        return "Upload your resume and I'll fill in your skills, headline and experience."
    if not any(s.get("verified") for s in sk):
        best = _verify_hint(p, ranked)
        return f"Verify {best} with a 12-minute check. Verified skills lift your job matches the most." if best else "Take a skill check to turn a self-reported skill into a verified one."
    if not (p.target_roles or []):
        return "Tell me the role you're aiming for and I'll build your path."
    return "Practise an interview for the role you want. It's private, and you get feedback straight away."


STAGE_LABEL = {"applied": "Applied", "shortlisted": "Shortlisted", "in_round": "In progress", "awaiting_review": "Being reviewed",
               "decision": "Being reviewed", "on_hold": "Being reviewed", "offer": "Offer", "hired": "Hired",
               "rejected": "Not selected", "withdrawn": "Withdrawn", "removed": "Closed"}


def merge_skills(old, incoming):
    """Saved skill list: names in canonical spelling, no duplicates (PRF-06), the source of each skill kept (so a
    new resume can replace the old resume's skills), and verified skills never removed by editing."""
    old = list(old or [])
    verified = [s for s in old if s.get("verified")]
    new = []
    for s in incoming:
        name = canon(str(s.get("name") or "").strip())[:80]
        if not name or any(same(name, x["name"]) for x in new):
            continue
        v = next((x for x in verified if same(x["name"], name)), None)
        if v:
            new.append(v)
            continue
        prev = next((x for x in old if same(x["name"], name)), None)
        try:
            lvl = max(1, min(5, int(s.get("level", 2))))
        except (TypeError, ValueError):
            lvl = 2
        new.append({"name": name, "level": lvl, "verified": False, "source": (prev or {}).get("source") or s.get("source") or "self"})
    for v in verified:  # verified skills can't be removed by editing
        if not any(same(v["name"], x["name"]) for x in new):
            new.append(v)
    return new


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
        p.skills = merge_skills(p.skills, d["skills"])
        _rescore_candidate(g.user.id)  # CAN-018 (V02.00.11): the candidate's matches follow their skills
    db.session.commit()
    return ok(p.to_dict())


def _resume_text():
    if "file" in request.files:
        return files.resume_text(request.files["file"])
    return body().get("text") or ""


def _resume_upload(user_id):
    """CAN-002 (V02.00.11): a file is kept as a pending version for the preview; pasted text has no file."""
    from services import resumes
    if "file" in request.files:
        name, kind, data, text = files.resume_upload(request.files["file"])
        return text, resumes.store_pending(user_id, name, kind, data, text, g.user.id).id
    return body().get("text") or "", None


@bp.post("/resume/read")
@auth_required
def resume_read():
    """PRF-09 / CP-004 (V02.00.10): read a resume and show what saving it would change. Nothing is saved yet."""
    try:
        text, upload_id = _resume_upload(g.user.id)
    except files.FileProblem as e:
        return err(str(e))
    if len(text.strip()) < 20:
        return err("That resume looks empty.")
    p = profile()
    fields = read_resume(text)
    plan = resume_plan(p, fields)
    db.session.commit()
    return ok({"text": text[:30000], "fields": fields, "plan": plan, "upload_id": upload_id})


@bp.post("/resume")
@auth_required
def resume():
    """Save a resume. A new resume replaces the skills read from the old one; hand-added and verified skills stay.
    After the preview the body names exactly which skills to add / remove and which fields to fill."""
    try:
        text = _resume_text()
    except files.FileProblem as e:
        return err(str(e))
    if len(text.strip()) < 20:
        return err("That resume looks empty.")
    p = profile()
    d = {} if "file" in request.files else body()
    fields = d.get("fields") or read_resume(text)
    plan = resume_plan(p, fields)
    res = apply_resume(p, text, plan, d.get("add"), d.get("remove"), d.get("fill"))
    from services import resumes
    rf = resumes.make_current(g.user.id, d.get("upload_id"))
    log("candidate.resume", "user", g.user.id, added=len(res["added"]), removed=len(res["removed"]), file=rf.filename if rf else None)
    _rescore_candidate(g.user.id)
    db.session.commit()
    return ok({"profile": p.to_dict(), "found_skills": res["added"], "file": resumes.info(rf), **res})


@bp.get("/resume/file")
@auth_required
def resume_file():
    """CAN-002 (V02.00.11): download the resume file on the candidate's profile."""
    from services import resumes
    rf = resumes.current(g.user.id)
    if not rf:
        return err("There's no resume file on your profile. A pasted resume has no file.", 404)
    return resumes.send(rf)


def _papers():
    from services import papers
    return papers


def _rescore_candidate(user_id):
    from services.pipeline import rescore_candidate
    return rescore_candidate(user_id)


@bp.post("/path")
@auth_required
def path():
    p = profile()
    goal = canon(str(body().get("goal") or "").strip())[:120]
    if len(goal) < 2:  # CP-002: no path for an empty role
        return err("Type or pick the role you're aiming for.", fields={"goal": "Type or pick a role."})
    p.target_roles = [goal]
    db.session.commit()
    return ok(ai.disha_path(goal, p.skills or []))


# ---------------------------------------------------------------- jobs

def _job_public(j, p):
    c = db.session.get(Company, j.company_id)
    score, got, missing = skill_match(j, p.skills or [])
    app = Application.query.filter_by(job_id=j.id, candidate_id=g.user.id).first()
    return {"id": j.id, "title": j.title, "company": None if j.client_hidden else (c.name if c else ""),
            "location": j.location, "work_mode": (j.work_mode or "").capitalize(), "level": j.level, "skills": j.skills,
            "salary": [j.salary_min, j.salary_max] if j.salary_visible else None,
            "description": j.description, "posted": j.created_at.isoformat() + "Z",
            "match": score, "matched": got, "missing": missing,
            "applied": bool(app), "applied_at": app.created_at.isoformat() + "Z" if app else None, "application_id": app.id if app else None,
            "saved": j.id in (p.saved_jobs or []),
            "rounds": [{"type": r["type"], "name": candidate_round_name(r.get("name") or ROUND_TYPES[r["type"]]),
                        "about": ROUND_ABOUT.get(r["type"], "")} for r in j.rounds or []]}


def candidate_round_name(name):
    """APP-04: Isha is the INTERVIEWER's copilot. Candidates see "AI-assisted" instead of an unexplained name."""
    import re
    out = re.sub(r"\s*(?:with\s+)?(?:the\s+)?Isha(?:\s+copilot)?\b", " (AI-assisted)", name or "", flags=re.I).strip()
    return re.sub(r"\s+", " ", out)


ROUND_ABOUT = {"mcq": "Online quiz: multiple-choice questions with a timer. Camera on.",
               "ai_interview": "Voice interview with Hira, Code2Hire's AI interviewer. You answer out loud.",
               "f2f_isha": "Live video interview with a person from the hiring team. Their notes are assisted by AI.",
               "f2f_human": "Live video interview with a person from the hiring team."}


def _ranked_jobs(p, args):
    """Jobs for the candidate, best match first, with the filters from the Jobs page (JOB-02)."""
    rows = [_job_public(j, p) for j in Job.query.filter_by(status="live", visibility="public").all()]
    text = (args.get("q") or "").lower().strip()
    if text:
        rows = [r for r in rows if text in (r["title"] + " " + (r["company"] or "") + " " + (r["location"] or "")
                                            + " " + " ".join(s["name"] if isinstance(s, dict) else s for s in r["skills"] or [])).lower()]
    if args.get("mode"):
        rows = [r for r in rows if r["work_mode"].lower() == args["mode"].lower()]
    if args.get("location"):
        rows = [r for r in rows if (r["location"] or "").lower() == args["location"].lower()]
    if args.get("level"):
        rows = [r for r in rows if (r["level"] or "").lower() == args["level"].lower()]
    if str(args.get("verified") or "") in ("1", "true"):
        rows = [r for r in rows if any("✓" in m for m in r["matched"])]
    if str(args.get("saved") or "") in ("1", "true"):
        rows = [r for r in rows if r["saved"]]
    if args.get("sort") == "posted":
        rows.sort(key=lambda r: r["posted"], reverse=True)
    else:
        rows.sort(key=lambda r: -(r["match"] or 0))
    return rows


def _verify_hint(p, rows):
    """JOB-04: the self-reported skill that, once verified, lifts the most listed jobs."""
    counts = {}
    for r in rows[:10]:
        for m in r["matched"]:
            if "✓" not in m:
                nm = m.rsplit(" L", 1)[0]
                counts[nm] = counts.get(nm, 0) + 1
    return max(counts, key=counts.get) if counts else None


@bp.get("/jobs")
@auth_required
def jobs():
    p = profile()
    rows = _ranked_jobs(p, request.args)
    every = _ranked_jobs(p, {})
    try:
        page = max(1, int(request.args.get("page", 1)))
        size = max(1, min(50, int(request.args.get("size", 12))))
    except ValueError:
        page, size = 1, 12
    hint = _verify_hint(p, rows or every)
    return ok({"items": rows[(page - 1) * size: page * size], "total": len(rows), "page": page, "size": size,
               "pages": max(1, (len(rows) + size - 1) // size),
               "filters": {"locations": sorted({r["location"] for r in every if r["location"]}),
                           "modes": sorted({r["work_mode"] for r in every if r["work_mode"]}),
                           "levels": sorted({r["level"] for r in every if r["level"]})},
               "verified_skills": sum(1 for s in p.skills or [] if s.get("verified")), "saved_count": len(p.saved_jobs or []),
               "banner": {"skill": hint, "jobs": sum(1 for r in rows[:10] if any(m.startswith(hint + " L") for m in r["matched"]))} if hint else None})


@bp.post("/jobs/<int:jid>/save")
@auth_required
def save_job(jid):
    """JOB-11: bookmark a job (or remove the bookmark)."""
    p = profile()
    if not Job.query.filter_by(id=jid, status="live").first():
        return err("This job isn't open.", 404)
    saved = [x for x in (p.saved_jobs or []) if x != jid]
    if body().get("on", True):
        saved.append(jid)
    p.saved_jobs = saved
    db.session.commit()
    return ok({"saved": jid in saved, "count": len(saved)})


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
        return err("Add your resume first so the team can see your experience.", fields={"resume": "needed"})
    score, got, missing = skill_match(j, p.skills or [])
    a = Application(job_id=jid, candidate_id=g.user.id, source="applied", match_score=score,
                    match_reasons={"matched": got, "missing": missing})
    db.session.add(a)
    log("application.apply", "job", jid, company_id=j.company_id)
    db.session.commit()
    return ok({"id": a.id, "match": score, "applied_at": a.created_at.isoformat() + "Z",
               "message": f"Application submitted for {j.title}. You'll see the first round on your home page."})


def syscheck_short(att):
    """V02.00.05: the short instructions shown on the candidate's home page next to each round."""
    from services.syscheck import instructions
    try:
        return instructions(att)["short"]
    except Exception:  # never break the home page over instructions
        return []


def _step_state(att, i, a):
    """APP-03: Completed, Scheduled, Next up, Upcoming, Not finished, Missed or Not selected."""
    if att:
        st = att.status
        if st in ("completed", "reviewed"):
            return "completed", "Completed"
        if st in ("invited", "scheduled", "in_progress", "paused"):
            return ("scheduled", "Scheduled") if att.scheduled_at and st in ("invited", "scheduled") else ("next", "Next up")
        if st == "not_finished":
            return "not_finished", "Not finished"
        if st == "expired":
            return "missed", "Missed"
        if st == "voided":
            return "next", "Next up"
    if a.stage == "rejected":
        return "not_selected", "Not selected"
    if a.stage in ("withdrawn", "removed"):
        return "closed", "Closed"
    return ("next", "Next up") if i == max(0, a.current_round) and a.stage in ("applied", "shortlisted", "in_round") else ("upcoming", "Upcoming")


@bp.get("/applications")
@auth_required
def applications():
    out = []
    for a in Application.query.filter_by(candidate_id=g.user.id).order_by(Application.created_at.desc()).all():
        j = db.session.get(Job, a.job_id)
        c = db.session.get(Company, j.company_id)
        steps = []
        # latest attempt per round wins (a re-interview replaces the earlier one on screen)
        # (V02.00.08: cancelled invites and rounds voided by a retake never hide the current one)
        atts = {att.round_index: att for att in RoundAttempt.query.filter(RoundAttempt.application_id == a.id,
                                                                          ~RoundAttempt.status.in_(("cancelled",)))
                .order_by(RoundAttempt.id.asc()).all() if att.status != "voided" or not ((att.result or {}).get("voided") or {}).get("retake_attempt_id")}
        seen_next = False
        for i, r in enumerate(j.rounds or []):
            att = atts.get(i)
            can_join, opens = join_window(att) if att else (False, None)
            state, label = _step_state(att, i, a)
            if state == "next":
                if seen_next:
                    state, label = "upcoming", "Upcoming"
                seen_next = True
            cfgm = (att.config if att else None) or (r.get("config") or {})
            mins = cfgm.get("mcq.minutes") if r["type"] == "mcq" else cfgm.get("interview.minutes")
            steps.append({"name": candidate_round_name(r.get("name") or ROUND_TYPES.get(r["type"], r["type"])), "type": r["type"],
                          "status": att.status if att else ("upcoming" if i > a.current_round else "skipped"),
                          "state": state, "label": label, "about": ROUND_ABOUT.get(r["type"], ""), "minutes": mins,
                          "attempt_id": att.id if att else None,
                          "deadline_at": att.deadline_at.isoformat() + "Z" if att and att.deadline_at else None,
                          "scheduled_at": att.scheduled_at.isoformat() + "Z" if att and att.scheduled_at else None,
                          "can_join": can_join, "opens_at": opens.isoformat() + "Z" if opens else None,
                          "setup_ok": bool(((att.result or {}).get("syscheck") or {}).get("passed")) if att else False})
        top = [(s["name"] if isinstance(s, dict) else s) for s in (j.skills or [])][:4]
        out.append({"id": a.id, "job": {"id": j.id, "title": j.title, "company": None if j.client_hidden else c.name},
                    "stage": STAGE_LABEL.get(a.stage, a.stage), "raw_stage": a.stage, "applied": a.created_at.isoformat() + "Z", "steps": steps,
                    "match": a.match_score, "active": a.stage not in ("rejected", "withdrawn", "hired", "removed"),
                    "prepare": {"role": j.title, "skills": top}})
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
    # CP-011 (V02.00.10): every practice is for a role, and its questions come from that role's skills
    role = canon(str(d.get("role") or "").strip())[:120]
    if len(role) < 2:
        return err("Choose the role you're practising for.", fields={"role": "Type or pick a role."})
    picked = [canon(str(x).strip()) for x in (d.get("skills") or []) if str(x).strip()]
    skills = picked or role_skills(role, profile().skills or [])
    try:  # V02.00.09: number boxes are checked on the server too
        nq = int(d.get("questions", 4 if rtype == "ai_interview" else 8))
    except (TypeError, ValueError):
        nq = 0
    hi = 10 if rtype == "ai_interview" else 30
    if not 1 <= nq <= hi:
        return err(f"Choose from 1 to {hi} questions.", fields={"questions": f"1 to {hi}."})
    d["questions"] = nq
    cfg = dict(PRACTICE_CFG)
    keys = ["voice.name", "voice.allowed", "voice.rate", "voice.candidate_can_choose", "voice.silence_seconds", "voice.enabled",
            "interview.followup_depth", "ai.language"]
    for k in keys:
        cfg[k] = resolve(k)[0]
    level = d.get("level") or {"easy": 2, "medium": 3, "hard": 4}.get(d.get("difficulty"), 3)
    cfg.update({"title": d.get("title") or f"Practice: {role}", "role": role, "skills": skills,
                "level": int(level), "role_level": d.get("role_level", "Mid"),
                "interview.questions": int(d.get("questions", 4)), "interview.difficulty": d.get("difficulty", "medium"),
                "interview.minutes": int(d.get("minutes", 20)), "mcq.questions": int(d.get("questions", 8)),
                "mcq.minutes": int(d.get("minutes", 12)), "mcq.randomise": True})
    att = RoundAttempt(practice_user_id=g.user.id, round_type=rtype, config=cfg, status="invited")  # N5: no deadline
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
    att = RoundAttempt(practice_user_id=g.user.id, round_type="mcq", config=cfg, status="invited")  # N5: no deadline
    db.session.add(att)
    db.session.commit()
    return ok({"attempt_id": att.id})


@bp.get("/practice/suggest")
@auth_required
def practice_suggest():
    """PRA-02: practice suggestions from the candidate's applications first, then their goal and skills."""
    p = profile()
    out = []
    for a in Application.query.filter_by(candidate_id=g.user.id).order_by(Application.created_at.desc()).all():
        if a.stage in ("withdrawn", "removed", "rejected"):
            continue
        j = db.session.get(Job, a.job_id)
        sk = [canon(o) for s in (j.skills or [])[:4] for o in options(s["name"] if isinstance(s, dict) else s)[:1]]
        if not any(same(j.title, x["role"]) for x in out):
            out.append({"role": canon(j.title), "skills": sk[:4], "why": "For your application"})
    for r in p.target_roles or []:
        if r and not any(same(r, x["role"]) for x in out):
            out.append({"role": canon(r), "skills": [], "why": "Your goal"})
    if len(out) < 3 and p.skills:
        top = [s["name"] for s in sorted(p.skills, key=lambda s: (not s.get("verified"), -(s.get("level") or 0)))[:3]]
        out.append({"role": canon(p.headline) if p.headline else "Your profile skills", "skills": top, "why": "Based on your skills"})
    roles = []
    for r in [x["role"] for x in out] + [canon(j.title) for j in Job.query.filter_by(status="live", visibility="public").limit(30).all()]:
        if r and not any(same(r, x) for x in roles):
            roles.append(r)
    return ok({"suggestions": out[:3], "roles": roles[:20],
               "profile_skills": [s["name"] for s in sorted(p.skills or [], key=lambda s: (not s.get("verified"), -(s.get("level") or 0)))]})


@bp.get("/practice/role-skills")
@auth_required
def practice_role_skills():
    """PRA-04: the skills a role needs, so the form can preselect only skills that fit the role."""
    role = (request.args.get("role") or "").strip()
    if len(role) < 2:
        return ok({"skills": []})
    return ok({"skills": role_skills(role, profile().skills or [])})


@bp.get("/practice/topics")
@auth_required
def practice_topics():
    """CD-005 (V02.00.08): the topics the question bank has questions for, with how many, for the practice quiz."""
    from services.mcq import bank_skills
    rows = sorted(bank_skills(None).items(), key=lambda x: (-x[1], x[0].lower()))
    return ok([{"skill": k, "count": v} for k, v in rows][:40])


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


@bp.delete("/practice/<int:att_id>")
@auth_required
def practice_delete(att_id):
    """CAN-004 (V02.00.11): a candidate deletes one of their practice sessions, permanently: answers, transcript,
    integrity events, system checks, the report and the recording (its files too). Skill checks are not practice:
    their badge is a record employers rely on, so they can't be deleted here. Only the count is kept, in the audit log."""
    from models import CallSignal, IntegrityEvent, Recording, SystemCheck, Turn
    from services import storage
    att = db.session.get(RoundAttempt, att_id)
    if not att or att.practice_user_id != g.user.id or att.application_id or att.cert_attempt_id:
        return err("Not found", 404)
    if (att.config or {}).get("skill_check"):
        return err("Skill checks can't be deleted. They back your badges.")
    for rec in Recording.query.filter_by(attempt_id=att.id).all():
        try:
            storage.delete(rec)
        except Exception:  # noqa: BLE001 - a file already gone must not stop the delete
            pass
        db.session.delete(rec)
    for model in (Turn, IntegrityEvent, CallSignal, SystemCheck, Report):
        model.query.filter_by(attempt_id=att.id).delete(synchronize_session=False)
    Notification.query.filter(Notification.user_id == g.user.id, Notification.link == f"/room/{att.id}").delete(synchronize_session=False)
    kind = att.round_type
    db.session.delete(att)
    log("practice.delete", "user", g.user.id, kind=kind)
    db.session.commit()
    return ok({"deleted": att_id})


@bp.post("/skills/add")
@auth_required
def skill_add():
    """CAN-018 (V02.00.11): from a job page, "I have this skill" adds it to the profile (self-reported) and rescores the
    candidate's applications. A skill already on the profile is left as it is."""
    d = body()
    name = canon(str(d.get("name") or "").strip())[:60]
    if len(name) < 1:
        return err("Name the skill.", fields={"name": "Name the skill."})
    try:
        level = min(5, max(1, int(d.get("level") or 2)))
    except (TypeError, ValueError):
        level = 2
    p = profile()
    have = p.skills or []
    if any(same(s.get("name"), name) for s in have):
        return ok({"added": False, "skills": have, "message": f"{name} is already on your profile."})
    p.skills = merge_skills(have, have + [{"name": name, "level": level, "source": "manual"}])
    n = _rescore_candidate(g.user.id)
    log("candidate.skill_add", "user", g.user.id, skill=name)
    db.session.commit()
    return ok({"added": True, "skills": p.skills, "rescored": n,
               "message": f"{name} added to your profile as self-reported. Verify it with a skill check to count for more."})


@bp.get("/skills/recommend")
@auth_required
def skills_recommend():
    """SKL-02 / SKL-03: skill checks ranked by the jobs the candidate applied to, then their goal, then their profile.
    Each reason names a real job or a real goal."""
    from services.mcq import bank_skills
    p = profile()
    have = p.skills or []
    held = {(c.skill or "").lower() for c in Credential.query.filter_by(user_id=g.user.id, revoked=False).all() if c.skill}
    recs = []

    def add(name, level, why):
        name = canon(name)
        if not name or name.lower() in held or any(same(name, r["skill"]) for r in recs):
            return
        mine = find(name, have)
        if mine and mine.get("verified"):
            return
        recs.append({"skill": name, "level": max(1, min(5, int(level or 2))), "why": why, "self_reported": bool(mine)})
    for a in Application.query.filter_by(candidate_id=g.user.id).order_by(Application.created_at.desc()).all():
        j = db.session.get(Job, a.job_id)
        if not j or a.stage in ("withdrawn", "removed"):
            continue
        for s in j.skills or []:
            nm = s["name"] if isinstance(s, dict) else s
            h = find(nm, have)
            if h:
                add(h["name"], (s.get("level") if isinstance(s, dict) else 2) or 2, f"Asked for by {j.title}, which you applied to")
    for r in p.target_roles or []:
        for sk in role_skills(r, have, 3):
            if find(sk, have):
                add(sk, 2, f"Needed for your goal: {r}")
    for s in sorted(have, key=lambda s: -(s.get("level") or 0)):
        add(s["name"], s.get("level") or 2, "On your profile, self-reported")
    bank = sorted(bank_skills(None).keys())
    return ok({"recommended": recs[:4], "levels": {str(k): {"name": v[0], "about": v[1]} for k, v in LEVELS.items()},
               "skills": sorted({canon(s["name"]) for s in have} | {canon(b) for b in bank}),
               "quick": [canon(s["name"]) for s in sorted(have, key=lambda s: -(s.get("level") or 0))][:4]})


@bp.get("/badges")
@auth_required
def badges():
    return ok([c.to_dict() for c in Credential.query.filter_by(user_id=g.user.id).order_by(Credential.created_at.desc()).all()])


# ---------------------------------------------------------------- learning

def _path_dict(lp):
    d = lp.to_dict()
    d["meta"] = lp.meta or {}
    topics = d.get("topics") or []
    left = [t for t in topics if not t.get("done")]
    d["current"] = next((i for i, t in enumerate(topics) if not t.get("done")), None)
    d["minutes_left"] = sum(int(t.get("minutes") or 10) for t in left)
    d["done_count"] = len(topics) - len(left)
    return d


def _path_job(skill, goal):
    """LRN-07: the candidate's application this path leads to (the job that asks for the skill, or has the goal's title)."""
    for a in Application.query.filter_by(candidate_id=g.user.id).order_by(Application.created_at.desc()).all():
        j = db.session.get(Job, a.job_id)
        if not j or a.stage in ("withdrawn", "removed"):
            continue
        asks = any(any(same(o, skill) for o in options(s["name"] if isinstance(s, dict) else s)) for s in j.skills or [])
        if asks or same(j.title, goal):
            c = db.session.get(Company, j.company_id)
            return {"application_id": a.id, "job_title": j.title, "company": None if j.client_hidden else (c.name if c else None),
                    "applied": a.created_at.isoformat() + "Z"}
    return {}


def _build(skill, goal, cur):
    data = ai.learning_path(goal, skill, cur)
    topics = []
    for i, t in enumerate(data.get("topics") or []):
        t = dict(t)
        t["title"] = str(t.get("title") or f"Topic {i + 1}").replace(skill.lower(), skill)
        try:
            t["minutes"] = max(5, min(45, int(t.get("minutes") or 10)))
        except (TypeError, ValueError):
            t["minutes"] = 10
        t["done"] = bool(t.get("done"))
        topics.append(t)
    return data, topics


@bp.get("/learning")
@auth_required
def learning():
    rows = LearningPath.query.filter_by(user_id=g.user.id).order_by(LearningPath.id.desc()).all()
    p = profile()
    gaps = []  # LRN-01: "Try" chips from the gaps on the candidate's jobs
    for r in _ranked_jobs(p, {})[:6]:
        for m in r["missing"]:
            for o in options(m)[:1]:
                if not any(same(o, x) for x in gaps):
                    gaps.append(canon(o))
    return ok({"paths": [_path_dict(lp) for lp in rows], "try": gaps[:5]})


@bp.post("/learning")
@auth_required
def new_learning():
    d = body()
    p = profile()
    skill = canon(str(d.get("skill") or "").strip())[:80]
    if len(skill) < 2:
        return err("Type what you want to learn.", fields={"skill": "Type a skill or topic."})
    existing = next((lp for lp in LearningPath.query.filter_by(user_id=g.user.id).all() if same(lp.skill, skill)), None)
    if existing:  # LRN-09: one path per skill; asking again opens the one you have
        return ok({**_path_dict(existing), "existing": True})
    cur = next((s.get("level", 1) for s in p.skills or [] if same(s["name"], skill)), 1)
    goal = canon(d.get("goal") or (p.target_roles or ["your next role"])[0])
    data, topics = _build(skill, goal, cur)
    meta = {"goal": goal, "basic": bool(data.get("_basic")), **_path_job(skill, goal)}
    lp = LearningPath(user_id=g.user.id, title=f"{skill} for {goal}" if goal.lower() != "your next role" else f"{skill} for your next role",
                      skill=skill, topics=topics, reason=d.get("reason") or f"Towards {goal}", meta=meta)
    db.session.add(lp)
    db.session.commit()
    return ok(_path_dict(lp))


@bp.post("/learning/<int:lid>/rebuild")
@auth_required
def rebuild_learning(lid):
    """LRN-03: rebuild a basic path with Disha, keeping the topics already done where the titles match."""
    lp = LearningPath.query.filter_by(id=lid, user_id=g.user.id).first_or_404()
    meta = dict(lp.meta or {})
    data, topics = _build(canon(lp.skill), meta.get("goal") or "your next role", 1)
    done = {t.get("title", "").lower() for t in lp.topics or [] if t.get("done")}
    for t in topics:
        t["done"] = t["title"].lower() in done
    lp.topics = topics
    lp.skill = canon(lp.skill)
    lp.title = canon(lp.skill) + " for " + (meta.get("goal") or "your next role")
    meta["basic"] = bool(data.get("_basic"))
    meta.update(_path_job(lp.skill, meta.get("goal") or ""))
    lp.meta = meta
    db.session.commit()
    if meta["basic"]:
        return err("Disha couldn't reach the AI just now, so this is still a basic outline. Try again in a minute.", 503)
    return ok(_path_dict(lp))


@bp.patch("/learning/<int:lid>/topics/<int:i>")
@auth_required
def toggle_topic(lid, i):
    lp = LearningPath.query.filter_by(id=lid, user_id=g.user.id).first_or_404()
    topics = [dict(t) for t in lp.topics or []]
    if 0 <= i < len(topics):
        topics[i]["done"] = bool(body().get("done", not topics[i].get("done")))
    lp.topics = topics
    db.session.commit()
    return ok(_path_dict(lp))


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


@bp.get("/feedback/waiting")
@auth_required
def feedback_waiting():
    """FDB-03: active applications with no shared feedback yet."""
    out = []
    for a in Application.query.filter_by(candidate_id=g.user.id).order_by(Application.created_at.desc()).all():
        if a.stage in ("withdrawn", "removed", "hired"):
            continue
        j = db.session.get(Job, a.job_id)
        shared = any(Report.query.filter_by(attempt_id=att.id, shared_with_candidate=True).first()
                     for att in RoundAttempt.query.filter_by(application_id=a.id).all())
        if not shared:
            c = db.session.get(Company, j.company_id)
            out.append({"application_id": a.id, "job": j.title, "company": None if j.client_hidden else (c.name if c else None),
                        "stage": STAGE_LABEL.get(a.stage, a.stage)})
    return ok(out)


FEEDBACK_TOPICS = ["Application experience", "Profile or resume", "Job recommendations", "Learning content",
                   "Practice interviews", "Skill checks", "Technical issue", "Something else"]


@bp.get("/product-feedback")
@auth_required
def product_feedback_topics():
    return ok({"topics": FEEDBACK_TOPICS})


@bp.post("/product-feedback")
@auth_required
def product_feedback():
    """CP-008: the candidate tells Code2Hire what works and what doesn't. The superadmin reads it."""
    from models import ProductFeedback
    d = body()
    topics = [t for t in (d.get("topics") or []) if t in FEEDBACK_TOPICS]
    text = str(d.get("text") or "").strip()[:3000]
    if not topics and len(text) < 5:
        return err("Pick a topic or write a few words.", fields={"text": "Pick a topic or write a few words."})
    rating = d.get("rating")
    try:
        rating = max(1, min(5, int(rating))) if rating not in (None, "") else None
    except (TypeError, ValueError):
        rating = None
    db.session.add(ProductFeedback(user_id=g.user.id, topics=topics, text=text or None, rating=rating, page=str(d.get("page") or "")[:120]))
    log("candidate.product_feedback", "user", g.user.id, topics=topics)
    db.session.commit()
    return ok({"thanks": True})


@bp.get("/search")
@auth_required
def search():
    """CP-005 / GLB-01: one search for jobs, skills and learning paths."""
    q = (request.args.get("q") or "").strip()
    if len(q) < 2:
        return ok({"jobs": [], "skills": [], "paths": [], "q": q})
    p = profile()
    jobs = _ranked_jobs(p, {"q": q})[:5]
    from services.skills import KNOWN
    names = {canon(s["name"]) for s in p.skills or []} | set(KNOWN)
    skills = sorted([s for s in names if q.lower() in s.lower()], key=lambda s: (not s.lower().startswith(q.lower()), len(s)))[:5]
    paths = [{"id": lp.id, "title": lp.title} for lp in LearningPath.query.filter_by(user_id=g.user.id).all() if q.lower() in (lp.title or "").lower()][:3]
    return ok({"q": q, "jobs": [{"id": j["id"], "title": j["title"], "company": j["company"], "match": j["match"]} for j in jobs],
               "skills": [{"name": s, "mine": any(same(s, x["name"]) for x in p.skills or [])} for s in skills], "paths": paths})


@bp.get("/feedback/<int:rid>/pdf")
@auth_required
def feedback_pdf(rid):
    """BUG-005: the candidate downloads their shared feedback, when the company allows it."""
    from flask import current_app
    from routes.reports import pdf_response, view
    from services.pdf import report_pdf
    from services.settings import resolve
    r = db.session.get(Report, rid)
    att = db.session.get(RoundAttempt, r.attempt_id) if r else None
    a = db.session.get(Application, att.application_id) if att and att.application_id else None
    if not r or not a or a.candidate_id != g.user.id or not r.shared_with_candidate:
        return err("Not found", 404)
    j = db.session.get(Job, a.job_id)
    if not resolve("report.candidate_pdf", company_id=j.company_id, team_id=j.team_id, job_id=j.id)[0]:
        return err("This company doesn't offer feedback downloads.", 403)
    v = view(r, att, j, "candidate")
    log("feedback.pdf", "report", r.id)
    db.session.commit()
    return pdf_response(report_pdf(v, current_app.config.get("APP_VERSION", ""), candidate=True), f"feedback-{j.title}-{v.get('round', '')}")


@bp.get("/practice/<int:att_id>/pdf")
@auth_required
def practice_pdf(att_id):
    """BUG-004 (V02.00.09): the candidate downloads their own practice report. Private to them, so nothing is hidden
    except the camera snapshots."""
    from flask import current_app
    from routes.reports import pdf_response
    from services.pdf import report_pdf
    att = db.session.get(RoundAttempt, att_id)
    r = Report.query.filter_by(attempt_id=att.id).first() if att else None
    if not att or att.practice_user_id != g.user.id or not r:
        return err("Not found", 404)
    s = dict(r.sections or {})
    if isinstance(s.get("integrity"), dict):
        s["integrity"] = {k: v for k, v in s["integrity"].items() if k != "snapshots"}
    title = (att.config or {}).get("title") or "Practice"
    v = {"id": r.id, "attempt_id": att.id, "round": title, "type": att.round_type, "job": {"id": None, "title": "Practice, private to you"},
         "candidate": {"name": g.user.name}, "overall": r.overall, "scale": 5, "sections": s,
         "completed_at": att.completed_at.isoformat() + "Z" if att.completed_at else None,
         "result": {"score": r.overall, "next_step": "Practise again or open a learning path to work on your gaps."}}
    return pdf_response(report_pdf(v, current_app.config.get("APP_VERSION", ""), candidate=True), f"practice-{title}")


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
    from routes.recordings import delete_for_candidate
    delete_for_candidate(u.id)  # interview videos show the person, so they go too
    from services import resumes
    resumes.erase_all(u.id)  # V02.00.11: resume files too
    log("candidate.delete", "user", u.id)
    db.session.commit()
    return ok()
