"""V02.01.08: Teams: how many interviews each person has taken. Company admins only.

GET /api/teams?from=YYYY-MM-DD&to=YYYY-MM-DD   the summary (tiles, top interviewers, weeks, upcoming, by person)
GET /api/teams/<user_id>?from=…&to=…            one person: their details, tiles and every interview
GET /api/teams/export.csv?from=…&to=…[&person=<id>]   the same as a CSV file
Dates are days in the company's time zone (IST unless set otherwise); the default is this month.
"""
import csv
import io
from datetime import date, datetime, timedelta, timezone

from flask import Blueprint, Response, g, request

from extensions import db
from models import Company, RoleAssignment, User
from routes.utils import err, ok
from services import activity
from services.audit import log
from services.perms import roles_of, staff_required

bp = Blueprint("teams", __name__, url_prefix="/api/teams")


def _admin():
    """Company admins only (the platform team too, when they're helping a company)."""
    u = g.user
    if u.is_superadmin:
        return True
    return RoleAssignment.query.filter_by(user_id=u.id, role="company_admin").first() is not None


def _company():
    from routes.company import cid
    return db.session.get(Company, cid())


def _period(tz):
    """[start, end) in UTC (naive) from ?from and ?to (inclusive days in the company's zone); default: this month."""
    today = datetime.now(timezone.utc).astimezone(tz).date()
    try:
        d1 = date.fromisoformat(request.args["from"]) if request.args.get("from") else today.replace(day=1)
        d2 = date.fromisoformat(request.args["to"]) if request.args.get("to") else (
            (today.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1))
    except ValueError:
        return None
    if d2 < d1 or (d2 - d1).days > 366:
        return None
    to_utc = lambda d: datetime(d.year, d.month, d.day, tzinfo=tz).astimezone(timezone.utc).replace(tzinfo=None)  # noqa: E731
    return to_utc(d1), to_utc(d2 + timedelta(days=1)), d1, d2


def _fmt(dt, tz, f):
    return activity.local(dt, tz).strftime(f).lstrip("0").replace(" 0", " ") if dt else None


def _row(r, tz):
    """One interview, ready for the table: date, time range, duration (or planned), status, result."""
    s = r["start"] or r["scheduled"]
    clock = lambda d: activity.local(d, tz).strftime("%I:%M %p").lstrip("0")  # noqa: E731
    if r["start"] and r["end"]:
        time, dur = f"{clock(r['start'])} – {clock(r['end'])}", f"{r['minutes']} min"
    elif r["status"] == "Upcoming" and r["scheduled"]:
        time, dur = f"{clock(r['scheduled'])} – {clock(r['scheduled'] + timedelta(minutes=r['planned']))}", f"{r['planned']} min planned"
    elif r["status"] == "Upcoming":
        time, dur = "Not scheduled yet", f"{r['planned']} min planned"
    else:
        time, dur = (clock(s) if s else "—"), "—"
    return {"id": r["id"], "date": _fmt(r["when"], tz, "%d %b"), "day": activity.local(r["when"], tz).date().isoformat(), "time": time,
            "duration": dur, "minutes": r["minutes"], "candidate": r["candidate"], "application_id": r["application_id"],
            "report_id": r["report_id"], "attempt_id": r["id"], "job": r["job"], "round": r["round"], "status": r["status"],
            "result": r["result"] or ("—" if r["status"] in ("Upcoming", "Cancelled", "In progress") else None)}


def _people(company_id, rows):
    """Everyone who interviews here: an interviewer role, or an interview in the period."""
    ids = {r["interviewer_id"] for r in rows}
    for ra in RoleAssignment.query.filter_by(role="interviewer").all():
        ids.add(ra.user_id)
    return [u for u in User.query.filter(User.id.in_(ids or [-1]), User.company_id == company_id).all()]


def _hm(minutes):
    return f"{minutes // 60}h {minutes % 60:02d}m" if minutes else "0h 00m"


@bp.get("")
@staff_required
def summary():
    if not _admin():
        return err("Teams is for company admins.", 403)
    co = _company()
    tz = activity.tz_of(co)
    p = _period(tz)
    if not p:
        return err("Choose a period of up to a year: from and to as dates.", 400)
    start, end, d1, d2 = p
    rows = activity.interviews(co.id, start, end)
    c = activity.counts(rows)
    groups = activity.by_person(rows)
    people = []
    for u in _people(co.id, rows):
        mine = groups.get(u.id, [])
        k = activity.counts(mine)
        last = max((r["start"] for r in mine if r["start"] and r["status"] in ("Completed", "Closed early")), default=None)
        people.append({"id": u.id, "name": u.name, "email": u.email, "total": k["total"], "completed": k["completed"], "upcoming": k["upcoming"],
                       "cancelled": k["cancelled"], "pending": k["pending"], "avg_minutes": k["avg_minutes"],
                       "last": _fmt(last, tz, "%d %b") if last else None})
    people.sort(key=lambda x: (-x["total"], x["name"]))
    soon = sorted((r for r in rows if r["status"] == "Upcoming"), key=lambda r: r["scheduled"] or r["when"])
    now = datetime.utcnow()
    soon = [r for r in soon if not r["scheduled"] or r["scheduled"] >= now - timedelta(hours=1)]
    names = {p_["id"]: p_["name"] for p_ in people}
    return ok({"period": {"from": d1.isoformat(), "to": d2.isoformat(), "zone": activity.tz_label(tz)},
               "tiles": {"interviewers": len([x for x in people if x["total"]]) or len(people), "taken": c["completed"],
                         "upcoming": c["upcoming"], "cancelled": c["cancelled"], "pending": c["pending"]},
               "top": [{"id": x["id"], "name": x["name"], "completed": x["completed"]} for x in sorted(people, key=lambda x: -x["completed"]) if x["completed"]][:5],
               "weeks": activity.weeks(rows, start, end, tz),
               "upcoming": {"of": len(soon), "items": [{"candidate": r["candidate"], "application_id": r["application_id"], "with": names.get(r["interviewer_id"], ""),
                                                         "date": _fmt(r["scheduled"] or r["when"], tz, "%d %b"),
                                                         "time": activity.local(r["scheduled"], tz).strftime("%I:%M %p").lstrip("0") if r["scheduled"] else None}
                                                        for r in soon[:5]]},
               "people": people})


@bp.get("/<int:uid>")
@staff_required
def person(uid):
    if not _admin():
        return err("Teams is for company admins.", 403)
    co = _company()
    u = User.query.filter_by(id=uid, company_id=co.id).first()
    if not u:
        return err("That person isn't in this company.", 404)
    tz = activity.tz_of(co)
    p = _period(tz)
    if not p:
        return err("Choose a period of up to a year: from and to as dates.", 400)
    start, end, d1, d2 = p
    rows = activity.interviews(co.id, start, end, interviewer_id=u.id)
    k = activity.counts(rows)
    # last and next interview, whatever the period
    every = activity.interviews(co.id, datetime(2000, 1, 1), datetime(2100, 1, 1), interviewer_id=u.id)
    last = max((r["start"] for r in every if r["start"] and r["status"] in ("Completed", "Closed early")), default=None)
    nxt = min((r["scheduled"] for r in every if r["status"] == "Upcoming" and r["scheduled"] and r["scheduled"] >= datetime.utcnow()), default=None)
    return ok({"period": {"from": d1.isoformat(), "to": d2.isoformat(), "zone": activity.tz_label(tz)},
               "person": {"id": u.id, "name": u.name, "email": u.email, "active": bool(u.active), "roles": [r["label"] for r in roles_of(u)],
                          "last": _fmt(last, tz, "%d %b %Y") if last else None,
                          "next": (_fmt(nxt, tz, "%d %b") + ", " + activity.local(nxt, tz).strftime("%I:%M %p").lstrip("0")) if nxt else None},
               "tiles": {"total": k["total"], "completed": k["completed"], "upcoming": k["upcoming"], "cancelled": k["cancelled"],
                         "pending": k["pending"], "avg_minutes": k["avg_minutes"], "time_spent": _hm(k["minutes"])},
               "interviews": [_row(r, tz) for r in rows]})


@bp.get("/export.csv")
@staff_required
def export():
    if not _admin():
        return err("Teams is for company admins.", 403)
    co = _company()
    tz = activity.tz_of(co)
    p = _period(tz)
    if not p:
        return err("Choose a period of up to a year: from and to as dates.", 400)
    start, end, d1, d2 = p
    pid = request.args.get("person", type=int)
    rows = activity.interviews(co.id, start, end, interviewer_id=pid)
    names = {u.id: u.name for u in User.query.filter(User.id.in_({r["interviewer_id"] for r in rows} or {-1})).all()}
    buf = io.StringIO()
    w = csv.writer(buf)
    zone = activity.tz_label(tz)
    w.writerow(["Interviewer", "Date", f"Time ({zone})", "Duration", "Candidate", "Job role", "Round", "Status", "Result"])
    for r in rows:
        x = _row(r, tz)
        w.writerow([names.get(r["interviewer_id"], ""), x["day"], x["time"], x["duration"], x["candidate"], x["job"], x["round"], x["status"], x["result"] or ""])
    log("teams.export", "company", co.id, company_id=co.id, period=f"{d1}..{d2}", person=pid)
    db.session.commit()
    name = f"interviews-{d1}-to-{d2}" + (f"-{pid}" if pid else "") + ".csv"
    return Response("﻿" + buf.getvalue(), mimetype="text/csv", headers={"Content-Disposition": f'attachment; filename="{name}"'})
