"""Interview reports (audience views, review, versions, sharing) and analytics (dashboards, report builder, exports)."""
import csv
import io
import secrets
from collections import defaultdict
from datetime import datetime, timedelta

from flask import Blueprint, Response, g, request

from extensions import db
from models import Application, Job, Report, RoundAttempt, SavedReport, Turn, User
from routes.utils import body, err, ok, table
from services import ai
from services.audit import log, notify
from services.perms import can, can_any, deny, staff_required, visible_job_ids
from services.pipeline import context, round_name
from services.policy import evaluate
from services.settings import resolve

bp = Blueprint("reports", __name__, url_prefix="/api")


def cid():
    if g.user.is_superadmin and request.headers.get("X-Company-Id"):
        return int(request.headers["X-Company-Id"])
    return g.user.company_id


def _load(rid):
    r = db.session.get(Report, rid)
    if not r:
        return None, None, None
    att = db.session.get(RoundAttempt, r.attempt_id)
    app, job, cand, profile = context(att)
    if not job or job.company_id != cid():
        return None, None, None
    if not (can(g.user, "reports.view", job=job) or att.interviewer_id == g.user.id):
        return None, None, None
    return r, att, job


def view(r, att, job, audience="internal"):
    app, _, cand, profile = context(att)
    s = dict(r.sections or {})
    out = {"id": r.id, "attempt_id": att.id, "status": r.status, "version": r.version, "audience": audience,
           "round": round_name(att, job), "type": att.round_type, "job": {"id": job.id, "title": job.title},
           "application_id": app.id if app else None,
           "candidate": {"id": cand.id, "name": cand.name, "headline": profile.headline if profile else ""} if cand else None,
           "overall": r.overall, "recommendation": r.recommendation, "confidence": r.confidence, "verdict": r.verdict,
           "note": r.note, "scale": resolve("report.scale", company_id=job.company_id, team_id=job.team_id, job_id=job.id)[0],
           "completed_at": att.completed_at.isoformat() + "Z" if att.completed_at else None,
           "warnings": att.warnings, "disputed": r.disputed, "dispute_note": r.dispute_note,
           "shared_with_candidate": r.shared_with_candidate, "history": r.history or []}
    if att.interviewer_id:
        iv = db.session.get(User, att.interviewer_id)
        out["interviewer"] = iv.name if iv else None
    if audience in ("internal", "hiring_manager"):
        out["sections"] = s
        out["recording"] = [{"part": i, "seconds": p.get("seconds"), "bytes": p.get("bytes")}
                            for i, p in enumerate((att.result or {}).get("recording") or [])]
    elif audience == "client":
        hide = set(resolve("report.client_hide", company_id=job.company_id, team_id=job.team_id, job_id=job.id)[0] or [])
        s = {k: v for k, v in s.items() if k not in ("notes", "interviewer_note")}
        if "integrity" in hide:
            s.pop("integrity", None)
            out["warnings"] = None
        if "ai_scores" in hide:
            s["competencies"] = [{k: v for k, v in c.items() if k != "ai_score"} for c in s.get("competencies", [])]
            s.pop("ai_agreement", None)
        if "replay" in hide:
            s["questions"] = [{k: v for k, v in q.items() if k not in ("a", "tags")} for q in s.get("questions", [])]
        out["sections"] = s
        out["history"] = []
        if job.client_hidden is False and "salary" in hide:
            out["job"] = {"id": job.id, "title": job.title}
    elif audience == "candidate":
        allowed = resolve("report.candidate_sections", company_id=job.company_id, team_id=job.team_id, job_id=job.id)[0] or []
        fb = r.candidate_feedback or ai.candidate_feedback(s, company_id=job.company_id)
        out["sections"] = {k: v for k, v in fb.items() if k in allowed or k == "next_steps" and "learning_path" in allowed}
        for k in ("overall", "recommendation", "confidence", "verdict", "note", "history", "interviewer", "warnings"):
            out.pop(k, None)
    return out


@bp.get("/reports")
@staff_required
def reports():
    jobs_q = Job.query.filter_by(company_id=cid())
    ids = visible_job_ids(g.user, "reports.view")
    if ids is not None:
        jobs_q = jobs_q.filter(Job.id.in_(ids or [0]))
    job_ids = [j.id for j in jobs_q.all()] or [0]
    q = (Report.query.join(RoundAttempt, RoundAttempt.id == Report.attempt_id)
         .join(Application, Application.id == RoundAttempt.application_id)
         .join(User, User.id == Application.candidate_id)
         .filter(Application.job_id.in_(job_ids)))

    def ser(r):
        att = db.session.get(RoundAttempt, r.attempt_id)
        app = db.session.get(Application, att.application_id)
        job = db.session.get(Job, app.job_id)
        cand = db.session.get(User, app.candidate_id)
        return {"id": r.id, "attempt_id": att.id, "status": r.status, "overall": r.overall, "recommendation": r.recommendation,
                "verdict": r.verdict, "candidate": cand.name, "job": job.title, "job_id": job.id, "round": round_name(att, job),
                "type": att.round_type, "warnings": att.warnings, "completed_at": att.completed_at.isoformat() + "Z" if att.completed_at else None,
                "disputed": r.disputed, "application_id": app.id}
    return table(q, [User.name], {"created": Report.created_at, "overall": Report.overall, "candidate": User.name,
                                  "status": Report.status},
                 "created", ser,
                 {"status": lambda q, v: q.filter(Report.status == v), "recommendation": lambda q, v: q.filter(Report.recommendation == v),
                  "job_id": lambda q, v: q.filter(Application.job_id == int(v)),
                  "type": lambda q, v: q.filter(RoundAttempt.round_type == v),
                  "disputed": lambda q, v: q.filter(Report.disputed.is_(True)) if v == "true" else q})


@bp.get("/reports/<int:rid>")
@staff_required
def get_report(rid):
    r, att, job = _load(rid)
    if not r:
        return deny("You can't see this report.")
    aud = request.args.get("audience", "internal")
    if aud not in ("internal", "hiring_manager", "client", "candidate"):
        aud = "internal"
    out = view(r, att, job, aud)
    out["can"] = {"review": can(g.user, "verdict.recommend", job=job), "share": can(g.user, "reports.share", job=job)}
    return ok(out)


@bp.get("/reports/by-attempt/<int:att_id>")
@staff_required
def by_attempt(att_id):
    r = Report.query.filter_by(attempt_id=att_id).first()
    if not r:
        att = db.session.get(RoundAttempt, att_id)
        if not att:
            return err("Not found", 404)
        return ok({"pending": True, "attempt": {**att.to_dict(exclude=("result", "brief")), "integrity_events": _events(att)}})
    return get_report(r.id)


def _events(att):
    from models import IntegrityEvent
    return [e.to_dict() for e in IntegrityEvent.query.filter_by(attempt_id=att.id).all()]


@bp.get("/reports/<int:rid>/transcript")
@staff_required
def report_transcript(rid):
    r, att, job = _load(rid)
    if not r:
        return deny()
    return ok({"turns": [t.to_dict() for t in Turn.query.filter_by(attempt_id=att.id).order_by(Turn.seq).all()],
               "integrity": _events(att)})


@bp.post("/reports/<int:rid>/review")
@staff_required
def review(rid):
    """A person checks the AI's work: edit scores (with a reason), add a note, record a verdict. Every change is versioned."""
    r, att, job = _load(rid)
    if not r:
        return deny()
    if not can(g.user, "verdict.recommend", job=job) and att.interviewer_id != g.user.id:
        return deny()
    d = body()
    sections = dict(r.sections or {})
    changes = []
    for edit in d.get("edits", []):
        for c in sections.get("competencies", []):
            if c["name"] == edit.get("name") and edit.get("score") is not None and c.get("score") != edit["score"]:
                if not edit.get("reason"):
                    return err(f"Give a reason for changing {c['name']}.")
                changes.append({"name": c["name"], "from": c.get("score"), "to": edit["score"], "reason": edit["reason"]})
                c["score"] = edit["score"]
                c["level"] = "Strong" if float(edit["score"]) >= 4 else ("Meets" if float(edit["score"]) >= 3 else "Weak")
    if changes:
        scored = [float(c["score"]) for c in sections.get("competencies", []) if c.get("score") is not None]
        if scored and att.round_type != "mcq":
            r.overall = round(sum(scored) / len(scored), 1)
    r.sections = sections
    if d.get("verdict"):
        r.verdict = d["verdict"]
    if "note" in d:
        r.note = d["note"]
    r.history = (r.history or []) + [{"version": r.version + 1, "by": g.user.name, "at": datetime.utcnow().isoformat() + "Z",
                                      "changes": changes, "verdict": d.get("verdict"), "note": d.get("note")}]
    r.version += 1
    r.status = "reviewed"
    r.reviewer_id = g.user.id
    r.reviewed_at = datetime.utcnow()
    if att.status == "completed":
        att.status = "reviewed"
    app = db.session.get(Application, att.application_id)
    if app and app.stage == "awaiting_review":
        app.stage = "decision"
    log("report.review", "report", rid, company_id=job.company_id, changes=changes, verdict=d.get("verdict"))
    db.session.commit()
    return get_report(rid)


@bp.post("/reports/<int:rid>/share")
@staff_required
def share(rid):
    r, att, job = _load(rid)
    if not r:
        return deny()
    if not can(g.user, "reports.share", job=job):
        return deny()
    d = body()
    aud = d.get("audience", "client")
    must_review, _, _ = resolve("report.review_before_share", company_id=job.company_id, team_id=job.team_id, job_id=job.id)
    if must_review and r.status == "awaiting_review":
        return err("A person must review this report before it's shared.", 409)
    res = evaluate(job.company_id, "report.share", {"audience": aud}, title=f"Share report ({aud}) for {job.title}",
                   ref_type="report", ref_id=rid, requested_by=g.user.id)
    if res["blocked"]:
        return err(res["blocked"], 403)
    if res["approval"]:
        db.session.commit()
        return ok({"approval": True})
    out = {}
    if aud == "candidate":
        r.candidate_feedback = ai.candidate_feedback(r.sections or {}, company_id=job.company_id)
        r.shared_with_candidate = True
        app = db.session.get(Application, att.application_id)
        notify(app.candidate_id, "Your interview feedback is ready", job.title, "/me/feedback")
    else:
        r.share_token = secrets.token_urlsafe(16)
        r.share_audience = aud
        r.share_expires_at = datetime.utcnow() + timedelta(days=int(d.get("days", 7)))
        out = {"token": r.share_token, "link": f"/shared/{r.share_token}", "expires_at": r.share_expires_at.isoformat() + "Z"}
    r.status = "shared"
    log("report.share", "report", rid, company_id=job.company_id, audience=aud)
    db.session.commit()
    return ok(out)


@bp.post("/reports/<int:rid>/unshare")
@staff_required
def unshare(rid):
    r, att, job = _load(rid)
    if not r or not can(g.user, "reports.share", job=job):
        return deny()
    r.share_token = None
    r.share_expires_at = None
    log("report.unshare", "report", rid, company_id=job.company_id)
    db.session.commit()
    return ok()


@bp.post("/reports/<int:rid>/resolve-dispute")
@staff_required
def resolve_dispute(rid):
    r, att, job = _load(rid)
    if not r or not can(g.user, "verdict.recommend", job=job):
        return deny()
    r.disputed = False
    r.history = (r.history or []) + [{"version": r.version, "by": g.user.name, "at": datetime.utcnow().isoformat() + "Z",
                                      "note": "Dispute resolved: " + (body().get("note") or "")}]
    app = db.session.get(Application, att.application_id)
    notify(app.candidate_id, "We looked into your concern", body().get("note") or job.title, "/me/feedback")
    db.session.commit()
    return ok()


# ---------------------------------------------------------------- analytics

def _job_ids():
    q = Job.query.filter_by(company_id=cid())
    ids = visible_job_ids(g.user, "analytics.view")
    if ids is not None:
        q = q.filter(Job.id.in_(ids or [0]))
    if request.args.get("job_id"):
        q = q.filter(Job.id == int(request.args["job_id"]))
    return [j.id for j in q.all()] or [0]


def _since():
    days = int(request.args.get("days") or 90)
    return datetime.utcnow() - timedelta(days=days)


@bp.get("/analytics/overview")
@staff_required
def overview():
    if not can_any(g.user, "analytics.view", cid()):
        return deny()
    jids = _job_ids()
    since = _since()
    apps = Application.query.filter(Application.job_id.in_(jids), Application.created_at >= since).all()
    order = ["applied", "shortlisted", "in_round", "awaiting_review", "decision", "offer", "hired"]
    reached = {s: 0 for s in order}
    for a in apps:
        if a.stage in order:
            for s in order[:order.index(a.stage) + 1]:
                reached[s] += 1
        elif a.stage in ("rejected", "on_hold"):
            reached["applied"] += 1
    atts = (RoundAttempt.query.join(Application, Application.id == RoundAttempt.application_id)
            .filter(Application.job_id.in_(jids), RoundAttempt.created_at >= since).all())
    done = [a for a in atts if a.completed_at]
    flagged = [a for a in done if a.warnings]
    pending = (Report.query.join(RoundAttempt, RoundAttempt.id == Report.attempt_id)
               .join(Application, Application.id == RoundAttempt.application_id)
               .filter(Application.job_id.in_(jids), Report.status == "awaiting_review").count())
    tt = [(a.completed_at - a.created_at).total_seconds() / 3600 for a in done]
    by_type = defaultdict(lambda: {"n": 0, "score": 0})
    for a in done:
        by_type[a.round_type]["n"] += 1
        by_type[a.round_type]["score"] += (a.score or 0) if a.round_type == "mcq" else (a.score or 0) * 20
    return ok({"funnel": [{"stage": s, "count": reached[s]} for s in order],
               "totals": {"applications": len(apps), "rounds": len(atts), "completed": len(done),
                          "rejected": sum(1 for a in apps if a.stage == "rejected"), "hired": sum(1 for a in apps if a.stage == "hired"),
                          "reports_pending": pending, "integrity_rate": round(100 * len(flagged) / max(1, len(done)), 1),
                          "avg_hours_to_complete": round(sum(tt) / max(1, len(tt)), 1)},
               "by_round": [{"type": k, "count": v["n"], "avg_pct": round(v["score"] / max(1, v["n"]), 1)} for k, v in by_type.items()]})


@bp.get("/analytics/interviewers")
@staff_required
def interviewers():
    """Calibration: who scores high or low, how often they agree with Isha, how fast they submit."""
    if not can_any(g.user, "analytics.view", cid()):
        return deny()
    jids = _job_ids()
    atts = (RoundAttempt.query.join(Application, Application.id == RoundAttempt.application_id)
            .filter(Application.job_id.in_(jids), RoundAttempt.interviewer_id.isnot(None)).all())
    agg = defaultdict(lambda: {"n": 0, "scores": [], "diffs": [], "hours": [], "rec": defaultdict(int)})
    for a in atts:
        r = Report.query.filter_by(attempt_id=a.id).first()
        if not r:
            continue
        x = agg[a.interviewer_id]
        x["n"] += 1
        x["scores"].append(r.overall or 0)
        x["rec"][r.recommendation] += 1
        ag = (r.sections or {}).get("ai_agreement")
        if ag:
            x["diffs"].append(ag["avg_diff"])
        if a.completed_at and a.started_at:
            x["hours"].append((r.created_at - a.started_at).total_seconds() / 3600)
    all_scores = [s for x in agg.values() for s in x["scores"]]
    mean = sum(all_scores) / max(1, len(all_scores))
    out = []
    for uid, x in agg.items():
        u = db.session.get(User, uid)
        avg = sum(x["scores"]) / max(1, len(x["scores"]))
        out.append({"id": uid, "name": u.name if u else "?", "interviews": x["n"], "avg_score": round(avg, 2),
                    "vs_team": round(avg - mean, 2), "ai_diff": round(sum(x["diffs"]) / len(x["diffs"]), 2) if x["diffs"] else None,
                    "proceed_rate": round(100 * x["rec"].get("proceed", 0) / max(1, x["n"]), 1),
                    "flag": "scores high" if avg - mean > 0.6 else ("scores low" if avg - mean < -0.6 else "")})
    out.sort(key=lambda r: -r["interviews"])
    return ok(out)


@bp.get("/analytics/questions")
@staff_required
def question_quality():
    """MCQ items: how often each is answered correctly. Items everyone gets right or wrong are flagged."""
    if not can_any(g.user, "analytics.view", cid()):
        return deny()
    jids = _job_ids()
    atts = (RoundAttempt.query.join(Application, Application.id == RoundAttempt.application_id)
            .filter(Application.job_id.in_(jids), RoundAttempt.round_type == "mcq", RoundAttempt.completed_at.isnot(None)).all())
    agg = defaultdict(lambda: [0, 0, ""])
    for a in atts:
        r = Report.query.filter_by(attempt_id=a.id).first()
        for q in ((r.sections or {}).get("questions") or []) if r else []:
            agg[q["q"]][0] += 1 if q.get("correct") else 0
            agg[q["q"]][1] += 1
            agg[q["q"]][2] = q.get("skill", "")
    out = [{"question": k, "skill": v[2], "asked": v[1], "correct_pct": round(100 * v[0] / v[1], 1),
            "flag": "too easy" if v[1] >= 3 and v[0] / v[1] > 0.95 else ("too hard" if v[1] >= 3 and v[0] / v[1] < 0.15 else "")}
           for k, v in agg.items()]
    out.sort(key=lambda r: -r["asked"])
    return ok(out)


SOURCES = {
    "applications": {"group_by": ["stage", "job", "source", "month", "week"], "measures": ["count", "avg_match"]},
    "interviews": {"group_by": ["type", "interviewer", "status", "job", "month", "week"],
                   "measures": ["count", "avg_score", "avg_warnings", "completion_rate"]},
    "reports": {"group_by": ["recommendation", "verdict", "status", "job", "month"], "measures": ["count", "avg_overall"]},
}


def _period(dt, kind):
    if kind == "week":
        return (dt - timedelta(days=dt.weekday())).strftime("%Y-%m-%d")
    return dt.strftime("%Y-%m")


def run_spec(spec):
    src = spec.get("source", "applications")
    if src not in SOURCES:
        src = "applications"
    group = spec.get("group_by") if spec.get("group_by") in SOURCES[src]["group_by"] else SOURCES[src]["group_by"][0]
    measure = spec.get("measure") if spec.get("measure") in SOURCES[src]["measures"] else "count"
    jids = _job_ids()
    jobs = {j.id: j.title for j in Job.query.filter(Job.id.in_(jids)).all()}
    since = _since()
    buckets = defaultdict(list)
    if src == "applications":
        for a in Application.query.filter(Application.job_id.in_(jids), Application.created_at >= since).all():
            key = {"stage": a.stage, "job": jobs.get(a.job_id), "source": a.source,
                   "month": _period(a.created_at, "month"), "week": _period(a.created_at, "week")}[group]
            buckets[key].append(a.match_score or 0)
    elif src == "interviews":
        for a in (RoundAttempt.query.join(Application, Application.id == RoundAttempt.application_id)
                  .filter(Application.job_id.in_(jids), RoundAttempt.created_at >= since).all()):
            iv = db.session.get(User, a.interviewer_id) if a.interviewer_id else None
            app = db.session.get(Application, a.application_id)
            key = {"type": a.round_type, "interviewer": iv.name if iv else "AI (Hira)", "status": a.status,
                   "job": jobs.get(app.job_id), "month": _period(a.created_at, "month"), "week": _period(a.created_at, "week")}[group]
            pct = (a.score or 0) if a.round_type == "mcq" else (a.score or 0) * 20
            buckets[key].append((pct, a.warnings or 0, 1 if a.completed_at else 0))
    else:
        for r in (Report.query.join(RoundAttempt, RoundAttempt.id == Report.attempt_id)
                  .join(Application, Application.id == RoundAttempt.application_id)
                  .filter(Application.job_id.in_(jids), Report.created_at >= since).all()):
            att = db.session.get(RoundAttempt, r.attempt_id)
            app = db.session.get(Application, att.application_id)
            key = {"recommendation": r.recommendation, "verdict": r.verdict or "none", "status": r.status,
                   "job": jobs.get(app.job_id), "month": _period(r.created_at, "month")}[group]
            buckets[key].append(r.overall or 0)
    rows = []
    for k, vals in buckets.items():
        if measure == "count":
            v = len(vals)
        elif measure in ("avg_match", "avg_overall"):
            v = round(sum(vals) / max(1, len(vals)), 1)
        elif measure == "avg_score":
            v = round(sum(x[0] for x in vals) / max(1, len(vals)), 1)
        elif measure == "avg_warnings":
            v = round(sum(x[1] for x in vals) / max(1, len(vals)), 2)
        else:
            v = round(100 * sum(x[2] for x in vals) / max(1, len(vals)), 1)
        rows.append({"label": str(k), "value": v, "n": len(vals)})
    rows.sort(key=lambda r: r["label"] if group in ("month", "week") else -r["value"])
    return {"spec": {**spec, "source": src, "group_by": group, "measure": measure}, "rows": rows}


@bp.get("/analytics/sources")
@staff_required
def sources():
    return ok(SOURCES)


@bp.post("/analytics/run")
@staff_required
def run():
    if not can_any(g.user, "analytics.view", cid()):
        return deny()
    return ok(run_spec(body().get("spec") or {}))


@bp.post("/analytics/ask")
@staff_required
def ask():
    """'Average AI interview score by interviewer this quarter' -> a report spec, then the numbers."""
    if not can_any(g.user, "analytics.view", cid()):
        return deny()
    spec = ai.nl_report(body().get("text", ""), SOURCES, company_id=cid())
    return ok(run_spec(spec))


@bp.get("/analytics/saved")
@staff_required
def saved():
    return ok([s.to_dict() for s in SavedReport.query.filter_by(company_id=cid()).all()])


@bp.post("/analytics/saved")
@staff_required
def save_report():
    if not can_any(g.user, "analytics.view", cid()):
        return deny()
    d = body()
    s = SavedReport(company_id=cid(), user_id=g.user.id, name=d.get("name") or "Report", spec=d.get("spec", {}))
    db.session.add(s)
    db.session.commit()
    return ok(s.to_dict())


@bp.delete("/analytics/saved/<int:sid>")
@staff_required
def delete_saved(sid):
    SavedReport.query.filter_by(id=sid, company_id=cid()).delete()
    db.session.commit()
    return ok()


@bp.get("/export/<source>")
@staff_required
def export(source):
    """CSV export of applications or reports. Needs the export permission and is audited."""
    if not can(g.user, "export", company_id=cid()):
        return deny("You need the export permission.")
    jids = _job_ids()
    jobs = {j.id: j.title for j in Job.query.filter(Job.id.in_(jids)).all()}
    buf = io.StringIO()
    w = csv.writer(buf)
    if source == "applications":
        w.writerow(["id", "job", "candidate", "email", "stage", "match", "verdict", "applied"])
        for a in Application.query.filter(Application.job_id.in_(jids)).all():
            u = db.session.get(User, a.candidate_id)
            w.writerow([a.id, jobs.get(a.job_id), u.name, u.email, a.stage, a.match_score, a.verdict or "", a.created_at.date()])
    elif source == "reports":
        w.writerow(["id", "job", "candidate", "round", "overall", "recommendation", "verdict", "status", "warnings"])
        for r in (Report.query.join(RoundAttempt, RoundAttempt.id == Report.attempt_id)
                  .join(Application, Application.id == RoundAttempt.application_id).filter(Application.job_id.in_(jids)).all()):
            att = db.session.get(RoundAttempt, r.attempt_id)
            app = db.session.get(Application, att.application_id)
            u = db.session.get(User, app.candidate_id)
            w.writerow([r.id, jobs.get(app.job_id), u.name, att.round_type, r.overall, r.recommendation, r.verdict or "", r.status, att.warnings])
    else:
        return err("Unknown export.")
    log("export", source, None, company_id=cid())
    db.session.commit()
    return Response(buf.getvalue(), mimetype="text/csv",
                    headers={"Content-Disposition": f"attachment; filename=code2hire-{source}.csv"})
