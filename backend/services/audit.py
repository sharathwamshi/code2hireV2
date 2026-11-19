import re

from flask import g, has_request_context

from extensions import db
from models import AuditLog, Notification, RoleAssignment


def log(action, target_type=None, target_id=None, company_id=None, **detail):
    actor = getattr(g, "user", None) if has_request_context() else None
    db.session.add(AuditLog(company_id=company_id or (actor.company_id if actor else None),
                            actor_id=actor.id if actor else None, action=action,
                            target_type=target_type, target_id=target_id, detail=detail))


_ISHA = [  # E3 (V02.00.12): Isha is the interviewer's copilot; candidates never see her name
    (re.compile(r"\b(?:F2F|Live interview|Live video interview)\s+(?:with|\+)\s+(?:the\s+)?Isha(?:\s+copilot)?\b", re.I), "Live interview"),
    (re.compile(r"\s*\(?(?:with|\+)\s+(?:the\s+)?Isha(?:\s+copilot)?\)?", re.I), ""),
    (re.compile(r"\bIsha(?:'s|\u2019s)?\s+(?:copilot|panel|brief|plan|score|scores|notes|live score)\b", re.I), "the interviewer's AI assistant"),
    (re.compile(r",\s*Isha,", re.I), ""),
]


def candidate_text(s):
    """Text shown to a candidate, with Isha's name taken out. Phrases only, so a person called Isha is untouched."""
    if not isinstance(s, str) or "isha" not in s.lower():
        return s
    for rx, to in _ISHA:
        s = rx.sub(to, s)
    return re.sub(r"[ \t]{2,}", " ", s).strip()


def candidate_json(x):
    """candidate_text over every string in a JSON value."""
    if isinstance(x, str):
        return candidate_text(x)
    if isinstance(x, list):
        return [candidate_json(v) for v in x]
    if isinstance(x, dict):
        return {k: candidate_json(v) for k, v in x.items()}
    return x


def notify(user_id, title, body="", link=""):
    if user_id:
        from models import User
        u = db.session.get(User, user_id)
        if u is not None and u.kind == "candidate":
            title, body = candidate_text(title), candidate_text(body)
        db.session.add(Notification(user_id=user_id, title=title, body=body, link=link))


def notify_roles(company_id, roles, title, body="", link=""):
    ids = {r.user_id for r in RoleAssignment.query.filter(RoleAssignment.company_id == company_id,
                                                          RoleAssignment.role.in_(roles)).all()}
    for uid in ids:
        notify(uid, title, body, link)


def notify_round_team(att, job, title, body):
    """B4 / F3 (V02.00.12): a paused round (or a waiting candidate) reaches the people on that job, not only company
    recruiters and managers: whoever created the job, whoever sent the invite, anyone assigned to the job, the
    interviewer, and the company's recruiters, managers and admins. One notification each. Live interviews link to
    the interview page; MCQ and AI rounds link to the round's report page, where Resume is."""
    from models import JobAssignment
    ids = {r.user_id for r in RoleAssignment.query.filter(RoleAssignment.company_id == job.company_id,
                                                          RoleAssignment.role.in_(["recruiter", "manager", "company_admin"])).all()}
    ids |= {a.user_id for a in JobAssignment.query.filter_by(job_id=job.id).all()}
    ids |= {x for x in (job.created_by, (att.result or {}).get("invited_by"), att.interviewer_id) if x}
    for uid in ids:
        link = f"/app/interviews/{att.id}" if att.round_type == "f2f" and uid == att.interviewer_id else f"/app/reports/{att.id}"
        notify(uid, title, body, link)
    return ids
