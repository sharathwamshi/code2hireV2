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
KINDS = {"join", "ready", "offer", "answer", "ice", "bye", "chat", "caption", "partial", "focus", "media", "device", "devlost",
         "iv_caption"}  # "integrity" is added by the server
ENDED = ("completed", "reviewed", "expired", "not_finished", "cancelled", "voided")
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


def _turn_urls(raw):
    """One TURN address or several, separated by commas, spaces or new lines (V02.00.08)."""
    import re
    out = []
    for u in re.split(r"[\s,;]+", str(raw or "").strip()):
        if re.match(r"^turns?:[A-Za-z0-9.\-\[\]:]+(\?transport=(udp|tcp))?$", u) and u not in out:
            out.append(u)
    return out[:6]


def turn_config(company_id=None):
    """(urls, username, credential, secret). The company's own TURN server (Video call settings) wins; otherwise the
    platform relay set by the superadmin (AI, voice and defaults → Integrations)."""
    from services.settings import platform_secret
    urls = _turn_urls(resolve("call.turn_url", company_id=company_id)[0])
    if urls:
        return urls, resolve("call.turn_username", company_id=company_id)[0], resolve("call.turn_credential", company_id=company_id)[0], ""
    return (_turn_urls(platform_secret("turn_urls")), platform_secret("turn_username"), platform_secret("turn_credential"),
            platform_secret("turn_secret"))


def ice_servers(company_id=None, label="c2h", ttl=8 * 3600):
    """STUN plus TURN. With a shared secret (coturn use-auth-secret) every call gets its own login that expires after
    `ttl` seconds, so no long-lived password ever reaches a browser."""
    import base64
    import hashlib
    import hmac
    stun, _, _ = resolve("call.stun_urls", company_id=company_id)
    servers = [{"urls": u} for u in (stun or [])]
    urls, user, cred, secret = turn_config(company_id)
    if urls:
        if secret:
            user = f"{int(time.time()) + ttl}:{label}"
            cred = base64.b64encode(hmac.new(secret.encode(), user.encode(), hashlib.sha1).digest()).decode()
        servers.append({"urls": urls, "username": user or "", "credential": cred or ""})
    return servers


def _ice(job, att=None):
    return ice_servers(job.company_id if job else None, f"att{att.id}" if att else "c2h")


def _speech_ready():
    """gap 11 (V02.00.07): whether Azure Speech is set up. Without it, captions only work in Chrome and Edge."""
    from services import speech
    try:
        return bool(speech.configured())
    except Exception:  # never break the call over this
        return False


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
               # V02.01.04: for the candidate's thank-you screen
               **({"end": __import__("services.candidate_end", fromlist=["details"]).details(att)} if role == "candidate" else {}),
               "enabled": cfg.get("call.enabled", True), "captions": cfg.get("call.captions", True), "record": must_record(att),
               "azure_speech": _speech_ready(),
               "integrity": {k: cfg.get(k) for k in ("integrity.fullscreen", "integrity.face_check", "integrity.block_paste", "integrity.warnings_allowed")},
               "warnings": att.warnings or 0, "recording_declined": bool((att.result or {}).get("recording_declined")),
               "screen_share": cfg.get("call.screen_share", True), "chat": cfg.get("call.chat", True),
               "watch_focus": cfg.get("call.watch_focus", True), "language": cfg.get("ai.language", "English"),
               "ice_servers": _ice(job, att), "relay": bool(turn_config(job.company_id if job else None)[0]), "cursor": last, "peer_online": _online(att, "interviewer" if role == "candidate" else "candidate")})


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
    if kind in ("caption", "partial") and role != "candidate":
        return err("Only the candidate's side sends captions.", 403)
    if kind in ("chat", "caption"):
        payload = {"text": str(payload.get("text", ""))[:2000]}
    if kind == "partial":  # words still being spoken (V02.00.05, F2F-007): shown grey, replaced by the final caption
        payload = {"text": str(payload.get("text", ""))[:500]}
    if kind == "iv_caption":  # bug 5 (V02.00.07): what the interviewer says, as subtitles the candidate can turn on (CC)
        if role != "interviewer":
            return err("Only the interviewer's side sends these subtitles.", 403)
        payload = {"text": str(payload.get("text", ""))[:500], "final": bool(payload.get("final"))}
    if kind == "devlost":  # the candidate's camera or microphone stopped mid-interview
        payload = {k: bool(payload.get(k)) for k in ("cam", "mic") if k in payload}
    if kind == "device":  # the candidate's pre-start check, shown to the interviewer
        payload = {k: payload.get(k) for k in ("cam", "mic", "faces", "level", "speaker", "captions", "cap_state", "headphones") if k in payload}
    if kind == "bye" and payload.get("ended") and role != "interviewer":
        payload = {}  # only the interviewer's side can end the interview for both
    if kind == "bye":
        payload = {k: bool(payload.get(k)) for k in ("ended", "closed") if payload.get(k)}
    db.session.add(CallSignal(attempt_id=att.id, sender=role, kind=kind, payload=payload))
    # Tab switches are counted by the candidate's integrity watcher (/rounds/<id>/integrity), not by this notice.
    if kind == "join":
        log("call.join", "attempt", att.id, role=role)
        if role == "candidate" and att.interviewer_id and not _online(att, "interviewer"):
            notify(att.interviewer_id, "Your candidate is waiting", f"{round_name(att, None)}: the candidate joined the call.",
                   f"/app/isha/{att.id}")
    if kind == "bye":  # gap 4: leaving (or closing the tab) shows as "left" at once, not after the 12-second presence window
        _seen.pop((att.id, role), None)
        res = dict(att.result or {})
        call = dict(res.get("call") or {})
        if call.get(f"{role}_seen"):
            call[f"{role}_seen"] = 0
            res["call"] = call
            att.result = res
    db.session.commit()
    if kind != "bye":
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


@bp.post("/<int:att_id>/path")
@auth_required
def path(att_id):
    """V02.00.08: how the video actually connected (direct, or through the relay), or that it couldn't connect.
    Kept on the attempt for the interviewer's panel and the report."""
    att, role = load(att_id)
    if not att:
        return err("This call isn't yours.", 403)
    d = body()
    state = d.get("state") if d.get("state") in ("connected", "failed", "retry", "relay_only") else None
    if not state:
        return err("Unknown state.")
    kind = d.get("path") if d.get("path") in ("direct", "relay", "unknown") else "unknown"
    entry = {"role": role, "state": state, "path": kind, "at": int(time.time())}
    for k in ("local", "remote"):
        if d.get(k) in ("host", "srflx", "prflx", "relay"):
            entry[k] = d[k]
    if d.get("protocol") in ("udp", "tcp", "tls"):
        entry["protocol"] = d["protocol"]
    if isinstance(d.get("rtt"), (int, float)):
        entry["rtt"] = round(float(d["rtt"]), 3)
    res = dict(att.result or {})
    call = dict(res.get("call") or {})
    events = list(call.get("path_events") or [])[-40:]
    events.append(entry)
    call["path_events"] = events
    if state == "connected":
        call["path"] = kind
        call["connected_once"] = True
        call.setdefault("first_connected_at", entry["at"])
        if kind == "relay":
            call["used_relay"] = True
    elif state == "failed":
        call["failures"] = int(call.get("failures") or 0) + 1
    res["call"] = call
    att.result = res
    db.session.commit()
    return ok({"saved": True})


def path_summary(att):
    """For the panel and the report: {"connected", "path", "used_relay", "failures", "retries"}."""
    call = (att.result or {}).get("call") or {}
    ev = call.get("path_events") or []
    return {"connected": bool(call.get("connected_once")), "path": call.get("path"), "used_relay": bool(call.get("used_relay")),
            "failures": int(call.get("failures") or 0), "retries": sum(1 for e in ev if e.get("state") in ("retry", "relay_only"))}


@bp.get("/<int:att_id>/chat")
@auth_required
def chat_history(att_id):
    att, role = load(att_id)
    if not att:
        return err("This call isn't yours.", 403)
    rows = CallSignal.query.filter_by(attempt_id=att.id, kind="chat").order_by(CallSignal.id).all()
    return ok([{"id": r.id, "from": r.sender, "text": r.payload.get("text"), "at": r.created_at.isoformat() + "Z"} for r in rows])


# Recording moved to routes/recordings.py (V02.00.04): chunked uploads from both sides, always on.


@bp.post("/<int:att_id>/message-team")
@auth_required
def message_team(att_id):
    """V02.01.04: from the end-of-interview screen, the candidate sends the hiring team a short message."""
    att, role = load(att_id)
    if not att or role != "candidate":
        return err("This call isn't yours.", 403)
    text = str(body().get("text") or "").strip()[:800]
    if len(text) < 2:
        return err("Write your message first.", fields={"text": "Required."})
    app, job, cand, _ = context(att)
    from services.audit import notify_round_team
    notify_round_team(att, job, f"Message from {cand.name if cand else 'a candidate'} after their interview", text)
    log("call.message_team", "attempt", att.id, company_id=job.company_id if job else None)
    db.session.commit()
    return ok({"message": "Sent. The hiring team will reply in your Code2Hire inbox or by email."})


@bp.post("/<int:att_id>/caption-gap")
@auth_required
def caption_gap(att_id):
    """V02.01.05: the candidate's side had no captions for a while: recorded for the scorecard's transcription offer."""
    att, role = load(att_id)
    if not att or role != "candidate":
        return err("This call isn't yours.", 403)
    d = body()
    try:
        secs = max(0, min(3600, int(d.get("seconds") or 0)))
    except (TypeError, ValueError):
        return err("seconds must be a number.")
    if secs >= 10:
        res = dict(att.result or {})
        res["caption_gaps"] = (list(res.get("caption_gaps") or [])[-49:]
                               + [{"at": str(d.get("at") or "")[:40], "seconds": secs, "who": "candidate"}])
        att.result = res
        db.session.commit()
    return ok({})
