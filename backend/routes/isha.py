"""Isha: the live F2F copilot. Brief, per-sentence analysis, ranked next questions, scorecard."""
from datetime import datetime

from flask import Blueprint, g

from extensions import db
from models import Report, RoundAttempt, Turn
from routes.utils import body, err, ok
from services import ai
from services.audit import log, notify
from services.perms import auth_required, can, deny
from services.pipeline import context, make_report, round_name

bp = Blueprint("isha", __name__, url_prefix="/api/isha")


def load(att_id):
    att = db.session.get(RoundAttempt, att_id)
    if not att or att.round_type not in ("f2f_isha", "f2f_human"):
        return None
    app, job, cand, profile = context(att)
    if g.user.is_superadmin or att.interviewer_id == g.user.id or (job and can(g.user, "interviews.run", job=job)):
        return att
    return None


def _prior(att):
    out = []
    for prev in RoundAttempt.query.filter(RoundAttempt.application_id == att.application_id,
                                          RoundAttempt.round_index < att.round_index).all():
        r = Report.query.filter_by(attempt_id=prev.id).first()
        if r:
            out.append({"round": prev.round_type, "overall": r.overall, "recommendation": r.recommendation,
                        "summary": (r.sections or {}).get("summary"), "gaps": (r.sections or {}).get("gaps", []),
                        "handoff": (r.sections or {}).get("handoff", []), "warnings": prev.warnings})
    return out


def _state(att):
    res = att.result or {}
    log_ = res.get("areas_log", [])
    brief = att.brief or {}
    asked = {a["area"] for a in log_}
    areas = brief.get("areas", [])
    covered = sum(1 for a in areas if a["area"] in asked)
    scores = [a["score"] for a in log_ if a.get("score")]
    hide = (att.config or {}).get("isha.hide_ai_scores_until_scorecard") and att.status != "completed"
    return {"areas_log": [{**a, "score": None if hide else a.get("score")} for a in log_],
            "current": res.get("current"), "notes": res.get("notes", []),
            "coverage": {"covered": covered, "total": len(areas)},
            "running_score": None if hide or not scores else round(sum(scores) / len(scores), 1),
            "remaining": [a for a in areas if a["area"] not in asked], "ended": res.get("ended", False)}


@bp.get("/<int:att_id>")
@auth_required
def room(att_id):
    att = load(att_id)
    if not att:
        return deny("You're not the interviewer for this round.")
    app, job, cand, profile = context(att)
    prior = _prior(att)
    if att.round_type == "f2f_isha" and not (att.brief or {}).get("areas"):
        att.brief = ai.isha_brief(job, profile.resume_text if profile else "", prior, company_id=job.company_id)
        db.session.commit()
    if att.round_type == "f2f_human" and not (att.brief or {}).get("areas"):
        att.brief = {"areas": [{"area": r["name"], "why": "Rubric", "q": "", "simple": "", "good": []} for r in (job.rubric or [])]}
        db.session.commit()
    return ok({"attempt": {**att.to_dict(exclude=("result",)), "name": round_name(att, job)},
               "job": {"id": job.id, "title": job.title, "level": job.level, "skills": job.skills, "rubric": job.rubric},
               "candidate": {"id": cand.id, "name": cand.name, "headline": profile.headline if profile else "",
                             "skills": profile.skills if profile else [], "resume": (profile.resume_text or "")[:6000] if profile else "",
                             "experience_years": profile.experience_years if profile else None},
               "prior": prior, "brief": att.brief, "state": _state(att),
               "options_count": (att.config or {}).get("isha.options", 4), "isha": att.round_type == "f2f_isha"})


@bp.post("/<int:att_id>/start")
@auth_required
def start(att_id):
    att = load(att_id)
    if not att:
        return deny()
    if att.status in ("completed", "reviewed"):
        return err("This interview is already complete.")
    att.status = "in_progress"
    att.started_at = att.started_at or datetime.utcnow()
    app, job, cand, _ = context(att)
    if app:
        app.stage = "in_round"
    log("isha.start", "attempt", att.id, company_id=job.company_id)
    db.session.commit()
    return ok(_state(att))


def _secs(att):
    return int((datetime.utcnow() - att.started_at).total_seconds()) if att.started_at else 0


@bp.post("/<int:att_id>/ask")
@auth_required
def ask(att_id):
    """The interviewer asks a question (from the brief, an Isha option, or their own words)."""
    att = load(att_id)
    if not att or att.status != "in_progress":
        return err("Start the interview first.", 409)
    d = body()
    res = dict(att.result or {})
    log_ = list(res.get("areas_log", []))
    area = d.get("area") or (res.get("current") or {}).get("area") or "General"
    brief_area = next((a for a in (att.brief or {}).get("areas", []) if a["area"] == area), {})
    entry = {"area": area, "q": d.get("q") or brief_area.get("q") or "", "type": d.get("type", "main"),
             "good": brief_area.get("good", []), "sentences": [], "tags": [], "score": None, "coverage": [],
             "at": _secs(att)}
    log_.append(entry)
    res["areas_log"] = log_
    res["current"] = {"index": len(log_) - 1, "area": area, "q": entry["q"]}
    att.result = res
    seq = Turn.query.filter_by(attempt_id=att.id).count()
    db.session.add(Turn(attempt_id=att.id, seq=seq, speaker="interviewer", text=entry["q"], topic=area, at_seconds=entry["at"]))
    db.session.commit()
    return ok(_state(att))


@bp.post("/<int:att_id>/sentence")
@auth_required
def sentence(att_id):
    """Called for every finished candidate sentence (from Azure STT). Isha tags it, re-scores and re-ranks options."""
    att = load(att_id)
    if not att or att.status != "in_progress":
        return err("The interview is not running.", 409)
    text = (body().get("text") or "").strip()
    if not text:
        return err("Empty sentence.")
    res = dict(att.result or {})
    log_ = [dict(a) for a in res.get("areas_log", [])]
    if not log_:
        log_.append({"area": "Opening", "q": "", "type": "main", "good": [], "sentences": [], "tags": [], "score": None,
                     "coverage": [], "at": _secs(att)})
        res["current"] = {"index": 0, "area": "Opening", "q": ""}
    idx = (res.get("current") or {}).get("index", len(log_) - 1)
    cur = log_[idx]
    app, job, cand, profile = context(att)
    asked = {a["area"] for a in log_}
    remaining = [a for a in (att.brief or {}).get("areas", []) if a["area"] not in asked]
    analysis = {"tags": [], "score": None, "coverage": [], "options": []}
    if att.round_type == "f2f_isha":
        analysis = ai.isha_analyze(cur["q"], cur["area"], cur.get("good", []), cur["sentences"], text,
                                   profile.resume_text if profile else "", remaining,
                                   int((att.config or {}).get("isha.options", 4)), company_id=job.company_id)
    cur["sentences"] = cur["sentences"] + [text]
    cur["tags"] = cur.get("tags", []) + [{"s": len(cur["sentences"]) - 1, **t} for t in analysis.get("tags", [])]
    cur["score"] = analysis.get("score")
    cur["coverage"] = analysis.get("coverage", [])
    log_[idx] = cur
    res["areas_log"] = log_
    res["options"] = analysis.get("options", [])
    att.result = res
    seq = Turn.query.filter_by(attempt_id=att.id).count()
    db.session.add(Turn(attempt_id=att.id, seq=seq, speaker="candidate", text=text, topic=cur["area"], analysis=analysis,
                        at_seconds=_secs(att)))
    db.session.commit()
    st = _state(att)
    hide = (att.config or {}).get("isha.hide_ai_scores_until_scorecard")
    return ok({"analysis": {**analysis, "score": None if hide else analysis.get("score")}, "state": st,
               "options": analysis.get("options", [])})


@bp.post("/<int:att_id>/note")
@auth_required
def note(att_id):
    att = load(att_id)
    if not att:
        return deny()
    res = dict(att.result or {})
    res["notes"] = res.get("notes", []) + [{"text": body().get("text", ""), "at": _secs(att),
                                            "area": (res.get("current") or {}).get("area")}]
    att.result = res
    db.session.commit()
    return ok(res["notes"])


@bp.post("/<int:att_id>/end")
@auth_required
def end(att_id):
    """Interview over: Isha drafts the scorecard from the live log. The interviewer edits and submits."""
    att = load(att_id)
    if not att:
        return deny()
    res = dict(att.result or {})
    res["ended"] = True
    res["ended_at"] = _secs(att)
    log_ = res.get("areas_log", [])
    app, job, _, _ = context(att)
    if att.round_type == "f2f_isha":
        draft = ai.isha_scorecard([{"area": a["area"], "q": a["q"], "sentences": a["sentences"], "score": a.get("score")}
                                   for a in log_], company_id=job.company_id)
    else:
        draft = {"competencies": [{"name": r["name"], "score": 3, "quote": ""} for r in (job.rubric or [])]}
    # make sure every rubric competency appears so nothing is skipped
    names = {c["name"] for c in draft.get("competencies", [])}
    for r in job.rubric or []:
        if r["name"] not in names:
            draft["competencies"].append({"name": r["name"], "score": None, "quote": "", "not_covered": True})
    res["draft_scorecard"] = draft
    att.result = res
    db.session.commit()
    return ok({"draft": draft, "state": _state(att)})


@bp.post("/<int:att_id>/scorecard")
@auth_required
def submit_scorecard(att_id):
    att = load(att_id)
    if not att:
        return deny()
    d = body()
    comps = [c for c in d.get("competencies", []) if c.get("score") is not None]
    if not comps:
        return err("Score at least one competency.")
    if not d.get("recommendation"):
        return err("Choose a recommendation.")
    app, job, cand, _ = context(att)
    res = dict(att.result or {})
    overall = round(sum(float(c["score"]) for c in comps) / len(comps), 1)
    log_ = res.get("areas_log", [])
    ai_scores = {a["area"]: a.get("score") for a in log_ if a.get("score")}
    sections = {"kind": att.round_type, "summary": d.get("summary") or f"Interviewer rated {overall} out of 5 and recommends {d['recommendation']}.",
                "competencies": [{"name": c["name"], "score": c["score"], "weight": 1, "evidence": c.get("quote", ""),
                                  "note": c.get("note", ""), "ai_score": ai_scores.get(c["name"]),
                                  "level": "Strong" if float(c["score"]) >= 4 else ("Meets" if float(c["score"]) >= 3 else "Weak")}
                                 for c in d.get("competencies", [])],
                "questions": [{"q": a["q"], "a": " ".join(a["sentences"]), "score": a.get("score"), "topic": a["area"],
                               "tags": a.get("tags", []), "time": f"{a.get('at', 0) // 60:02d}:{a.get('at', 0) % 60:02d}"}
                              for a in log_],
                "notes": res.get("notes", []), "interviewer_note": d.get("note"),
                "strengths": [c["name"] for c in comps if float(c["score"]) >= 4],
                "gaps": [c["name"] for c in comps if float(c["score"]) < 3],
                "ai_agreement": _agreement(comps, ai_scores),
                "coverage": {"planned": [a["area"] for a in (att.brief or {}).get("areas", [])], "tested": [a["area"] for a in log_]}}
    att.score = overall
    att.status = "completed"
    att.completed_at = datetime.utcnow()
    att.result = res
    r = make_report(att, sections, overall, d["recommendation"], "high")
    r.reviewer_id = g.user.id
    if app:
        app.stage = "awaiting_review"
    log("isha.scorecard", "attempt", att.id, company_id=job.company_id, overall=overall, rec=d["recommendation"])
    if cand:
        notify(cand.id, "Thanks for interviewing", f"{job.title}. The team will be in touch.", "/me/applications")
    db.session.commit()
    return ok({"report_id": r.id, "overall": overall})


def _agreement(comps, ai_scores):
    pairs = [(float(c["score"]), float(ai_scores[c["name"]])) for c in comps if ai_scores.get(c["name"])]
    if not pairs:
        return None
    diff = sum(abs(a - b) for a, b in pairs) / len(pairs)
    return {"pairs": len(pairs), "avg_diff": round(diff, 2), "level": "high" if diff < 0.75 else ("medium" if diff < 1.5 else "low")}
