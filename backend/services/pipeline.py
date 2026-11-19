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
CALL_KEYS = ["call.enabled", "call.captions", "call.screen_share", "call.chat", "call.watch_focus",
             "call.join_early_minutes", "ai.language"]
ROUND_KEYS = {
    "mcq": ["mcq.questions", "mcq.minutes", "mcq.negative_marking", "mcq.randomise", "mcq.folder_ids",
            "mcq.paper", "mcq.review_before_start", "mcq.fixed_ids"],
    "ai_interview": ["interview.questions", "interview.followup_depth", "interview.difficulty", "interview.minutes",
                     "voice.enabled", "voice.name", "voice.allowed", "voice.rate", "voice.candidate_can_choose",
                     "voice.silence_seconds", "ai.language"],
    "f2f_isha": ["f2f.questions", "f2f.own_questions", "isha.enabled", "isha.options", "isha.hide_ai_scores_until_scorecard"] + CALL_KEYS,
    "f2f_human": ["f2f.questions", "f2f.own_questions"] + CALL_KEYS,
}
COMMON_KEYS = ["pass.advance", "pass.reject", "pass.auto", "integrity.warnings_allowed", "integrity.fullscreen",
               "integrity.face_check", "integrity.block_paste", "integrity.instant_pause", "report.scale",
               "report.review_before_share", "instructions.extra"]


def clean_rounds(rounds, **scope):
    """Rounds as saved on a job or template: known types only, names trimmed, each round's overrides checked against
    the same limits as the settings screens. Returns (rounds, error_message_or_None)."""
    from services.settings import check_round_config
    out, problems = [], []
    for i, r in enumerate(rounds or []):
        if not isinstance(r, dict) or r.get("type") not in ROUND_TYPES:
            continue
        name = (str(r.get("name") or "").strip() or ROUND_TYPES[r["type"]])[:120]
        allowed = set(ROUND_KEYS.get(r["type"], []) + COMMON_KEYS)
        cfg, errs = check_round_config({k: v for k, v in (r.get("config") or {}).items() if k in allowed}, **scope)
        for e in errs.values():
            problems.append(f"Round {i + 1} ({name}): {e}")
        out.append({"type": r["type"], "name": name, "config": cfg})
    return out, (problems[0] if problems else None)


def round_config(job, idx):
    rnd = (job.rounds or [])[idx]
    keys = ROUND_KEYS.get(rnd["type"], []) + COMMON_KEYS
    cfg = {}
    for k in keys:
        v, src, _ = resolve(k, company_id=job.company_id, team_id=job.team_id, job_id=job.id, round_cfg=rnd.get("config") or {})
        cfg[k] = v
    return cfg


def deadline_for(job, days=None):
    """N5 (V02.00.09): rounds have no deadline unless the company sets round.deadline_days (0 = none)."""
    if days is None:
        from services.settings import resolve
        days = int(resolve("round.deadline_days", company_id=job.company_id, team_id=job.team_id, job_id=job.id)[0] or 0)
    return datetime.utcnow() + timedelta(days=days) if days and days > 0 else None


def invite_to_round(app, idx, actor_id=None, interviewer_id=None, scheduled_at=None, days=None):
    job = db.session.get(Job, app.job_id)
    if idx >= len(job.rounds or []):
        app.stage = "decision"
        return None
    rnd = job.rounds[idx]
    open_att = active_attempt(app.id, idx)
    if open_att:  # never two live attempts for the same round: inviting again reschedules the one that exists
        if open_att.status in ("invited", "scheduled"):
            reschedule(open_att, job, interviewer_id, scheduled_at)
        return open_att
    att = RoundAttempt(application_id=app.id, round_index=idx, round_type=rnd["type"], config=round_config(job, idx),
                       status="scheduled" if scheduled_at else "invited", interviewer_id=interviewer_id,
                       scheduled_at=scheduled_at, deadline_at=deadline_for(job, days),
                       result={"invited_by": actor_id} if actor_id else {})  # B5 / F3 (V02.00.12): who sent the invite
    db.session.add(att)
    app.current_round = idx
    app.stage = "in_round"
    db.session.flush()
    from services import papers  # CAN-015 / CAN-016 (V02.00.11): MCQ questions are drawn now, for review
    paper = papers.prepare(att, job)
    if paper == papers.PENDING:
        notify(app.candidate_id, f"You're invited: {rnd.get('name') or ROUND_TYPES[rnd['type']]}",
               f"{job.title}. The hiring team is preparing your test. We'll tell you as soon as you can start.", "/me#upcoming")
        log("round.invite", "application", app.id, company_id=job.company_id, round=idx, type=rnd["type"], paper=paper)
        return att
    if scheduled_at:  # bug 8 (V02.00.07): a scheduled interview opens the Upcoming card on the home page
        notify(app.candidate_id, f"Interview scheduled: {rnd.get('name') or ROUND_TYPES[rnd['type']]}",
               f"{job.title}. The date and time, in your time zone, are on your home page under Upcoming interview.", "/me#upcoming")
    else:
        notify(app.candidate_id, f"You're invited: {rnd.get('name') or ROUND_TYPES[rnd['type']]}",
               f"{job.title}. " + (f"Complete it before {att.deadline_at:%d %b}." if att.deadline_at else "Take it whenever you're ready."), "/me#upcoming")
    if interviewer_id:
        notify(interviewer_id, "New interview assigned", f"{job.title}", f"/app/interviews/{att.id}")
    log("round.invite", "application", app.id, company_id=job.company_id, round=idx, type=rnd["type"])
    return att


ACTIVE = ("invited", "scheduled", "in_progress", "paused")


def join_window(att):
    """For live (face-to-face) rounds: (can_join, opens_at) for the candidate. One rule for the home page, the
    applications list and the call room, so a Join button is only active when the room really lets them in."""
    if att.round_type not in ("f2f_isha", "f2f_human"):
        return True, None
    if att.status in ("completed", "reviewed", "expired", "cancelled"):
        return False, None
    # N5 (V02.00.09): the live setting (default 0 = any time), not the value copied when the invite was sent
    job = db.session.get(Job, db.session.get(Application, att.application_id).job_id) if att.application_id else None
    if job:
        from services.settings import resolve
        early = int(resolve("call.join_early_minutes", company_id=job.company_id, team_id=job.team_id, job_id=job.id)[0] or 0)
    else:
        early = 0
    if not early or not att.scheduled_at:
        return True, None
    opens = att.scheduled_at - timedelta(minutes=early)
    return datetime.utcnow() >= opens, opens


def active_attempt(application_id, idx):
    return (RoundAttempt.query.filter(RoundAttempt.application_id == application_id, RoundAttempt.round_index == idx,
                                      RoundAttempt.status.in_(ACTIVE))
            .order_by(RoundAttempt.id.desc()).first())


def reschedule(att, job, interviewer_id=None, scheduled_at=None):
    """Updates an invited/scheduled attempt in place and tells the people involved."""
    app = db.session.get(Application, att.application_id)
    changed = []
    if interviewer_id and int(interviewer_id) != (att.interviewer_id or 0):
        old = att.interviewer_id
        att.interviewer_id = int(interviewer_id)
        changed.append("interviewer")
        notify(att.interviewer_id, "New interview assigned", job.title, f"/app/isha/{att.id}")
        if old:
            notify(old, "Interview reassigned", f"{job.title}: another interviewer will take it.", "/app/interviews")
    if scheduled_at and scheduled_at != att.scheduled_at:
        att.scheduled_at = scheduled_at
        att.status = "scheduled"
        changed.append("time")
    if changed and app:
        notify(app.candidate_id, "Your interview was updated", f"{job.title}: new {' and '.join(changed)}. Check the time on your home page.",
               "/me#upcoming")
        res = dict(att.result or {})
        res["rescheduled_at"] = datetime.utcnow().isoformat() + "Z"
        att.result = res
        log("round.reschedule", "attempt", att.id, company_id=job.company_id, changed=changed)
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
    """Disha's job match: verified levels against what the JD requires.
    V02.00.10 (JOB-07): a requirement with alternatives ("JavaScript / TypeScript", "framework (React, Angular or Vue)")
    is met by any one of them, and common synonyms count (JS = JavaScript)."""
    from services.skills import find
    have = list(profile_skills or [])
    need = job.skills or []
    if not need:
        return 50, [], []
    got, missing, pts = [], [], 0
    for s in need:
        name = s["name"] if isinstance(s, dict) else s
        lvl = s.get("level", 2) if isinstance(s, dict) else 2
        h = find(name, have)
        if h:
            ratio = min(1, (h.get("level") or 1) / max(1, lvl))
            pts += ratio * (1.4 if h.get("verified") else 1)
            got.append(f"{h['name']} L{h.get('level')}" + (" ✓" if h.get("verified") else ""))
        else:
            missing.append(name)
    return min(100, int(round(100 * pts / len(need)))), got, missing


DONE_STAGES = ("hired", "rejected", "withdrawn", "removed")


def rescore(apps, why):
    """CAN-018 (V02.00.11): recompute the skill match of open applications after the job's skills or the candidate's
    skills change. The previous score is kept in match_reasons["previous"], with why and when, so the change shows."""
    from models import CandidateProfile, Job
    changed = 0
    apps = [a for a in apps if a.stage not in DONE_STAGES]
    # F10 (V02.00.12): jobs and profiles are loaded in two queries, not two per application, so a job with
    # thousands of applicants rescores in a moment inside the save
    jobs = {j.id: j for j in Job.query.filter(Job.id.in_({a.job_id for a in apps} or {0})).all()}
    profs = {}
    ids = list({a.candidate_id for a in apps})
    for i in range(0, len(ids), 500):
        for p in CandidateProfile.query.filter(CandidateProfile.user_id.in_(ids[i:i + 500])).all():
            profs[p.user_id] = p
    for a in apps:
        job = jobs.get(a.job_id)
        p = profs.get(a.candidate_id)
        if not job:
            continue
        score, got, missing = skill_match(job, p.skills if p else [])
        old = dict(a.match_reasons or {})
        if score == a.match_score and got == old.get("matched") and missing == old.get("missing"):
            continue
        new = {**old, "matched": got, "missing": missing,
               "previous": {"score": a.match_score, "at": datetime.utcnow().isoformat() + "Z", "why": why}}
        if old.get("reasons"):
            new["reasons_note"] = "Hira's notes were written before the skills changed. Run Shortlist again to refresh them."
        a.match_score, a.match_reasons = score, new
        changed += 1
    return changed


def rescore_job(job, why="The job's skills changed"):
    from models import Application
    return rescore(Application.query.filter_by(job_id=job.id).all(), why)


def rescore_candidate(user_id, why="The candidate's skills changed"):
    from models import Application
    return rescore(Application.query.filter_by(candidate_id=user_id).all(), why)


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
            from services.skills import same
            for s in skills:
                if same(s["name"], skill):
                    s["level"] = max(s.get("level") or 0, level)
                    s["verified"] = True
                    break
            else:
                skills.append({"name": skill, "level": level, "verified": True, "source": "badge"})
            p.skills = skills
    notify(user_id, f"New {kind}: {title}", f"Verification ID {code}", "/me/badges")
    if skill and level:
        rescore_candidate(user_id, f"{skill} was verified")  # CAN-018 (V02.00.11)
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
    if r.sections != sections:
        r.candidate_feedback = {}  # D1 (V02.00.12): written again (once) the next time it's needed, from the new sections
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
