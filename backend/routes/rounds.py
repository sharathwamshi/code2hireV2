"""The candidate's assessment rooms: MCQ, AI voice interview with Hira, integrity events, consent, pause and resume."""
import random
from datetime import datetime

from flask import Blueprint, g

from extensions import db
from models import Application, IntegrityEvent, Job, Question, Report, RoundAttempt, Turn, User
from routes.utils import body, err, ok
from services import ai
from services.audit import log, notify
from services.perms import auth_required, can, deny
from services.pipeline import apply_pass_rules, context, issue_credential, make_report, round_name
from services.settings import resolve

bp = Blueprint("rounds", __name__, url_prefix="/api/rounds")

COUNTED = {"tab_switch", "fullscreen_exit", "devtools", "copy_paste", "multi_face", "no_face", "paste", "screen_share_stop"}
NOTICE_ONLY = {"window_blur", "disconnect", "reconnect", "noise"}
SEVERITY = {"multi_face": "high", "devtools": "high", "tab_switch": "medium", "fullscreen_exit": "medium",
            "copy_paste": "medium", "paste": "medium", "no_face": "medium", "window_blur": "low", "disconnect": "low"}
LABELS = {"tab_switch": "Switched tab or app", "fullscreen_exit": "Left fullscreen", "devtools": "Developer tools opened",
          "copy_paste": "Tried to copy or paste", "paste": "Tried to paste", "multi_face": "More than one person in view",
          "no_face": "No face in view", "window_blur": "Window lost focus", "disconnect": "Connection dropped",
          "screen_share_stop": "Stopped screen sharing"}


def load(att_id, staff_ok=True):
    """Returns (attempt, role) where role is 'candidate' | 'staff' | None."""
    att = db.session.get(RoundAttempt, att_id)
    if not att:
        return None, None
    app, job, cand, _ = context(att)
    if cand and cand.id == g.user.id:
        return att, "candidate"
    if staff_ok and (g.user.kind == "staff" or g.user.is_superadmin):
        if g.user.is_superadmin or (job and (can(g.user, "candidates.view", job=job) or att.interviewer_id == g.user.id)):
            return att, "staff"
    return None, None


def public_attempt(att, role):
    app, job, cand, profile = context(att)
    cfg = att.config or {}
    res = att.result or {}
    d = {"id": att.id, "type": att.round_type, "status": att.status, "name": round_name(att, job),
         "job": job.title if job else (cfg.get("title") or "Practice"), "company": None,
         "config": {k: v for k, v in cfg.items() if not k.startswith("pass.")} if role == "candidate" else cfg,
         "warnings": att.warnings, "warnings_allowed": cfg.get("integrity.warnings_allowed", 2),
         "consented": bool(att.consent_at), "voice": att.voice, "pause_reason": att.pause_reason,
         "deadline_at": att.deadline_at.isoformat() + "Z" if att.deadline_at else None,
         "started_at": att.started_at.isoformat() + "Z" if att.started_at else None,
         "practice": bool(att.practice_user_id), "cert": bool(att.cert_attempt_id),
         "candidate": cand.name if cand else None, "score": att.score if role == "staff" or att.practice_user_id else None}
    if job:
        from models import Company
        c = db.session.get(Company, job.company_id)
        d["company"] = None if job.client_hidden else (c.name if c else None)
        d["branding"] = (c.branding or {}) if c else {}
    if att.round_type == "mcq" and att.status in ("in_progress", "paused"):
        d["questions"] = _mcq_public(att)
        d["answers"] = res.get("answers", {})
        d["flagged"] = res.get("flagged", [])
    if att.round_type == "ai_interview" and att.status in ("in_progress", "paused"):
        d["current"] = res.get("current")
        d["progress"] = {"done": res.get("main_done", 0), "total": len(res.get("plan", []))}
    if att.status in ("completed", "reviewed") and (att.practice_user_id or role == "staff"):
        r = Report.query.filter_by(attempt_id=att.id).first()
        d["report_id"] = r.id if r else None
        if att.practice_user_id and r:
            d["practice_report"] = r.sections
    return d


@bp.get("/<int:att_id>")
@auth_required
def get_attempt(att_id):
    att, role = load(att_id)
    if not att:
        return deny("This assessment isn't yours.")
    if att.deadline_at and att.deadline_at < datetime.utcnow() and att.status in ("invited", "scheduled"):
        att.status = "expired"
        db.session.commit()
    d = public_attempt(att, role)
    if att.round_type == "ai_interview":
        allowed = (att.config or {}).get("voice.allowed") or []
        d["voices"] = allowed
    return ok(d)


@bp.post("/<int:att_id>/consent")
@auth_required
def consent(att_id):
    att, role = load(att_id, staff_ok=False)
    if not att:
        return deny()
    d = body()
    att.consent_at = datetime.utcnow()
    cfg = att.config or {}
    v = d.get("voice")
    if v and cfg.get("voice.candidate_can_choose", True) and (not cfg.get("voice.allowed") or v in cfg["voice.allowed"]):
        att.voice = v
    else:
        att.voice = att.voice or cfg.get("voice.name")
    log("round.consent", "attempt", att.id, checks=d.get("checks"))
    db.session.commit()
    return ok(public_attempt(att, role))


# ---------------------------------------------------------------- MCQ

def _mcq_public(att):
    ids = (att.result or {}).get("question_ids", [])
    qs = {q.id: q for q in Question.query.filter(Question.id.in_(ids or [0])).all()}
    out = []
    for i in ids:
        q = qs.get(i)
        if q:
            out.append({"id": q.id, "skill": q.skill, "level": q.level, "text": q.text, "code": q.code, "options": q.options})
    return out


def _pick_questions(att, job, n):
    skills = [s["name"] if isinstance(s, dict) else s for s in (job.skills if job else [])] or (att.config or {}).get("skills", [])
    level = (att.config or {}).get("level")
    company_id = job.company_id if job else None
    pool = Question.query.filter(Question.status == "approved",
                                 (Question.company_id == company_id) | (Question.company_id.is_(None)))
    if skills:
        pool = pool.filter(Question.skill.in_(skills))
    if level:
        pool = pool.filter(Question.level >= max(1, int(level) - 1), Question.level <= int(level) + 1)
    qs = pool.all()
    if len(qs) < n:
        gen = ai.generate_mcq(skills or ["General aptitude"], int(level or 3), n - len(qs), company_id=company_id)
        for x in gen:
            q = Question(company_id=company_id, skill=x.get("skill") or (skills[0] if skills else "General"), level=x.get("level", 3),
                         text=x["text"], code=x.get("code") or None, options=x["options"][:4], answer=int(x.get("answer", 0)),
                         explanation=x.get("explanation"), status="approved", source="ai")
            db.session.add(q)
            qs.append(q)
        db.session.flush()
    random.shuffle(qs)
    return [q.id for q in qs[:n]]


@bp.post("/<int:att_id>/start")
@auth_required
def start(att_id):
    att, role = load(att_id, staff_ok=False)
    if not att:
        return deny()
    if att.status in ("completed", "reviewed", "expired"):
        return err("This assessment is already closed.")
    if att.status == "paused":
        return err("This assessment is paused. The recruiter has been told and will let you continue.", 409)
    if not att.consent_at:
        return err("Please complete the checks and consent first.")
    app, job, cand, profile = context(att)
    cfg = att.config or {}
    res = dict(att.result or {})
    if att.status != "in_progress":
        att.status = "in_progress"
        att.started_at = datetime.utcnow()
        if app:
            app.stage = "in_round"
        if att.round_type == "mcq":
            ids = _pick_questions(att, job, int(cfg.get("mcq.questions", 10)))
            if not cfg.get("mcq.randomise", True):
                ids.sort()
            res.update({"question_ids": ids, "answers": {}, "flagged": []})
        elif att.round_type == "ai_interview":
            plan_job = job or _practice_job(cfg)
            plan = ai.interview_plan(plan_job, profile.resume_text if profile else "", int(cfg.get("interview.questions", 5)),
                                     cfg.get("interview.difficulty", "medium"), company_id=job.company_id if job else None)
            res.update({"plan": plan["questions"], "main_done": 0, "followups": 0, "qa": []})
            first = plan["questions"][0]
            res["current"] = {"q": first["q"], "topic": first.get("topic"), "kind": "main", "index": 0}
            db.session.add(Turn(attempt_id=att.id, seq=0, speaker="ai", text=first["q"], topic=first.get("topic"), at_seconds=0))
        att.result = res
        log("round.start", "attempt", att.id, company_id=job.company_id if job else None)
        db.session.commit()
    return ok(public_attempt(att, role))


def _practice_job(cfg):
    skills = [{"name": s, "level": cfg.get("level", 3), "must": True} for s in cfg.get("skills", [])] or [{"name": "Communication", "level": 3}]
    return Job(title=cfg.get("title") or "Practice interview", level=cfg.get("role_level", "Mid"), skills=skills, plan={}, company_id=0)


def _elapsed_ok(att, minutes_key):
    mins = (att.config or {}).get(minutes_key)
    if not mins or not att.started_at:
        return True
    return (datetime.utcnow() - att.started_at).total_seconds() <= mins * 60 + 90  # grace for network lag


@bp.post("/<int:att_id>/answer")
@auth_required
def mcq_answer(att_id):
    att, _ = load(att_id, staff_ok=False)
    if not att or att.round_type != "mcq":
        return deny()
    if att.status != "in_progress":
        return err("This assessment is not running." if att.status != "paused" else "Paused. Wait for the recruiter.", 409)
    if not _elapsed_ok(att, "mcq.minutes"):
        return _mcq_finish(att, reason="time")
    d = body()
    res = dict(att.result or {})
    answers = dict(res.get("answers", {}))
    if "choice" in d:
        answers[str(d["qid"])] = d["choice"]
    flagged = set(res.get("flagged", []))
    if "flagged" in d:
        (flagged.add if d["flagged"] else flagged.discard)(int(d["qid"]))
    res["answers"], res["flagged"] = answers, sorted(flagged)
    att.result = res
    db.session.commit()
    return ok({"saved": True, "answered": len(answers)})


@bp.post("/<int:att_id>/submit")
@auth_required
def mcq_submit(att_id):
    att, _ = load(att_id, staff_ok=False)
    if not att or att.round_type != "mcq":
        return deny()
    if att.status not in ("in_progress",):
        return err("This assessment is not running.", 409)
    return _mcq_finish(att, reason=body().get("reason", "submitted"))


def _mcq_finish(att, reason="submitted"):
    res = dict(att.result or {})
    ids = res.get("question_ids", [])
    answers = res.get("answers", {})
    qs = {q.id: q for q in Question.query.filter(Question.id.in_(ids or [0])).all()}
    neg = (att.config or {}).get("mcq.negative_marking")
    correct = wrong = 0
    per_skill, rows = {}, []
    for i in ids:
        q = qs.get(i)
        if not q:
            continue
        a = answers.get(str(i))
        ok_ = a is not None and int(a) == q.answer
        correct += ok_
        wrong += (a is not None and not ok_)
        s = per_skill.setdefault(q.skill, [0, 0])
        s[0] += ok_
        s[1] += 1
        rows.append({"q": q.text, "skill": q.skill, "chosen": a, "answer": q.answer, "correct": ok_,
                     "options": q.options, "explanation": q.explanation})
    raw = correct - (0.25 * wrong if neg else 0)
    pct = round(max(0, raw) * 100 / max(1, len(ids)), 1)
    att.score = pct
    att.status = "completed"
    att.completed_at = datetime.utcnow()
    res["finished_reason"] = reason
    att.result = res
    skills = [{"name": k, "score": round(v[0] * 5 / max(1, v[1]), 1), "correct": v[0], "of": v[1],
               "level": "Strong" if v[0] / max(1, v[1]) >= .8 else ("Meets" if v[0] / max(1, v[1]) >= .5 else "Weak")}
              for k, v in per_skill.items()]
    rec = "proceed" if pct >= 70 else ("hold" if pct >= 40 else "reject")
    sections = {"summary": f"Scored {pct}% ({correct} of {len(ids)} correct" + (", negative marking on" if neg else "") + ").",
                "competencies": [{"name": s["name"], "score": s["score"], "level": s["level"],
                                  "evidence": f"{s['correct']} of {s['of']} correct", "weight": 1} for s in skills],
                "questions": rows, "strengths": [s["name"] for s in skills if s["level"] == "Strong"],
                "gaps": [s["name"] for s in skills if s["level"] == "Weak"], "integrity": _integrity_summary(att),
                "finished_reason": reason, "kind": "mcq"}
    make_report(att, sections, round(pct / 20, 1), rec, "high")
    outcome = _after_round(att)
    db.session.commit()
    return ok({"done": True, "score": pct if att.practice_user_id or (att.config or {}).get("skill_check") else None,
               "outcome": outcome})


def _after_round(att):
    cfg = att.config or {}
    if att.cert_attempt_id:
        from routes.certs import on_section_done
        return on_section_done(att)
    if cfg.get("skill_check"):
        pct = att.score if att.round_type == "mcq" else (att.score or 0) * 20
        if pct >= cfg.get("pass_pct", 70) and att.warnings <= cfg.get("integrity.warnings_allowed", 2):
            issue_credential(att.practice_user_id, "badge", f"{cfg['skills'][0]} L{cfg.get('level', 2)}", cfg["skills"][0],
                             int(cfg.get("level", 2)), months=24)
            return "badge"
        return "not_yet"
    if att.practice_user_id:
        return "practice"
    out = apply_pass_rules(att)
    app, job, cand, _ = context(att)
    if cand:
        notify(cand.id, "Thanks, your round is complete", f"{round_name(att, job)} for {job.title}. We'll be in touch.", "/me/applications")
    return out


def _integrity_summary(att):
    evs = IntegrityEvent.query.filter_by(attempt_id=att.id).order_by(IntegrityEvent.created_at).all()
    return {"warnings": att.warnings, "events": [{"type": e.event_type, "label": LABELS.get(e.event_type, e.event_type),
                                                 "severity": e.severity, "counted": e.counted, "q": e.question_index,
                                                 "at": e.created_at.isoformat() + "Z"} for e in evs],
            "level": "clean" if att.warnings == 0 else ("minor" if att.warnings < 2 else "review")}


# ---------------------------------------------------------------- AI interview with Hira

@bp.post("/<int:att_id>/turn")
@auth_required
def interview_turn(att_id):
    """Candidate finished speaking. Save the answer; Hira decides on a follow-up or the next question."""
    att, _ = load(att_id, staff_ok=False)
    if not att or att.round_type != "ai_interview":
        return deny()
    if att.status != "in_progress":
        return err("Paused. Wait for the recruiter." if att.status == "paused" else "This interview is not running.", 409)
    d = body()
    answer = (d.get("answer") or "").strip()
    res = dict(att.result or {})
    cur = res.get("current")
    if not cur:
        return err("No question is waiting for an answer.")
    secs = int((datetime.utcnow() - att.started_at).total_seconds()) if att.started_at else 0
    seq = Turn.query.filter_by(attempt_id=att.id).count()
    db.session.add(Turn(attempt_id=att.id, seq=seq, speaker="candidate", text=answer or "(no answer)", topic=cur.get("topic"),
                        at_seconds=secs))
    qa = list(res.get("qa", []))
    qa.append({"q": cur["q"], "a": answer, "topic": cur.get("topic"), "at": f"{secs // 60:02d}:{secs % 60:02d}", "kind": cur["kind"]})
    res["qa"] = qa
    cfg = att.config or {}
    plan = res.get("plan", [])
    depth = int(cfg.get("interview.followup_depth", 1))
    out_of_time = not _elapsed_ok(att, "interview.minutes")
    nxt = None
    if not out_of_time and not d.get("skip") and cur["kind"] == "main" and depth > 0 and answer:
        fu = ai.followup(cur["q"], answer, cur.get("topic"))
        if fu.get("ask") and fu.get("q"):
            nxt = {"q": fu["q"], "topic": cur.get("topic"), "kind": "followup", "index": cur["index"], "depth": 1}
    elif not out_of_time and cur["kind"] == "followup" and cur.get("depth", 1) < depth and answer:
        fu = ai.followup(cur["q"], answer, cur.get("topic"))
        if fu.get("ask") and fu.get("q"):
            nxt = {"q": fu["q"], "topic": cur.get("topic"), "kind": "followup", "index": cur["index"], "depth": cur.get("depth", 1) + 1}
    if not nxt:
        res["main_done"] = cur["index"] + 1
        if cur["index"] + 1 < len(plan) and not out_of_time:
            p = plan[cur["index"] + 1]
            nxt = {"q": p["q"], "topic": p.get("topic"), "kind": "main", "index": cur["index"] + 1}
    res["current"] = nxt
    att.result = res
    if nxt:
        db.session.add(Turn(attempt_id=att.id, seq=seq + 1, speaker="ai", text=nxt["q"], topic=nxt.get("topic"), at_seconds=secs))
        db.session.commit()
        return ok({"next": nxt, "done": False, "progress": {"done": res["main_done"], "total": len(plan)}})
    db.session.commit()
    return _interview_finish(att, "time" if out_of_time else "completed")


@bp.post("/<int:att_id>/finish")
@auth_required
def interview_finish(att_id):
    att, _ = load(att_id, staff_ok=False)
    if not att or att.round_type != "ai_interview" or att.status != "in_progress":
        return deny()
    return _interview_finish(att, body().get("reason", "ended_early"))


def _interview_finish(att, reason):
    app, job, cand, profile = context(att)
    cfg = att.config or {}
    res = dict(att.result or {})
    qa = [x for x in res.get("qa", [])]
    rjob = job or _practice_job(cfg)
    rep = ai.interview_report(rjob, profile.resume_text if profile else "", qa, rjob.rubric or [],
                              company_id=job.company_id if job else None, round_name=round_name(att, job))
    rep["integrity"] = _integrity_summary(att)
    rep["finished_reason"] = reason
    rep["kind"] = "ai_interview"
    att.score = float(rep.get("overall") or 0)
    att.status = "completed"
    att.completed_at = datetime.utcnow()
    res["current"] = None
    att.result = res
    make_report(att, rep, att.score, rep.get("recommendation", "hold"), rep.get("confidence", "medium"))
    outcome = _after_round(att)
    db.session.commit()
    return ok({"done": True, "outcome": outcome, "next": None})


@bp.get("/<int:att_id>/transcript")
@auth_required
def transcript(att_id):
    att, role = load(att_id)
    if not att or (role == "candidate" and not att.practice_user_id):
        return deny()
    return ok([t.to_dict() for t in Turn.query.filter_by(attempt_id=att.id).order_by(Turn.seq).all()])


# ---------------------------------------------------------------- integrity

@bp.post("/<int:att_id>/integrity")
@auth_required
def integrity(att_id):
    att, _ = load(att_id, staff_ok=False)
    if not att:
        return deny()
    d = body()
    et = d.get("type")
    if et not in COUNTED | NOTICE_ONLY:
        return err("Unknown event.")
    cfg = att.config or {}
    allowed = int(cfg.get("integrity.warnings_allowed", 2))
    instant = set(cfg.get("integrity.instant_pause") or [])
    counted = et in COUNTED and att.status == "in_progress"
    db.session.add(IntegrityEvent(attempt_id=att.id, event_type=et, severity=SEVERITY.get(et, "medium"), counted=counted,
                                  question_index=d.get("question_index"), note=(d.get("note") or "")[:250]))
    paused = False
    if counted:
        att.warnings = (att.warnings or 0) + 1
        if et in instant or att.warnings > allowed:
            att.status = "paused"
            att.pause_reason = LABELS.get(et, et)
            paused = True
            app, job, cand, _ = context(att)
            if job:
                from services.audit import notify_roles
                notify_roles(job.company_id, ["recruiter", "manager"], "Assessment paused",
                             f"{cand.name if cand else 'A candidate'}: {att.pause_reason} ({job.title})", f"/app/reports/{att.id}")
                if att.interviewer_id:
                    notify(att.interviewer_id, "Assessment paused", att.pause_reason, f"/app/interviews/{att.id}")
    log("integrity.event", "attempt", att.id, type=et, counted=counted, paused=paused)
    db.session.commit()
    return ok({"warnings": att.warnings, "allowed": allowed, "counted": counted, "paused": paused,
               "label": LABELS.get(et, et), "status": att.status,
               "message": ("Paused: " + att.pause_reason) if paused else
               (f"Warning {att.warnings} of {allowed}: {LABELS.get(et, et)}" if counted else "Noted. No warning given.")})


@bp.post("/<int:att_id>/resume")
@auth_required
def resume(att_id):
    """A recruiter lets a paused candidate continue (or ends the attempt)."""
    att, role = load(att_id)
    if not att or role != "staff":
        return deny()
    app, job, cand, _ = context(att)
    if job and not can(g.user, "interviews.run", job=job):
        return deny()
    if att.status != "paused":
        return err("This attempt isn't paused.")
    if body().get("end"):
        if att.round_type == "mcq":
            att.status = "in_progress"
            return _mcq_finish(att, "ended_by_recruiter")
        att.status = "in_progress"
        return _interview_finish(att, "ended_by_recruiter")
    att.status = "in_progress"
    att.pause_reason = None
    if body().get("reset_warnings"):
        att.warnings = 0
    if cand:
        notify(cand.id, "You can continue", "The recruiter has let you continue your assessment.", f"/room/{att.id}")
    log("round.resume", "attempt", att.id, company_id=job.company_id if job else None, note=body().get("note"))
    db.session.commit()
    return ok(public_attempt(att, role))


@bp.get("/<int:att_id>/status")
@auth_required
def status(att_id):
    """Light poll so a paused candidate sees when they may continue."""
    att, _ = load(att_id)
    if not att:
        return deny()
    return ok({"status": att.status, "warnings": att.warnings, "pause_reason": att.pause_reason})
