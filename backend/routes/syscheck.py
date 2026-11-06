"""System check and candidate instructions (V02.00.05).

GET  /api/syscheck/requirements?attempt=&role=&mode=   which steps this round needs, plus the instructions
POST /api/syscheck                                     save one run; returns passed / failed steps
POST /api/syscheck/help                                "I need help": tells the recruiter which step failed
POST /api/syscheck/upload-test                         a 3-second test video, to prove recording reaches us
GET  /api/syscheck/ping?bytes=  POST /api/syscheck/ping internet speed test (download / upload)
GET  /api/syscheck/instructions/<att>/pdf              the instructions as a PDF
"""
import os

from flask import Blueprint, Response, current_app, g, request

from extensions import db
from models import RoundAttempt, SystemCheck
from routes.utils import body, err, ok
from services import syscheck as S
from services.audit import log, notify, notify_roles
from services.perms import auth_required, deny
from services.pipeline import context

bp = Blueprint("syscheck", __name__, url_prefix="/api/syscheck")
MAX_TEST_VIDEO = 3 * 1024 * 1024
MAX_PING = 2 * 1024 * 1024


def _ua():
    return (request.headers.get("User-Agent") or "")[:400]


def _load(att_id, role):
    """The attempt, if this person may run the check for it in this role."""
    if not att_id:
        return None, None
    att = db.session.get(RoundAttempt, int(att_id)) if str(att_id).isdigit() else None
    if not att:
        return None, err("Round not found.", 404)
    if role == "interviewer":
        from routes.isha import load as isha_load
        return (att, None) if isha_load(att.id) else (None, deny())
    from routes.rounds import load as round_load
    a, r = round_load(att.id, staff_ok=False)
    return (a, None) if a else (None, deny("This round isn't yours."))


def _role():
    r = (request.args.get("role") or body().get("role") or "candidate").lower()
    return r if r in ("candidate", "interviewer") else "candidate"


@bp.get("/requirements")
@auth_required
def requirements():
    role = _role()
    mode = request.args.get("mode") if request.args.get("mode") in ("full", "recheck", "test") else "full"
    att, problem = _load(request.args.get("attempt"), role)
    if problem:
        return problem
    asked = mode
    mode = S.effective_mode(att, role, mode) if att else mode
    out = {"role": role, "upgraded": asked != mode, "mode": mode if att else "test", "steps": S.required_steps(att, role, mode if att else "full"),
           "mobile": S.is_mobile(_ua()), "mobile_message": S.MOBILE_MESSAGE, "needs": S.needs(att, role),
           "enforced": S.must_check(att) if att and role == "candidate" else False}
    if att and role == "candidate":
        out["instructions"] = S.instructions(att)
    elif role == "interviewer":
        out["guide"] = S.interviewer_guide()
    if att:
        out["passed_recently"] = S.passed_recently(att, role)
    return ok(out)


@bp.post("")
@auth_required
def save():
    d = body()
    role = _role()
    mode = d.get("mode") if d.get("mode") in ("full", "recheck", "test") else "full"
    att, problem = _load(d.get("attempt_id"), role)
    if problem:
        return problem
    if not att:
        mode = "test"
    else:
        mode = S.effective_mode(att, role, mode)
    passed, failed, steps = S.evaluate(att, role, "full" if mode == "test" else mode, d.get("steps") or {}, _ua())
    device = d.get("device") if isinstance(d.get("device"), dict) else {}
    device = {k: (str(v)[:160] if not isinstance(v, (int, float, bool)) else v) for k, v in list(device.items())[:20]}
    if att and role == "candidate" and S.must_check(att) and mode == "full" and not d.get("instructions_read") \
            and not (att.result or {}).get("instructions_read_at"):
        passed, failed = False, failed + ["instructions"]
    c = SystemCheck(attempt_id=att.id if att else None, user_id=g.user.id, role=role, mode=mode, passed=passed, steps=steps,
                    device=device, user_agent=_ua())
    db.session.add(c)
    db.session.flush()
    if att and role == "candidate" and d.get("instructions_read"):
        S.mark_read(att)
    S.attach_to_attempt(c)
    if att and role == "candidate":
        S.set_progress(att, "passed" if passed else "check", failed[0] if failed else None)
    log("syscheck.run", "attempt", att.id if att else None, role=role, mode=mode, passed=passed, failed=failed)
    db.session.commit()
    return ok({"id": c.id, "passed": passed, "failed": failed, "steps": steps})


@bp.post("/help")
@auth_required
def help_request():
    """The candidate can't get past a step. The invite stays valid; the hiring team is told which step failed."""
    d = body()
    role = _role()
    att, problem = _load(d.get("attempt_id"), role)
    if problem:
        return problem
    step = str(d.get("step") or "")[:30]
    if step not in S.STEPS and step not in S.HELP_ONLY:
        return err("Choose the step you need help with.")
    note = str(d.get("note") or "").strip()[:500]
    c = SystemCheck(attempt_id=att.id if att else None, user_id=g.user.id, role=role, mode="help", passed=False,
                    steps=d.get("steps") if isinstance(d.get("steps"), dict) else {}, device={}, user_agent=_ua(),
                    help_step=step, help_note=note)
    db.session.add(c)
    db.session.flush()
    if att:
        S.attach_to_attempt(c)
        if role == "candidate":
            S.set_progress(att, "help", step)
        app, job, cand, _ = context(att)
        label = {**S.STEPS, **S.HELP_ONLY}[step][0]
        if job and role == "candidate":
            title = f"{cand.name if cand else 'A candidate'} needs help with the system check" if step in S.STEPS else \
                f"{cand.name if cand else 'A candidate'} needs help joining their round"
            text = (f"{job.title}: they can't get past “{label}”." if step in S.STEPS else f"{job.title}: they're stuck and asked for help.") + (f" They wrote: “{note}”" if note else "") + " Their invite is still valid."
            link = f"/app/applications/{att.application_id}" if att.application_id else "/app/today"
            notify_roles(job.company_id, ["recruiter", "manager"], title, text, link)
            if att.interviewer_id:
                notify(att.interviewer_id, title, text, link)
    log("syscheck.help", "attempt", att.id if att else None, step=step)
    db.session.commit()
    return ok({"sent": True, "message": "The hiring team has been told. Your invite stays valid, so you can try again any time."})


@bp.post("/progress")
@auth_required
def progress():
    """The candidate's page says where they are (instructions, which check step, passed, joined, stuck), so the
    interviewer isn't left guessing (C2). Throttled by the page to one call per step."""
    d = body()
    att, problem = _load(d.get("attempt_id"), "candidate")
    if problem:
        return problem
    if not att:
        return ok({"saved": False})
    S.set_progress(att, str(d.get("stage") or ""), d.get("step"), d.get("index"), d.get("total"), d.get("note"))
    if d.get("stage") == "stuck":
        log("syscheck.stuck", "attempt", att.id, note=str(d.get("note") or "")[:200])
    db.session.commit()
    return ok({"saved": True})


@bp.post("/upload-test")
@auth_required
def upload_test():
    """Proves a short recording can reach the server. Nothing is kept."""
    f = request.files.get("file")
    if not f:
        return err("No test video arrived.")
    data = f.read(MAX_TEST_VIDEO + 1)
    if len(data) > MAX_TEST_VIDEO:
        return err("The test video is too large.", 413)
    if len(data) < 200:
        return err("The test video was empty. Check that the camera and microphone are on.")
    webm = data[:4] == b"\x1a\x45\xdf\xa3"
    mp4 = data[4:8] == b"ftyp"
    if not (webm or mp4):
        return err("The test video isn't in a format we can record (WebM or MP4).")
    return ok({"bytes": len(data), "format": "webm" if webm else "mp4"})


@bp.get("/ping")
@auth_required
def ping_down():
    try:
        n = max(0, min(MAX_PING, int(request.args.get("bytes") or 0)))
    except ValueError:
        n = 0
    return Response(os.urandom(n), mimetype="application/octet-stream", headers={"Cache-Control": "no-store"})


@bp.post("/ping")
@auth_required
def ping_up():
    size = 0
    stream = request.stream
    while True:
        chunk = stream.read(65536)
        if not chunk:
            break
        size += len(chunk)
        if size > MAX_PING:
            return err("Too much data.", 413)
    return ok({"bytes": size})


@bp.get("/instructions/<int:att_id>/pdf")
@auth_required
def instructions_pdf(att_id):
    att, problem = _load(att_id, "candidate")
    if problem:
        return problem
    from routes.reports import pdf_response
    from services.pdf import instructions_pdf as build
    data = S.instructions(att)
    return pdf_response(build(data, current_app.config.get("APP_VERSION", "")), f"Instructions {data['title']}")
