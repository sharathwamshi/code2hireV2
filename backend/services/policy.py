"""Company rules: When [event] if [conditions] then [require approval | block | notify]."""
from extensions import db
from models import Approval, Policy
from services.audit import log, notify_roles

EVENTS = {
    "job.publish": {"label": "A job is published", "fields": ["visibility", "salary_max", "team_id"]},
    "offer.create": {"label": "An offer is created", "fields": ["salary", "salary_max", "over_band"]},
    "candidate.reject": {"label": "A candidate is rejected", "fields": ["stage", "round_type"]},
    "reinterview.request": {"label": "A re-interview is requested", "fields": ["previous_reinterviews"]},
    "report.share": {"label": "A report is shared", "fields": ["audience"]},
    "grant.create": {"label": "A sensitive permission is granted", "fields": ["permission"]},
    "credits.threshold": {"label": "Credit use crosses a threshold", "fields": ["percent_used"]},
}
ACTIONS = {"require_approval": "Require approval", "block": "Block", "notify": "Notify"}
OPS = {
    "eq": lambda a, b: a == b, "ne": lambda a, b: a != b,
    "gt": lambda a, b: a is not None and b is not None and float(a) > float(b),
    "gte": lambda a, b: a is not None and b is not None and float(a) >= float(b),
    "lt": lambda a, b: a is not None and b is not None and float(a) < float(b),
    "in": lambda a, b: a in (b or []), "any": lambda a, b: True,
}

DEFAULT_POLICIES = [
    {"name": "Public jobs need manager approval", "event": "job.publish",
     "conditions": [{"field": "visibility", "op": "eq", "value": "public"}], "action": "require_approval",
     "params": {"approvals": 1, "roles": ["manager", "company_admin"]}},
    {"name": "Offers above the salary band need two approvals", "event": "offer.create",
     "conditions": [{"field": "over_band", "op": "eq", "value": True}], "action": "require_approval",
     "params": {"approvals": 2, "roles": ["manager", "company_admin"]}},
    {"name": "Only one re-interview per candidate per job", "event": "reinterview.request",
     "conditions": [{"field": "previous_reinterviews", "op": "gte", "value": 1}], "action": "block",
     "params": {"message": "This candidate has already had a re-interview for this job."}},
    {"name": "Tell managers when a candidate is rejected after an interview", "event": "candidate.reject",
     "conditions": [{"field": "round_type", "op": "ne", "value": None}], "action": "notify",
     "params": {"roles": ["manager"]}},
    {"name": "Sharing a sensitive grant needs approval", "event": "grant.create",
     "conditions": [{"field": "permission", "op": "in", "value": ["export", "salary.view"]}],
     "action": "require_approval", "params": {"approvals": 1, "roles": ["company_admin"]}},
    {"name": "Alert at 80% credit use", "event": "credits.threshold",
     "conditions": [{"field": "percent_used", "op": "gte", "value": 80}], "action": "notify",
     "params": {"roles": ["company_admin", "manager"]}},
]


def install_defaults(company_id):
    for p in DEFAULT_POLICIES:
        db.session.add(Policy(company_id=company_id, **p))


def _match(policy, ctx):
    for c in policy.conditions or []:
        fn = OPS.get(c.get("op", "eq"))
        if not fn or not fn(ctx.get(c.get("field")), c.get("value")):
            return False
    return True


def evaluate(company_id, event, ctx, title="", ref_type=None, ref_id=None, requested_by=None, payload=None):
    """Returns {"blocked": msg|None, "approval": Approval|None, "notified": [names]}."""
    out = {"blocked": None, "approval": None, "notified": [], "matched": []}
    for p in Policy.query.filter_by(company_id=company_id, event=event, enabled=True).all():
        if not _match(p, ctx):
            continue
        out["matched"].append(p.name)
        log("policy.hit", "policy", p.id, company_id=company_id, event=event, rule_action=p.action, ctx=ctx)
        if p.action == "block" and not out["blocked"]:
            out["blocked"] = (p.params or {}).get("message") or f"Blocked by policy: {p.name}"
        elif p.action == "require_approval" and not out["approval"]:
            a = Approval(company_id=company_id, kind=event, ref_type=ref_type, ref_id=ref_id,
                         title=title or p.name, requested_by=requested_by,
                         approvals_needed=int((p.params or {}).get("approvals", 1)), payload=payload or {},
                         note=p.name)
            db.session.add(a)
            db.session.flush()
            out["approval"] = a
            notify_roles(company_id, (p.params or {}).get("roles", ["manager", "company_admin"]),
                         "Approval needed", title or p.name, "/app/approvals")
        elif p.action == "notify":
            notify_roles(company_id, (p.params or {}).get("roles", ["manager"]), p.name, title, "/app/today")
            out["notified"].append(p.name)
    return out
