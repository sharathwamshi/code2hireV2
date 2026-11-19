"""The candidate's assessment rooms: MCQ, AI voice interview with Hira, integrity events, consent, pause and resume."""
import threading
import time
from datetime import datetime, timedelta

from flask import Blueprint, current_app, g, request

from extensions import db
from models import Application, IntegrityEvent, Job, Question, Report, RoundAttempt, Turn, User
from routes.utils import body, err, ok
from services import ai
from services.audit import log, notify
from services.perms import auth_required, can, deny
from services.pipeline import apply_pass_rules, context, issue_credential, make_report, round_name
from services.settings import resolve
from services import syscheck as SC

bp = Blueprint("rounds", __name__, url_prefix="/api/rounds")

COUNTED = {"tab_switch", "fullscreen_exit", "devtools", "copy_paste", "multi_face", "no_face", "paste", "screen_share_stop"}
NOTICE_ONLY = {"window_blur", "disconnect", "reconnect", "noise", "face_check_unavailable", "returned"}
MAX_SNAPSHOTS = 8  # per attempt; each is a ~20 KB JPEG of the moment a face warning was raised
SEVERITY = {"multi_face": "high", "devtools": "high", "tab_switch": "medium", "fullscreen_exit": "medium",
            "copy_paste": "medium", "paste": "medium", "no_face": "medium", "window_blur": "low", "disconnect": "low"}
LABELS = {"tab_switch": "Switched tab or app", "fullscreen_exit": "Left fullscreen", "devtools": "Developer tools opened",
          "copy_paste": "Tried to copy or paste", "paste": "Tried to paste", "multi_face": "More than one person in view",
          "no_face": "No face in view", "window_blur": "Window lost focus", "disconnect": "Connection dropped",
          "screen_share_stop": "Stopped screen sharing", "face_check_unavailable": "Face check couldn't run in this browser",
          "returned": "Came back to the round"}


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


def _resume_note(cand):
    """CAN-014 (V02.00.11): which resume Hira will read when the interview starts, so it can be replaced first."""
    from models import CandidateProfile
    from services import resumes
    if not cand:
        return None
    p = CandidateProfile.query.filter_by(user_id=cand.id).first()
    return {"file": resumes.info(resumes.current(cand.id)), "has_text": bool(p and (p.resume_text or "").strip()),
            "chars": len((p.resume_text or "") if p else ""), "updated_at": (p.updated_at.isoformat() + "Z") if p and getattr(p, "updated_at", None) else None}


def _blocked(att):
    """V02.00.05: no phones or tablets, and a passing system check plus "I've read the instructions" before a real round."""
    if SC.is_mobile(request.headers.get("User-Agent")):
        return err(SC.MOBILE_MESSAGE, 403, {"code": "use_laptop"})
    if SC.must_check(att):
        if not SC.passed_recently(att):
            return err("Please finish the system check first. Every step except the internet test must pass.", 409, {"code": "system_check"})
        if not (att.result or {}).get("instructions_read_at"):
            return err("Please read the instructions and tick \u201cI've read the instructions\u201d.", 409, {"code": "instructions"})
    return None


def _must_record(att):
    from routes.recordings import must_record
    return must_record(att)


def public_attempt(att, role):
    app, job, cand, profile = context(att)
    cfg = att.config or {}
    res = att.result or {}
    d = {"id": att.id, "type": att.round_type, "status": att.status, "name": round_name(att, job),
         "retake_attempt_id": ((att.result or {}).get("voided") or {}).get("retake_attempt_id"),
         "job": job.title if job else (cfg.get("title") or "Practice"), "company": None,
         "config": {k: v for k, v in cfg.items() if not k.startswith("pass.")} if role == "candidate" else cfg,
         "warnings": att.warnings or 0, "warnings_allowed": cfg.get("integrity.warnings_allowed", 2),
         "seconds_left": None if time_left(att) is None else max(0, int(time_left(att))),
         "server_now": datetime.utcnow().isoformat() + "Z",
         "consented": bool(att.consent_at), "voice": att.voice, "pause_reason": att.pause_reason,
         "record": _must_record(att), "recording_declined": bool(res.get("recording_declined")),
         "deadline_at": att.deadline_at.isoformat() + "Z" if att.deadline_at else None,
         "started_at": att.started_at.isoformat() + "Z" if att.started_at else None,
         "practice": bool(att.practice_user_id), "cert": bool(att.cert_attempt_id), "has_team": bool(job),
         "paper_pending": not __import__("services.papers", fromlist=["ready"]).ready(att),
         "resume": _resume_note(cand) if role == "candidate" and att.round_type == "ai_interview" and att.status in ("invited", "scheduled") else None,
         "paused_at": (res.get("paused_at") or None),
         "scheduled_at": att.scheduled_at.isoformat() + "Z" if att.scheduled_at else None,
         "check_required": SC.must_check(att), "check_passed": SC.passed_recently(att) if role == "candidate" else None,
         "instructions_read": bool(res.get("instructions_read_at")),
         "had_full_check": SC.had_full(att) if role == "candidate" else None,
         "earlier_open": SC.earlier_open(att),
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
    if att.round_type == "ai_interview" and att.status in ("completed", "reviewed"):
        d["report_state"] = report_progress(att) or "ready"
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
    close_if_overdue(att)
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
    if att.status in ("voided", "cancelled", "expired", "completed", "reviewed"):
        return err("This round is closed.", 409)
    blocked = _blocked(att)
    if blocked:
        return blocked
    d = body()
    att.consent_at = datetime.utcnow()
    cfg = att.config or {}
    v = d.get("voice")
    if v and cfg.get("voice.candidate_can_choose", True) and (not cfg.get("voice.allowed") or v in cfg["voice.allowed"]):
        att.voice = v
    else:
        att.voice = att.voice or cfg.get("voice.name")
    if att.round_type.startswith("f2f"):
        SC.set_progress(att, "joined")
    log("round.consent", "attempt", att.id, checks=d.get("checks"))
    db.session.commit()
    return ok(public_attempt(att, role))


# ---------------------------------------------------------------- MCQ

def _qview(att):
    """The exact question versions this attempt was started with (falls back to the live question for old attempts)."""
    res = att.result or {}
    ids = res.get("question_ids", [])
    snap = res.get("qsnap") or {}
    live = {q.id: q for q in Question.query.filter(Question.id.in_(ids or [0])).all()}
    out = {}
    for i in ids:
        if str(i) in snap:
            out[i] = snap[str(i)]
        elif i in live:
            out[i] = {**live[i].snapshot(), "version": live[i].version or 1}
    return out


def _mcq_public(att):
    view = _qview(att)
    return [{"id": i, "skill": q.get("skill"), "level": q.get("level"), "text": q.get("text"), "code": q.get("code"), "options": q.get("options")}
            for i, q in view.items()]


def _pick_questions(att, job, n, allow_ai=True):
    """See services/mcq.py: no repeats in a test, unseen questions first, no copies saved, shorter test over padding."""
    from services.mcq import pick, shuffle_entry
    qs, info = pick(att, job, n, allow_ai=allow_ai)
    res = dict(att.result or {})
    res["mcq_info"] = info
    # unsaved filler questions (negative ids) exist only in this attempt's snapshot (CD-005, V02.00.08)
    res["pick_snap"] = {str(q.id): shuffle_entry({**q.snapshot(), "version": 1}) for q in qs if (q.id or 0) < 0}
    att.result = res
    return [q.id for q in qs]


@bp.post("/<int:att_id>/start")
@auth_required
def start(att_id):
    att, role = load(att_id, staff_ok=False)
    if not att:
        return deny()
    if att.status in ("completed", "reviewed", "expired", "voided", "cancelled"):
        return err("This round was replaced by a retake. Use the new invite on your home page." if att.status == "voided"
                   else "This invite was cancelled." if att.status == "cancelled" else "This assessment is already closed.")
    if att.status == "paused":
        return err("This assessment is paused. The recruiter has been told and will let you continue.", 409)
    if not att.consent_at:
        return err("Please complete the checks and consent first.")
    from services import papers
    if not papers.ready(att):
        return err("The hiring team is still preparing your test. We'll tell you as soon as you can start.", 409, {"code": "paper_review"})
    blocked = _blocked(att)
    if blocked:
        return blocked
    if (att.result or {}).get("recording_declined") and _must_record(att):
        return err("This interview can't start because recording was declined. The hiring team will contact you.", 409)
    app, job, cand, profile = context(att)
    cfg = att.config or {}
    res = dict(att.result or {})
    if att.status != "in_progress":
        prev_status = att.status
        att.status = "in_progress"
        att.started_at = datetime.utcnow()
        if app:
            app.stage = "in_round"
        if att.round_type == "mcq" and (att.result or {}).get("paper", {}).get("state") == "approved" and (att.result or {}).get("question_ids"):
            # V02.00.11: the paper drawn at invite and approved by the hiring team, exactly as they checked it
            res = dict(att.result or {})
            res.update({"answers": {}, "flagged": []})
        elif att.round_type == "mcq":
            ids = _pick_questions(att, job, int(cfg.get("mcq.questions", 10)))
            if not ids:
                att.status, att.started_at = prev_status, None
                db.session.commit()  # keeps the recruiter's notification
                return err("This assessment has no questions yet. The hiring team has been told; please try again later.", 409)
            res = dict(att.result or {})
            if not cfg.get("mcq.randomise", True):
                ids.sort()
            from services.mcq import shuffled_snap
            # A2 (V02.00.12): every paper gets its own option order, saved with the answer key for that order
            snap = shuffled_snap(Question.query.filter(Question.id.in_([i for i in ids if i > 0] or [0])).all())
            snap.update(res.pop("pick_snap", None) or {})
            res.update({"question_ids": ids, "answers": {}, "flagged": [], "qsnap": snap})
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
    """CP-011 (V02.00.10): the practice "job" is the role the candidate chose, with that role's skills, so every question
    is about the role."""
    skills = [{"name": s, "level": cfg.get("level", 3), "must": True} for s in cfg.get("skills", [])] or [{"name": "Communication", "level": 3}]
    role = cfg.get("role")
    desc = (f"Practice interview for a {role} role. Ask only about {', '.join(s['name'] for s in skills)} as used by a {role}; "
            "never ask about other roles.") if role else ""
    return Job(title=role or cfg.get("title") or "Practice interview", level=cfg.get("role_level", "Mid"), skills=skills, plan={},
               company_id=0, description=desc)


GRACE_S = 90  # network lag allowance after the clock reaches zero


def time_left(att):
    """Seconds left by the SERVER's clock (never the candidate's device), not counting time spent paused by the
    recruiter. None when the round has no time limit or hasn't started."""
    key = "mcq.minutes" if att.round_type == "mcq" else "interview.minutes"
    mins = (att.config or {}).get(key)
    if not mins or not att.started_at:
        return None
    res = att.result or {}
    now = datetime.utcnow()
    paused = float(res.get("paused_total") or 0)
    if att.status == "paused" and res.get("paused_at"):
        try:
            paused += (now - datetime.fromisoformat(res["paused_at"])).total_seconds()
        except ValueError:
            pass
    return float(mins) * 60 - ((now - att.started_at).total_seconds() - paused)


def _elapsed_ok(att, minutes_key=None):
    left = time_left(att)
    return left is None or left > -GRACE_S


def close_if_overdue(att):
    """A round whose time ran out while the candidate's laptop slept or the tab was closed is submitted by the
    server, so it can never stay open past its limit."""
    if att.status != "in_progress" or att.round_type not in ("mcq", "ai_interview"):
        return False
    left = time_left(att)
    if left is None or left > -GRACE_S:
        return False
    if att.round_type == "mcq":
        _mcq_finish(att, "time_up")
    else:
        _interview_finish(att, "time_up")
    return True


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
    qs = _qview(att)
    neg = (att.config or {}).get("mcq.negative_marking")
    correct = wrong = 0
    per_skill, rows = {}, []
    for i in ids:
        q = qs.get(i)
        if not q:
            continue
        a = answers.get(str(i))
        ok_ = a is not None and int(a) == q["answer"]
        correct += ok_
        wrong += (a is not None and not ok_)
        s = per_skill.setdefault(q.get("skill") or "General", [0, 0])
        s[0] += ok_
        s[1] += 1
        rows.append({"q": q["text"], "skill": q.get("skill"), "chosen": a, "answer": q["answer"], "correct": ok_, "qid": i,
                     "version": q.get("version", 1), "options": q.get("options"), "explanation": q.get("explanation")})
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
                                                 "note": e.note, "at": e.created_at.isoformat() + "Z"} for e in evs],
            "snapshots": [{"event": x["event"], "label": LABELS.get(x["event"], x["event"]), "at": x["at"], "image": x["image"]}
                          for x in (att.result or {}).get("snapshots", [])],
            "level": "clean" if not att.warnings else ("minor" if att.warnings < 2 else "review")}


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
    """BUG-002/005/006 (V02.00.09): the interview closes at once and Hira writes the report in the background, so the
    candidate's screen, camera and microphone are released straight away. The Done screen polls /status."""
    res = dict(att.result or {})
    if res.get("report_state") in ("writing", "ready") or Report.query.filter_by(attempt_id=att.id).first():
        return ok({"done": True, "outcome": res.get("outcome"), "next": None, "report": res.get("report_state") or "ready"})
    res["current"] = None
    res["finished_reason"] = reason
    res["report_state"] = "writing"
    res["report_started"] = time.time()
    att.status = "completed"
    att.completed_at = datetime.utcnow()
    att.result = res
    db.session.commit()
    start_report(att.id)
    db.session.refresh(att)
    res = att.result or {}
    return ok({"done": True, "outcome": res.get("outcome"), "next": None, "report": res.get("report_state")})


REPORT_STALE_S = 180  # a report still "writing" after this long is finished with the built-in fallback


def start_report(att_id):
    app = current_app._get_current_object()

    def work():
        with app.app_context():
            try:
                write_report(att_id)
            finally:
                db.session.remove()
    if app.config.get("TESTING"):
        write_report(att_id)
    else:
        threading.Thread(target=work, daemon=True).start()


def write_report(att_id, offline=False):
    """Writes the AI-interview report once. offline=True uses the built-in fallback (no AI call)."""
    att = db.session.get(RoundAttempt, att_id)
    if not att or Report.query.filter_by(attempt_id=att.id).first():
        return
    try:
        app, job, cand, profile = context(att)
        cfg = att.config or {}
        res = dict(att.result or {})
        qa = [x for x in res.get("qa", [])]
        rjob = job or _practice_job(cfg)
        kw = dict(company_id=job.company_id if job else None, round_name=round_name(att, job))
        if offline:
            with ai.offline():
                rep = ai.interview_report(rjob, profile.resume_text if profile else "", qa, rjob.rubric or [], **kw)
        else:
            rep = ai.interview_report(rjob, profile.resume_text if profile else "", qa, rjob.rubric or [], **kw)
        att = db.session.get(RoundAttempt, att_id)
        if Report.query.filter_by(attempt_id=att.id).first():  # another worker finished first
            return
        rep["integrity"] = _integrity_summary(att)
        rep["finished_reason"] = res.get("finished_reason")
        rep["kind"] = "ai_interview"
        att.score = float(rep.get("overall") or 0)
        r = make_report(att, rep, att.score, rep.get("recommendation", "hold"), rep.get("confidence", "medium"))
        if att.application_id and r is not None:  # D1 (V02.00.12): runs in the background, so the candidate view opens at once later
            try:
                r.candidate_feedback = ai.candidate_feedback(rep, company_id=job.company_id if job else None)
            except Exception:  # noqa: BLE001 - written on first view instead
                pass
        outcome = _after_round(att)
        res = dict(att.result or {})
        res["report_state"] = "ready"
        res["outcome"] = outcome
        att.result = res
        db.session.commit()
    except Exception:  # noqa: BLE001 - the next status poll or housekeeping finishes it with the fallback
        db.session.rollback()
        import logging
        logging.getLogger(__name__).exception("report for attempt %s", att_id)
        if not offline:
            write_report(att_id, offline=True)


def report_progress(att):
    """("writing" | "ready" | None). Finishes a report that has been writing too long (worker restarted, AI stuck)."""
    res = att.result or {}
    st = res.get("report_state")
    if st == "writing" and time.time() - float(res.get("report_started") or 0) > REPORT_STALE_S:
        write_report(att.id, offline=True)
        db.session.refresh(att)
        st = (att.result or {}).get("report_state")
    return st


@bp.get("/<int:att_id>/transcript")
@auth_required
def transcript(att_id):
    att, role = load(att_id)
    # CAN-017 (V02.00.11): during a round the candidate sees the conversation so far (only what was said, no analysis)
    live = att is not None and att.status in ("in_progress", "paused")
    if not att or (role == "candidate" and not att.practice_user_id and not live):
        return deny()
    rows = Turn.query.filter_by(attempt_id=att.id).order_by(Turn.seq).all()
    if role == "candidate":
        return ok([{"seq": t.seq, "speaker": t.speaker, "text": t.text} for t in rows])
    return ok([t.to_dict() for t in rows])


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
    # CAN-021 (V02.00.11): practice is a rehearsal. Events are shown to the candidate but never count or pause.
    rehearsal = bool(att.practice_user_id) and not cfg.get("skill_check")
    counted = et in COUNTED and att.status == "in_progress" and not rehearsal
    if et == "returned":  # how long the candidate was away from the round, for the report
        try:
            away = max(0, min(3600, int(float(d.get("seconds") or 0))))
        except (TypeError, ValueError):
            away = 0
        d["note"] = f"Away for {away} s"
        res = dict(att.result or {})
        res["away_seconds"] = int(res.get("away_seconds") or 0) + away
        att.result = res
    ev = IntegrityEvent(attempt_id=att.id, event_type=et, severity=SEVERITY.get(et, "medium"), counted=counted,
                        question_index=d.get("question_index") if isinstance(d.get("question_index"), int) else None,
                        note=(str(d.get("note") or ""))[:250])
    db.session.add(ev)
    snap = d.get("snapshot")
    if et in ("multi_face", "no_face") and isinstance(snap, str) and snap.startswith("data:image/jpeg;base64,") and len(snap) < 120_000:
        res = dict(att.result or {})
        shots = list(res.get("snapshots") or [])
        if len(shots) < MAX_SNAPSHOTS:
            shots.append({"event": et, "at": datetime.utcnow().isoformat() + "Z", "image": snap, "counted": counted})
            res["snapshots"] = shots
            att.result = res
    paused = False
    live = att.round_type in ("f2f_isha", "f2f_human")
    if counted:
        att.warnings = (att.warnings or 0) + 1
    if live:
        # Live interviews: warn and count, never pause on our own; the interviewer sees it at once and decides.
        from models import CallSignal
        db.session.add(CallSignal(attempt_id=att.id, sender="candidate", kind="integrity",
                                  payload={"type": et, "label": LABELS.get(et, et), "counted": counted, "warnings": att.warnings or 0,
                                           "note": (str(d.get("note") or ""))[:120]}))
    elif counted and not job_of(att) and (et in instant or att.warnings > allowed):
        # A skill check or a certification section has no recruiter who could let the candidate continue, so going
        # past the limit ends the attempt (scored as it stands, marked "ended for integrity") instead of a pause
        # that would never end.
        log("integrity.event", "attempt", att.id, type=et, counted=counted, ended=True)
        db.session.commit()
        if att.round_type == "mcq":
            _mcq_finish(att, reason="integrity")
        elif att.round_type == "ai_interview":
            _interview_finish(att, "integrity")
        return ok({"warnings": att.warnings, "allowed": allowed, "counted": True, "paused": False, "ended": True,
                   "label": LABELS.get(et, et), "status": att.status,
                   "message": f"Ended: {LABELS.get(et, et)}. You went past the {allowed} warnings allowed."})
    elif counted:
        if et in instant or att.warnings > allowed:
            att.status = "paused"
            att.pause_reason = LABELS.get(et, et)
            res = dict(att.result or {})
            res["paused_at"] = datetime.utcnow().isoformat()
            att.result = res
            paused = True
            app, job, cand, _ = context(att)
            if job:
                from services.audit import notify_round_team
                notify_round_team(att, job, "Assessment paused",
                                  f"{cand.name if cand else 'A candidate'}: {att.pause_reason} ({job.title})")
    log("integrity.event", "attempt", att.id, type=et, counted=counted, paused=paused)
    db.session.commit()
    return ok({"warnings": att.warnings, "allowed": allowed, "counted": counted, "paused": paused,
               "label": LABELS.get(et, et), "status": att.status,
               "rehearsal": rehearsal,
               "message": (f"Practice: {LABELS.get(et, et)}. In a real round this would count as a warning." if rehearsal and et in COUNTED else
                           ("Paused: " + att.pause_reason) if paused else
               (f"Warning {att.warnings}: {LABELS.get(et, et)}. The interviewer has been told." if counted and live else
                f"Warning {att.warnings} of {allowed}: {LABELS.get(et, et)}" if counted else "Noted. No warning given."))})


def job_of(att):
    _, job, _, _ = context(att)
    return job


def _paper_staff(att_id):
    from services import papers
    att, role = load(att_id)
    if not att or role != "staff" or not papers.applies(att):
        return None, None, deny()
    app, job, cand, _ = context(att)
    if not papers.can_review(g.user, job):  # A1 (V02.00.12): people assigned to the job (interviewers too) can review
        return None, None, deny("You can't review questions on this job.")
    return att, job, None


@bp.get("/<int:att_id>/paper")
@auth_required
def paper_view(att_id):
    """CAN-015 / CAN-016 (V02.00.11): the hiring team sees a candidate's MCQ questions, with answers, before the test."""
    from services import papers
    att, job, e = _paper_staff(att_id)
    if e:
        return e
    return ok(papers.view(att))


@bp.post("/<int:att_id>/paper/<action>")
@auth_required
def paper_change(att_id, action):
    from services import papers
    att, job, e = _paper_staff(att_id)
    if e:
        return e
    if att.status not in ("invited", "scheduled"):
        return err("The candidate has started, so the questions are locked.", 409)
    d = body()
    if action == "swap":
        try:
            problem = papers.swap(att, job, int(d.get("question_id")), g.user.id)
        except (TypeError, ValueError):
            problem = "Choose a question to swap."
    elif action == "redraw":
        problem = papers.redraw(att, job, g.user.id)
    elif action == "approve":
        problem = papers.approve(att, g.user.id, g.user.name)
    elif action == "fill":  # the bank was short: Hira writes the missing questions
        problem = papers.fill(att, job, g.user.id)
    else:
        return err("Unknown action.", 404)
    if problem:
        return err(problem)
    log(f"paper.{action}", "attempt", att.id, company_id=job.company_id)
    db.session.commit()
    return ok(papers.view(att))


@bp.post("/<int:att_id>/nudge")
@auth_required
def nudge(att_id):
    """CAN-022 (V02.00.11): a candidate whose round is paused reminds the hiring team. At most once every 10 minutes."""
    att, role = load(att_id, staff_ok=False)
    if not att or role != "candidate":
        return deny()
    if att.status != "paused":
        return err("This round isn't paused.")
    res = dict(att.result or {})
    last = res.get("nudged_at")
    if last and datetime.utcnow() - datetime.fromisoformat(last) < timedelta(minutes=10):
        return err("You've already told the hiring team. Give them a few minutes.", 429)
    app, job, cand, _ = context(att)
    if not job:
        return err("There's no hiring team for this round.")
    from services.audit import notify_round_team
    notify_round_team(att, job, "A candidate is waiting",
                      f"{cand.name if cand else 'A candidate'} is waiting for you to check their paused round ({job.title}).")
    res["nudged_at"] = datetime.utcnow().isoformat()
    att.result = res
    db.session.commit()
    return ok({"message": "The hiring team has been reminded."})


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
    res = dict(att.result or {})
    if res.get("paused_at"):  # the clock doesn't run while the candidate waits for the recruiter
        try:
            res["paused_total"] = float(res.get("paused_total") or 0) + (datetime.utcnow() - datetime.fromisoformat(res["paused_at"])).total_seconds()
        except ValueError:
            pass
        res.pop("paused_at", None)
        att.result = res
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
    close_if_overdue(att)
    left = time_left(att)
    out = {"status": att.status, "warnings": att.warnings or 0, "pause_reason": att.pause_reason,
           "seconds_left": None if left is None else max(0, int(left)), "server_now": datetime.utcnow().isoformat() + "Z"}
    if att.round_type == "ai_interview" and att.status in ("completed", "reviewed"):  # V02.00.09: background report
        out["report"] = report_progress(att) or "ready"
        res = att.result or {}
        out["outcome"] = res.get("outcome")
        if out["report"] == "ready" and att.practice_user_id:
            r = Report.query.filter_by(attempt_id=att.id).first()
            out["report_id"] = r.id if r else None
            out["practice_report"] = r.sections if r else None
            out["score"] = att.score
    return ok(out)
