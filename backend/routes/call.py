"""Built-in video call for F2F rounds.

Media flows peer-to-peer (WebRTC). This blueprint is the signalling channel (HTTP long-poll friendly, works behind
any WSGI server), presence, live captions for Isha, focus notices and the optional recording upload.
"""
import time

from flask import Blueprint, g, request

from extensions import db
from models import CallSignal, RoundAttempt, User
from routes.utils import body, err, ok
from services.audit import log, notify
from services.perms import auth_required, can
from services.pipeline import context, join_window, round_name
from services.settings import resolve

bp = Blueprint("call", __name__, url_prefix="/api/call")
KINDS = {"join", "ready", "offer", "answer", "ice", "bye", "chat", "caption", "focus", "media", "device"}  # "integrity" is added by the server
ENDED = ("completed", "reviewed", "expired", "not_finished", "cancelled")
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
    can_join, opens = join_window(att) if role == "candidate" else (True, None)
    opens_at = opens.isoformat() + "Z" if opens else None
    last = db.session.query(db.func.max(CallSignal.id)).filter(CallSignal.attempt_id == att.id).scalar() or 0
    _touch(att, role)
    from routes.recordings import must_record
    return ok({"attempt_id": att.id, "role": role, "status": att.status, "round": round_name(att, job), "job": job.title,
               "company": None if job.client_hidden else None, "candidate": cand.name if cand else "",
               "interviewer": iv.name if iv else "", "scheduled_at": att.scheduled_at.isoformat() + "Z" if att.scheduled_at else None,
               "can_join": can_join and att.status not in ENDED and not (att.result or {}).get("ended"), "opens_at": opens_at,
               "ended": att.status in ENDED or bool((att.result or {}).get("ended")),
               "enabled": cfg.get("call.enabled", True), "captions": cfg.get("call.captions", True), "record": must_record(att),
               "integrity": {k: cfg.get(k) for k in ("integrity.fullscreen", "integrity.face_check", "integrity.block_paste", "integrity.warnings_allowed")},
               "warnings": att.warnings or 0, "recording_declined": bool((att.result or {}).get("recording_declined")),
               "screen_share": cfg.get("call.screen_share", True), "chat": cfg.get("call.chat", True),
               "watch_focus": cfg.get("call.watch_focus", True), "language": cfg.get("ai.language", "English"),
               "ice_servers": _ice(job), "cursor": last, "peer_online": _online(att, "interviewer" if role == "candidate" else "candidate")})


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
    if (att.status in ENDED or (att.result or {}).get("ended")) and kind not in ("bye",):
        return err("This interview has ended.", 409)
    payload = d.get("payload") or {}
    if kind == "caption" and role != "candidate":
        return err("Only the candidate's side sends captions.", 403)
    if kind in ("chat", "caption"):
        payload = {"text": str(payload.get("text", ""))[:2000]}
    if kind == "device":  # the candidate's pre-start check, shown to the interviewer
        payload = {k: payload.get(k) for k in ("cam", "mic", "faces", "level") if k in payload}
    if kind == "bye" and payload.get("ended") and role != "interviewer":
        payload = {}  # only the interviewer's side can end the interview for both
    db.session.add(CallSignal(attempt_id=att.id, sender=role, kind=kind, payload=payload))
    # Tab switches are counted by the candidate's integrity watcher (/rounds/<id>/integrity), not by this notice.
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
               "cursor": cursor, "peer_online": _online(att, other), "status": att.status,
               "ended": att.status in ENDED or bool((att.result or {}).get("ended")), "warnings": att.warnings or 0})


@bp.get("/<int:att_id>/chat")
@auth_required
def chat_history(att_id):
    att, role = load(att_id)
    if not att:
        return err("This call isn't yours.", 403)
    rows = CallSignal.query.filter_by(attempt_id=att.id, kind="chat").order_by(CallSignal.id).all()
    return ok([{"id": r.id, "from": r.sender, "text": r.payload.get("text"), "at": r.created_at.isoformat() + "Z"} for r in rows])


# Recording moved to routes/recordings.py (V02.00.04): chunked uploads from both sides, always on.
