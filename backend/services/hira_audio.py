"""V02.01.01: Hira's voice in the AI-interview recording.

The candidate's browser records the camera and microphone. Hira's voice used to be mixed in by the browser, which
only worked for Azure speech: when Hira fell back to the browser's own voice (Azure not set up, or a request failed),
no website can capture it, so the recording was silent while Hira spoke. Her opening lines could also be lost
because they played before the recording started.

Now the server keeps every piece of Hira's speech with the time it was spoken (`result.hira_audio`), and when a
recorded piece is finished, ffmpeg mixes them into the video at the right moments. Speech the browser said itself is
made again on the server: with Azure when set up, else with espeak-ng when installed. Without either, the questions
still show as captions in the player (`captions.vtt`).
"""
import os
import shutil
import subprocess
import tempfile
from datetime import datetime, timedelta

from flask import current_app

from extensions import db
from services import speech, storage


def _clip_key(att_id, n):
    return f"att{att_id}-hira-{n:03d}.mp3"


def can_merge():
    return bool(storage.ffmpeg())


def save(att, text, audio):
    """Called for every Hira line the candidate's browser asks to hear. audio = MP3 bytes, or None when the browser
    speaks it with its own voice."""
    res = dict(att.result or {})
    clips = list(res.get("hira_audio") or [])
    n = len(clips)
    key = None
    if audio:
        key = _clip_key(att.id, n)
        with open(storage.local_path(key), "wb") as fh:
            fh.write(audio)
    clips.append({"n": n, "key": key, "at": datetime.utcnow().isoformat(), "text": text[:1500]})
    res["hira_audio"] = clips[-400:]
    att.result = res


def _espeak():
    return shutil.which("espeak-ng") or shutil.which("espeak")


def _make_audio(text, voice, rate, out_base):
    """Audio for a line the browser spoke itself: Azure first, else espeak. Returns a file path or None."""
    try:
        mp3 = speech.synthesize(text, voice, rate)
    except Exception:  # noqa: BLE001
        mp3 = None
    if mp3:
        p = out_base + ".mp3"
        with open(p, "wb") as fh:
            fh.write(mp3)
        return p
    es = _espeak()
    if es:
        p = out_base + ".wav"
        try:
            subprocess.run([es, "-v", "en", "-s", "160", "-w", p, text[:1500]], check=True, capture_output=True, timeout=60)
            return p
        except Exception:  # noqa: BLE001
            return None
    return None


def merge(rec, att):
    """Mixes Hira's speech into one finished piece of the candidate's recording (rec.file_key, a local file).
    Returns (included, total) or None when there was nothing to do."""
    clips = (att.result or {}).get("hira_audio") or []
    if not clips or not rec.file_key or not rec.started_at:
        return None
    bin_ = storage.ffmpeg()
    if not bin_:
        return None
    start = rec.started_at
    end = (rec.last_at or start) + timedelta(seconds=15)
    mine = []
    for c in clips:
        try:
            at = datetime.fromisoformat(c["at"])
        except (KeyError, ValueError):
            continue
        if start - timedelta(seconds=30) <= at <= end:
            mine.append((max(0.0, (at - start).total_seconds()), c))
    if not mine:
        return None
    voice = (att.result or {}).get("hira_voice") or "en-IN-NeerjaNeural"
    tmp = tempfile.mkdtemp(prefix="hira-")
    inputs, used = [], 0
    try:
        for off, c in mine:
            path = storage.local_path(c["key"]) if c.get("key") else None
            if not path or not os.path.exists(path):
                path = _make_audio(c.get("text") or "", voice, "0%", os.path.join(tmp, f"c{c.get('n', 0)}"))
            if path and os.path.exists(path):
                inputs.append((off, path))
                used += 1
        if not inputs:
            return 0, len(mine)
        src = storage.local_path(rec.file_key)
        ext = "mp4" if (rec.mime or "").endswith("mp4") else "webm"
        out_key = rec.file_key.rsplit(".", 1)[0] + f"-hira.{ext}"
        out = storage.local_path(out_key)
        cmd = [bin_, "-y", "-loglevel", "error", "-i", src]
        for _, p in inputs:
            cmd += ["-i", p]
        parts, labels = [], []
        for k, (off, _) in enumerate(inputs, start=1):
            ms = int(off * 1000)
            parts.append(f"[{k}:a]aresample=48000,adelay={ms}|{ms}[h{k}]")
            labels.append(f"[h{k}]")
        has_audio = _has_audio(src)
        if has_audio:
            mix = "[0:a]" + "".join(labels) + f"amix=inputs={len(labels) + 1}:duration=first:dropout_transition=0:normalize=0[a]"
        else:
            mix = "".join(labels) + f"amix=inputs={len(labels)}:duration=longest:dropout_transition=0:normalize=0[a]"
        cmd += ["-filter_complex", ";".join(parts + [mix]), "-map", "0:v?", "-map", "[a]", "-c:v", "copy",
                "-c:a", "aac" if ext == "mp4" else "libopus"]
        if not has_audio:
            cmd += ["-shortest"]
        cmd += [out]
        subprocess.run(cmd, check=True, capture_output=True, timeout=1800)
        if os.path.getsize(out) > 0:
            try:
                os.remove(src)
            except OSError:
                pass
            rec.file_key = out_key
        return used, len(mine)
    except Exception as e:  # noqa: BLE001 - keep the recording as it is
        current_app.logger.warning("merging Hira's voice into recording %s failed: %s", rec.id, e)
        return None
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _has_audio(path):
    probe = shutil.which("ffprobe")
    if not probe:
        return True
    try:
        r = subprocess.run([probe, "-v", "error", "-select_streams", "a", "-show_entries", "stream=index", "-of", "csv=p=0", path],
                           capture_output=True, text=True, timeout=60)
        return bool(r.stdout.strip())
    except Exception:  # noqa: BLE001
        return True


def vtt(att, rec):
    """Hira's questions as captions for one recorded piece."""
    lines = ["WEBVTT", ""]
    start = rec.started_at
    if not start:
        return "\n".join(lines)
    k = 0
    for c in (att.result or {}).get("hira_audio") or []:
        try:
            at = datetime.fromisoformat(c["at"])
        except (KeyError, ValueError):
            continue
        off = (at - start).total_seconds()
        if off < -30 or (rec.seconds and off > rec.seconds + 15):
            continue
        off = max(0.0, off)
        dur = max(2.5, min(20.0, len((c.get("text") or "").split()) / 2.6))
        k += 1
        lines += [str(k), f"{_ts(off)} --> {_ts(off + dur)}", "Hira: " + " ".join((c.get("text") or "").split())[:400], ""]
    return "\n".join(lines)


def _ts(s):
    h, rem = divmod(int(s), 3600)
    m, sec = divmod(rem, 60)
    return f"{h:02d}:{m:02d}:{sec:02d}.{int((s - int(s)) * 1000):03d}"
