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
        if audio:
            speech.record(True)
    except Exception as e:
        speech.record(False, f"Azure text-to-speech failed ({type(e).__name__})")
        audio = None
    _keep_for_video(d.get("attempt_id"), text, voice, audio)
    if not audio:
        return ok({"fallback": True, "voice": voice, "rate": rate})
    return Response(audio, mimetype="audio/mpeg")


def _keep_for_video(att_id, text, voice, audio):
    """V02.01.01: in the candidate's AI interview, every line Hira says is kept with its time so it can be mixed
    into the recording afterwards, also when the browser spoke it with its own voice."""
    if not att_id:
        return
    from extensions import db
    from models import RoundAttempt
    from services import hira_audio
    try:
        att = db.session.get(RoundAttempt, int(att_id))
    except (TypeError, ValueError):
        return
    if not att or att.round_type != "ai_interview" or att.status != "in_progress":
        return
    from models import Application
    app_ = db.session.get(Application, att.application_id) if att.application_id else None
    if not app_ or app_.candidate_id != g.user.id:
        return
    try:
        hira_audio.save(att, text, audio)
        res = dict(att.result or {})
        res["hira_voice"] = voice
        att.result = res
        db.session.commit()
    except Exception:  # noqa: BLE001 - speaking never fails because of this
        db.session.rollback()
