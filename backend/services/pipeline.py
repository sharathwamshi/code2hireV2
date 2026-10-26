"""Moving candidates through a job's rounds, applying pass rules, and Disha's matching."""
from datetime import datetime, timedelta
import secrets

from extensions import db
from models import Application, Credential, Job, RoundAttempt, User
from services.audit import log, notify
from services.settings import DEFAULTS, resolve

ROUND_TYPES = {
    "mcq": "MCQ screening",
    "ai_interview": "AI interview with Hira",
    "f2f_isha": "F2F with Isha",
    "f2f_human": "Human F2F",
}
CALL_KEYS = ["call.enabled", "call.captions", "call.record", "call.screen_share", "call.chat", "call.watch_focus",
             "call.join_early_minutes", "ai.language"]
ROUND_KEYS = {
    "mcq": ["mcq.questions", "mcq.minutes", "mcq.negative_marking", "mcq.randomise"],
    "ai_interview": ["interview.questions", "interview.followup_depth", "interview.difficulty", "interview.minutes",
                     "voice.enabled", "voice.name", "voice.allowed", "voice.rate", "voice.candidate_can_choose",
                     "voice.silence_seconds", "ai.language"],
    "f2f_isha": ["isha.enabled", "isha.options", "isha.hide_ai_scores_until_scorecard"] + CALL_KEYS,
    "f2f_human": CALL_KEYS,
}
COMMON_KEYS = ["pass.advance", "pass.reject", "pass.auto", "integrity.warnings_allowed", "integrity.fullscreen",
               "integrity.face_check", "integrity.block_paste", "integrity.instant_pause", "report.scale",
               "report.review_before_share"]


def round_config(job, idx):
    rnd = (job.rounds or [])[idx]
    keys = ROUND_KEYS.get(rnd["type"], []) + COMMON_KEYS
    cfg = {}
    for k in keys:
        v, src, _ = resolve(k, company_id=job.company_id, team_id=job.team_id, job_id=job.id, round_cfg=rnd.get("config") or {})
        cfg[k] = v
    return cfg


def invite_to_round(app, idx, actor_id=None, interviewer_id=None, scheduled_at=None, days=5):
    job = db.session.get(Job, app.job_id)
    if idx >= len(job.rounds or []):
        app.stage = "decision"
        return None
    rnd = job.rounds[idx]
    att = RoundAttempt(application_id=app.id, round_index=idx, round_type=rnd["type"], config=round_config(job, idx),
                       status="scheduled" if scheduled_at else "invited", interviewer_id=interviewer_id,
                       scheduled_at=scheduled_at, deadline_at=datetime.utcnow() + timedelta(days=days))
    db.session.add(att)
    app.current_round = idx
    app.stage = "in_round"
    db.session.flush()
    notify(app.candidate_id, f"You're invited: {rnd.get('name') or ROUND_TYPES[rnd['type']]}",
           f"{job.title}. Complete it before {att.deadline_at:%d %b}.", "/me/applications")
    if interviewer_id:
        notify(interviewer_id, "New interview assigned", f"{job.title}", f"/app/interviews/{att.id}")
    log("round.invite", "application", app.id, company_id=job.company_id, round=idx, type=rnd["type"])
    return att


def apply_pass_rules(att):
    """After an auto-scored round: advance, reject or leave for the recruiter."""
    app = db.session.get(Application, att.application_id) if att.application_id else None
    if not app:
        return "none"
    cfg = att.config or {}
    if not cfg.get("pass.auto"):
        app.stage = "awaiting_review"
        return "review"
    pct = att.score if att.round_type == "mcq" else (att.score or 0) * 20
    if pct >= cfg.get("pass.advance", 70):
        invite_to_round(app, att.round_index + 1)
        return "advanced"
    if pct < cfg.get("pass.reject", 40):
        app.stage = "rejected"
        app.verdict = "reject"
        return "rejected"
    app.stage = "awaiting_review"
    return "review"


def skill_match(job, profile_skills):
    """Disha's job match: verified levels against what the JD requires."""
    have = {s["name"].lower(): s for s in (profile_skills or [])}
    need = job.skills or []
    if not need:
        return 50, [], []
    got, missing, pts = [], [], 0
    for s in need:
        name = s["name"] if isinstance(s, dict) else s
        lvl = s.get("level", 2) if isinstance(s, dict) else 2
        h = have.get(name.lower())
        if h:
            ratio = min(1, (h.get("level") or 1) / max(1, lvl))
            pts += ratio * (1.4 if h.get("verified") else 1)
            got.append(f"{name} L{h.get('level')}" + (" ✓" if h.get("verified") else ""))
        else:
            missing.append(name)
    return min(100, int(round(100 * pts / len(need)))), got, missing


def issue_credential(user_id, kind, title, skill=None, level=None, grade=None, issuer="Code2Hire", cert_id=None, months=12):
    code = f"C2H-{(skill or kind)[:3].upper()}{level or ''}-{secrets.randbelow(900000) + 100000}"
    c = Credential(code=code, user_id=user_id, kind=kind, title=title, skill=skill, level=level, grade=grade,
                   issuer=issuer, cert_id=cert_id, expires_at=datetime.utcnow() + timedelta(days=30 * months))
    db.session.add(c)
    if skill and level:
        from models import CandidateProfile
        p = CandidateProfile.query.filter_by(user_id=user_id).first()
        if p:
            skills = [dict(s) for s in (p.skills or [])]
            for s in skills:
                if s["name"].lower() == skill.lower():
                    s["level"] = max(s.get("level") or 0, level)
                    s["verified"] = True
                    break
            else:
                skills.append({"name": skill, "level": level, "verified": True, "source": "badge"})
            p.skills = skills
    notify(user_id, f"New {kind}: {title}", f"Verification ID {code}", "/me/badges")
    return c


# ---------------------------------------------------------------- shared helpers for rounds and reports

def context(att):
    """(application, job, candidate user, profile) for an attempt. Any may be None for practice attempts."""
    from models import CandidateProfile
    app = db.session.get(Application, att.application_id) if att.application_id else None
    job = db.session.get(Job, app.job_id) if app else None
    uid = app.candidate_id if app else att.practice_user_id
    if not uid and att.cert_attempt_id:
        from models import CertAttempt
        ca = db.session.get(CertAttempt, att.cert_attempt_id)
        uid = ca.user_id if ca else None
    user = db.session.get(User, uid) if uid else None
    profile = CandidateProfile.query.filter_by(user_id=uid).first() if uid else None
    return app, job, user, profile


def round_name(att, job=None):
    if job and job.rounds and att.round_index < len(job.rounds):
        return job.rounds[att.round_index].get("name") or ROUND_TYPES.get(att.round_type)
    return (att.config or {}).get("title") or ROUND_TYPES.get(att.round_type, att.round_type)


def make_report(att, sections, overall, recommendation, confidence="medium"):
    from models import Report
    r = Report.query.filter_by(attempt_id=att.id).first()
    if not r:
        r = Report(attempt_id=att.id)
        db.session.add(r)
    r.sections = sections
    r.original = sections
    r.overall = overall
    r.recommendation = recommendation
    r.confidence = confidence
    r.status = "awaiting_review"
    app = db.session.get(Application, att.application_id) if att.application_id else None
    if app:
        job = db.session.get(Job, app.job_id)
        from services.audit import notify_roles
        notify_roles(job.company_id, ["recruiter", "manager"], "Report ready to review",
                     f"{round_name(att, job)} for {job.title}", f"/app/reports/{att.id}")
    db.session.flush()
    return r


def spend(company_id, n, reason):
    """Charge credits and fire the credits.threshold policy when usage crosses it."""
    from models import Company
    from services.policy import evaluate
    c = db.session.get(Company, company_id)
    if not c:
        return True
    if c.credits_used + n > c.credits_total:
        return False
    before = int(100 * c.credits_used / max(1, c.credits_total))
    c.credits_used += n
    after = int(100 * c.credits_used / max(1, c.credits_total))
    log("credits.spend", "company", company_id, company_id=company_id, n=n, reason=reason)
    for t in (80, 95, 100):
        if before < t <= after:
            evaluate(company_id, "credits.threshold", {"percent_used": after}, title=f"Credit use at {after}%")
            break
    return True


CREDIT_COST = {"mcq": 1, "ai_interview": 5, "f2f_isha": 3, "f2f_human": 0}
