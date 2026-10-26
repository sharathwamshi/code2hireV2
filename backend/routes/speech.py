"""Azure Speech for the browser: STT tokens, the voice catalogue (with allowed-voice filtering) and TTS."""
from flask import Blueprint, Response, g, request

from routes.utils import body, err, ok
from services import speech
from services.perms import auth_required
from services.settings import resolve

bp = Blueprint("speech", __name__, url_prefix="/api/speech")


@bp.get("/token")
@auth_required
def token():
    """Short-lived token for the Azure Speech SDK in the browser. Falls back to the browser's own recogniser."""
    if not speech.configured():
        return ok({"configured": False})
    try:
        return ok({"configured": True, **speech.issue_token()})
    except Exception:
        return ok({"configured": False, "error": "Azure Speech didn't respond. Using the browser's speech engine."})


@bp.get("/voices")
@auth_required
def voices():
    """All voices, or only those allowed for an attempt (?attempt=ID) or a scope (?company_id=...)."""
    allv = speech.voices()
    att_id = request.args.get("attempt")
    allowed = None
    if att_id:
        from extensions import db
        from models import RoundAttempt
        att = db.session.get(RoundAttempt, int(att_id))
        allowed = (att.config or {}).get("voice.allowed") if att else None
    elif request.args.get("allowed") == "1":
        allowed = resolve("voice.allowed", company_id=g.user.company_id)[0]
    rows = [v for v in allv if not allowed or v["name"] in allowed]
    return ok({"voices": rows, "azure": speech.configured(),
               "default": resolve("voice.name", company_id=g.user.company_id)[0]})


@bp.post("/tts")
@auth_required
def tts():
    d = body()
    text = (d.get("text") or "").strip()[:1500]
    if not text:
        return err("Nothing to say.")
    voice = d.get("voice") or resolve("voice.name", company_id=g.user.company_id)[0]
    rate = d.get("rate") or resolve("voice.rate", company_id=g.user.company_id)[0]
    try:
        audio = speech.synthesize(text, voice, rate)
    except Exception:
        audio = None
    if not audio:
        return ok({"fallback": True, "voice": voice, "rate": rate})
    return Response(audio, mimetype="audio/mpeg")
