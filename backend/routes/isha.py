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
            "topics": _live_topics(att),
            # V02.01.02: for the scorecard: the selected questions with no answer (each needs a decision) and the
            # extra questions the interviewer asked (shown on the report only when ticked)
            "unanswered": _unanswered(att), "extras": _extras(att),
            # V02.01.04: what was captured, and whether the video can be transcribed when the captions missed it
            "transcribe": res.get("transcribe"),
        "caption_gaps": res.get("caption_gaps") or [],
        "wrapup": res.get("wrapup"), "draft_ready": bool(res.get("draft_scorecard")), "can_transcribe": _can_transcribe(),
            "file_topics": _file_topics(att), "manual_filing": res.get("manual_filing") or {}}


def _file_topics(att):
    from services.isha_review import file_topics
    _, job, _, profile = context(att)
    return file_topics(att, job, profile)


def _can_transcribe():
    try:
        from services import transcribe
        return transcribe.available()
    except Exception:  # noqa: BLE001
        return False


def _answered_areas(log_):
    return {e.get("area") for e in log_ if e.get("type") != "smalltalk" and (e.get("sentences") or [])}


def _unanswered(att):
    """Selected (planned) questions with no answer in the reviewed transcript. The Wrap-up and questions skipped
    during the interview need no decision."""
    res = att.result or {}
    if not (res.get("ended") or att.status in ("completed", "reviewed")):
        return []
    done = _answered_areas(res.get("areas_log") or [])
    return [{"area": a["area"], "q": a.get("q"), "section": a.get("section"), "type": a.get("type_label") or a.get("type")}
            for a in (att.brief or {}).get("areas", [])
            if a.get("area") != "Wrap-up" and not a.get("skipped") and a["area"] not in done]


def _extras(att):
    """Questions asked that weren't in the plan, with their place in the log (for Show on report)."""
    res = att.result or {}
    plan = {a["area"] for a in (att.brief or {}).get("areas", [])}
    return [{"index": i, "q": e.get("q"), "at": e.get("at", 0), "sentences": len(e.get("sentences") or [])}
            for i, e in enumerate(res.get("areas_log") or [])
            if e.get("type") not in ("smalltalk", "Follow-up", "added") and e.get("followup_of") is None and e.get("area") not in plan
            and (e.get("sentences") or [])]


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
    from services import ibank
    secs = {s_["key"]: s_ for s_ in prep.get("sections") or []}
    for q in prep.get("questions") or []:   # V02.01.05: about this candidate only: can't be kept for the job
        q["personal"] = ibank.personal({**q, "section_kind": (secs.get(q["section"]) or {}).get("kind")}) if q["type"] != "own" else False
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


def _used(res, cur):
    """V02.01.06: the follow-up purposes this question already had."""
    return list(((res.get("fu_used") or {}).get(cur.get("area") or "") or []))


def _last(res, cur):
    return list(((res.get("fu_last") or {}).get(cur.get("area") or "") or []))


def _use(res, cur, opts):
    u, l_ = dict(res.get("fu_used") or {}), dict(res.get("fu_last") or {})
    k = cur.get("area") or ""
    now = [o["purpose"] for o in opts if o.get("purpose")]
    u[k] = (list(u.get(k) or []) + now)[-12:]
    l_[k] = now
    res["fu_used"], res["fu_last"] = u, l_


def _short(t, n=10):
    w = " ".join(str(t or "").split()).split(" ")
    return " ".join(w[:n]).strip(" ,.;:") + ("…" if len(w) > n else "")


def _with_evidence(opts, cur, said, profile, job):
    """V02.01.05: every follow-up says what it picks up on: {"evidence": {"from": "conversation" | "resume" | "job" |
    "plan", "quote"}}. Claude names it; the built-in ones get it from how they were made."""
    resume = ((profile.resume_text if profile else "") or "").lower()
    jd = ((job.description if job else "") or "").lower()
    out = []
    for o in opts or []:
        o = dict(o)
        ev = o.get("evidence") if isinstance(o.get("evidence"), dict) else {}
        frm, quote = str(ev.get("from") or "").lower(), str(ev.get("quote") or "").strip().strip('"')
        if frm not in ("conversation", "resume", "job", "plan"):
            frm = ""
        if not frm:
            if o.get("type") == "Move on" or o.get("source") == "plan":
                frm, quote = "plan", o.get("area") or quote
            elif o.get("source") == "prepared":
                frm, quote = "plan", (o.get("why") or "").replace("Not covered yet: ", "")
            else:
                frm, quote = "conversation", quote or said
        if quote and frm == "conversation":   # the words might really be from the resume or the job description
            ql = quote.lower()[:60]
            if len(ql) > 12 and ql in resume and ql not in said.lower():
                frm = "resume"
            elif len(ql) > 12 and ql in jd and ql not in said.lower():
                frm = "job"
        o["evidence"] = {"from": frm, "quote": _short(quote)}
        out.append(o)
    return out


@bp.post("/<int:att_id>/followups")
@auth_required
def refresh_followups(att_id):
    """V02.01.05: the ↻ in Isha's panel: new follow-ups now, from the answer so far."""
    att = load(att_id)
    if not att or att.status != "in_progress" or att.round_type != "f2f_isha":
        return err("Follow-ups come while the interview runs.", 409)
    res = dict(att.result or {})
    log_ = res.get("areas_log") or []
    idx = (res.get("current") or {}).get("index")
    if idx is None or idx >= len(log_):
        return ok({"options": res.get("options") or [], "state": _state(att)})
    cur = log_[idx]
    app, job, cand, profile = context(att)
    asked = {a["area"] for a in log_}
    remaining = [a for a in (att.brief or {}).get("areas", []) if a["area"] not in asked]
    shown = list(res.get("shown_options") or []) + [a.get("q") for a in log_ if a.get("q")] + [o.get("q") for o in res.get("options") or []]
    plan_area = next((a for a in (att.brief or {}).get("areas", []) if a["area"] == cur["area"]), {})
    sents = cur.get("sentences") or []
    last = sents[-1] if sents else (cur.get("q") or "")
    analysis = ai.isha_analyze(cur.get("q") or "", cur["area"], cur.get("good", []), sents[:-1], last,
                               profile.resume_text if profile else "", remaining, _options(att), company_id=job.company_id,
                               shown=shown, prepared=(plan_area.get("followups") or []) if cur.get("q") == plan_area.get("q") else [],
                               asked=[a.get("q") for a in log_ if a.get("q")], used=_used(res, cur), last=_last(res, cur))
    opts = _with_evidence(analysis.get("options", []), cur, last, profile, job)
    _use(res, cur, opts)
    if sents:   # V02.01.06: follow-ups come per answer: the answer's points and score are brought up to date here too
        cur = dict(cur)
        cur["score"] = cur["score_ai"] = analysis.get("score")
        cur["coverage_ai"] = analysis.get("coverage", [])
        cur["tags"] = (cur.get("tags") or []) + [{"s": len(sents) - 1, **t} for t in analysis.get("tags", [])]
        cur = apply_ticks(cur)
        log_ = [dict(a) for a in log_]
        log_[idx] = cur
        res["areas_log"] = log_
    res["options"] = opts
    res["shown_options"] = (list(res.get("shown_options") or []) + [o["q"] for o in opts if o.get("type") != "Move on"])[-60:]
    att.result = res
    db.session.commit()
    return ok({"options": opts, "state": _state(att)})


@bp.post("/<int:att_id>/caption-gap")
@auth_required
def caption_gap(att_id):
    """V02.01.05: a stretch with no captions (Azure dropped and the browser took over, or the network went). {at, seconds,
    who}. Shown on the capture line; at End the scorecard offers to transcribe the recording."""
    att = load(att_id)
    if not att:
        return deny()
    d = body()
    try:
        secs = max(0, min(3600, int(d.get("seconds") or 0)))
    except (TypeError, ValueError):
        return err("seconds must be a number.")
    if secs < 10:
        return ok({"gaps": (att.result or {}).get("caption_gaps") or []})
    res = dict(att.result or {})
    gaps = list(res.get("caption_gaps") or [])[-49:]
    gaps.append({"at": str(d.get("at") or datetime.utcnow().isoformat() + "Z")[:40], "seconds": secs,
                 "who": "candidate" if d.get("who") == "candidate" else "interviewer"})
    res["caption_gaps"] = gaps
    att.result = res
    db.session.commit()
    return ok({"gaps": gaps})


@bp.post("/<int:att_id>/keep")
@auth_required
def keep_for_job(att_id):
    """V02.01.05: "Keep for this job": {ids: [prep question ids] | "selected"}. Kept questions become this job's set:
    the next candidates for the job get them first, already selected. Questions about this candidate's own resume
    are never kept. Works before, during and after the interview."""
    att = load(att_id)
    if not att or att.round_type != "f2f_isha":
        return deny()
    app, job, cand, profile = context(att)
    prep = (att.brief or {}).get("prep") or {}
    ids = body().get("ids")
    ids = prep.get("selected") or [] if ids == "selected" else [str(i) for i in (ids or [])]
    secs = {s_["key"]: s_ for s_ in prep.get("sections") or []}
    items = [{**q, "section_kind": (secs.get(q["section"]) or {}).get("kind"), "skill": (secs.get(q["section"]) or {}).get("skill")}
             for q in prep.get("questions") or [] if q["id"] in ids and q["type"] not in ("wrap",)]
    if not items:
        return err("Choose the questions to keep.")
    from services import ibank
    got = ibank.keep(job, items, g.user.name)
    kept = {q.text for q in got["kept"]}
    for q in prep.get("questions") or []:
        if q["q"] in kept or q["id"] in ids and not ibank.personal({**q, "section_kind": (secs.get(q["section"]) or {}).get("kind")}):
            q["kept"] = True
    att.brief = {**(att.brief or {}), "prep": prep}
    log("isha.keep_for_job", "job", job.id, company_id=job.company_id, kept=len(got["kept"]), personal=got["personal"])
    db.session.commit()
    n, p_ = len(got["kept"]), got["personal"]
    msg = (f"Kept {n} question{'s' if n != 1 else ''} for {job.title}." if n else "Nothing new to keep.") + \
        (f" {p_} about this candidate's resume {'weren' if p_ != 1 else 'wasn'}'t kept." if p_ else "") + \
        (f" {got['already']} {'were' if got['already'] != 1 else 'was'} already in the job's set." if got["already"] else "")
    return ok({**_prep_out(att), "message": msg})


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
    if (att.result or {}).get("ended") or att.status == "not_finished":
        return err("This interview has ended. It can't start again.", 409)
    d = body() or {}
    if att.status == "in_progress":  # V02.01.04: started already (by the other tab, or the auto-start): nothing to do
        return ok(_state(att))
    att.status = "in_progress"
    att.started_at = att.started_at or datetime.utcnow()
    app, job, cand, _ = context(att)
    if app:
        app.stage = "in_round"
    # V02.01.04: what both of you said after the call connected but before Start is kept, at the very start
    pre = [x for x in (d.get("pre") or [])[-60:] if isinstance(x, dict) and str(x.get("text") or "").strip()]
    if pre:
        seq = db.session.query(db.func.max(Turn.seq)).filter_by(attempt_id=att.id).scalar() or 0
        for k, x in enumerate(pre, start=1):
            who = "interviewer" if x.get("who") == "interviewer" else "candidate"
            db.session.add(Turn(attempt_id=att.id, seq=seq + k, speaker=who, text=str(x["text"]).strip()[:1000], at_seconds=0,
                                topic="Before the start"))
    video = d.get("video")
    if video in ("not_connected", "candidate_absent"):  # V02.00.08: the report says the interview started without video
        res = dict(att.result or {})
        res["started_without_video"] = video
        att.result = res
    log("isha.start", "attempt", att.id, company_id=job.company_id, **({"video": video} if video else {}),
        **({"auto": True} if d.get("auto") else {}), **({"before_start": len(pre)} if pre else {}))
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
    analysis = {"tags": [], "score": None, "coverage": cur.get("coverage") or [], "options": res.get("options") or []}
    defer = bool(body().get("defer"))   # V02.01.06: while the candidate is talking; follow-ups come after a pause (/followups)
    if att.round_type == "f2f_isha" and not defer:
        shown = list(res.get("shown_options") or []) + [a.get("q") for a in log_ if a.get("q")]
        plan_area = next((a for a in (att.brief or {}).get("areas", []) if a["area"] == cur["area"]), {})
        analysis = ai.isha_analyze(cur["q"], cur["area"], cur.get("good", []), cur["sentences"], text,
                                   profile.resume_text if profile else "", remaining,
                                   _options(att), company_id=job.company_id, shown=shown,
                                   prepared=(plan_area.get("followups") or []) if cur.get("q") == plan_area.get("q") else [],
                                   asked=[a.get("q") for a in log_ if a.get("q")], used=_used(res, cur), last=_last(res, cur))
        res["shown_options"] = (list(res.get("shown_options") or []) + [o["q"] for o in analysis.get("options", []) if o.get("type") != "Move on"])[-60:]
        _use(res, cur, analysis.get("options", []))
    cur["sentences"] = cur["sentences"] + [text]
    cur["tags"] = cur.get("tags", []) + [{"s": len(cur["sentences"]) - 1, **t} for t in analysis.get("tags", [])]
    if not defer:
        cur["score"] = analysis.get("score")
        cur["score_ai"] = analysis.get("score")
        cur["coverage_ai"] = analysis.get("coverage", [])
        cur["full_marks"] = False
        cur = apply_ticks(cur)
    analysis = {**analysis, "score": cur["score"], "coverage": cur["coverage"]}
    log_[idx] = cur
    res["areas_log"] = log_
    if not defer:
        analysis["options"] = _with_evidence(analysis.get("options", []), cur, text, profile, job)
    res["options"] = analysis.get("options", [])
    att.result = res
    seq = Turn.query.filter_by(attempt_id=att.id).count()
    db.session.add(Turn(attempt_id=att.id, seq=seq, speaker="candidate", text=text, topic=cur["area"], analysis=analysis,
                        at_seconds=_secs(att)))
    db.session.flush()
    from services.isha_review import track_now
    prev, now = track_now(att)   # V02.01.04: which topic each answer belongs to, for Isha's live score
    db.session.commit()
    st = _state(att)
    hide = (att.config or {}).get("isha.hide_ai_scores_until_scorecard")
    return ok({"analysis": {**analysis, "score": None if hide else analysis.get("score")}, "state": st,
               "options": analysis.get("options", []), **({"topic_ended": prev} if prev else {})})


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
    """Interview over. V02.01.06: answers at once, so the screen never freezes. The candidate's call closes, a quick
    keyword review lets the scorecard open straight away, and Isha's full review (reading the whole conversation,
    scoring, deciding) and the candidate's thank-you run in the background: GET the room for result.wrapup."""
    att = load(att_id)
    if not att:
        return deny()
    app, job, cand, _ = context(att)
    res = dict(att.result or {})
    if res.get("ended") and (res.get("wrapup") or {}).get("state") in ("running", "done"):
        return ok({"draft": res.get("draft_scorecard"), "state": _state(att), "review": res.get("review")})   # ended already
    res["ended"] = True
    res["ended_at"] = _secs(att)
    att.result = res
    from models import CallSignal
    db.session.add(CallSignal(attempt_id=att.id, sender="interviewer", kind="bye", payload={"ended": True}))  # candidate's room closes
    from services.isha_review import review as review_all
    if (res.get("review") or {}).get("source") != "manual":
        review_all(att, company_id=job.company_id if job else None, use_ai=False)   # quick, so a scorecard can open now
    from services.scorecard import draft as make_draft
    res = dict(att.result or {})
    res["draft_scorecard"] = make_draft(att, job, cand.name if cand else "The candidate", use_ai=False)
    att.result = res
    from services import wrapup
    wrapup.begin(att)
    log("isha.end", "attempt", att.id, company_id=job.company_id if job else None)
    db.session.commit()
    _run_wrapup(att, str(request.args.get("ai", "1")) != "0")
    db.session.refresh(att)
    res = att.result or {}
    return ok({"draft": res.get("draft_scorecard"), "state": _state(att), "review": res.get("review")})


def _run_wrapup(att, use_ai):
    """In the background on a server; in tests (and with ?ai=0) at once, so results are there when the call returns."""
    from services import wrapup
    if current_app.config.get("TESTING") or not use_ai:
        wrapup.run(att.id, use_ai)
    else:
        wrapup.start(current_app._get_current_object(), att.id, use_ai)


@bp.post("/<int:att_id>/wrapup")
@auth_required
def wrapup_again(att_id):
    """V02.01.06: Retry in the "Wrapping up" window: runs the background steps again."""
    att = load(att_id)
    if not att:
        return deny()
    if not (att.result or {}).get("ended"):
        return err("The interview hasn't ended.", 409)
    if att.status in ("completed", "reviewed"):
        return err("The scorecard is already submitted.", 409)
    if ((att.result or {}).get("wrapup") or {}).get("state") == "running":
        return ok({"state": _state(att)})
    from services import wrapup
    wrapup.begin(att)
    db.session.commit()
    _run_wrapup(att, bool(body().get("ai", True)))
    db.session.refresh(att)
    return ok({"state": _state(att), "draft": (att.result or {}).get("draft_scorecard")})


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
    if att.status in ("completed", "reviewed") and not _unconfirmed(att):
        return err("The scorecard for this interview is already submitted.", 409)
    if att.status in ("voided", "cancelled"):
        return err("This interview was replaced by a retake.", 409)
    d = body()
    draft_ = (att.result or {}).get("draft_scorecard") or {}
    isha = draft_.get("isha") or {}
    if d.get("agree"):
        # V02.01.06: "Agree and submit": Isha's scores and decision as they are; questions with no answer are skipped
        if not isha or isha.get("insufficient"):
            return err("Isha didn't have enough evidence to score it. Score it yourself from your notes or the video.", 409)
        if d.get("recommendation") not in ("proceed", "hold", "reject"):
            return err("Choose your recommendation: Proceed, Hold or Do not proceed.", fields={"recommendation": "Required."})
        d = _from_isha(att, draft_, d)
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
    # V02.01.02: every selected question with no answer needs a decision: pick its answer, or Skip
    decisions = {str(x.get("area")): x for x in d.get("question_decisions") or [] if isinstance(x, dict) and x.get("area")}
    undecided = [u["area"] for u in _unanswered(att) if not decisions.get(u["area"], {}).get("skip")]
    if missing or undecided:
        msg = []
        if missing:
            msg.append(f"Rating not received for: {', '.join(missing)}. Rate each from 1 to 5, or press Skip if you didn't assess it.")
        if undecided:
            msg.append(f"Decision needed for: {', '.join(undecided)}. Pick its answer from the transcript, or press Skip.")
        return err(" ".join(msg), fields={"missing": missing, "undecided": undecided})
    if not comps:
        return err("Rate at least one competency from 1 to 5 before submitting. Skipped ones aren't counted.")
    if d.get("recommendation") not in ("proceed", "hold", "reject"):
        return err("Choose a recommendation: Proceed, Hold or Do not proceed.")
    # V02.01.07: changing Isha's scores needs no reason
    r = publish(att, d, g.user)
    return ok({"report_id": r.id, "overall": att.score})


def _unconfirmed(att):
    """V02.01.06: a report Isha published on her own (24 hours without the interviewer) can still be confirmed."""
    from models import Report
    r = Report.query.filter_by(attempt_id=att.id).first()
    return bool(r and ((r.sections or {}).get("interviewer") or {}).get("confirmed") is False)


def _from_isha(att, draft_, d):
    isha = draft_.get("isha") or {}
    comps = [{**c, "score": c.get("score"), "skipped": not c.get("score"), "suggested": c.get("score")} for c in draft_.get("competencies") or []]
    return {**d, "competencies": comps, "recommendation": d.get("recommendation"),
            "question_decisions": [{"area": u["area"], "skip": True} for u in _unanswered(att)], "agreed": True}


def publish(att, d, user=None, regen=False):
    """Builds the report from a scorecard. user=None: Isha publishes on her own (not confirmed by the interviewer).
    regen: the report is rebuilt (Regenerate): its status, verdict and sharing stay as they are."""
    comps = [c for c in d.get("competencies", []) if c.get("score") not in (None, "")]
    decisions = {str(x.get("area")): x for x in d.get("question_decisions") or [] if isinstance(x, dict) and x.get("area")}
    app, job, cand, _ = context(att)
    res = dict(att.result or {})
    overall = round(sum(float(c["score"]) for c in comps) / len(comps), 1)
    log_ = res.get("areas_log", [])
    ai_scores = {a["area"]: a.get("score") for a in log_ if a.get("score")}
    ai_scores.update({c["name"]: c["ai_score"] for c in d.get("competencies", []) if isinstance(c.get("ai_score"), (int, float))})
    draft_ = res.get("draft_scorecard") or {}
    isha = draft_.get("isha") or {}
    rec_word = {"proceed": "Proceed", "hold": "Hold", "reject": "Do not proceed"}.get(d.get("recommendation"))
    # V02.01.07: one assessment: the final scores as submitted, with no record on the report of what changed from
    # Isha's scores (that stays in the audit log), and nothing about how it was produced
    sections = {"kind": att.round_type, "v": 2, "summary": d.get("summary") or draft_.get("summary") or f"Rated {overall} out of 5" + (f"; recommendation: {rec_word}." if rec_word else "."),
                "competencies": [{"name": c["name"], "score": c["score"], "weight": 1, "evidence": c.get("quote") or c.get("evidence", ""),
                                  "note": c.get("note", ""),
                                  # V02.00.13: a competency left on Skip is "Not rated", not a crash ("Something went wrong")
                                  # V02.01.01: an explicit Skip shows as such, with the optional reason, and isn't counted
                                  "level": "Skipped" if c.get("score") in (None, "") and c.get("skipped") else _level(c.get("score")),
                                  **({"skipped": True, "skip_reason": (str(c.get("skip_reason") or "").strip()[:300] or None)}
                                     if c.get("score") in (None, "") and c.get("skipped") else {})}
                                 # V02.01.02: a skipped competency is on the report only when "Show on report" is ticked
                                 for c in d.get("competencies", []) if c.get("name")
                                 and not (c.get("score") in (None, "") and c.get("skipped") and not c.get("show_on_report"))],
                "questions": _report_questions(att, log_, decisions, d.get("show_extras") or []),
                "sources": _source_counts(att),
                # V02.01.01: how the answers were filed: by Isha reading the whole transcript, or as filed live
                "review": {k: v for k, v in (res.get("review") or {}).items() if k in ("turns", "asked", "of", "not_asked", "extra", "followups", "undone")},
                "notes": res.get("notes", []), "interviewer_note": d.get("note"),
                "strengths": [c["name"] for c in comps if float(c["score"]) >= 4],
                "gaps": [c["name"] for c in comps if float(c["score"]) < 3],
                "coverage": {"planned": [a["area"] for a in (att.brief or {}).get("areas", [])], "tested": [a["area"] for a in log_]},
                "isha": {k: isha.get(k) for k in ("insufficient", "confidence", "reason", "strengths", "concerns", "flags", "rank", "topics")} if isha else None,
                "interviewer": {"confirmed": bool(user)}}
    # V02.01.01: a short summary of each part and of the whole interview, written when the scorecard is submitted
    _add_summaries(sections, job, cand.name if cand else "The candidate")
    was_done = att.status in ("completed", "reviewed")
    att.score = overall
    att.status = att.status if was_done else "completed"
    att.completed_at = att.completed_at if was_done and att.completed_at else datetime.utcnow()
    att.result = res
    from models import Report
    old = Report.query.filter_by(attempt_id=att.id).first()
    keep = {k: getattr(old, k) for k in ("status", "verdict", "candidate_feedback")} if (regen and old) else None
    r = make_report(att, sections, overall, d.get("recommendation"), isha.get("confidence") or ("high" if user else "medium"), notify=not regen)
    if keep:
        for k, v in keep.items():
            setattr(r, k, v)
    if user:
        r.reviewer_id = user.id
    if app and not was_done:
        app.stage = "awaiting_review"
    changed = [{"name": c["name"], "isha": c.get("suggested"), "final": c["score"]} for c in comps
               if c.get("suggested") not in (None, "") and float(c["score"]) != float(c["suggested"])]
    log("isha.regenerate" if regen else "isha.scorecard" if user else "isha.autopublish", "attempt", att.id, company_id=job.company_id,
        overall=overall, rec=d.get("recommendation"), changed=changed)   # what changed from Isha's scores: audit only
    if cand and not was_done:
        notify(cand.id, "Thanks for interviewing", f"{job.title}. The team will be in touch.", "/me/applications")
    db.session.commit()
    return r


def publish_unconfirmed(hours=24):
    """V02.01.06 (housekeeping): an ended interview whose scorecard nobody submitted goes to the hiring team as
    Isha's review after `hours`, marked "not yet confirmed by the interviewer". The interviewer can still confirm it."""
    from models import RoundAttempt
    cutoff = datetime.utcnow().timestamp() - hours * 3600
    n = 0
    for att in RoundAttempt.query.filter(RoundAttempt.round_type == "f2f_isha", RoundAttempt.status == "in_progress").all():
        res = att.result or {}
        w = res.get("wrapup") or {}
        if not res.get("ended") or w.get("state") not in ("done", "failed") or not res.get("draft_scorecard"):
            continue
        try:
            fin = datetime.fromisoformat(str(w.get("finished") or w.get("started")).rstrip("Z")).timestamp()
        except ValueError:
            continue
        if fin > cutoff:
            continue
        d = _from_isha(att, res["draft_scorecard"], {"recommendation": None})   # the recommendation is the hiring team's
        if not any(c.get("score") for c in d["competencies"]):
            continue   # nothing Isha could score: the interviewer has to look at it
        r = publish(att, d, None)
        _, job, cand, _ = context(att)
        try:
            from services.audit import notify_round_team
            notify_round_team(att, job, f"Isha's review is ready: {cand.name if cand else 'candidate'}",
                              f"The interviewer didn't submit a scorecard within {hours} hours, so Isha's review went to the report. "
                              "It's marked as not yet confirmed.")
        except Exception:  # noqa: BLE001
            pass
        n += 1 if r else 0
    return n


def _report_questions(att, log_, decisions, show_extras):
    """V02.01.02: the report has the selected questions that were answered, in plan order, each with its follow-ups
    folded in. Skipped questions and extra questions appear only when the interviewer ticked Show on report."""
    plan_list = (att.brief or {}).get("areas", [])
    plan = {p["area"]: p for p in plan_list}
    out = []
    for p in plan_list:
        area = p["area"]
        mains = [e for e in log_ if e.get("area") == area and e.get("type") in (None, "main") and e.get("followup_of") is None]
        fus = [e for e in log_ if e.get("area") == area and (e.get("type") == "Follow-up" or e.get("followup_of") is not None)]
        heard = [e for e in mains + fus if e.get("sentences")]
        if heard:
            base = next((e for e in mains if e.get("sentences")), None) or mains[0] if mains else heard[0]
            q = _report_question_v13(base, plan)
            q["followup"] = False
            q["followups"] = [{"q": f.get("q"), "a": " ".join(f.get("sentences") or []), "score": f.get("score"),
                               "time": f"{f.get('at', 0) // 60:02d}:{f.get('at', 0) % 60:02d}"} for f in fus if f.get("sentences")]
            out.append(q)
            continue
        dec = decisions.get(area) or {}
        if dec.get("skip") and dec.get("show_on_report"):
            out.append({"q": p.get("q"), "a": "", "topic": area, "section": p.get("section"), "qtype": p.get("type_label") or p.get("type"),
                        "source": p.get("source"), "skipped": True, "skip_reason": (str(dec.get("reason") or "").strip()[:300] or None),
                        "good_answer": [], "covered": [], "covered_level": [], "tags": [], "time": "", "kind": "main", "followups": []})
    # V02.01.04: a topic from the job description or the resume that the interviewer filed answers under is on the
    # report: they chose it
    for e in log_:
        if e.get("type") == "added" and e.get("sentences"):
            q = _report_question_v13(e, plan)
            q.update({"added": True, "added_from": e.get("source_topic"), "followup": False, "followups": []})
            out.append(q)
    shown = {int(i) for i in show_extras if str(i).lstrip("-").isdigit()}
    for i, e in enumerate(log_):
        if i in shown and e.get("area") not in plan and e.get("type") != "smalltalk" and e.get("sentences"):
            q = _report_question_v13(e, plan)
            q.update({"extra": True, "followup": False, "followups": []})
            out.append(q)
    return out


def _add_summaries(sections, job, name):
    # summaries only for answered questions; a question's follow-up answers count as part of its answer
    parts = [{**q, "a": " ".join([q.get("a") or ""] + [f.get("a") or "" for f in q.get("followups") or []]).strip()}
             for q in sections.get("questions") or [] if not q.get("skipped")]
    try:
        out = ai.answer_summaries(job, name, parts, [c for c in sections.get("competencies") or [] if not c.get("skipped")],
                                  company_id=job.company_id if job else None)
    except Exception:  # noqa: BLE001 - a report without summaries is still a report
        current_app.logger.exception("summaries")
        return
    for q, sm in zip([q for q in sections.get("questions") or [] if not q.get("skipped")], out.get("parts") or []):
        if sm:
            q["summary"] = sm
    sections["isha_summary"] = out.get("overall")


@bp.post("/<int:att_id>/move-quote")
@auth_required
def move_quote(att_id):
    """V02.01.01: on the scorecard, the interviewer moves a quote Isha filed under the wrong topic.
    {index, sentence, to: a plan area | "From the job description: X" | "From the resume: X" | "Small talk" |
    "Not in the plan"}. Both topics are scored again, and the choice is kept when Isha reviews again (V02.01.04)."""
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
    from services.isha_review import _norm_s, entry_map, move_sentence
    try:   # V02.01.04: also a job-description or resume topic that wasn't in the plan
        log_ = move_sentence(log_, i, j, to, plan, [a.get("competency") for a in plan.values() if a.get("competency")])
    except ValueError as e:
        return err(str(e))
    manual = dict(res.get("manual_filing") or {})
    manual[_norm_s(quote)] = to   # kept: Review again won't undo it
    res["manual_filing"] = manual
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
    if out.get("source") == "claude" and out.get("questions"):  # V02.01.04: what Claude writes goes into the question bank
        from services import ibank
        skill = ai._wanted(msg, job)[0]
        ibank.save(job.company_id, [{**q, "skill": skill or (cur_e or {}).get("competency") or "General",
                                     "level": {"Easy": 2, "Medium": 3, "Hard": 4}.get(q.get("level"), 3)} for q in out["questions"]],
                   note="Suggested by Ask Isha (Claude) in a live interview")
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
        from services.candidate_end import thank
        thank(att)   # V02.01.04: "stopped before the end" and what happens next
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


# ---------------------------------------------------------------------------------------------------- V02.01.04
@bp.post("/<int:att_id>/score-topic")
@auth_required
def score_topic(att_id):
    """Isha's suggested score for a topic whose answer just ended (the room calls this when the topic changes, or
    after a quiet spell). Claude judges it when available; otherwise the points covered."""
    att = load(att_id)
    if not att or att.status not in ("in_progress", "paused"):
        return err("The interview is not running.", 409)
    area = str(body().get("area") or "")
    if area not in {a["area"] for a in (att.brief or {}).get("areas", [])}:
        return err("Choose a question from the plan.")
    from services.isha_review import rate_topic
    app, job, cand, _ = context(att)
    got = rate_topic(att, area, company_id=job.company_id if job else None, use_ai=request.args.get("ai", "1") != "0")
    db.session.commit()
    return ok({"score": got, "state": _state(att)})


@bp.post("/<int:att_id>/topic-rating")
@auth_required
def topic_rating(att_id):
    """The interviewer's own 1-5 rating for a topic, with one click (or null to clear it). Optional: Isha's
    suggestion stands when nobody rates."""
    att = load(att_id)
    if not att or att.status in ("completed", "reviewed", "voided", "cancelled"):
        return err("This interview is closed.", 409)
    d = body()
    area = str(d.get("area") or "")
    if area not in {a["area"] for a in (att.brief or {}).get("areas", [])}:
        return err("Choose a question from the plan.")
    score = d.get("score")
    if score not in (None, ""):
        try:
            score = int(score)
        except (TypeError, ValueError):
            return err("A rating is from 1 to 5.")
        if not 1 <= score <= 5:
            return err("A rating is from 1 to 5.")
    res = dict(att.result or {})
    tr = dict(res.get("topic_ratings") or {})
    if score in (None, ""):
        tr.pop(area, None)
    else:
        tr[area] = score
    res["topic_ratings"] = tr
    att.result = res
    db.session.commit()
    return ok(_state(att))


@bp.post("/<int:att_id>/transcribe")
@auth_required
def transcribe_recording(att_id):
    """Rebuilds the transcript from the interview video with Azure Speech, when the live captions missed it. Runs in
    the background; the room state's `transcribe` says how far it got."""
    att = load(att_id)
    if not att:
        return deny()
    if att.status in ("completed", "reviewed"):
        return err("The scorecard is already submitted.", 409)
    if not ((att.result or {}).get("ended") or att.status == "not_finished"):
        return err("End the interview first: the video is transcribed once it's finished.", 409)
    from services import transcribe
    if not transcribe.available():
        return err("Transcribing the video needs Azure Speech and ffmpeg on the server.", 409)
    if ((att.result or {}).get("transcribe") or {}).get("state") == "running":
        return ok(_state(att))
    res = dict(att.result or {})
    res["transcribe"] = {"state": "running", "done": 0, "total": 0, "at": datetime.utcnow().isoformat() + "Z"}
    att.result = res
    log("isha.transcribe", "attempt", att.id)
    db.session.commit()
    transcribe.start(current_app._get_current_object(), att.id)
    return ok(_state(att))


@bp.post("/<int:att_id>/file-sentence")
@auth_required
def file_sentence(att_id):
    """V02.01.04: during the interview, the interviewer files one of the candidate's sentences under a topic from the
    live transcript. Nothing moves now (nothing is filed live): Isha's end-of-interview review puts it there and keeps
    it there. {text, to} ("" to clear)."""
    att = load(att_id)
    if not att or att.status in ("completed", "reviewed", "voided", "cancelled"):
        return err("This interview is closed.", 409)
    d = body()
    text = str(d.get("text") or "").strip()
    to = str(d.get("to") or "")
    if not text:
        return err("Choose a sentence.")
    from services.isha_review import TOPIC_JD, TOPIC_RESUME, _norm_s
    plan = {a["area"] for a in (att.brief or {}).get("areas", [])}
    if to and to not in plan and to not in ("Small talk", "Not in the plan") and not to.startswith((TOPIC_JD, TOPIC_RESUME)):
        return err("Choose one of the interview's topics.")
    res = dict(att.result or {})
    manual = dict(res.get("manual_filing") or {})
    if to:
        manual[_norm_s(text)] = to
    else:
        manual.pop(_norm_s(text), None)
    res["manual_filing"] = manual
    att.result = res
    db.session.commit()
    return ok(_state(att))
