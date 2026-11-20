"""Isha: the live F2F copilot. Brief, per-sentence analysis, ranked next questions, scorecard."""
from datetime import datetime

from flask import current_app, Blueprint, g, request

from extensions import db
from models import Report, RoundAttempt, Turn
from routes.utils import body, err, ok
from services import ai
from services.audit import log, notify
from services.perms import auth_required, can, deny
from services import isha_prep
from services.pipeline import context, make_report, round_name
from services.settings import resolve

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
    for prev in RoundAttempt.query.filter(RoundAttempt.application_id == att.application_id, RoundAttempt.status != "voided",
                                          RoundAttempt.round_index < att.round_index).all():
        r = Report.query.filter_by(attempt_id=prev.id).first()
        if r:
            out.append({"round": prev.round_type, "overall": r.overall, "recommendation": r.recommendation,
                        "summary": (r.sections or {}).get("summary"), "gaps": (r.sections or {}).get("gaps", []),
                        "handoff": (r.sections or {}).get("handoff", []), "warnings": prev.warnings})
    return out


def _asked_before(att):
    """Questions asked in this candidate's earlier rounds of the same application (F2F-003: never asked twice)."""
    out = []
    if not att.application_id:
        return out
    for prev in RoundAttempt.query.filter(RoundAttempt.application_id == att.application_id, RoundAttempt.id != att.id).all():
        for a in (prev.result or {}).get("areas_log", []) or []:
            if a.get("q"):
                out.append(a["q"])
        for q in (prev.result or {}).get("questions", []) or []:
            if isinstance(q, dict) and q.get("q"):
                out.append(q["q"])
    return out[:40]


def apply_ticks(e):
    """N3 (V02.00.09): the interviewer's own ticks count as covered, and an answer that covers every point of a good
    answer scores full marks (5 / 5), even when Isha's own reading scored it lower or couldn't read it."""
    good = e.get("good") or []
    ai_cov = list(e.get("coverage_ai") if e.get("coverage_ai") is not None else (e.get("coverage") or []))
    ticks = set(e.get("ticks") or [])
    cov = [("full" if i in ticks else (ai_cov[i] if i < len(ai_cov) else "none")) for i in range(len(good))]
    e["coverage_ai"] = ai_cov
    e["coverage"] = cov
    full = bool(good) and all(c == "full" for c in cov)
    if full:
        if not e.get("full_marks"):
            e["score_ai"] = e.get("score")
        e["score"] = 5.0
        e["full_marks"] = True
    elif e.get("full_marks"):  # a tick was taken back: Isha's own score again
        e["score"] = e.get("score_ai")
        e["full_marks"] = False
    return e


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
            "remaining": [a for a in areas if a["area"] not in asked and not a.get("skipped")], "ended": res.get("ended", False),
            "review": res.get("review"), "can_undo_review": res.get("areas_log_live") is not None,
            # V02.01.01: what has come up so far, from the whole transcript (nothing is filed during the interview)
            "topics": _live_topics(att)}


def _live_topics(att):
    if att.round_type not in ("f2f_isha", "f2f_human") or att.status not in ("in_progress", "paused", "not_finished", "completed", "reviewed"):
        return None
    try:
        from services.isha_review import live_topics
        return live_topics(att)
    except Exception:  # noqa: BLE001 - never break the room over the coverage strip
        return None


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
    not_started = att.status not in ("in_progress", "completed", "reviewed", "not_finished", "voided", "cancelled")
    isha_on = att.round_type == "f2f_isha" and cfg.get("isha.enabled", True)
    # BUG-001: build (or rebuild, while the interview hasn't started) a plan with exactly the round's number of
    # questions. V02.00.13: once the interviewer has saved their own choice on the Prepare screen, it's kept.
    saved = (brief.get("prep") or {}).get("saved")
    stale = brief.get("areas") and not_started and not saved and \
        (len(brief["areas"]) != n or brief.get("own") != own or (isha_on and not brief.get("prep")))
    if not brief.get("areas") or stale:
        from services.scorecard import competencies, link_plan
        comps = competencies(job)
        if isha_on:
            prep = isha_prep.propose(job, profile, prior, own=own, avoid=_asked_before(att), company_id=job.company_id)
            prep["selected"] = isha_prep.default_pick(prep, n_tech=_tech_slots(n, own), minutes=_minutes(att), intro=n >= 3)
            att.brief = _brief_from(att, prep, job, n, own, prior)
        else:
            names = [r["name"] for r in (job.rubric or [])] or [s_["name"] if isinstance(s_, dict) else s_ for s_ in (job.skills or [])]
            att.brief = {"areas": link_plan(ai.fill_plan([], n, names, own=own), comps), "gaps": [], "own": own}
        db.session.commit()
    return ok({"attempt": {**att.to_dict(exclude=("result",)), "name": round_name(att, job)},
               "job": {"id": job.id, "title": job.title, "level": job.level, "skills": job.skills, "rubric": job.rubric},
               "candidate": {"id": cand.id, "name": cand.name, "headline": profile.headline if profile else "",
                             "skills": profile.skills if profile else [], "resume": (profile.resume_text or "")[:6000] if profile else "",
                             "experience_years": profile.experience_years if profile else None},
               "prior": prior, "brief": att.brief, "state": _state(att),
               "options_count": _options(att), "isha": att.round_type == "f2f_isha",
               "draft": (att.result or {}).get("draft_scorecard"), "integrity": _integrity(att),
               "chat": (att.result or {}).get("chat") or [], "minutes": _minutes(att),
               "options": (att.result or {}).get("options") or [] if att.status == "in_progress" else [],
               "ai": {k: v for k, v in ai.status().items() if k in ("configured", "working", "recent_error", "error")}})


def _minutes(att):
    try:
        return max(10, min(240, int((att.config or {}).get("f2f.minutes", 45))))
    except (TypeError, ValueError):
        return 45


def _tech_slots(n, own):
    """Questions left for Isha's picks once the introduction, your own questions and the wrap-up have their places."""
    return max(0, n - len(own or []) - (2 if n >= 3 else 0))


def _brief_from(att, prep, job, n=None, own=(), prior=()):
    """The live plan from the chosen questions: introduction, your own, the picks, then Wrap-up. Before the interviewer
    has chosen, the plan is topped up to the round's question count with general questions (BUG-001)."""
    from services.scorecard import competencies, link_plan
    comps = competencies(job)
    areas = isha_prep.to_areas(prep, comps)
    want = (n - 1 if n and n >= 3 else n) if not prep.get("saved") else None
    if want and len(areas) < want:
        skills = [s_["name"] if isinstance(s_, dict) else s_ for s_ in (job.skills or [])]
        extra = ai.fill_plan([], want - len(areas) + (1 if n >= 3 else 0), skills, avoid=[a["q"] for a in areas] + _asked_before(att))
        extra = [dict(e, source="builtin", type=e.get("type") or "general", type_label="General") for e in extra if e["area"] != "Wrap-up"]
        names = {a["area"] for a in areas}
        for e in extra:
            if len(areas) >= want:
                break
            if e["area"] in names or any(e["q"] == a["q"] for a in areas):
                continue
            names.add(e["area"])
            areas.append(e)
        areas = link_plan(areas, comps)
    if (n is None or n >= 3) and not any(a["area"] == "Wrap-up" for a in areas):
        areas.append(dict(ai.WRAP_UP, source="builtin", type="wrap", type_label="Wrap-up"))
    gaps = []
    for r in prior or []:
        gaps += (r.get("handoff") or []) + (r.get("gaps") or [])
    return {"prep": prep, "areas": areas, "gaps": gaps[:4], "own": list(own or []), "ai": bool(prep.get("ai"))}


def _prep_out(att):
    prep = (att.brief or {}).get("prep") or {}
    return {"prep": prep, "levels": isha_prep.LEVELS, "types": {k: {"label": v[0], "meaning": v[1], "minutes": v[2]} for k, v in isha_prep.TYPES.items()},
            "kinds": {k: {"label": v[0], "meaning": v[1]} for k, v in isha_prep.SECTION_KINDS.items()},
            "summary": isha_prep.summary(prep, _minutes(att)), "locked": att.status in ("in_progress", "completed", "reviewed", "not_finished"),
            "brief": att.brief, "ai": {k: v for k, v in ai.status().items() if k in ("configured", "working", "recent_error")}}


@bp.get("/<int:att_id>/prepare")
@auth_required
def prepare_get(att_id):
    """V02.00.13: the Prepare questions screen. Opening the room first writes the proposals if they don't exist."""
    att = load(att_id)
    if not att or att.round_type != "f2f_isha":
        return deny("Prepare questions is for interviews with Isha.")
    if not (att.brief or {}).get("prep"):
        room(att_id)
    return ok(_prep_out(att))


@bp.post("/<int:att_id>/prepare")
@auth_required
def prepare_save(att_id):
    """Save the interviewer's choice: {selected: [ids in order], level?, add?: {section, q}, remove?: id, refresh?: section key | "all"}."""
    att = load(att_id)
    if not att or att.round_type != "f2f_isha":
        return deny()
    if att.status in ("in_progress", "completed", "reviewed", "not_finished", "voided", "cancelled"):
        return err("The interview has started, so its questions are set. Add or skip questions from the room instead.", 409)
    app, job, cand, profile = context(att)
    d = body()
    brief = dict(att.brief or {})
    prep = dict(brief.get("prep") or {})
    if not prep:
        return err("Open the interview room once so Isha can propose questions.", 409)
    own = brief.get("own") or []
    if d.get("level") and d["level"] != prep.get("level"):
        if d["level"] not in isha_prep.LEVELS:
            return err("Choose Fresher, Mid-level, Senior or Lead.")
        prep = isha_prep.propose(job, profile, _prior(att), own=own, level=d["level"], avoid=_asked_before(att), company_id=job.company_id)
        prep["selected"] = isha_prep.default_pick(prep, minutes=_minutes(att))
    if d.get("refresh"):
        keys = {s_["key"] for s_ in prep.get("sections") or []}
        if d["refresh"] == "all":  # every unselected question is written again; chosen ones stay
            prep = isha_prep.propose(job, profile, _prior(att), own=own, level=prep.get("level"), avoid=_asked_before(att),
                                     company_id=job.company_id, prep=prep, only_section="*")
        elif d["refresh"] in keys:
            prep = isha_prep.propose(job, profile, _prior(att), own=own, level=prep.get("level"), avoid=_asked_before(att),
                                     company_id=job.company_id, prep=prep, only_section=d["refresh"])
        else:
            return err("That section wasn't found.")
    if d.get("reset"):  # "Use Isha's picks"
        prep["selected"] = isha_prep.default_pick(prep, minutes=_minutes(att))
    if isinstance(d.get("add"), dict):
        q = " ".join(str(d["add"].get("q") or "").split())[:400]
        if len(q) < 8:
            return err("Write the question first (at least a few words).")
        if any(x["q"].lower() == q.lower() for x in prep.get("questions", [])):
            return err("That question is already in the list.")
        secs = prep.setdefault("sections", [])
        sec = next((s_ for s_ in secs if s_["key"] == d["add"].get("section")), None)
        if not sec:
            sec = next((s_ for s_ in secs if s_["key"] == "own"), None)
            if not sec:
                sec = {"key": "own", "kind": "own", "name": "Your questions", "skill": None, "must": False}
                secs.append(sec)
        new = {**isha_prep._question(prep, sec, "experience", {"q": q, "simple": q, "good": [], "followups": []}, "own"), "type": "own"}
        prep["questions"] = prep.get("questions", []) + [new]
        prep["selected"] = list(prep.get("selected") or []) + [new["id"]]
    if isinstance(d.get("selected"), list):
        ids = {q["id"] for q in prep.get("questions", [])}
        sel = [str(i) for i in d["selected"] if str(i) in ids]
        sel = list(dict.fromkeys(sel))
        if not sel:
            return err("Choose at least one question.")
        if len(sel) > 30:
            return err("Choose at most 30 questions.")
        prep["selected"] = sel
    if d.get("remove"):
        prep["selected"] = [i for i in prep.get("selected") or [] if i != d["remove"]]
    prep["saved"] = True
    prep["saved_by"] = g.user.id
    att.brief = _brief_from(att, prep, job, None, own, _prior(att))
    log("isha.prepare", "attempt", att.id, company_id=job.company_id, chosen=len(prep["selected"]), level=prep.get("level"))
    db.session.commit()
    return ok(_prep_out(att))


@bp.post("/<int:att_id>/start")
@auth_required
def start(att_id):
    att = load(att_id)
    if not att:
        return deny()
    if att.status in ("completed", "reviewed"):
        return err("This interview is already complete.")
    if att.status in ("voided", "cancelled"):
        return err("This interview was replaced by a retake. Open the new one from the candidate's page.", 409)
    att.status = "in_progress"
    att.started_at = att.started_at or datetime.utcnow()
    app, job, cand, _ = context(att)
    if app:
        app.stage = "in_round"
    video = (body() or {}).get("video")
    if video in ("not_connected", "candidate_absent"):  # V02.00.08: the report says the interview started without video
        res = dict(att.result or {})
        res["started_without_video"] = video
        att.result = res
    log("isha.start", "attempt", att.id, company_id=job.company_id, **({"video": video} if video else {}))
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
    qtext = d.get("q") or brief_area.get("q") or ""
    same = (d.get("q") or "").strip() == (brief_area.get("q") or "").strip()
    good = (brief_area.get("good") if same or not d.get("q") else None) or ai.expected_points(qtext, area)
    entry = {"area": area, "q": qtext, "type": d.get("type", "main"), "good": good, "sentences": [], "tags": [], "score": None,
             "coverage": [], "at": _secs(att)}
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


def _best_match(said, items, key="q"):
    words = set(_content(said))
    if len(words) < 3:
        return None, 0.0
    best, best_score = None, 0.0
    for a in items:
        q = set(_content(a.get(key) if isinstance(a, dict) else a))
        if len(q) < 3:
            continue
        score = len(q & words) / len(q)
        if score > best_score:
            best, best_score = a, score
    return best, best_score


def match_question(said, areas, current_area=None, maybe=False):
    """F2F-005: the interviewer read a plan question out loud. Returns the matching area, or None.
    A plan question matches when most of its content words were said (order and filler words don't matter).
    V02.00.13: with maybe=True, returns (area, "sure" | "maybe") so a half match can be confirmed with one tap."""
    best, score = _best_match(said, areas)
    ok_ = best is not None and best.get("area") != current_area
    if not maybe:
        return best if ok_ and score >= 0.6 else None
    if ok_ and score >= 0.6:
        return best, "sure"
    if ok_ and score >= 0.35:
        return best, "maybe"
    return None, None


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
    asked_areas = {a["area"] for a in res.get("areas_log", [])}
    hit, how = match_question(" ".join(recent), areas, cur_area, maybe=True)
    maybe = None
    if hit and how == "maybe":  # V02.00.13: not sure enough to move by itself: the room asks "Did you ask …?"
        maybe = {"area": hit["area"], "q": hit.get("q")} if hit["area"] not in asked_areas else None
        hit = None
    log_ = [dict(a) for a in res.get("areas_log", [])]
    moved = None
    followup = None
    if not hit and log_:
        # V02.00.13: a follow-up Isha suggested (or one the interviewer pinned) that was asked out loud is filed by itself
        sugg = [o for o in (res.get("options") or []) if o.get("type") != "Move on"] + \
               [{"q": q, "type": "Pinned"} for q in (body().get("pinned") or []) if isinstance(q, str)]
        fu, fscore = _best_match(" ".join(recent), sugg)
        if fu and fscore >= 0.6:
            followup = fu
    if followup:
        idx = (res.get("current") or {}).get("index", len(log_) - 1)
        area_ = log_[idx]["area"] if 0 <= idx < len(log_) else (cur_area or "General")
        entry = {"area": area_, "q": followup["q"], "type": followup.get("type") or "Follow-up",
                 "good": ai.expected_points(followup["q"], area_), "sentences": [], "tags": [], "score": None,
                 "coverage": [], "at": _secs(att), "auto": True, "said": [], "followup_of": idx}
        log_.append(entry)
        res["current"] = {"index": len(log_) - 1, "area": area_, "q": entry["q"]}
        res["iv_recent"] = []
        moved = {"area": area_, "index": len(log_) - 1, "from": cur_area, "followup": True, "q": entry["q"]}
    elif hit:
        entry = {"area": hit["area"], "q": hit.get("q") or text, "type": "main",
                 "good": hit.get("good") or ai.expected_points(hit.get("q"), hit["area"]), "sentences": [],
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
    return ok({"moved": moved, "maybe": maybe, "state": _state(att)})


@bp.get("/<int:att_id>/candidate-status")
@auth_required
def candidate_status(att_id):
    """C2: where the candidate is before they're connected (instructions, check step, help, joined), and C3: an earlier
    round of theirs that is still running."""
    att = load(att_id)
    if not att:
        return err("Not found", 404)
    from services.syscheck import candidate_status as status
    return ok(status(att))


@bp.post("/<int:att_id>/relabel")
@auth_required
def relabel(att_id):
    """gap 7: the interviewer says which plan question an answer belongs to (an "assumed" one, or one Isha guessed)."""
    att = load(att_id)
    if not att:
        return err("This interview isn't yours.", 403)
    if att.status not in ("in_progress", "completed"):
        return err("The interview is not open.", 409)
    d = body()
    res = dict(att.result or {})
    log_ = [dict(a) for a in res.get("areas_log", [])]
    try:
        i = int(d.get("index"))
    except (TypeError, ValueError):
        return err("Choose the answer to move.")
    if not 0 <= i < len(log_):
        return err("Choose the answer to move.")
    area = next((a for a in (att.brief or {}).get("areas", []) if a["area"] == d.get("area")), None)
    if not area:
        return err("Choose a question from the plan.")
    e = log_[i]
    e.update({"area": area["area"], "q": area.get("q") or e.get("q"), "good": area.get("good") or ai.expected_points(area.get("q"), area["area"]),
              "assumed": False, "auto": False, "coverage": []})
    log_[i] = e
    res["areas_log"] = log_
    if (res.get("current") or {}).get("index") == i:
        res["current"] = {"index": i, "area": e["area"], "q": e["q"]}
    att.result = res
    db.session.commit()
    return ok(_state(att))


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
    if not log_ or not res.get("current"):
        # gap 7 (V02.00.07): an answer with no question selected is never lost under "Opening": it goes to the next plan
        # question, marked "assumed", and the interviewer can move it with one click.
        asked_now = {a["area"] for a in log_}
        nxt = next((a for a in (att.brief or {}).get("areas", []) if a["area"] not in asked_now and not a.get("skipped")), None)
        if nxt:
            log_.append({"area": nxt["area"], "q": nxt.get("q") or "", "type": "main", "good": nxt.get("good") or ai.expected_points(nxt.get("q"), nxt["area"]),
                         "sentences": [], "tags": [], "score": None, "coverage": [], "at": _secs(att), "assumed": True})
        else:
            log_.append({"area": "Opening", "q": "", "type": "main", "good": [], "sentences": [], "tags": [], "score": None,
                         "coverage": [], "at": _secs(att)})
        res["current"] = {"index": len(log_) - 1, "area": log_[-1]["area"], "q": log_[-1]["q"]}
    idx = (res.get("current") or {}).get("index", len(log_) - 1)
    cur = log_[idx]
    app, job, cand, profile = context(att)
    asked = {a["area"] for a in log_}
    remaining = [a for a in (att.brief or {}).get("areas", []) if a["area"] not in asked]
    analysis = {"tags": [], "score": None, "coverage": [], "options": []}
    if att.round_type == "f2f_isha":
        shown = list(res.get("shown_options") or []) + [a.get("q") for a in log_ if a.get("q")]
        plan_area = next((a for a in (att.brief or {}).get("areas", []) if a["area"] == cur["area"]), {})
        analysis = ai.isha_analyze(cur["q"], cur["area"], cur.get("good", []), cur["sentences"], text,
                                   profile.resume_text if profile else "", remaining,
                                   _options(att), company_id=job.company_id, shown=shown,
                                   prepared=(plan_area.get("followups") or []) if cur.get("q") == plan_area.get("q") else [],
                                   asked=[a.get("q") for a in log_ if a.get("q")])
        res["shown_options"] = (list(res.get("shown_options") or []) + [o["q"] for o in analysis.get("options", []) if o.get("type") != "Move on"])[-60:]
    cur["sentences"] = cur["sentences"] + [text]
    cur["tags"] = cur.get("tags", []) + [{"s": len(cur["sentences"]) - 1, **t} for t in analysis.get("tags", [])]
    cur["score"] = analysis.get("score")
    cur["score_ai"] = analysis.get("score")
    cur["coverage_ai"] = analysis.get("coverage", [])
    cur["full_marks"] = False
    cur = apply_ticks(cur)
    analysis = {**analysis, "score": cur["score"], "coverage": cur["coverage"]}
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
    if att.status in ("completed", "reviewed", "voided", "cancelled"):
        return err("This interview is complete." if att.status in ("completed", "reviewed") else "This interview was replaced by a retake.")
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
    app, job, cand, _ = context(att)
    att.result = res
    # V02.01.01: before the scorecard, Isha reads the WHOLE transcript and files every answer under the question it
    # answers, whether or not anyone marked the questions as asked. Claude when available, keywords otherwise.
    from services.isha_review import review as review_all
    if (res.get("review") or {}).get("source") != "manual":
        review_all(att, company_id=job.company_id if job else None, use_ai=str(request.args.get("ai", "1")) != "0")
    res = dict(att.result or {})
    from services.scorecard import draft as make_draft
    # N2 (V02.00.09): the scorecard opens at once from Isha's own scores; Claude improves it from the screen (redraft)
    draft = make_draft(att, job, cand.name if cand else "The candidate", use_ai=False)  # F2F-004 / SA-010 (V02.00.08)
    res["draft_scorecard"] = draft
    att.result = res
    from models import CallSignal
    db.session.add(CallSignal(attempt_id=att.id, sender="interviewer", kind="bye", payload={"ended": True}))  # candidate's room closes
    log("isha.end", "attempt", att.id, company_id=job.company_id if job else None)
    db.session.commit()
    return ok({"draft": draft, "state": _state(att), "review": res.get("review")})


@bp.post("/<int:att_id>/review")
@auth_required
def review_again(att_id):
    """V02.01.01: read the whole transcript again and re-file the answers ({ai: false} for the keyword method), or put
    back what was filed during the interview ({undo: true}). The draft scorecard is rebuilt either way."""
    att = load(att_id)
    if not att or att.round_type not in ("f2f_isha", "f2f_human"):
        return deny()
    if att.status in ("completed", "reviewed", "voided", "cancelled"):
        return err("The scorecard is already submitted, so the answers can't be re-filed." if att.status in ("completed", "reviewed")
                   else "This interview was replaced by a retake.", 409)
    if att.status not in ("in_progress", "paused", "not_finished") and not (att.result or {}).get("ended"):
        return err("End the interview first. Isha reviews the whole transcript when it ends.", 409)
    d = body()
    app, job, cand, _ = context(att)
    res = dict(att.result or {})
    if d.get("undo"):
        if res.get("areas_log_live") is None:
            return err("There's nothing to undo: the answers are still filed as they were during the interview.", 409)
        res["areas_log"] = res.pop("areas_log_live")
        res["review"] = {**(res.get("review") or {}), "source": "manual", "undone": True}
        att.result = res
        log("isha.review_undo", "attempt", att.id)
    else:
        from services.isha_review import review as review_all
        out = review_all(att, company_id=job.company_id if job else None, use_ai=d.get("ai", True) is not False)
        log("isha.review", "attempt", att.id, source=out.get("source"), asked=out.get("asked"), of=out.get("of"))
    from services.scorecard import draft as make_draft
    res = dict(att.result or {})
    res["draft_scorecard"] = make_draft(att, job, cand.name if cand else "The candidate", use_ai=False)
    att.result = res
    db.session.commit()
    return ok({"review": res.get("review"), "draft": res["draft_scorecard"], "state": _state(att)})


@bp.post("/<int:att_id>/edit-sentence")
@auth_required
def edit_sentence(att_id):
    """F2F-001 (V02.00.08): the interviewer corrects a caption that was written out wrong, or removes one that
    wasn't the candidate's. The scorecard and the report use the corrected words."""
    att = load(att_id)
    if not att:
        return deny()
    if att.status in ("completed", "reviewed", "voided", "cancelled"):
        return err("The scorecard is already submitted." if att.status in ("completed", "reviewed") else "This interview was replaced by a retake.")
    d = body()
    res = dict(att.result or {})
    log_ = [dict(a) for a in res.get("areas_log", [])]
    try:
        i, j = int(d.get("index")), int(d.get("sentence"))
        e = log_[i]
        sents = list(e.get("sentences") or [])
        sents[j]
    except (TypeError, ValueError, IndexError):
        return err("That sentence wasn't found.")
    text = str(d.get("text") or "").strip()[:2000]
    old_text = sents[j]
    # V02.01.01: the saved transcript changes too, so a review of the whole interview reads the corrected words
    t_ = Turn.query.filter_by(attempt_id=att.id, speaker="candidate", text=old_text).order_by(Turn.seq).first()
    if t_ is not None:
        if text:
            t_.text = text
        else:
            db.session.delete(t_)
    if text:
        sents[j] = text
        e["edited"] = sorted(set((e.get("edited") or []) + [j]))
    else:  # remove it, and the tags that pointed at it
        sents.pop(j)
        e["tags"] = [{**t, "s": t["s"] - 1} if t.get("s", 0) > j else t for t in (e.get("tags") or []) if t.get("s") != j]
        e["edited"] = [k - 1 if k > j else k for k in (e.get("edited") or []) if k != j]
    e["sentences"] = sents
    log_[i] = e
    res["areas_log"] = log_
    att.result = res
    log("isha.edit_sentence", "attempt", att.id, index=i, sentence=j, removed=not text)
    db.session.commit()
    return ok(_state(att))


@bp.post("/<int:att_id>/redraft")
@auth_required
def redraft(att_id):
    """Rebuilds Isha's draft scorecard, for example after answers were moved to the right question."""
    att = load(att_id)
    if not att:
        return deny()
    if att.status in ("completed", "reviewed", "voided", "cancelled"):
        return err("The scorecard is already submitted." if att.status in ("completed", "reviewed") else "This interview was replaced by a retake.")
    app, job, cand, _ = context(att)
    from services.scorecard import draft as make_draft
    use_ai = str(request.args.get("ai", "1")) != "0"
    draft = make_draft(att, job, cand.name if cand else "The candidate", use_ai=use_ai)
    res = dict(att.result or {})
    res["draft_scorecard"] = draft
    att.result = res
    db.session.commit()
    return ok({"draft": draft})


def _level(score):
    if score in (None, ""):
        return "Not rated"
    v = float(score)
    return "Strong" if v >= 4 else ("Meets" if v >= 3 else "Weak")


@bp.post("/<int:att_id>/scorecard")
@auth_required
def submit_scorecard(att_id):
    att = load(att_id)
    if not att:
        return deny()
    if att.status in ("completed", "reviewed"):
        return err("The scorecard for this interview is already submitted.", 409)
    if att.status in ("voided", "cancelled"):
        return err("This interview was replaced by a retake.", 409)
    d = body()
    comps, missing = [], []
    for c in d.get("competencies", []):
        sc = c.get("score")
        if sc in (None, ""):
            # V02.01.01: every competency needs a rating or an explicit Skip; Skip is left out of every score
            if not c.get("skipped") and c.get("name"):
                missing.append(c["name"])
            continue
        try:
            sc = float(sc)
        except (TypeError, ValueError):
            return err(f"The score for {c.get('name') or 'a competency'} must be a number from 1 to 5.")
        if not 1 <= sc <= 5:
            return err(f"The score for {c.get('name') or 'a competency'} must be from 1 to 5.")
        c["score"] = sc
        comps.append(c)
    if missing:
        return err(f"Rating not received for: {', '.join(missing)}. Rate each from 1 to 5, or press Skip if you didn't assess it.",
                   fields={"missing": missing})
    if not comps:
        return err("Rate at least one competency from 1 to 5 before submitting. Skipped ones aren't counted.")
    if d.get("recommendation") not in ("proceed", "hold", "reject"):
        return err("Choose a recommendation: Proceed, Hold or Do not proceed.")
    app, job, cand, _ = context(att)
    res = dict(att.result or {})
    overall = round(sum(float(c["score"]) for c in comps) / len(comps), 1)
    log_ = res.get("areas_log", [])
    ai_scores = {a["area"]: a.get("score") for a in log_ if a.get("score")}
    ai_scores.update({c["name"]: c["ai_score"] for c in d.get("competencies", []) if isinstance(c.get("ai_score"), (int, float))})
    sections = {"kind": att.round_type, "summary": d.get("summary") or f"Interviewer rated {overall} out of 5 and recommends {d['recommendation']}.",
                "competencies": [{"name": c["name"], "score": c["score"], "weight": 1, "evidence": c.get("quote", ""),
                                  "note": c.get("note", ""), "ai_score": ai_scores.get(c["name"]),
                                  "suggested": c.get("suggested"), "disagree": (str(c.get("disagree") or "").strip()[:500] or None),
                                  # V02.00.13: a competency left on Skip is "Not rated", not a crash ("Something went wrong")
                                  # V02.01.01: an explicit Skip shows as such, with the optional reason, and isn't counted
                                  "level": "Skipped" if c.get("score") in (None, "") and c.get("skipped") else _level(c.get("score")),
                                  **({"skipped": True, "skip_reason": (str(c.get("skip_reason") or "").strip()[:300] or None)}
                                     if c.get("score") in (None, "") and c.get("skipped") else {})}
                                 for c in d.get("competencies", []) if c.get("name")],
                "questions": [_report_question_v13(a, {p["area"]: p for p in (att.brief or {}).get("areas", [])}) for a in log_
                              if a.get("type") != "smalltalk"],
                "sources": _source_counts(att),
                # V02.01.01: how the answers were filed: by Isha reading the whole transcript, or as filed live
                "review": {k: v for k, v in (res.get("review") or {}).items() if k in ("source", "turns", "asked", "of", "not_asked", "extra", "followups", "undone")},
                "notes": res.get("notes", []), "interviewer_note": d.get("note"),
                "strengths": [c["name"] for c in comps if float(c["score"]) >= 4],
                "gaps": [c["name"] for c in comps if float(c["score"]) < 3],
                "ai_agreement": _agreement(comps, ai_scores),
                "coverage": {"planned": [a["area"] for a in (att.brief or {}).get("areas", [])], "tested": [a["area"] for a in log_]}}
    # V02.01.01: a short summary of each part and of the whole interview, written when the scorecard is submitted
    _add_summaries(sections, job, cand.name if cand else "The candidate")
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


def _add_summaries(sections, job, name):
    try:
        out = ai.answer_summaries(job, name, sections.get("questions") or [], sections.get("competencies") or [],
                                  company_id=job.company_id if job else None)
    except Exception:  # noqa: BLE001 - a report without summaries is still a report
        current_app.logger.exception("summaries")
        return
    for q, sm in zip(sections.get("questions") or [], out.get("parts") or []):
        if sm:
            q["summary"] = sm
    sections["isha_summary"] = out.get("overall")


@bp.post("/<int:att_id>/move-quote")
@auth_required
def move_quote(att_id):
    """V02.01.01: on the scorecard, the interviewer moves a quote Isha filed under the wrong topic.
    {index, sentence, to: a plan area | "Small talk" | "Not in the plan"}. Both topics are scored again."""
    att = load(att_id)
    if not att:
        return deny()
    if att.status in ("completed", "reviewed", "voided", "cancelled"):
        return err("The scorecard is already submitted." if att.status in ("completed", "reviewed") else "This interview was replaced by a retake.", 409)
    d = body()
    res = dict(att.result or {})
    log_ = [dict(a) for a in res.get("areas_log", [])]
    try:
        i, j = int(d.get("index")), int(d.get("sentence"))
        src = log_[i]
        quote = list(src.get("sentences") or [])[j]
    except (TypeError, ValueError, IndexError):
        return err("That quote wasn't found. Reload the scorecard and try again.")
    to = str(d.get("to") or "")
    plan = {a["area"]: a for a in (att.brief or {}).get("areas", [])}
    if to not in plan and to not in ("Small talk", "Not in the plan"):
        return err("Choose one of the interview's topics.")
    if to == src.get("area"):
        return err("The quote is already under that topic.")
    from services.isha_review import entry_map, rescore
    src["sentences"] = [x for k, x in enumerate(src.get("sentences") or []) if k != j]
    log_[i] = rescore(src) if src.get("type") != "smalltalk" else src
    k = next((n for n, e in enumerate(log_) if e.get("area") == to and e.get("type") in (None, "main", "smalltalk", "own")
              and e.get("followup_of") is None), None)
    if k is None:
        p = plan.get(to) or {}
        typ = "smalltalk" if to == "Small talk" else "main" if p else "own"
        log_.append({"area": to, "q": p.get("q") or to, "type": typ, "good": p.get("good") or [], "sentences": [], "tags": [],
                     "score": None, "coverage": [], "at": src.get("at") or 0, "reviewed": True, "moved_in": True})
        k = len(log_) - 1
    tgt = dict(log_[k])
    tgt["sentences"] = list(tgt.get("sentences") or []) + [quote]
    log_[k] = rescore(tgt) if tgt.get("type") != "smalltalk" else tgt
    res["areas_log"] = log_
    rv = dict(res.get("review") or {})
    rv["map"] = entry_map(log_)
    rv["moved"] = int(rv.get("moved") or 0) + 1
    res["review"] = rv
    att.result = res
    app, job, cand, _ = context(att)
    from services.scorecard import draft as make_draft
    res = dict(att.result or {})
    res["draft_scorecard"] = make_draft(att, job, cand.name if cand else "The candidate", use_ai=False)
    att.result = res
    log("isha.move_quote", "attempt", att.id, to=to)
    db.session.commit()
    return ok({"review": res["review"], "draft": res["draft_scorecard"], "state": _state(att)})


@bp.post("/<int:att_id>/tick")
@auth_required
def tick(att_id):
    """N3 (V02.00.09): the interviewer marks a point of a good answer as covered (or not) when Isha missed it."""
    att = load(att_id)
    if not att:
        return deny()
    if att.status in ("completed", "reviewed", "voided", "cancelled"):
        return err("This interview is closed.", 409)
    d = body()
    res = dict(att.result or {})
    log_ = [dict(a) for a in res.get("areas_log", [])]
    try:
        i, p = int(d.get("index")), int(d.get("point"))
        e = log_[i]
        (e.get("good") or [])[p]
    except (TypeError, ValueError, IndexError):
        return err("That point wasn't found.")
    ticks = set(e.get("ticks") or [])
    if d.get("on", True):
        ticks.add(p)
    else:
        ticks.discard(p)
    e["ticks"] = sorted(ticks)
    log_[i] = apply_ticks(e)
    res["areas_log"] = log_
    att.result = res
    log("isha.tick", "attempt", att.id, index=i, point=p, on=bool(d.get("on", True)))
    db.session.commit()
    return ok(_state(att))


@bp.post("/<int:att_id>/rate")
@auth_required
def rate(att_id):
    """V02.00.13: the interviewer's own 1-5 rating for one question, given in the room. It counts first on the scorecard.
    {index, score: 1-5 or null to clear}"""
    att = load(att_id)
    if not att:
        return deny()
    if att.status in ("completed", "reviewed", "voided", "cancelled"):
        return err("This interview is closed, so ratings can't change here. Use the report to edit scores.", 409)
    d = body()
    res = dict(att.result or {})
    log_ = [dict(a) for a in res.get("areas_log", [])]
    try:
        i = int(d.get("index"))
        e = log_[i]
    except (TypeError, ValueError, IndexError):
        return err("Ask the question first, then rate the answer.")
    sc = d.get("score")
    if sc in (None, ""):
        e.pop("rating", None)
    else:
        try:
            sc = int(sc)
        except (TypeError, ValueError):
            return err("Pick a rating from 1 to 5.")
        if not 1 <= sc <= 5:
            return err("Pick a rating from 1 to 5.")
        e["rating"] = sc
    log_[i] = e
    res["areas_log"] = log_
    att.result = res
    log("isha.rate", "attempt", att.id, index=i, score=e.get("rating"))
    db.session.commit()
    return ok(_state(att))


@bp.post("/<int:att_id>/chat")
@auth_required
def chat(att_id):
    """V02.00.13: Ask Isha. The interviewer's private chat about this interview: more questions, follow-ups, whether
    a point was covered. Never shown to the candidate. {message}"""
    att = load(att_id)
    if not att or att.round_type != "f2f_isha":
        return deny()
    msg = " ".join(str(body().get("message") or "").split())[:800]
    if len(msg) < 2:
        return err("Type a question for Isha.")
    app, job, cand, profile = context(att)
    res = dict(att.result or {})
    log_ = res.get("areas_log", [])
    cur = (res.get("current") or {})
    idx = cur.get("index")
    cur_e = log_[idx] if isinstance(idx, int) and 0 <= idx < len(log_) else None
    plan = (att.brief or {}).get("areas", [])
    history = (res.get("chat") or [])[-12:]
    mins = (att.config or {}).get("f2f.minutes") or resolve("f2f.minutes", company_id=job.company_id, team_id=job.team_id, job_id=job.id)[0]
    out = ai.isha_chat(msg, job, profile.resume_text if profile else "", plan, log_, cur_e, history, company_id=job.company_id,
                       ctx={"minutes": mins, "elapsed": _secs(att)})
    res["chat"] = (list(res.get("chat") or []) + [{"who": "you", "text": msg, "at": _secs(att)},
                                                  {"who": "isha", "text": out["reply"], "questions": out.get("questions") or [],
                                                   "source": out.get("source"), "at": _secs(att)}])[-80:]
    att.result = res
    db.session.commit()
    return ok({"chat": res["chat"], "reply": res["chat"][-1]})


def captured(att):
    """How much of the interview was recorded: sentences heard and video pieces."""
    from models import Recording
    sents = sum(len(a.get("sentences") or []) for a in (att.result or {}).get("areas_log", []))
    videos = Recording.query.filter(Recording.attempt_id == att.id, Recording.status.in_(("ready", "processing", "recording"))).count()
    return {"sentences": sents, "videos": videos, "any": bool(sents or videos)}


@bp.get("/<int:att_id>/close")
@auth_required
def close_info(att_id):
    """N4 (V02.00.09): what the Close interview window offers for this interview."""
    att = load(att_id)
    if not att:
        return deny()
    cap = captured(att)
    open_ = att.status in ("in_progress", "paused", "not_finished", "invited", "scheduled")
    return ok({"status": att.status, "captured": cap, "can_close": att.status in ("in_progress", "paused", "invited", "scheduled"),
               "can_score": att.status in ("in_progress", "paused", "not_finished"),
               "open": open_, "closed": (att.result or {}).get("closed")})


@bp.post("/<int:att_id>/close")
@auth_required
def close(att_id):
    """N4 (V02.00.09): close an interview that is still open, without a scorecard. It is marked not finished with
    the reason; the transcript and the video stay, and someone can still submit the scorecard later."""
    att = load(att_id)
    if not att:
        return deny()
    if att.status not in ("in_progress", "paused", "invited", "scheduled"):
        return err("This interview is already closed." if att.status in ("not_finished", "completed", "reviewed", "expired")
                   else "This interview was replaced or cancelled.", 409)
    reason = str(body().get("reason") or "").strip()[:500]
    if not reason:
        return err("Say briefly why you're closing it.", fields={"reason": "Required."})
    app, job, cand, _ = context(att)
    res = dict(att.result or {})
    res["closed"] = {"reason": "closed_by_staff", "note": reason, "by": g.user.name, "by_id": g.user.id,
                     "at": datetime.utcnow().isoformat() + "Z", "captured": captured(att)}
    res["ended"] = True
    att.result = res
    was_live = att.status in ("in_progress", "paused")
    att.status = "not_finished"
    att.completed_at = att.completed_at or datetime.utcnow()
    if app and app.stage == "in_round":
        app.stage = "awaiting_review"
    if was_live:
        from models import CallSignal
        db.session.add(CallSignal(attempt_id=att.id, sender="interviewer", kind="bye", payload={"ended": True}))
    log("isha.close", "attempt", att.id, company_id=job.company_id if job else None, reason=reason)
    db.session.commit()
    return ok({"status": att.status, "state": _state(att)})


def _report_question(a):
    """R6 (V02.00.06): one question in the F2F report: what was asked, what a good answer covers (from Isha's plan),
    which points the candidate covered, the candidate's own words, and what the interviewer said around it."""
    good = a.get("good") or ai.expected_points(a.get("q"), a.get("area"))
    cov = list(a.get("coverage") or [])
    return {"q": a["q"], "a": " ".join(a.get("sentences") or []), "score": a.get("score"), "topic": a["area"],
            "tags": a.get("tags", []), "time": f"{a.get('at', 0) // 60:02d}:{a.get('at', 0) % 60:02d}", "kind": a.get("type"),
            "good_answer": good, "covered": [(cov[i] if i < len(cov) else "") == "full" for i in range(len(good))],
            "covered_level": [(cov[i] if i < len(cov) else "") for i in range(len(good))],
            "interviewer_said": [x.get("t") for x in (a.get("said") or []) if x.get("t")], "auto": bool(a.get("auto")),
            "assumed": bool(a.get("assumed")), "rating": a.get("rating")}


def _report_question_v13(a, plan):
    """V02.00.13: also the section, the question type and where the question came from (Claude, built-in, yours)."""
    out = _report_question(a)
    p = plan.get(a.get("area")) or {}
    out.update({"section": p.get("section"), "qtype": p.get("type_label") or p.get("type"), "source": p.get("source"),
                "followup": a.get("followup_of") is not None or (a.get("type") not in (None, "main"))})
    return out


def _source_counts(att):
    out = {}
    for p in (att.brief or {}).get("areas", []):
        k = p.get("source") or ("own" if p.get("own") else "claude" if (att.brief or {}).get("ai") else "builtin")
        out[k] = out.get(k, 0) + 1
    return out


def _agreement(comps, ai_scores):
    pairs = [(float(c["score"]), float(ai_scores[c["name"]])) for c in comps if ai_scores.get(c["name"])]
    if not pairs:
        return None
    diff = sum(abs(a - b) for a, b in pairs) / len(pairs)
    return {"pairs": len(pairs), "avg_diff": round(diff, 2), "level": "high" if diff < 0.75 else ("medium" if diff < 1.5 else "low")}
