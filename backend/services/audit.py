from flask import g, has_request_context

from extensions import db
from models import AuditLog, Notification, RoleAssignment


def log(action, target_type=None, target_id=None, company_id=None, **detail):
    actor = getattr(g, "user", None) if has_request_context() else None
    db.session.add(AuditLog(company_id=company_id or (actor.company_id if actor else None),
                            actor_id=actor.id if actor else None, action=action,
                            target_type=target_type, target_id=target_id, detail=detail))


def notify(user_id, title, body="", link=""):
    if user_id:
        db.session.add(Notification(user_id=user_id, title=title, body=body, link=link))


def notify_roles(company_id, roles, title, body="", link=""):
    ids = {r.user_id for r in RoleAssignment.query.filter(RoleAssignment.company_id == company_id,
                                                          RoleAssignment.role.in_(roles)).all()}
    for uid in ids:
        notify(uid, title, body, link)
