"""Today: a single action inbox per person, built from their roles, plus notifications."""
from datetime import datetime, timedelta

from flask import Blueprint, g

from extensions import db
from models import Application, Approval, Company, Job, Notification, Report, RoundAttempt, User
from routes.utils import ok
from services.validate import iso
from services.perms import auth_required, can, effective, visible_job_ids
from services.pipeline import round_name

bp = Blueprint("inbox", __name__, url_prefix="/api/inbox")


@bp.get("/today")
@auth_required
def today():
    u = g.user
    cards = []
    if u.kind == "candidate":
        for a in Application.query.filter_by(candidate_id=u.id).all():
            for att in RoundAttempt.query.filter(RoundAttempt.application_id == a.id,
                                                 RoundAttempt.status.in_(["invited", "scheduled", "paused"])).all():
                j = db.session.get(Job, a.job_id)
                paused = att.status == "paused"
                cards.append({"kind": "invite", "priority": 1, "title": f"{round_name(att, j)} · {j.title}",
                              "body": "Paused, waiting for the recruiter" if paused else "",
                              "at": None if paused else iso(att.scheduled_at or att.deadline_at),
                              "at_label": "" if paused else ("At " if att.scheduled_at else "Due "),
                              "link": f"/room/{att.id}", "action": "Open"})
        return ok({"cards": cards, "unread": Notification.query.filter_by(user_id=u.id, read=False).count()})
    if u.is_superadmin and not u.company_id:
        cards.append({"kind": "platform", "priority": 2, "title": "Platform console", "body": "Companies, credits, integrations",
                      "link": "/admin", "action": "Open"})
        return ok({"cards": cards, "unread": Notification.query.filter_by(user_id=u.id, read=False).count()})
    cid = u.company_id
    perms = effective(u, cid)
    if "approvals.decide" in perms:
        for a in Approval.query.filter_by(company_id=cid, status="pending").all():
            if a.requested_by != u.id:
                cards.append({"kind": "approval", "priority": 1, "title": a.title, "body": a.note or a.kind,
                              "link": "/app/approvals", "action": "Decide", "ref": a.id})
    for att in RoundAttempt.query.filter(RoundAttempt.interviewer_id == u.id,
                                         RoundAttempt.status.in_(["invited", "scheduled", "in_progress"])).all():
        a = db.session.get(Application, att.application_id)
        j = db.session.get(Job, a.job_id)
        cand = db.session.get(User, a.candidate_id)
        cards.append({"kind": "interview", "priority": 1 if att.scheduled_at and att.scheduled_at < datetime.utcnow() + timedelta(hours=24) else 2,
                      "title": f"Interview {cand.name}", "body": j.title if att.scheduled_at else f"{j.title} · Not scheduled yet",
                      "at": iso(att.scheduled_at), "at_label": "", "link": f"/app/isha/{att.id}", "action": "Join"})
    ids = visible_job_ids(u, "reports.view")
    jq = Job.query.filter_by(company_id=cid)
    if ids is not None:
        jq = jq.filter(Job.id.in_(ids or [0]))
    jobs = jq.all()
    jids = [j.id for j in jobs] or [0]
    if "reports.view" in perms or ids:
        pending = (Report.query.join(RoundAttempt, RoundAttempt.id == Report.attempt_id)
                   .join(Application, Application.id == RoundAttempt.application_id)
                   .filter(Application.job_id.in_(jids), Report.status == "awaiting_review").all())
        for r in pending[:20]:
            att = db.session.get(RoundAttempt, r.attempt_id)
            a = db.session.get(Application, att.application_id)
            cand = db.session.get(User, a.candidate_id)
            j = db.session.get(Job, a.job_id)
            cards.append({"kind": "review", "priority": 2, "title": f"Review {cand.name}",
                          "body": f"{round_name(att, j)} · {j.title} · Hira says {r.recommendation}",
                          "link": f"/app/reports/{att.id}", "action": "Review"})
    for att in (RoundAttempt.query.join(Application, Application.id == RoundAttempt.application_id)
                .filter(Application.job_id.in_(jids), RoundAttempt.status == "paused").all()):
        a = db.session.get(Application, att.application_id)
        cand = db.session.get(User, a.candidate_id)
        cards.append({"kind": "paused", "priority": 1, "title": f"{cand.name} is paused", "body": att.pause_reason or "",
                      "link": f"/app/reports/{att.id}", "action": "Resume or end"})
    if "candidates.move" in perms or ids:
        for j in jobs:
            n = Application.query.filter_by(job_id=j.id, stage="applied").count()
            if n and j.status == "live":
                cards.append({"kind": "shortlist", "priority": 3, "title": f"{n} new applicants", "body": j.title,
                              "link": f"/app/jobs/{j.id}", "action": "Ask Hira to shortlist"})
        for a in Application.query.filter(Application.job_id.in_(jids), Application.stage == "decision").all():
            cand = db.session.get(User, a.candidate_id)
            j = db.session.get(Job, a.job_id)
            cards.append({"kind": "decision", "priority": 2, "title": f"Decide on {cand.name}", "body": j.title,
                          "link": f"/app/applications/{a.id}", "action": "Decide"})
    c = db.session.get(Company, cid)
    if c and c.credits_total and c.credits_used / c.credits_total >= 0.8 and "billing.view" in perms:
        cards.append({"kind": "credits", "priority": 1, "title": "Credits running low",
                      "body": f"{c.credits_used} of {c.credits_total} used", "link": "/app/admin", "action": "View"})
    cards.sort(key=lambda x: x["priority"])
    return ok({"cards": cards, "unread": Notification.query.filter_by(user_id=u.id, read=False).count()})


@bp.get("/notifications")
@auth_required
def notifications():
    rows = Notification.query.filter_by(user_id=g.user.id).order_by(Notification.created_at.desc()).limit(50).all()
    return ok([n.to_dict() for n in rows])


@bp.post("/notifications/read")
@auth_required
def read_all():
    Notification.query.filter_by(user_id=g.user.id, read=False).update({"read": True})
    db.session.commit()
    return ok()


@bp.post("/notifications/<int:nid>/read")
@auth_required
def read_one(nid):
    n = Notification.query.filter_by(id=nid, user_id=g.user.id).first()
    if not n:
        return ok()  # already cleared: nothing to do
    n.read = True
    db.session.commit()
    return ok()


@bp.delete("/notifications/<int:nid>")
@auth_required
def clear_one(nid):
    Notification.query.filter_by(id=nid, user_id=g.user.id).delete()
    db.session.commit()
    return ok()


@bp.delete("/notifications")
@auth_required
def clear_all():
    """Clear all: removes this person's notifications (only theirs)."""
    n = Notification.query.filter_by(user_id=g.user.id).delete()
    db.session.commit()
    return ok({"cleared": n})
