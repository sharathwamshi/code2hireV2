"""Interview videos (NEW-001): every AI interview and every live interview on the built-in call is recorded.

The recording browser uploads a chunk every 10 seconds. Each chunk carries its piece ("segment") and its number
("seq"), so a retried upload is never stored twice and a missing one is asked for again. A crash or a dropped
connection loses at most the chunk that was being recorded.
"""
import secrets
import threading
from datetime import datetime, timedelta

from flask import Blueprint, current_app, g, redirect, request, send_file

from extensions import db
from models import IntegrityEvent, Recording, RoundAttempt
from routes.utils import body, err, ok
from services import storage
from services.audit import log, notify, notify_roles
from services.perms import auth_required, can
from services.pipeline import context, round_name
from services.validate import iso

bp = Blueprint("recordings", __name__, url_prefix="/api/recordings")

RECORDED_TYPES = ("ai_interview", "f2f_isha", "f2f_human")
MAX_CHUNK = 40 * 1024 * 1024  # a 10-second chunk is about 1-2 MB; this only stops abuse
LATE_UPLOAD = timedelta(minutes=30)  # chunks still queued in the browser may arrive after the interview ends
IDLE_FINISH = timedelta(minutes=3)  # a piece with no new chunk for this long is finished by housekeeping
MIMES = {"video/webm", "video/mp4"}


def must_record(att):
    """Job and certification interviews are always recorded. Practice interviews are the candidate's own and are not."""
    return att.round_type in RECORDED_TYPES and not att.practice_user_id


def not_recorded_reason(att):
    if not must_record(att):
        return "Practice interviews are not recorded."
    if att.round_type != "ai_interview" and not (att.config or {}).get("call.enabled", True):
        return "Not recorded: this round used an outside meeting tool."
    if (att.result or {}).get("recording_declined"):
        return "Not recorded: the candidate declined recording, so the interview did not start."
    return None


def _side(att):
    """Which side the signed-in user records for this attempt, or None."""
    app, job, cand, _ = context(att)
    if cand and cand.id == g.user.id:
        return "candidate"
    if att.round_type != "ai_interview" and (g.user.kind == "staff" or g.user.is_superadmin):
        if g.user.is_superadmin or att.interviewer_id == g.user.id or (job and can(g.user, "interviews.run", job=job)):
            return "interviewer"
    return None


def can_watch(att):
    app, job, cand, _ = context(att)
    if g.user.is_superadmin:
        return True  # platform team: support access and disputes
    if g.user.kind != "staff":
        return False  # never candidates
    return att.interviewer_id == g.user.id or bool(job and can(g.user, "reports.view", job=job))


def can_download(att):
    app, job, _, _ = context(att)
    return g.user.is_superadmin or bool(job and can(g.user, "recordings.download", job=job))


@bp.post("/<int:att_id>/chunk")
@auth_required
def chunk(att_id):
    att = db.session.get(RoundAttempt, att_id)
    if not att or not must_record(att):
        return err("This interview isn't recorded.", 404)
    side = _side(att)
    if not side:
        return err("You can't record this interview.", 403)
    open_ = att.status in ("in_progress", "paused") or (
        att.completed_at and datetime.utcnow() - att.completed_at < LATE_UPLOAD) or (att.result or {}).get("ended")
    if not open_:
        return err("This interview isn't running.", 409)
    seg = (request.form.get("segment") or "").strip()
    if not seg or len(seg) > 30 or not seg.replace("-", "").isalnum():
        return err("Missing recording piece.")
    try:
        seq = int(request.form.get("seq", ""))
    except ValueError:
        return err("Missing chunk number.")
    mime = (request.form.get("mime") or "video/webm").split(";")[0].strip()
    if mime not in MIMES:
        return err("Unsupported video format.")
    f = request.files.get("file")
    data = f.read(MAX_CHUNK + 1) if f else b""
    if not data:
        return err("Empty chunk.")
    if len(data) > MAX_CHUNK:
        return err("Chunk too large.", 413)
    rec = Recording.query.filter_by(attempt_id=att.id, segment=seg).first()
    if rec is None:
        if seq != 0:
            return err("Start the piece from chunk 0.", 409, fields={"expected": 0})
        ext = "mp4" if mime == "video/mp4" else "webm"
        try:  # the first chunk arrives when its 10 seconds are over: date the piece from when recording began
            first = min(60.0, max(0.0, float(request.form.get("seconds") or 0)))
        except ValueError:
            first = 0.0
        rec = Recording(attempt_id=att.id, side=side, segment=seg, mime=mime, started_at=datetime.utcnow() - timedelta(seconds=first),
                        raw_key=f"att{att.id}-{side}-{seg}-{secrets.token_hex(4)}-raw.{ext}", next_seq=0, bytes=0)
        db.session.add(rec)
        db.session.flush()
    if rec.side != side:
        return err("This piece belongs to the other side.", 403)
    if rec.status != "recording":
        return ok({"saved": True, "next": rec.next_seq, "finished": True})
    if seq < rec.next_seq:
        return ok({"saved": True, "next": rec.next_seq, "duplicate": True})  # a retry of a chunk we already have
    if seq > rec.next_seq:
        return err("A chunk is missing.", 409, fields={"expected": rec.next_seq})
    rec.bytes = storage.append(rec.raw_key, data)
    rec.next_seq = seq + 1
    rec.last_at = datetime.utcnow()
    try:
        rec.seconds = max(rec.seconds or 0, float(request.form.get("seconds") or 0))
    except ValueError:
        pass
    db.session.commit()
    return ok({"saved": True, "next": rec.next_seq, "seconds": rec.seconds})


@bp.post("/<int:att_id>/finish")
@auth_required
def finish(att_id):
    """The browser has sent every chunk of a piece. The server finishes it in the background."""
    att = db.session.get(RoundAttempt, att_id)
    if not att or not _side(att):
        return err("You can't record this interview.", 403)
    rec = Recording.query.filter_by(attempt_id=att.id, segment=str(body().get("segment") or "")).first()
    if not rec:
        return ok({"finished": False})
    if rec.status == "recording":
        rec.status = "processing"
        db.session.commit()
        start_finishing(rec.id)
    return ok({"finished": True, "status": rec.status})


def start_finishing(rec_id, wait=False):
    app = current_app._get_current_object()

    def work():
        with app.app_context():
            finish_now(rec_id)
            db.session.remove()
    if wait or app.config.get("TESTING"):
        work()
    else:
        threading.Thread(target=work, daemon=True).start()


def finish_now(rec_id):
    rec = db.session.get(Recording, rec_id)
    if not rec or rec.status not in ("processing", "recording"):
        return
    try:
        key, seconds, note = storage.finish(rec.raw_key, rec.mime)
        if not key:
            rec.status, rec.note = "failed", note
        else:
            rec.file_key = key
            rec.seconds = seconds or rec.seconds
            rec.storage = storage.store(key, rec.mime)
            rec.status, rec.note = "ready", note
        rec.raw_key = None if key else rec.raw_key
    except Exception as e:  # noqa: BLE001 - keep the raw file, report the problem
        current_app.logger.exception("finishing recording %s", rec_id)
        rec.status, rec.note = "failed", f"Could not finish the video: {e}"[:250]
    db.session.commit()


def finish_idle():
    """Pieces whose browser stopped sending (crash, closed tab) are finished after a few quiet minutes."""
    cutoff = datetime.utcnow() - IDLE_FINISH
    done = 0
    for rec in Recording.query.filter(Recording.status == "recording", Recording.last_at < cutoff).limit(20).all():
        rec.status = "processing"
        db.session.commit()
        finish_now(rec.id)
        done += 1
    # a piece that started but never got a chunk past 0 bytes
    return done


def _timeline(att, recs):
    """The main side (interviewer for live calls, candidate for AI interviews) with gaps filled from the backup."""
    main = "candidate" if att.round_type == "ai_interview" else "interviewer"
    t0 = att.started_at or min([r.started_at for r in recs if r.started_at] or [datetime.utcnow()])

    def off(d):
        return max(0.0, (d - t0).total_seconds()) if d else 0.0

    def span(r):
        start = off(r.started_at)
        end = start + float(r.seconds or 0) if r.seconds else off(r.last_at or r.started_at)
        return start, max(start, end)

    ready = [r for r in recs if r.status in ("ready", "processing", "recording")]
    mains = sorted([r for r in ready if r.side == main], key=lambda r: r.started_at or t0)
    backups = sorted([r for r in ready if r.side != main], key=lambda r: r.started_at or t0)
    parts, gaps = [], []
    cursor = 0.0
    end_all = max([span(r)[1] for r in ready] or [0.0])

    def fill(a, b):
        """Cover [a, b) with backup pieces where they exist; what's left is a gap."""
        pos = a
        for r in backups:
            s, e = span(r)
            if e <= pos or s >= b:
                continue
            if s > pos + 2:
                gaps.append({"from": round(pos), "to": round(s)})
            parts.append({"id": r.id, "side": r.side, "from": round(max(s, pos), 1), "to": round(min(e, b), 1),
                          "skip": round(max(0, pos - s), 1), "backup": True, "status": r.status})
            pos = min(e, b)
        if b - pos > 2:
            gaps.append({"from": round(pos), "to": round(b)})

    for r in mains:
        s, e = span(r)
        if s > cursor + 2:
            fill(cursor, s)
        parts.append({"id": r.id, "side": r.side, "from": round(s, 1), "to": round(e, 1), "skip": 0, "backup": False, "status": r.status})
        cursor = max(cursor, e)
    if end_all > cursor + 2:
        fill(cursor, end_all)
    return parts, gaps


def summary(att, for_staff=True):
    """What the report shows about the video."""
    recs = Recording.query.filter(Recording.attempt_id == att.id, Recording.status != "deleted").order_by(Recording.id).all()
    deleted = Recording.query.filter_by(attempt_id=att.id, status="deleted").count()
    reason = not_recorded_reason(att)
    if not recs:
        if deleted:
            reason = "The video was deleted under the company's retention policy."
        elif not reason and att.status in ("completed", "reviewed", "not_finished"):
            reason = "No video reached the server for this interview."
        return {"status": "none", "reason": reason, "pieces": [], "parts": [], "gaps": []}
    parts, gaps = _timeline(att, recs)
    t0 = att.started_at or recs[0].started_at
    events = IntegrityEvent.query.filter_by(attempt_id=att.id).order_by(IntegrityEvent.id).all()
    from routes.rounds import LABELS
    markers = [{"at": max(0, round((e.created_at - t0).total_seconds())), "kind": "integrity", "label": LABELS.get(e.event_type, e.event_type),
                "counted": e.counted} for e in events if t0 and e.created_at >= t0]
    res = att.result or {}
    for a in res.get("areas_log", []):  # F2F questions (seconds since start)
        if a.get("q"):
            markers.append({"at": int(a.get("at") or 0), "kind": "question", "label": a["q"][:120]})
    if att.round_type == "ai_interview":  # Hira's questions, from the transcript
        from models import Turn
        for t in Turn.query.filter_by(attempt_id=att.id, speaker="ai").order_by(Turn.seq).all():
            markers.append({"at": int(t.at_seconds or 0), "kind": "question", "label": (t.text or "")[:120]})
    status = "processing" if any(r.status in ("processing", "recording") for r in recs) else (
        "ready" if any(r.status == "ready" for r in recs) else "failed")
    return {"status": status, "reason": None, "gaps": gaps, "parts": parts, "markers": sorted(markers, key=lambda m: m["at"]),
            "can_download": can_download(att) if for_staff else False,
            "pieces": [{"id": r.id, "side": r.side, "status": r.status, "seconds": r.seconds, "bytes": r.bytes,
                        "started_at": iso(r.started_at), "mime": r.mime, "note": r.note} for r in recs]}


@bp.get("/<int:att_id>")
@auth_required
def get_summary(att_id):
    att = db.session.get(RoundAttempt, att_id)
    if not att or not can_watch(att):
        return err("You can't watch this recording.", 403)
    return ok(summary(att))


@bp.get("/<int:att_id>/<int:rec_id>/video")
@auth_required
def video(att_id, rec_id):
    att = db.session.get(RoundAttempt, att_id)
    if not att or not can_watch(att):
        return err("You can't watch this recording.", 403)
    rec = Recording.query.filter_by(id=rec_id, attempt_id=att.id).first()
    if not rec or rec.status == "deleted":
        return err("Not found", 404)
    download = request.args.get("download") == "1"
    if download and not can_download(att):
        return err("Downloading interview videos needs the \"Download interview videos\" permission.", 403)
    if not request.headers.get("Range") or download:  # log each viewing once, not every range request
        log("recording.download" if download else "recording.view", "attempt", att.id, piece=rec.id)
        db.session.commit()
    if rec.storage == "azure" and rec.file_key:
        return redirect(storage.link(rec, download=download))
    key = rec.file_key or rec.raw_key
    path = storage.local_path(key) if key else None
    import os
    if not path or not os.path.exists(path):
        return err("The video file is missing on the server.", 404)
    return send_file(path, mimetype=rec.mime or "video/webm", conditional=True, as_attachment=download,
                     download_name=f"interview-{att.id}-{rec.side}-{rec.id}.{path.rsplit('.', 1)[-1]}")


@bp.post("/<int:att_id>/declined")
@auth_required
def declined(att_id):
    """The candidate said no to recording. The interview can't start; the hiring team is told."""
    att = db.session.get(RoundAttempt, att_id)
    if not att or _side(att) != "candidate":
        return err("This isn't your interview.", 403)
    res = dict(att.result or {})
    if not res.get("recording_declined"):
        res["recording_declined"] = datetime.utcnow().isoformat() + "Z"
        att.result = res
        app, job, cand, _ = context(att)
        if job:
            notify_roles(job.company_id, ["recruiter", "manager"], "Candidate declined recording",
                         f"{cand.name if cand else 'A candidate'} did not agree to {round_name(att, job)} being recorded, so it has not started.",
                         f"/app/jobs/{job.id}")
            if att.interviewer_id:
                notify(att.interviewer_id, "Candidate declined recording", f"{round_name(att, job)} for {job.title} has not started.", "")
        log("recording.declined", "attempt", att.id)
        db.session.commit()
    return ok({"declined": True})


def purge_expired():
    """Delete videos older than the company's retention period (default 180 days)."""
    from services.settings import resolve
    done = 0
    cutoff_min = datetime.utcnow() - timedelta(days=30)
    for rec in Recording.query.filter(Recording.status.in_(("ready", "failed")), Recording.created_at < cutoff_min).limit(200).all():
        att = db.session.get(RoundAttempt, rec.attempt_id)
        _, job, _, _ = context(att) if att else (None, None, None, None)
        days = resolve("recording.retention_days", company_id=job.company_id, team_id=job.team_id, job_id=job.id)[0] if job else 180
        if datetime.utcnow() - rec.created_at >= timedelta(days=int(days)):
            delete_recording(rec, "retention")
            done += 1
    db.session.commit()
    return done


def delete_recording(rec, why):
    storage.delete(rec)
    rec.status, rec.deleted_at, rec.note = "deleted", datetime.utcnow(), f"Deleted ({why})"
    log("recording.delete", "attempt", rec.attempt_id, piece=rec.id, why=why)


def delete_for_candidate(user_id):
    """Used when a candidate's data is erased."""
    from models import Application
    att_ids = [a.id for a in RoundAttempt.query.join(Application, Application.id == RoundAttempt.application_id)
               .filter(Application.candidate_id == user_id).all()]
    for rec in Recording.query.filter(Recording.attempt_id.in_(att_ids or [0]), Recording.status != "deleted").all():
        delete_recording(rec, "candidate data erased")
