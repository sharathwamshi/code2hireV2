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
    skipped = sum(1 for a in areas if a.get("skipped") and a["area"] not in asked)
    scores = [a["score"] for a in log_ if a.get("score")]
    hide = (att.config or {}).get("isha.hide_ai_scores_until_scorecard") and att.status != "completed"
    return {"areas_log": [{**a, "score": None if hide else a.get("score")} for a in log_],
            "current": res.get("current"), "notes": res.get("notes", []),
            "coverage": {"covered": covered, "total": len(areas), "skipped": skipped},
            "running_score": None if hide or not scores else round(sum(scores) / len(scores), 1),
            "remaining": [a for a in areas if a["area"] not in asked and not a.get("skipped")], "ended": res.get("ended", False)}


@bp.get("/<int:att_id>")
@auth_required
def room(att_id):
    att = load(att_id)
    if not att:
        return deny("You're not the interviewer for this round.")
    app, job, cand, profile = context(att)
    prior = _prior(att)
    cfg = att.config or {}
    n = _count(att)
    own = [str(q).strip() for q in (cfg.get("f2f.own_questions") or []) if str(q).strip()][:30]
    brief = att.brief or {}
    # BUG-001: build (or rebuild, while the interview hasn't started) a plan with exactly the round's number of questions
    stale = brief.get("areas") and att.status not in ("in_progress", "completed", "reviewed", "not_finished") and \
        (len(brief["areas"]) != n or brief.get("own") != own)
    if not brief.get("areas") or stale:
        if att.round_type == "f2f_isha" and cfg.get("isha.enabled", True):
            att.brief = {**ai.isha_brief(job, profile.resume_text if profile else "", prior, company_id=job.company_id, n=n, own=own), "own": own}
        else:
            names = [r["name"] for r in (job.rubric or [])] or [s_["name"] if isinstance(s_, dict) else s_ for s_ in (job.skills or [])]
            att.brief = {"areas": ai.fill_plan([], n, names, own=own), "gaps": [], "own": own}
        db.session.commit()
    return ok({"attempt": {**att.to_dict(exclude=("result",)), "name": round_name(att, job)},
               "job": {"id": job.id, "title": job.title, "level": job.level, "skills": job.skills, "rubric": job.rubric},
               "candidate": {"id": cand.id, "name": cand.name, "headline": profile.headline if profile else "",
                             "skills": profile.skills if profile else [], "resume": (profile.resume_text or "")[:6000] if profile else "",
                             "experience_years": profile.experience_years if profile else None},
               "prior": prior, "brief": att.brief, "state": _state(att),
               "options_count": _options(att), "isha": att.round_type == "f2f_isha",
               "draft": (att.result or {}).get("draft_scorecard"), "integrity": _integrity(att)})


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


def _integrity(att):
    from models import IntegrityEvent
    from routes.rounds import LABELS
    return [{"type": e.event_type, "label": LABELS.get(e.event_type, e.event_type), "counted": e.counted, "note": e.note,
             "at": e.created_at.isoformat() + "Z"} for e in IntegrityEvent.query.filter_by(attempt_id=att.id).order_by(IntegrityEvent.id).all()]


def _count(att):
    try:
        return max(1, min(30, int((att.config or {}).get("f2f.questions", 7))))
    except (TypeError, ValueError):
        return 7


def _options(att):
    """BUG-007: saved values outside 2 to 6 (from before the limit) can't break the room."""
    try:
        return max(2, min(6, int((att.config or {}).get("isha.options", 4))))
    except (TypeError, ValueError):
        return 4


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


_STOP = set("a an the and or but to of in on for with about your you we our is are was were be been do does did can could would "
             "should will what how why when where which who tell me us please so that this it its at as from have has had".split())


def _content(text):
    import re
    return [w for w in re.findall(r"[a-z0-9+#]+", (text or "").lower()) if w not in _STOP and len(w) > 1]


def match_question(said, areas, current_area=None):
    """F2F-005: the interviewer read a plan question out loud. Returns the matching area, or None.
    A plan question matches when most of its content words were said (order and filler words don't matter)."""
    words = set(_content(said))
    if len(words) < 3:
        return None
    best, best_score = None, 0.0
    for a in areas:
        q = set(_content(a.get("q")))
        if len(q) < 3:
            continue
        score = len(q & words) / len(q)
        if score > best_score:
            best, best_score = a, score
    if best and best_score >= 0.6 and best.get("area") != current_area:
        return best
    return None


@bp.post("/<int:att_id>/said")
@auth_required
def said(att_id):
    """The interviewer's own speech, from their microphone (V02.00.05). It goes into the transcript labelled as the
    interviewer, and when it is a question from the plan, Isha marks that question as asked by herself (F2F-005)."""
    att = load(att_id)
    if not att or att.status != "in_progress":
        return err("The interview is not running.", 409)
    text = (body().get("text") or "").strip()[:1000]
    if not text:
        return err("Empty sentence.")
    res = dict(att.result or {})
    recent = (res.get("iv_recent") or [])[-1:] + [text]  # a long question can arrive as two sentences
    res["iv_recent"] = recent
    areas = [a for a in (att.brief or {}).get("areas", []) if not a.get("skipped")]
    cur_area = (res.get("current") or {}).get("area")
    hit = match_question(" ".join(recent), areas, cur_area)
    log_ = [dict(a) for a in res.get("areas_log", [])]
    moved = None
    if hit:
        entry = {"area": hit["area"], "q": hit.get("q") or text, "type": "main", "good": hit.get("good", []), "sentences": [],
                 "tags": [], "score": None, "coverage": [], "at": _secs(att), "auto": True, "said": []}
        log_.append(entry)
        res["current"] = {"index": len(log_) - 1, "area": hit["area"], "q": entry["q"]}
        res["iv_recent"] = []
        moved = {"area": hit["area"], "index": len(log_) - 1, "from": cur_area}
    elif log_:
        idx = (res.get("current") or {}).get("index", len(log_) - 1)
        cur = log_[idx]
        cur["said"] = (cur.get("said") or []) + [{"t": text, "after": len(cur.get("sentences") or [])}]
        log_[idx] = cur
    res["areas_log"] = log_
    att.result = res
    seq = Turn.query.filter_by(attempt_id=att.id).count()
    db.session.add(Turn(attempt_id=att.id, seq=seq, speaker="interviewer", text=text, topic=hit["area"] if hit else cur_area,
                        at_seconds=_secs(att)))
    db.session.commit()
    return ok({"moved": moved, "state": _state(att)})


@bp.post("/<int:att_id>/undo-move")
@auth_required
def undo_move(att_id):
    """Isha moved to a question by herself and the interviewer says she was wrong: go back to the previous one.
    The automatic entry is removed if the candidate hasn't answered it yet."""
    att = load(att_id)
    if not att or att.status != "in_progress":
        return err("The interview is not running.", 409)
    res = dict(att.result or {})
    log_ = [dict(a) for a in res.get("areas_log", [])]
    if not log_ or not log_[-1].get("auto"):
        return err("There's nothing to undo.")
    last = log_[-1]
    if not last.get("sentences"):
        log_.pop()
    prev = len(log_) - 2 if last.get("sentences") else len(log_) - 1
    if prev < 0:
        res["current"] = None
    else:
        res["current"] = {"index": prev, "area": log_[prev]["area"], "q": log_[prev]["q"]}
    res["areas_log"] = log_
    att.result = res
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
                                   _options(att), company_id=job.company_id)
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


@bp.post("/<int:att_id>/plan")
@auth_required
def edit_plan(att_id):
    """Reorder the plan, skip or un-skip a question, or add one of the interviewer's own (kept in the plan and the report)."""
    att = load(att_id)
    if not att:
        return deny()
    if att.status in ("completed", "reviewed"):
        return err("This interview is complete.")
    d = body()
    brief = dict(att.brief or {})
    areas = [dict(a) for a in brief.get("areas", [])]
    by = {a["area"]: a for a in areas}
    if isinstance(d.get("order"), list):
        order = [by[n] for n in d["order"] if n in by]
        order += [a for a in areas if a["area"] not in d["order"]]
        areas = order
    if d.get("skip") in by:
        by[d["skip"]]["skipped"] = True
    if d.get("unskip") in by:
        by[d["unskip"]].pop("skipped", None)
    if d.get("add"):
        q = " ".join(str(d["add"]).split())[:300]
        if len(q) < 5:
            return err("Write the question first.")
        if any(a.get("q", "").lower() == q.lower() for a in areas):
            return err("That question is already in the plan.")
        if len(areas) >= 40:
            return err("The plan can hold at most 40 questions.")
        k = sum(1 for a in areas if a.get("own")) + 1
        areas.insert(len([a for a in areas if a["area"] != "Wrap-up"]), {"area": f"Your question {k}" if f"Your question {k}" not in by else f"Your question {k}b",
                                                                          "why": "Added during the interview", "q": q, "simple": q, "good": [], "own": True})
    brief["areas"] = areas
    att.brief = brief
    db.session.commit()
    return ok({"brief": att.brief, "state": _state(att)})


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
    from models import CallSignal
    db.session.add(CallSignal(attempt_id=att.id, sender="interviewer", kind="bye", payload={"ended": True}))  # candidate's room closes
    log("isha.end", "attempt", att.id, company_id=job.company_id if job else None)
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
