"""Built-in video call for F2F rounds.

Media flows peer-to-peer (WebRTC). This blueprint is the signalling channel (HTTP long-poll friendly, works behind
any WSGI server), presence, live captions for Isha, focus notices and the optional recording upload.
"""
import os
import time
from datetime import datetime, timedelta

from flask import Blueprint, current_app, g, request, send_file

from extensions import db
from models import CallSignal, IntegrityEvent, RoundAttempt, User
from routes.utils import body, err, ok
from services.audit import log, notify
from services.perms import auth_required, can
from services.pipeline import context, round_name
from services.settings import resolve

bp = Blueprint("call", __name__, url_prefix="/api/call")
KINDS = {"join", "ready", "offer", "answer", "ice", "bye", "chat", "caption", "focus", "media"}
_seen = {}  # (attempt_id, role) -> last poll time; per-process cache, persisted to the attempt every few seconds


def load(att_id):
    """Returns (attempt, role) for the candidate or the interviewer side, else (None, None)."""
    att = db.session.get(RoundAttempt, att_id)
    if not att or att.round_type not in ("f2f_isha", "f2f_human"):
        return None, None
    app, job, cand, _ = context(att)
    if cand and cand.id == g.user.id:
        return att, "candidate"
    if g.user.kind == "staff" or g.user.is_superadmin:
        if g.user.is_superadmin or att.interviewer_id == g.user.id or (job and can(g.user, "interviews.run", job=job)):
            return att, "interviewer"
    return None, None


def _ice(job):
    stun, _, _ = resolve("call.stun_urls", company_id=job.company_id)
    servers = [{"urls": u} for u in (stun or [])]
    turn = resolve("call.turn_url", company_id=job.company_id)[0]
    if turn:
        servers.append({"urls": turn, "username": resolve("call.turn_username", company_id=job.company_id)[0],
                        "credential": resolve("call.turn_credential", company_id=job.company_id)[0]})
    return servers


def _touch(att, role):
    now = time.time()
    key = (att.id, role)
    if now - _seen.get(key, 0) > 4:
        _seen[key] = now
        res = dict(att.result or {})
        call = dict(res.get("call") or {})
        call[f"{role}_seen"] = now
        call.setdefault(f"{role}_first", now)
        res["call"] = call
        att.result = res
        db.session.commit()


def _online(att, role):
    t = max(_seen.get((att.id, role), 0), ((att.result or {}).get("call") or {}).get(f"{role}_seen", 0))
    return time.time() - t < 12


@bp.get("/<int:att_id>")
@auth_required
def info(att_id):
    att, role = load(att_id)
    if not att:
        return err("This call isn't yours.", 403)
    app, job, cand, profile = context(att)
    cfg = att.config or {}
    iv = db.session.get(User, att.interviewer_id) if att.interviewer_id else None
    early = int(cfg.get("call.join_early_minutes", 15) or 0)
    can_join = True
    opens_at = None
    if role == "candidate" and early and att.scheduled_at:
        opens = att.scheduled_at - timedelta(minutes=early)
        can_join = datetime.utcnow() >= opens
        opens_at = opens.isoformat() + "Z"
    last = db.session.query(db.func.max(CallSignal.id)).filter(CallSignal.attempt_id == att.id).scalar() or 0
    _touch(att, role)
    rec = (att.result or {}).get("recording")
    return ok({"attempt_id": att.id, "role": role, "status": att.status, "round": round_name(att, job), "job": job.title,
               "company": None if job.client_hidden else None, "candidate": cand.name if cand else "",
               "interviewer": iv.name if iv else "", "scheduled_at": att.scheduled_at.isoformat() + "Z" if att.scheduled_at else None,
               "can_join": can_join and att.status not in ("completed", "reviewed", "expired"), "opens_at": opens_at,
               "enabled": cfg.get("call.enabled", True), "captions": cfg.get("call.captions", True), "record": cfg.get("call.record", True),
               "screen_share": cfg.get("call.screen_share", True), "chat": cfg.get("call.chat", True),
               "watch_focus": cfg.get("call.watch_focus", True), "language": cfg.get("ai.language", "English"),
               "ice_servers": _ice(job), "cursor": last, "peer_online": _online(att, "interviewer" if role == "candidate" else "candidate"),
               "has_recording": bool(rec)})


@bp.post("/<int:att_id>/signal")
@auth_required
def send(att_id):
    att, role = load(att_id)
    if not att:
        return err("This call isn't yours.", 403)
    d = body()
    kind = d.get("kind")
    if kind not in KINDS:
        return err("Unknown signal.")
    if att.status in ("completed", "reviewed", "expired") and kind not in ("bye",):
        return err("This interview has ended.", 409)
    payload = d.get("payload") or {}
    if kind == "caption" and role != "candidate":
        return err("Only the candidate's side sends captions.", 403)
    if kind in ("chat", "caption"):
        payload = {"text": str(payload.get("text", ""))[:2000]}
    db.session.add(CallSignal(attempt_id=att.id, sender=role, kind=kind, payload=payload))
    if kind == "focus" and role == "candidate" and payload.get("visible") is False:
        db.session.add(IntegrityEvent(attempt_id=att.id, event_type="tab_switch", severity="low", counted=False,
                                      note="Left the call tab during the live interview"))
    if kind == "join":
        log("call.join", "attempt", att.id, role=role)
        if role == "candidate" and att.interviewer_id and not _online(att, "interviewer"):
            notify(att.interviewer_id, "Your candidate is waiting", f"{round_name(att, None)}: the candidate joined the call.",
                   f"/app/isha/{att.id}")
    db.session.commit()
    _touch(att, role)
    return ok({"sent": True})


@bp.get("/<int:att_id>/signal")
@auth_required
def poll(att_id):
    """Signals from the other side after ?after=<id>. Waits up to ~8 seconds for something new (long poll)."""
    att, role = load(att_id)
    if not att:
        return err("This call isn't yours.", 403)
    after = int(request.args.get("after") or 0)
    wait = min(8.0, float(request.args.get("wait") or 0))
    other = "interviewer" if role == "candidate" else "candidate"
    deadline = time.time() + wait
    while True:
        rows = (CallSignal.query.filter(CallSignal.attempt_id == att.id, CallSignal.id > after, CallSignal.sender == other)
                .order_by(CallSignal.id).limit(200).all())
        if rows or time.time() >= deadline:
            break
        db.session.remove()
        time.sleep(0.4)
        att = db.session.get(RoundAttempt, att_id)
    _touch(att, role)
    cursor = max([r.id for r in rows] + [after])
    if not rows:  # move the cursor past our own signals too so it never stalls
        cursor = max(cursor, after)
    return ok({"signals": [{"id": r.id, "kind": r.kind, "payload": r.payload, "at": r.created_at.isoformat() + "Z"} for r in rows],
               "cursor": cursor, "peer_online": _online(att, other), "status": att.status})


@bp.get("/<int:att_id>/chat")
@auth_required
def chat_history(att_id):
    att, role = load(att_id)
    if not att:
        return err("This call isn't yours.", 403)
    rows = CallSignal.query.filter_by(attempt_id=att.id, kind="chat").order_by(CallSignal.id).all()
    return ok([{"id": r.id, "from": r.sender, "text": r.payload.get("text"), "at": r.created_at.isoformat() + "Z"} for r in rows])


@bp.post("/<int:att_id>/recording")
@auth_required
def upload_recording(att_id):
    att, role = load(att_id)
    if not att or role != "interviewer":
        return err("Only the interviewer's side uploads the recording.", 403)
    if not (att.config or {}).get("call.record", True):
        return err("Recording is switched off for this round.", 403)
    f = request.files.get("file")
    if not f:
        return err("No recording received.")
    folder = os.path.join(current_app.config["UPLOAD_DIR"], "recordings")
    os.makedirs(folder, exist_ok=True)
    part = int(request.form.get("part", 0))
    path = os.path.join(folder, f"attempt-{att.id}-{part}.webm")
    f.save(path)
    res = dict(att.result or {})
    parts = list(res.get("recording", []))
    parts.append({"file": os.path.basename(path), "bytes": os.path.getsize(path), "at": datetime.utcnow().isoformat() + "Z",
                  "seconds": float(request.form.get("seconds") or 0)})
    res["recording"] = parts
    att.result = res
    log("call.recording", "attempt", att.id, bytes=parts[-1]["bytes"])
    db.session.commit()
    return ok({"parts": len(parts)})


@bp.get("/<int:att_id>/recording/<int:part>")
@auth_required
def get_recording(att_id, part):
    att, role = load(att_id)
    if not att or role != "interviewer":
        app, job, _, _ = context(att) if att else (None, None, None, None)
        if not (att and job and can(g.user, "reports.view", job=job)):
            return err("You can't watch this recording.", 403)
    parts = (att.result or {}).get("recording") or []
    if part >= len(parts):
        return err("Not found", 404)
    log("call.recording.view", "attempt", att.id, part=part)
    db.session.commit()
    return send_file(os.path.join(current_app.config["UPLOAD_DIR"], "recordings", parts[part]["file"]), mimetype="video/webm",
                     conditional=True)
