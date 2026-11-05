"""Work that must happen even when nobody clicks: finishing videos whose browser went away, closing live interviews
both people left, deleting videos past their retention period.

Runs at most once a minute from normal API traffic (see app.py), and can also be run from cron:
    flask --app app housekeeping
"""
import time
from datetime import datetime

from extensions import db

ABANDON_S = 30 * 60  # both sides away this long -> the live round closes as "not finished"
_last = {"t": 0.0}


def close_abandoned_calls():
    from models import RoundAttempt
    from services.audit import log, notify, notify_roles
    from services.pipeline import context, round_name
    now = time.time()
    closed = 0
    rows = RoundAttempt.query.filter(RoundAttempt.status.in_(("in_progress", "paused")),
                                     RoundAttempt.round_type.in_(("f2f_isha", "f2f_human"))).limit(200).all()
    for att in rows:
        call = (att.result or {}).get("call") or {}
        seen = [call.get("candidate_seen"), call.get("interviewer_seen")]
        if not any(seen):
            continue  # never used the built-in call (outside meeting); the interviewer closes it
        last = max(s or 0 for s in seen)
        if now - last < ABANDON_S:
            continue
        res = dict(att.result or {})
        res["closed"] = {"reason": "both_left", "at": datetime.utcnow().isoformat() + "Z"}
        att.result = res
        att.status = "not_finished"
        att.completed_at = datetime.utcnow()
        app, job, cand, _ = context(att)
        if app:
            app.stage = "awaiting_review"
        msg = f"{cand.name if cand else 'The candidate'} · {round_name(att, job)}: both people left the call 30 minutes ago, so it was closed as not finished. Submit the scorecard if the interview was done, or invite again."
        if att.interviewer_id:
            notify(att.interviewer_id, "Interview closed as not finished", msg, f"/app/isha/{att.id}")
        if job:
            notify_roles(job.company_id, ["recruiter"], "Interview closed as not finished", msg, f"/app/jobs/{job.id}")
        log("call.abandoned", "attempt", att.id)
        closed += 1
    db.session.commit()
    return closed


def run(force=False):
    if not force and time.time() - _last["t"] < 60:
        return None
    _last["t"] = time.time()
    from routes.recordings import finish_idle, purge_expired
    out = {}
    for name, fn in (("calls_closed", close_abandoned_calls), ("videos_finished", finish_idle), ("videos_deleted", purge_expired)):
        try:
            out[name] = fn()
        except Exception:  # noqa: BLE001 - never break a user's request because of background work
            db.session.rollback()
            import logging
            logging.getLogger(__name__).exception("housekeeping %s", name)
    return out
