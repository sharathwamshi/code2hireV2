"""Candidate disputes: one set of outcomes for the company's reviewers and for the platform team.

reinterview  the candidate gets a fresh attempt at the same round (no credits charged: the platform/company grants it)
changed      the reviewer changed the outcome or scores (they edit the report separately); the note says what changed
dismissed    looked into and the result stands; the note says why
Every outcome is written to the report history, the audit log and the candidate's notifications.
"""
from datetime import datetime

from extensions import db
from models import Application, Report, RoundAttempt, User
from services.audit import log, notify
from services.pipeline import active_attempt, invite_to_round

ACTIONS = {"reinterview": "Re-interview granted", "changed": "Outcome changed", "dismissed": "Dismissed: result stands"}


def status_of(r):
    if r.dispute_status:
        return r.dispute_status
    return "open" if r.disputed else None


def resolve(r, att, job, action, note, actor):
    """Returns (ok, message). Commits on success."""
    if action not in ACTIONS:
        return False, "Choose what to do: re-interview, change the outcome, or dismiss."
    note = (note or "").strip()
    if len(note) < 10:
        return False, "Write at least a sentence for the candidate (10+ characters). They will see it."
    if status_of(r) != "open":
        return False, "This dispute was already resolved."
    app = db.session.get(Application, att.application_id) if att.application_id else None
    new_att = None
    if action == "reinterview":
        if not app:
            return False, "Practice rounds can't be re-interviewed."
        if app.stage in ("withdrawn",):
            return False, "The candidate withdrew from this job."
        if active_attempt(app.id, att.round_index):
            return False, "The candidate already has an open invite for this round."
        new_att = invite_to_round(app, att.round_index, actor.id, att.interviewer_id)
        notes = list(app.notes or [])
        notes.append({"kind": "reinterview", "by": actor.name, "text": "Granted after a dispute: " + note, "at": datetime.utcnow().isoformat() + "Z"})
        app.notes = notes
    r.disputed = False
    r.dispute_status = action
    r.dispute_resolution = note[:2000]
    r.dispute_resolved_by = actor.id
    r.dispute_resolved_at = datetime.utcnow()
    r.history = (r.history or []) + [{"version": r.version, "by": actor.name, "at": datetime.utcnow().isoformat() + "Z",
                                      "note": f"Dispute: {ACTIONS[action]}. {note}"}]
    if app:
        extra = " You've been invited to take this round again; it's on your home page." if new_att else ""
        notify(app.candidate_id, "We looked into your concern", f"{job.title}: {ACTIONS[action]}. {note}{extra}"[:500], "/me/feedback")
    log("report.dispute.resolve", "report", r.id, company_id=job.company_id, outcome=action,
        new_attempt=new_att.id if new_att else None)
    db.session.commit()
    return True, ACTIONS[action]


def row(r):
    """List row for the disputes pages."""
    from models import Company, Job
    att = db.session.get(RoundAttempt, r.attempt_id)
    app = db.session.get(Application, att.application_id) if att and att.application_id else None
    job = db.session.get(Job, app.job_id) if app else None
    cand = db.session.get(User, app.candidate_id) if app else None
    comp = db.session.get(Company, job.company_id) if job else None
    by = db.session.get(User, r.dispute_resolved_by) if r.dispute_resolved_by else None
    from services.pipeline import round_name
    return {"id": r.id, "attempt_id": r.attempt_id, "candidate": cand.name if cand else "", "candidate_email": cand.email if cand else "",
            "company": comp.name if comp else "", "company_id": comp.id if comp else None, "job": job.title if job else "",
            "round": round_name(att, job) if att else "", "type": att.round_type if att else "", "note": r.dispute_note,
            "status": status_of(r), "resolution": r.dispute_resolution, "resolved_by": by.name if by else None,
            "disputed_at": r.disputed_at.isoformat() + "Z" if r.disputed_at else (r.created_at.isoformat() + "Z"),
            "resolved_at": r.dispute_resolved_at.isoformat() + "Z" if r.dispute_resolved_at else None,
            "overall": r.overall, "recommendation": r.recommendation, "warnings": att.warnings or 0 if att else 0}


def query(status=None, company_id=None):
    from models import Job
    q = Report.query.filter((Report.disputed.is_(True)) | (Report.dispute_status.isnot(None)))
    if status == "open":
        q = q.filter((Report.dispute_status == "open") | ((Report.dispute_status.is_(None)) & (Report.disputed.is_(True))))
    elif status == "resolved":
        q = q.filter(Report.dispute_status.in_(list(ACTIONS)))
    if company_id:
        job_ids = [j.id for j in Job.query.filter_by(company_id=company_id).all()] or [0]
        att_ids = db.session.query(RoundAttempt.id).join(Application, Application.id == RoundAttempt.application_id).filter(Application.job_id.in_(job_ids))
        q = q.filter(Report.attempt_id.in_(att_ids))
    return q.order_by(Report.id.desc())
