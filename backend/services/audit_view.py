"""The audit log in plain words (V02.00.08, SA-005 and SA-006).

Each row gets a readable action ("Invited to a round"), a named target ("Arjun Mehta · Senior Python Developer"),
the company, and its details as labelled fields ("Round: 2 · Type: AI interview") instead of raw JSON. Search looks
at all of that.
"""
from extensions import db
from models import Application, Company, Job, RoundAttempt, User

ACTIONS = {
    "application.add": "Candidate added to a job", "application.apply": "Candidate applied", "application.reinterview": "Re-interview requested",
    "application.verdict": "Hiring decision recorded", "application.withdraw": "Application withdrawn", "approval.decide": "Approval decided",
    "assistant.ask": "Asked Hira", "auth.login_failed": "Failed sign-in", "call.abandoned": "Live call closed (both left)", "call.join": "Joined the video call",
    "candidate.add": "Candidate created", "candidate.delete": "Candidate deleted", "candidate.link": "Candidate account linked",
    "candidate.resume": "Resume uploaded", "candidate.signup": "Candidate signed up", "cert.create": "Certification created",
    "cert.publish": "Certification published", "cert.review": "Certification reviewed", "cert.start": "Certification started",
    "cert.update": "Certification changed", "company.credits": "Credits changed", "company.onboard": "Company onboarded",
    "company.profile": "Company profile changed", "company.update": "Company changed", "credential.pdf": "Credential downloaded",
    "credential.revoke": "Credential revoked", "credits.spend": "Credits used", "feedback.pdf": "Feedback downloaded",
    "grant.cover": "Cover access given", "grant.create": "Access granted", "grant.revoke": "Access removed", "hira.shortlist": "Hira shortlisted",
    "integrations.update": "Integration keys changed", "integrity.event": "Integrity warning", "isha.edit_sentence": "Caption corrected",
    "isha.end": "Live interview ended", "isha.scorecard": "Scorecard submitted", "isha.start": "Live interview started",
    "job.assign": "Job assigned", "job.close": "Job closed", "job.create": "Job created", "job.publish": "Job published", "job.update": "Job changed",
    "policy.create": "Policy created", "policy.delete": "Policy deleted", "policy.hit": "Policy triggered", "policy.update": "Policy changed",
    "qbank.create": "Question added", "qbank.duplicate": "Question copied", "qbank.export": "Questions exported", "qbank.generate": "Questions drafted by Hira",
    "qbank.import": "Questions imported", "qbank.restore": "Question version restored", "qbank.update": "Question changed",
    "question.generate": "Global questions drafted", "question.review": "Global question reviewed", "recording.declined": "Recording declined",
    "recording.delete": "Interview video deleted", "recording.download": "Interview video downloaded", "report.dispute": "Report disputed",
    "report.pdf": "Report downloaded", "report.review": "Report reviewed", "report.share": "Report shared", "report.unshare": "Report unshared",
    "round.consent": "Candidate agreed to start", "round.invite": "Invited to a round", "round.reschedule": "Round rescheduled",
    "round.resume": "Round resumed", "round.start": "Round started", "settings.platform": "Platform settings changed",
    "settings.update": "Settings changed", "support.access": "Support access opened", "syscheck.help": "Asked for help with the system check",
    "syscheck.run": "System check run", "syscheck.stuck": "Stuck in the system check", "team.create": "Team created",
    "template.archive": "Template archived", "template.create": "Template created", "template.delete": "Template deleted for good",
    "template.duplicate": "Template copied", "template.update": "Template changed", "user.archive": "User deleted (archived)",
    "user.invite": "User invited", "user.password_changed": "Password changed", "user.rename": "Name changed", "user.reset_password": "Password reset",
    "user.restore": "User restored", "user.roles": "Roles changed", "user.update": "User changed",
}
TARGETS = {"application": "Application", "approval": "Approval", "assistant": "Hira", "attempt": "Round", "cert": "Certification",
           "certification": "Certification", "company": "Company", "credential": "Credential", "folder": "Folder", "grant": "Access grant",
           "job": "Job", "policy": "Policy", "question": "Question", "report": "Report", "role": "Role", "setting": "Setting",
           "team": "Team", "template": "Template", "user": "User", "recording": "Video"}
FIELDS = {"round": "Round", "type": "Type", "role": "Role", "status": "Status", "name": "Name", "email": "Email", "title": "Title",
          "overall": "Score", "rec": "Recommendation", "recommendation": "Recommendation", "keys": "Keys", "minutes": "Minutes",
          "amount": "Amount", "credits": "Credits", "reason": "Reason", "ip": "IP address", "via": "Via", "video": "Video",
          "changed": "Changed", "version": "Version", "count": "Count", "n": "Count", "skill": "Skill", "skills": "Skills",
          "level": "Level", "approve": "Approved", "verdict": "Decision", "index": "Question", "sentence": "Sentence",
          "removed": "Removed", "step": "Step", "passed": "Passed", "mode": "Mode", "when": "When", "scheduled_at": "Scheduled for"}
VALUES = {"mcq": "MCQ test", "ai_interview": "AI interview", "f2f_isha": "Live interview with Isha", "f2f_human": "Live interview",
          "proceed": "Proceed", "hold": "Hold", "reject": "Do not proceed", "not_connected": "Started before the video connected",
          "candidate_absent": "Started before the candidate joined", "interviewer": "Interviewer", "candidate": "Candidate"}


def action_label(code):
    return ACTIONS.get(code) or (code or "").replace(".", " ").replace("_", " ").capitalize()


def matching_actions(term):
    """Action codes whose plain-words label contains the search term ("invited" finds round.invite)."""
    t = (term or "").lower().strip()
    return [k for k, v in ACTIONS.items() if t and t in v.lower()]


def _val(k, v):
    if isinstance(v, bool):
        return "Yes" if v else "No"
    if k == "round" and isinstance(v, int):
        return str(v + 1)  # rounds are stored from 0; people count from 1
    if isinstance(v, list):
        return ", ".join(str(VALUES.get(x, x)) for x in v[:8]) + ("…" if len(v) > 8 else "")
    if isinstance(v, dict):
        return ", ".join(f"{FIELDS.get(a, a.replace('_', ' ').capitalize())}: {b}" for a, b in list(v.items())[:6])
    return str(VALUES.get(v, v)) if v is not None else "—"


def detail_items(detail):
    """[{"label", "value"}] from the stored JSON."""
    if not isinstance(detail, dict):
        return [{"label": "Detail", "value": str(detail)}] if detail else []
    return [{"label": FIELDS.get(k, k.replace("_", " ").capitalize()), "value": _val(k, v)} for k, v in detail.items()]


def target_label(a, cache):
    """A name for the thing the action was done to."""
    t, i = a.target_type, a.target_id
    base = TARGETS.get(t, (t or "").capitalize())
    if not i:
        return base or "—"
    key = (t, i)
    if key in cache:
        return cache[key]
    name = None
    try:
        if t == "application":
            app = db.session.get(Application, i)
            if app:
                cand, job = db.session.get(User, app.candidate_id), db.session.get(Job, app.job_id)
                name = " · ".join(x for x in ((cand.name if cand else None), (job.title if job else None)) if x)
        elif t == "attempt":
            att = db.session.get(RoundAttempt, i)
            if att:
                from services.pipeline import context
                _, job, cand, _ = context(att)
                name = " · ".join(x for x in ((cand.name if cand else None), (job.title if job else None), VALUES.get(att.round_type)) if x)
        elif t == "user":
            u = db.session.get(User, i)
            name = u.name if u else None
        elif t == "job":
            j = db.session.get(Job, i)
            name = j.title if j else None
        elif t == "company":
            c = db.session.get(Company, i)
            name = c.name if c else None
        elif t == "template":
            from models import HiringTemplate
            x = db.session.get(HiringTemplate, i)
            name = x.name if x else None
    except Exception:
        name = None
    out = f"{base}: {name}" if name else f"{base} #{i}"
    cache[key] = out
    return out


def serialize(a, cache, companies):
    d = a.to_dict()
    u = db.session.get(User, a.actor_id) if a.actor_id else None
    d["actor"] = u.name if u else "System"
    d["action_label"] = action_label(a.action)
    d["target_label"] = target_label(a, cache)
    d["company"] = companies.get(a.company_id)
    d["detail_items"] = detail_items(a.detail)
    return d


def search(query, term):
    """Search across the action (code and plain words), who did it, the company, the target number and the details."""
    from sqlalchemy import String, cast, or_
    from models import AuditLog
    t = (term or "").strip()
    if not t:
        return query
    like = f"%{t}%"
    conds = [AuditLog.action.ilike(like), AuditLog.target_type.ilike(like), cast(AuditLog.detail, String).ilike(like)]
    codes = matching_actions(t)
    if codes:
        conds.append(AuditLog.action.in_(codes))
    users = [u.id for u in User.query.filter(or_(User.name.ilike(like), User.email.ilike(like))).limit(200).all()]
    if users:
        conds.append(AuditLog.actor_id.in_(users))
        conds.append((AuditLog.target_type == "user") & AuditLog.target_id.in_(users))
        apps = [a.id for a in Application.query.filter(Application.candidate_id.in_(users)).limit(500).all()]
        if apps:
            conds.append((AuditLog.target_type == "application") & AuditLog.target_id.in_(apps))
            atts = [x.id for x in RoundAttempt.query.filter(RoundAttempt.application_id.in_(apps)).limit(1000).all()]
            if atts:
                conds.append((AuditLog.target_type == "attempt") & AuditLog.target_id.in_(atts))
    cos = [c.id for c in Company.query.filter(Company.name.ilike(like)).all()]
    if cos:
        conds.append(AuditLog.company_id.in_(cos))
    num = t.lstrip("#")
    if num.isdigit():
        conds.append(AuditLog.target_id == int(num))
        conds.append(AuditLog.id == int(num))
    if t.lower() == "system":
        conds.append(AuditLog.actor_id.is_(None))
    return query.filter(or_(*conds))
