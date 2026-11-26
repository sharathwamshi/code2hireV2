"""V02.01.08: interviewer activity (the Teams pages) and when an interview really happened (reports).

An interview here is a live round with an interviewer assigned: F2F with Isha, or a live interview without her.
Times are shown in the company's time zone (IST, Asia/Kolkata, unless the company set another).
"""
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from extensions import db

LIVE = ("f2f_isha", "f2f_human")
UPCOMING = ("invited", "scheduled")
CANCELLED = ("cancelled", "voided", "expired")
DONE = ("completed", "reviewed", "not_finished")


def tz_of(company):
    try:
        return ZoneInfo((company.timezone if company else None) or "Asia/Kolkata")
    except Exception:  # noqa: BLE001 - an unknown zone name
        return ZoneInfo("Asia/Kolkata")


def tz_label(tz, when=None):
    """IST for India; otherwise the zone's own abbreviation (or its UTC offset)."""
    key = getattr(tz, "key", "")
    if key in ("Asia/Kolkata", "Asia/Calcutta"):
        return "IST"
    name = (when or datetime.now(timezone.utc)).astimezone(tz).tzname() or key
    return name


def local(dt, tz):
    """A stored (UTC, naive) time in the company's zone."""
    return dt.replace(tzinfo=timezone.utc).astimezone(tz) if dt else None


def _planned(att):
    try:
        return max(10, min(240, int((att.config or {}).get("f2f.minutes", 45))))
    except (TypeError, ValueError):
        return 45


def window(att):
    """When the interview really ran: {start, end (UTC, naive), minutes}; planned length for one not taken yet."""
    res = att.result or {}
    start = att.started_at
    end = None
    if start and isinstance(res.get("ended_at"), (int, float)) and res["ended_at"] > 0:
        end = start + timedelta(seconds=int(res["ended_at"]))
    elif start and att.completed_at and att.completed_at >= start:
        end = att.completed_at
    minutes = max(1, round((end - start).total_seconds() / 60)) if start and end else None
    return {"start": start, "end": end, "minutes": minutes, "planned": _planned(att)}


def _clock(d):
    return d.strftime("%I:%M %p").lstrip("0")


def when_text(att, tz):
    """{"date", "time", "length", "label", "start", "end", "minutes", "zone"} in the company's zone, for reports."""
    w = window(att)
    if not w["start"]:
        return None
    s, e = local(w["start"], tz), local(w["end"], tz)
    zone = tz_label(tz, s)
    date = s.strftime("%a, %d %b %Y").replace(" 0", " ")
    time = f"{_clock(s)} – {_clock(e)} {zone}" if e else f"from {_clock(s)} {zone}"
    length = f"{w['minutes']} min" if w["minutes"] else "—"
    return {"date": date, "time": time, "length": length, "label": f"{date} · {time} · {length}", "zone": zone,
            "start": s.isoformat(), "end": e.isoformat() if e else None, "minutes": w["minutes"]}


def when_of(att):
    """The day an interview belongs to: when it ran, else when it's planned, else when it was set up."""
    return att.started_at or att.scheduled_at or att.created_at


def status_of(att, report):
    """("Upcoming" | "In progress" | "Completed" | "Closed early" | "Cancelled", result word or None, feedback_pending)."""
    res = att.result or {}
    if att.status in CANCELLED:
        return "Cancelled", None, False
    if att.status in UPCOMING:
        return "Upcoming", None, False
    ended = att.status in DONE or bool(res.get("ended"))
    if not ended:
        return ("In progress" if att.status in ("in_progress", "paused") else att.status.replace("_", " ").capitalize()), None, False
    label = "Closed early" if att.status == "not_finished" else "Completed"
    confirmed = report is not None and ((report.sections or {}).get("interviewer") or {}).get("confirmed", True) is not False
    if not confirmed:
        return label, "Feedback pending", True
    word = {"proceed": "Proceed", "hold": "Hold", "reject": "Reject"}.get(report.recommendation)
    return label, word or "Awaiting the hiring team", False


def interviews(company_id, start, end, interviewer_id=None):
    """Live interviews with an interviewer, in [start, end) (UTC, naive), newest first, with what's needed for a row."""
    from models import Application, Job, Report, RoundAttempt, User
    q = (db.session.query(RoundAttempt, Application, Job)
         .join(Application, Application.id == RoundAttempt.application_id)
         .join(Job, Job.id == Application.job_id)
         .filter(Job.company_id == company_id, RoundAttempt.round_type.in_(LIVE), RoundAttempt.interviewer_id.isnot(None)))
    if interviewer_id:
        q = q.filter(RoundAttempt.interviewer_id == interviewer_id)
    rows = []
    atts = [(a, ap, j) for a, ap, j in q.all() if start <= when_of(a) < end]
    reps = {r.attempt_id: r for r in Report.query.filter(Report.attempt_id.in_([a.id for a, _, _ in atts] or [-1])).all()}
    cands = {u.id: u for u in User.query.filter(User.id.in_([ap.candidate_id for _, ap, _ in atts] or [-1])).all()}
    for a, ap, j in atts:
        st, result, pending = status_of(a, reps.get(a.id))
        w = window(a)
        rnd = (j.rounds or [])[a.round_index] if j.rounds and a.round_index is not None and a.round_index < len(j.rounds) else {}
        cand = cands.get(ap.candidate_id)
        rows.append({"id": a.id, "interviewer_id": a.interviewer_id, "when": when_of(a), "start": w["start"], "end": w["end"],
                     "minutes": w["minutes"], "planned": w["planned"], "scheduled": a.scheduled_at, "status": st, "result": result,
                     "pending": pending, "candidate": cand.name if cand else "Candidate", "candidate_id": ap.candidate_id,
                     "application_id": ap.id, "job": j.title, "job_id": j.id, "round": rnd.get("name") or a.round_type,
                     "report_id": reps[a.id].id if a.id in reps else None})
    rows.sort(key=lambda r: r["when"], reverse=True)
    return rows


def counts(rows):
    c = {"total": len(rows), "completed": 0, "upcoming": 0, "cancelled": 0, "pending": 0, "minutes": 0, "timed": 0}
    for r in rows:
        if r["status"] in ("Completed", "Closed early"):
            c["completed"] += 1
        elif r["status"] == "Upcoming":
            c["upcoming"] += 1
        elif r["status"] == "Cancelled":
            c["cancelled"] += 1
        if r["pending"]:
            c["pending"] += 1
        if r["minutes"]:
            c["minutes"] += r["minutes"]
            c["timed"] += 1
    c["avg_minutes"] = round(c["minutes"] / c["timed"]) if c["timed"] else None
    return c


def weeks(rows, start, end, tz):
    """Completed interviews per 7-day block from the start of the period: [{"label", "count"}]."""
    out, s = [], start
    while s < end:
        e = min(s + timedelta(days=7), end)
        n = sum(1 for r in rows if r["status"] in ("Completed", "Closed early") and s <= r["when"] < e)
        a, b = local(s, tz), local(e - timedelta(seconds=1), tz)
        label = f"{a.day}–{b.day} {b.strftime('%b')}" if a.month == b.month else f"{a.day} {a.strftime('%b')}–{b.day} {b.strftime('%b')}"
        out.append({"label": label, "count": n})
        s = e
    return out


def by_person(rows):
    g = defaultdict(list)
    for r in rows:
        g[r["interviewer_id"]].append(r)
    return g
