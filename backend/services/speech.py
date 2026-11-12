"""Azure Speech: short-lived browser tokens (speech-to-text), the voice catalogue and text-to-speech."""
import time
from xml.sax.saxutils import escape

import requests
from flask import current_app

from services.settings import platform_secret

# Used when the Azure voice list cannot be fetched (no key yet, or offline).
FALLBACK_VOICES = [
    {"name": "en-IN-NeerjaNeural", "label": "Neerja", "locale": "en-IN", "gender": "Female", "style": "Warm, Indian English"},
    {"name": "en-IN-PrabhatNeural", "label": "Prabhat", "locale": "en-IN", "gender": "Male", "style": "Calm, Indian English"},
    {"name": "en-IN-AaravNeural", "label": "Aarav", "locale": "en-IN", "gender": "Male", "style": "Friendly, Indian English"},
    {"name": "en-IN-AashiNeural", "label": "Aashi", "locale": "en-IN", "gender": "Female", "style": "Bright, Indian English"},
    {"name": "hi-IN-SwaraNeural", "label": "Swara", "locale": "hi-IN", "gender": "Female", "style": "Hindi"},
    {"name": "hi-IN-MadhurNeural", "label": "Madhur", "locale": "hi-IN", "gender": "Male", "style": "Hindi"},
    {"name": "ta-IN-PallaviNeural", "label": "Pallavi", "locale": "ta-IN", "gender": "Female", "style": "Tamil"},
    {"name": "te-IN-ShrutiNeural", "label": "Shruti", "locale": "te-IN", "gender": "Female", "style": "Telugu"},
    {"name": "en-US-JennyNeural", "label": "Jenny", "locale": "en-US", "gender": "Female", "style": "US English"},
    {"name": "en-US-GuyNeural", "label": "Guy", "locale": "en-US", "gender": "Male", "style": "US English"},
    {"name": "en-GB-RyanNeural", "label": "Ryan", "locale": "en-GB", "gender": "Male", "style": "British English"},
    {"name": "en-GB-SoniaNeural", "label": "Sonia", "locale": "en-GB", "gender": "Female", "style": "British English"},
]
_cache = {"voices": None, "at": 0}


def _creds():
    key = platform_secret("azure_speech_key", current_app.config.get("AZURE_SPEECH_KEY", ""))
    region = platform_secret("azure_speech_region", current_app.config.get("AZURE_SPEECH_REGION", "centralindia"))
    return key, region


def configured():
    return bool(_creds()[0])


# V02.00.08: whether Azure actually answers, so a saved key that fails shows up instead of silently using the browser.
_status = {"ok_at": None, "error": None, "error_at": None}


def record(ok_, error=None):
    now = time.time()
    if ok_:
        _status["ok_at"] = now
    else:
        _status.update(error=error, error_at=now)


def status():
    st = dict(_status)
    st["configured"] = configured()
    st["working"] = bool(st["configured"] and st["ok_at"] and (not st["error_at"] or st["ok_at"] > st["error_at"]))
    st["recent_error"] = bool(st["error_at"] and time.time() - st["error_at"] < 3600 and not st["working"])
    return st


def issue_token():
    key, region = _creds()
    if not key:
        return None
    try:
        r = requests.post(f"https://{region}.api.cognitive.microsoft.com/sts/v1.0/issueToken",
                          headers={"Ocp-Apim-Subscription-Key": key}, timeout=10)
        if r.status_code in (401, 403):
            record(False, f"Azure rejected the key for region {region}")
        r.raise_for_status()
    except requests.RequestException as e:
        if not _status["error_at"] or _status["error_at"] < time.time() - 1:
            record(False, f"Azure Speech didn't answer ({type(e).__name__})")
        raise
    record(True)
    return {"token": r.text, "region": region, "expires_in": 540}


def voices(locales=("en-IN", "hi-IN", "en-US", "en-GB", "ta-IN", "te-IN", "kn-IN", "mr-IN", "bn-IN")):
    key, region = _creds()
    if not key:
        return FALLBACK_VOICES
    if _cache["voices"] and time.time() - _cache["at"] < 3600:
        return _cache["voices"]
    try:
        r = requests.get(f"https://{region}.tts.speech.microsoft.com/cognitiveservices/voices/list",
                         headers={"Ocp-Apim-Subscription-Key": key}, timeout=10)
        r.raise_for_status()
        out = [{"name": v["ShortName"], "label": v.get("DisplayName", v["ShortName"]), "locale": v["Locale"],
                "gender": v.get("Gender"), "style": v.get("LocaleName", v["Locale"])}
               for v in r.json() if v["Locale"] in locales]
        _cache.update(voices=out or FALLBACK_VOICES, at=time.time())
        return _cache["voices"]
    except Exception:
        return FALLBACK_VOICES


def synthesize(text, voice="en-IN-NeerjaNeural", rate="0%"):
    """Returns MP3 bytes, or None when Azure is not configured (the browser then speaks instead)."""
    key, region = _creds()
    if not key:
        return None
    locale = "-".join(voice.split("-")[:2])
    ssml = (f"<speak version='1.0' xml:lang='{locale}'><voice name='{voice}'>"
            f"<prosody rate='{rate}'>{escape(text)}</prosody></voice></speak>")
    r = requests.post(f"https://{region}.tts.speech.microsoft.com/cognitiveservices/v1",
                      headers={"Ocp-Apim-Subscription-Key": key, "Content-Type": "application/ssml+xml",
                               "X-Microsoft-OutputFormat": "audio-24khz-48kbitrate-mono-mp3",
                               "User-Agent": "code2hire"},
                      data=ssml.encode("utf-8"), timeout=20)
    r.raise_for_status()
    return r.content
