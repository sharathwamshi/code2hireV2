"""V02.00.08: removing and re-adding people, and retaking a round after a technical problem.

Remove from job      the application leaves the pipeline (stage "removed"); open invites are cancelled and their
                     credits come back; reports and videos stay. Restore continues where they left off, or Start
                     fresh keeps earlier rounds as history (voided) and begins again from round 1.
Remove from pool     the company stops seeing the candidate in its talent pool and searches; their own account and
                     their jobs are untouched. Adding them again brings them back.
Technical retake     the round that went wrong is voided (kept for the audit trail and its video kept, left out of
                     scores and decisions) and a new invite is sent for the same round. Anyone on the hiring team who
                     can see the job can do it. It's charged like a re-interview, and limited per candidate per round
                     by the superadmin's "policy.retake_max" (default 5).
"""
from datetime import datetime

from extensions import db
from models import Application, Recording, Report, RoundAttempt
from services.audit import log
from services.pipeline import ACTIVE, CREDIT_COST, invite_to_round, spend

RETAKE_REASONS = {
    "video": "The video didn't connect",
    "audio": "Audio problems (couldn't hear or be heard)",
    "candidate_device": "The candidate's camera, microphone or computer failed",
    "internet": "The internet connection dropped",
    "platform": "A Code2Hire error",
    "interviewer_device": "The interviewer's camera, microphone or computer failed",
    "other": "Something else",
}
RETAKEABLE = ("in_progress", "paused", "completed", "reviewed", "not_finished", "expired")


def refund(company_id, n, reason):
    """Gives back credits for an invite that never ran."""
    from models import Company
    c = db.session.get(Company, company_id)
    if c and n:
        c.credits_used = max(0, (c.credits_used or 0) - n)
        log("credits.refund", "company", company_id, company_id=company_id, n=n, reason=reason)


def _void(att, kind, by, reason=None, note=None, evidence=None):
    res = dict(att.result or {})
    res["voided"] = {"kind": kind, "reason": reason, "reason_text": RETAKE_REASONS.get(reason) if reason else None,
                     "note": (note or "")[:1000], "by": by.id, "by_name": by.name, "at": datetime.utcnow().isoformat() + "Z",
                     "status_before": att.status, "evidence": evidence or {}}
    att.result = res
    att.status = "voided"
    r = Report.query.filter_by(attempt_id=att.id).first()
    if r and r.status != "voided":
        r.status = "voided"


# ---------------------------------------------------------------- technical retake

def retakes_used(app_id, idx):
    return sum(1 for a in RoundAttempt.query.filter_by(application_id=app_id, round_index=idx).all()
               if ((a.result or {}).get("voided") or {}).get("kind") == "technical")


def retake_limit(job):
    from services.settings import resolve
    return int(resolve("policy.retake_max", company_id=job.company_id)[0] or 0)


def evidence(att):
    """What Code2Hire recorded about the round, attached to the retake so anyone can see why."""
    out = {"status": att.status, "warnings": att.warnings or 0,
           "minutes": round((((att.completed_at or datetime.utcnow()) - att.started_at).total_seconds()) / 60, 1) if att.started_at else 0,
           "videos": Recording.query.filter(Recording.attempt_id == att.id, Recording.status.in_(("ready", "processing"))).count()}
    if att.round_type.startswith("f2f"):
        from routes.call import path_summary
        out["connection"] = path_summary(att)
        out["started_without_video"] = (att.result or {}).get("started_without_video")
    try:
        from services.syscheck import summary
        out["setup_candidate"] = summary(att, "candidate")
        if att.round_type.startswith("f2f"):
            out["setup_interviewer"] = summary(att, "interviewer")
    except Exception:
        pass
    return out


def retake(att, job, by, reason, note=None, interviewer_id=None, scheduled_at=None):
    """Returns (new attempt, None) or (None, error message)."""
    if reason not in RETAKE_REASONS:
        return None, "Choose what went wrong."
    if reason == "other" and not (note or "").strip():
        return None, "Say briefly what went wrong."
    if not att.application_id:
        return None, "Only hiring rounds can be retaken."
    if att.status not in RETAKEABLE:
        return None, ("This round hasn't started yet. Reschedule it instead." if att.status in ("invited", "scheduled")
                      else "This round can't be retaken.")
    app = db.session.get(Application, att.application_id)
    if app.stage in ("removed", "withdrawn"):
        return None, "This candidate isn't in the job any more."
    limit = retake_limit(job)
    used = retakes_used(app.id, att.round_index)
    if used >= limit:
        return None, f"This candidate has had {used} technical retake{'s' if used != 1 else ''} of this round, the most Code2Hire allows ({limit})."
    other = (RoundAttempt.query.filter(RoundAttempt.application_id == app.id, RoundAttempt.round_index == att.round_index,
                                       RoundAttempt.id != att.id, RoundAttempt.status.in_(ACTIVE)).first())
    if other:
        return None, "A newer invite for this round is already open. Use that one."
    cost = CREDIT_COST.get(att.round_type, 0)
    if not spend(job.company_id, cost, f"technical retake of round {att.round_index + 1} for application {app.id}"):
        return None, "Not enough credits. Ask your admin to top up."
    ev = evidence(att)
    was_live = att.status in ("in_progress", "paused")
    _void(att, "technical", by, reason, note, ev)
    db.session.flush()
    new = invite_to_round(app, att.round_index, by.id, interviewer_id or att.interviewer_id, scheduled_at)
    if not new:
        return None, "Couldn't create the new invite."
    res = dict(new.result or {})
    res["retake_of"] = att.id
    res["retake_reason"] = RETAKE_REASONS[reason]
    new.result = res
    vres = dict(att.result)
    vres["voided"] = {**vres["voided"], "retake_attempt_id": new.id}
    att.result = vres
    notes = list(app.notes or [])
    notes.append({"kind": "retake", "by": by.name, "text": f"Retake (technical problem): {RETAKE_REASONS[reason]}" + (f". {note.strip()}" if (note or "").strip() else ""),
                  "at": datetime.utcnow().isoformat() + "Z"})
    app.notes = notes
    if was_live:  # anyone still in the room is told the round ended, so nobody keeps talking to a voided session
        from models import CallSignal
        db.session.add(CallSignal(attempt_id=att.id, sender="interviewer", kind="bye", payload={"ended": True, "retake": True}))
    log("round.retake", "attempt", att.id, company_id=job.company_id, reason=reason, note=(note or "")[:200], new_attempt=new.id,
        used=used + 1, limit=limit, credits=cost)
    return new, None


# ---------------------------------------------------------------- remove from job / restore

def remove_from_job(app, job, by, note=None):
    if app.stage == "removed":
        return "Already removed from this job."
    live = RoundAttempt.query.filter(RoundAttempt.application_id == app.id, RoundAttempt.status.in_(("in_progress", "paused"))).first()
    if live:
        return "This candidate is taking a round right now. Wait for it to end, or retake it, before removing them."
    for a in RoundAttempt.query.filter(RoundAttempt.application_id == app.id, RoundAttempt.status.in_(("invited", "scheduled"))).all():
        a.status = "cancelled"
        refund(job.company_id, CREDIT_COST.get(a.round_type, 0), f"invite cancelled: candidate removed from job {job.id}")
    app.removed_stage = app.stage
    app.removed_at, app.removed_by = datetime.utcnow(), by.id
    app.stage = "removed"
    notes = list(app.notes or [])
    notes.append({"kind": "removed", "by": by.name, "text": "Removed from the job" + (f": {note.strip()}" if (note or "").strip() else ""),
                  "at": datetime.utcnow().isoformat() + "Z"})
    app.notes = notes
    log("application.remove", "application", app.id, company_id=job.company_id, note=(note or "")[:200])
    return None


def restore_to_job(app, job, by, mode="continue"):
    """continue: back to where they were. fresh: earlier rounds stay as history (voided), and they start at round 1."""
    if app.stage != "removed":
        return "This candidate is in the job already."
    if mode not in ("continue", "fresh"):
        return "Choose Restore or Start fresh."
    if mode == "fresh":
        for a in RoundAttempt.query.filter(RoundAttempt.application_id == app.id, RoundAttempt.status != "voided",
                                           RoundAttempt.status != "cancelled").all():
            _void(a, "fresh_start", by, note="Candidate re-added to the job and started fresh")
        app.stage, app.current_round = "applied", -1
        app.verdict, app.verdict_by, app.verdict_note = None, None, None
    else:
        app.stage = app.removed_stage or "applied"
    app.removed_at = app.removed_by = app.removed_stage = None
    notes = list(app.notes or [])
    notes.append({"kind": "restored", "by": by.name, "text": "Started fresh from round 1" if mode == "fresh" else "Restored to the job",
                  "at": datetime.utcnow().isoformat() + "Z"})
    app.notes = notes
    log("application.restore", "application", app.id, company_id=job.company_id, mode=mode)
    return None


# ---------------------------------------------------------------- talent pool

def pool_removed_ids(company_id):
    from models import PoolRemoval
    return {r.user_id for r in PoolRemoval.query.filter_by(company_id=company_id).all()}


def back_in_pool(company_id, user_id):
    """Adding someone again (to a job, by email or from search) brings them back to the pool."""
    from models import PoolRemoval
    PoolRemoval.query.filter_by(company_id=company_id, user_id=user_id).delete()
