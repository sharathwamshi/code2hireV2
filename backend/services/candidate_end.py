"""V02.01.04: what the candidate sees and receives when a live interview ends.

The candidate's call screen shows a thank-you with what happens next, whatever way the interview ended (the
interviewer ended it, closed it early, the page was reloaded, the link opened later, or the connection dropped). The
same message goes to their Code2Hire inbox and by email, so they keep the instructions. No AI character appears: the
interview was with a person.
"""
from flask import current_app

from extensions import db


def details(att):
    """{"first", "job", "company", "round", "next_round", "closed"} for the candidate's end screen."""
    from models import Company
    from services.pipeline import context, round_name
    app, job, cand, _ = context(att)
    company = None
    if job and not job.client_hidden:
        co = db.session.get(Company, job.company_id)
        company = co.name if co else None
    nxt = None
    if job and job.rounds and att.round_index is not None and att.round_index + 1 < len(job.rounds):
        nxt = job.rounds[att.round_index + 1].get("name")
    res = att.result or {}
    closed = att.status == "not_finished" or bool(res.get("closed"))
    return {"first": ((cand.name if cand else "") or "").split(" ")[0], "job": job.title if job else "", "company": company,
            "round": round_name(att, job), "next_round": nxt, "closed": closed}


def message(att):
    d = details(att)
    at = f" at {d['company']}" if d["company"] else ""
    if d["closed"]:
        title = "Your interview was stopped before the end"
        lines = [f"Hi {d['first'] or 'there'},", f"Your {d['round']} for {d['job']}{at} was stopped before the end.",
                 "The hiring team will contact you about what happens next. You don't need to do anything now."]
    else:
        title = "Thank you for your interview"
        lines = [f"Hi {d['first'] or 'there'},", f"Thank you for your {d['round']} for {d['job']}{at}. It's complete.",
                 "What happens next: the interviewer submits their notes, then the hiring team reviews them. A person makes every decision.",
                 "You'll hear back in your Code2Hire inbox and by email."]
        if d["next_round"]:
            lines.append(f"Next: {d['next_round']}. You'll get an invite.")
        lines.append("If the hiring team shares a summary of your interview, it will appear with your feedback.")
    return title, lines


def thank(att):
    """Sends the inbox message and the email once per interview. Never raises."""
    res = dict(att.result or {})
    if res.get("thanked"):
        return False
    from services.audit import notify
    from services.pipeline import context
    _, _, cand, _ = context(att)
    if not cand:
        return False
    title, lines = message(att)
    notify(cand.id, title, " ".join(lines[1:]), "/me")
    try:
        from services import mailer
        if mailer.configured() and cand.email:
            from routes.auth import _site_url
            mailer.send(cand.email, title, "\n\n".join(lines) + "\n\nCode2Hire",
                        mailer.layout(title, lines, "Open Code2Hire", f"{_site_url()}/me"))
    except Exception as e:  # noqa: BLE001 - the inbox message is enough when email fails
        current_app.logger.info("thank-you email for attempt %s: %s", att.id, e)
    res["thanked"] = True
    att.result = res
    return True
