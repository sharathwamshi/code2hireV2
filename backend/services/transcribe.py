"""V02.01.04: a transcript from the interview video, when the live captions missed it.

Live captions come from the browsers during the call. If they were off, or a browser couldn't caption, the transcript
is thin and Isha has little to review or score. The video of each side was recorded, so the server can turn its sound
into text with Azure Speech (the same service the live captions use) and rebuild the transcript from it.

Each recorded piece is cut into 50-second pieces of 16 kHz mono sound with ffmpeg and sent to Azure's short-audio
speech-to-text. A side's sentences replace that side's live captions only when the recording gave more words. Then
Isha reviews the interview again and the scorecard draft is rebuilt.

It runs in a background thread; result.transcribe says where it is: {"state": running|done|failed|nothing, "done",
"total", "words": {"candidate", "interviewer"}, "error"}.
"""
import os
import shutil
import subprocess
import tempfile
import threading
from datetime import datetime

import requests

PIECE_S = 50


def available():
    from services import speech, storage
    return bool(speech.configured() and storage.ffmpeg())


def _local_file(rec, tmp):
    from services import storage
    p = storage.local_path(rec.file_key) if rec.file_key else None
    if p and os.path.exists(p):
        return p
    if rec.storage == "azure" and rec.file_key and storage.azure_conn():
        _, c = storage._container()
        out = os.path.join(tmp, "rec-" + os.path.basename(rec.file_key))
        with open(out, "wb") as fh:
            fh.write(c.download_blob(rec.file_key).readall())
        return out
    return None


def _pieces(path, tmp, k):
    from services import storage
    pattern = os.path.join(tmp, f"r{k}-%03d.wav")
    subprocess.run([storage.ffmpeg(), "-y", "-loglevel", "error", "-i", path, "-vn", "-ac", "1", "-ar", "16000", "-f", "segment",
                    "-segment_time", str(PIECE_S), pattern], check=True, capture_output=True, timeout=1800)
    return sorted(os.path.join(tmp, f) for f in os.listdir(tmp) if f.startswith(f"r{k}-") and f.endswith(".wav"))


def recognize(wav_path, language="en-IN"):
    """Text of one short (< 60 s) WAV piece from Azure Speech, or "" when nothing was recognised."""
    from services.speech import _creds
    key, region = _creds()
    with open(wav_path, "rb") as fh:
        r = requests.post(f"https://{region}.stt.speech.microsoft.com/speech/recognition/conversation/cognitiveservices/v1",
                          params={"language": language, "format": "simple"},
                          headers={"Ocp-Apim-Subscription-Key": key, "Content-Type": "audio/wav; codecs=audio/pcm; samplerate=16000",
                                   "Accept": "application/json"}, data=fh.read(), timeout=60)
    if r.status_code != 200:
        raise RuntimeError(f"Azure Speech answered {r.status_code}")
    d = r.json() or {}
    return str(d.get("DisplayText") or "").strip() if d.get("RecognitionStatus") in ("Success", None) else ""


def _set(att, **kw):
    from extensions import db
    res = dict(att.result or {})
    res["transcribe"] = {**(res.get("transcribe") or {}), **kw, "at": datetime.utcnow().isoformat() + "Z"}
    att.result = res
    db.session.commit()


def run(att_id, language="en-IN", use_ai=True):
    """Does the work (call it in a thread with an app context). Returns the final transcribe state."""
    from extensions import db
    from models import Recording, RoundAttempt, Turn
    att = db.session.get(RoundAttempt, att_id)
    recs = (Recording.query.filter(Recording.attempt_id == att_id, Recording.status == "ready", Recording.side.in_(("candidate", "interviewer")))
            .order_by(Recording.started_at).all())
    if not recs:
        _set(att, state="nothing", error="There's no finished recording of this interview to transcribe.")
        return att.result["transcribe"]
    tmp = tempfile.mkdtemp(prefix="c2h-stt-")
    lines = {"candidate": [], "interviewer": []}
    try:
        work = []
        for k, rec in enumerate(recs):
            path = _local_file(rec, tmp)
            if not path:
                continue
            for n, piece in enumerate(_pieces(path, tmp, k)):
                base = ((rec.started_at - att.started_at).total_seconds() if rec.started_at and att.started_at else 0) + n * PIECE_S
                work.append((rec.side, max(0, int(base)), piece))
        _set(att, state="running", done=0, total=len(work))
        for i, (side, at, piece) in enumerate(work, start=1):
            text = recognize(piece, language)
            if text:
                lines[side].append((at, text))
            if i % 5 == 0 or i == len(work):
                _set(att, done=i)
        words = {s: sum(len(t.split()) for _, t in v) for s, v in lines.items()}
        have = {s: sum(len((t.text or "").split()) for t in Turn.query.filter_by(attempt_id=att_id, speaker=s).all()) for s in lines}
        replaced = []
        for side, got in lines.items():
            if got and words[side] > have[side]:  # the recording heard more than the live captions did
                Turn.query.filter_by(attempt_id=att_id, speaker=side).delete()
                for at, text in got:
                    db.session.add(Turn(attempt_id=att_id, seq=0, speaker=side, text=text[:1500], at_seconds=at, topic="From the recording"))
                replaced.append(side)
        db.session.flush()
        for n, t in enumerate(Turn.query.filter_by(attempt_id=att_id).order_by(Turn.at_seconds, Turn.id).all()):
            t.seq = n
        if replaced:
            from services.isha_review import review as review_all
            from services.pipeline import context
            _, job, _, _ = context(att)
            review_all(att, job.company_id if job else None, use_ai=use_ai)
        _set(att, state="done", words=words, replaced=replaced, done=len(work), total=len(work))
    except Exception as e:  # noqa: BLE001 - the live transcript stays as it was
        db.session.rollback()
        att = db.session.get(RoundAttempt, att_id)
        _set(att, state="failed", error=str(e)[:200])
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return att.result["transcribe"]


def start(app, att_id):
    """Starts run() in a background thread."""
    def go():
        with app.app_context():
            run(att_id)
    t = threading.Thread(target=go, daemon=True, name=f"transcribe-{att_id}")
    t.start()
    return t
