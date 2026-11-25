"""V02.01.06: what happens after End, in the background, step by step, so the interviewer's screen never freezes.

The room cuts the call and stops the captions and the recording itself; the server marks the interview ended at once
(with a quick keyword review, so a scorecard can open immediately) and then runs these steps, saving progress in
result.wrapup after each one. The room's "Wrapping up" window shows them as they happen. A failed step says why and
can be retried; nothing is lost if the page is closed or reloaded.
"""
import threading
from datetime import datetime

from flask import current_app

from extensions import db

STEPS = [("transcript", "Isha is reading the transcript"),
         ("scores", "Isha is scoring each answer"),
         ("topics", "Isha is going through the whole conversation"),
         ("competencies", "Isha is rating the competencies"),
         ("decision", "Isha is deciding"),
         ("thanks", "Thank-you to the candidate")]


def _now():
    return datetime.utcnow().isoformat() + "Z"


def _set(att, key=None, state=None, detail=None, items=None, overall=None, **extra):
    res = dict(att.result or {})
    w = dict(res.get("wrapup") or {})
    if key:
        steps = dict(w.get("steps") or {})
        st = dict(steps.get(key) or {})
        if state:
            st["state"] = state
        if detail is not None:
            st["detail"] = detail
        if items is not None:
            st["items"] = items
        steps[key] = st
        w["steps"] = steps
    if overall:
        w["state"] = overall
    w.update(extra)
    res["wrapup"] = w
    att.result = res
    db.session.commit()


def begin(att):
    """Marks the wrap-up as queued (every step to do), before the background work starts."""
    res = dict(att.result or {})
    n = (res.get("wrapup") or {}).get("attempt", 0)
    res["wrapup"] = {"state": "running", "started": _now(), "attempt": n, "steps": {k: {"state": "todo", "label": label} for k, label in STEPS}}
    att.result = res


def run(att_id, use_ai=True):
    from models import RoundAttempt
    from services.candidate_end import thank
    from services.isha_review import consolidate, review as review_all
    from services.pipeline import context
    from services.scorecard import draft as make_draft
    att = db.session.get(RoundAttempt, att_id)
    if not att:
        return None
    app, job, cand, profile = context(att)
    cid = job.company_id if job else None
    failed = []

    def step(key, fn):
        _set(att, key, "doing")
        try:
            detail, items = fn()
            _set(att, key, "done", detail, items)
            return True
        except Exception as e:  # noqa: BLE001 - one step failing never stops the others; it says why and can be retried
            db.session.rollback()
            current_app.logger.exception("wrap-up %s for attempt %s", key, att_id)
            failed.append(key)
            _set(att, key, "failed", f"Couldn't finish: {str(e)[:160]}")
            return False

    def transcript_():
        if (att.result.get("review") or {}).get("source") != "manual":
            review_all(att, company_id=cid, use_ai=use_ai)
        rv = att.result.get("review") or {}
        how = "with Claude" if rv.get("source") == "claude" else "by keywords"
        return f"Read {rv.get('turns', 0)} turns {how}: {rv.get('asked', 0)} of {rv.get('of', 0)} planned questions were asked", None

    def scores_():
        log_ = att.result.get("areas_log") or []
        items = [{"name": e.get("area"), "score": e.get("score")} for e in log_
                 if e.get("type") in (None, "main", "own", "added") and e.get("sentences") and e.get("score") is not None]
        return (f"Scored {len(items)} answer{'s' if len(items) != 1 else ''}" if items else "No answers to score"), items[:12]

    def topics_():
        t = consolidate(att, job, profile, cid, use_ai)
        unplanned = [x for x in t if not x.get("planned")]
        return (f"{len(t)} topic{'s' if len(t) != 1 else ''} discussed" + (f", {len(unplanned)} beyond your plan" if unplanned else "")
                if t else "Nothing beyond small talk"), [{"name": x["topic"], "score": x["score"]} for x in t[:8]]

    def competencies_():
        d = make_draft(att, job, cand.name if cand else "The candidate", use_ai=use_ai)
        res = dict(att.result or {})
        res["draft_scorecard"] = d
        att.result = res
        sc = [c for c in d["competencies"] if c.get("score")]
        return f"{len(sc)} of {len(d['competencies'])} rated", [{"name": c["name"], "score": c.get("score")} for c in d["competencies"]][:10]

    def decision_():
        isha = (att.result.get("draft_scorecard") or {}).get("isha") or {}
        if isha.get("insufficient"):
            return isha.get("reason"), None
        word = {"proceed": "Proceed", "hold": "Hold", "reject": "Do not proceed"}.get(isha.get("recommendation"), "—")
        rk = isha.get("rank")
        items = [{"name": "Confidence", "text": isha.get("confidence")}]
        if rk:
            items.append({"name": "Among this job's candidates", "text": f"{rk['place']} of {rk['of']}"})
        return f"{word} · {isha.get('reason') or ''}".strip(" ·"), items

    def thanks_():
        sent = thank(att)
        return ("Sent to their inbox" + (" and email" if cand and cand.email else "") if sent else "Already sent"), None

    _set(att, overall="running", attempt=((att.result or {}).get("wrapup") or {}).get("attempt", 0) + 1)
    ok_t = step("transcript", transcript_)
    step("scores", scores_) if ok_t else _set(att, "scores", "skipped", "Needs the transcript step")
    step("topics", topics_)
    ok_c = step("competencies", competencies_)
    step("decision", decision_) if ok_c else _set(att, "decision", "skipped", "Needs the competency scores")
    step("thanks", thanks_)
    _set(att, overall="failed" if failed else "done", finished=_now(), failed=failed)
    return att.result.get("wrapup")


def start(app, att_id, use_ai=True):
    """Runs run() in a background thread."""
    def go():
        with app.app_context():
            try:
                run(att_id, use_ai)
            finally:
                db.session.remove()
    t = threading.Thread(target=go, daemon=True, name=f"wrapup-{att_id}")
    t.start()
    return t
