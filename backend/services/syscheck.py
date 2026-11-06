"""The system check before an interview, and the candidate instructions (V02.00.05).

Every step except the internet measurement must pass before the round can start. The browser runs the steps; the
server decides which steps a round needs, checks the results it is sent, blocks phones and tablets by their user agent
as well, and refuses consent until a passing check and "I've read the instructions" are on record.
"""
import re
from datetime import datetime, timedelta

from extensions import db
from models import RoundAttempt, SystemCheck

# key: (label shown to people, what it proves)
STEPS = {
    "device": ("Laptop or desktop", "Interviews can't be taken on a phone or tablet."),
    "browser": ("Supported browser", "Chrome, Edge or Safari 15 and newer."),
    "permissions": ("Camera and microphone allowed", "The browser lets Code2Hire use them."),
    "camera": ("Camera", "The camera shows a clear picture."),
    "face": ("Face in view", "Exactly one face, with enough light."),
    "mic": ("Microphone", "Your voice reaches us and is written out correctly."),
    "speaker": ("Speaker", "You can hear Hira and the interviewer."),
    "recording": ("Recording", "A short test video reaches the server."),
    "fullscreen": ("Fullscreen", "The round can run in fullscreen."),
    "internet": ("Internet", "Speed and delay. Only a warning, never blocks."),
    "room": ("Your room", "Quiet room, alone, phone away, charger plugged in."),
}
ORDER = list(STEPS)
HELP_ONLY = {"other": ("Something else", "Anything not covered by a step.")}  # "Contact the hiring team" on an error screen
WARN_ONLY = {"internet"}
FRESH_HOURS = 12  # a passing check is good for this long
MOBILE = re.compile(r"Mobi|Android|iPhone|iPad|iPod|Windows Phone|webOS|BlackBerry|Opera Mini|IEMobile", re.I)
MOBILE_MESSAGE = ("Please join from a laptop or desktop. Interviews on Code2Hire can't be taken on a phone or tablet, "
                  "because the camera, microphone and screen checks need a computer.")


def is_mobile(user_agent):
    return bool(MOBILE.search(user_agent or ""))


def _proctored(att):
    cfg = (att.config or {}) if att else {}
    return bool(att) and (not att.practice_user_id or bool(cfg.get("skill_check")))


def needs(att, role="candidate"):
    """What this round uses: camera, microphone, speaker, recording, fullscreen."""
    if role == "interviewer":
        from routes.recordings import must_record
        return {"camera": True, "mic": True, "speaker": True, "recording": bool(att and must_record(att)), "fullscreen": False,
                "face": False, "room": False}
    if not att:  # "Test my setup": everything an AI interview needs
        return {"camera": True, "mic": True, "speaker": True, "recording": True, "fullscreen": True, "face": True, "room": True}
    from routes.recordings import must_record
    cfg = att.config or {}
    t = att.round_type
    proctored = _proctored(att)
    live = t.startswith("f2f")
    camera = t == "ai_interview" or live or (proctored and bool(cfg.get("integrity.face_check")))
    mic = t == "ai_interview" or live
    speaker = (t == "ai_interview" and cfg.get("voice.enabled", True) is not False) or live
    return {"camera": camera, "mic": mic, "speaker": speaker, "recording": must_record(att),
            "fullscreen": proctored and bool(cfg.get("integrity.fullscreen")) and not live,
            "face": camera and (proctored or live) and cfg.get("integrity.face_check", True) is not False, "room": proctored or live}


def required_steps(att, role="candidate", mode="full"):
    """Ordered list of {key, label, about, blocking} for this round and person."""
    n = needs(att, role)
    keys = ["device", "browser"]
    if n["camera"] or n["mic"]:
        keys.append("permissions")
    for k in ("camera", "face", "mic", "speaker", "recording", "fullscreen"):
        if n.get(k):
            keys.append(k)
    keys.append("internet")
    if n["room"] and role == "candidate":
        keys.append("room")
    if mode == "recheck":  # rejoining: only the devices again
        keys = [k for k in keys if k in ("permissions", "camera", "mic", "speaker")] or ["device"]
    return [{"key": k, "label": STEPS[k][0], "about": STEPS[k][1], "blocking": k not in WARN_ONLY} for k in keys]


def evaluate(att, role, mode, steps, user_agent):
    """Checks what the browser sent. Returns (passed, failed_keys, clean_steps)."""
    clean, failed = {}, []
    for s in required_steps(att, role, mode):
        k = s["key"]
        got = steps.get(k) if isinstance(steps, dict) else None
        got = got if isinstance(got, dict) else {}
        status = got.get("status") if got.get("status") in ("pass", "fail", "warn", "skip") else "fail"
        detail = str(got.get("detail") or "")[:200]
        if k == "device" and is_mobile(user_agent):
            status, detail = "fail", "Phone or tablet"
        if s["blocking"] and status != "pass":
            failed.append(k)
        clean[k] = {"status": status, "detail": detail}
    return not failed, failed, clean


def latest(att, role="candidate"):
    return (SystemCheck.query.filter_by(attempt_id=att.id, role=role).filter(SystemCheck.help_step.is_(None))
            .order_by(SystemCheck.id.desc()).first())


def passed_recently(att, role="candidate"):
    c = SystemCheck.query.filter_by(attempt_id=att.id, role=role, passed=True).order_by(SystemCheck.id.desc()).first()
    return bool(c and c.created_at > datetime.utcnow() - timedelta(hours=FRESH_HOURS))


def had_full(att, role="candidate"):
    """V02.00.06 (B1): a re-check is only allowed after this person has passed the full check for this round (and, for a
    candidate, read the instructions). Whether the round has started doesn't matter: the interviewer may have started it."""
    if not att:
        return False
    full = SystemCheck.query.filter(SystemCheck.attempt_id == att.id, SystemCheck.role == role, SystemCheck.passed.is_(True),
                                    SystemCheck.mode == "full").first()
    if role == "candidate":
        return bool(full) and bool((att.result or {}).get("instructions_read_at"))
    return bool(full)


def effective_mode(att, role, mode):
    if mode == "recheck" and not had_full(att, role):
        return "full"
    return mode


def must_check(att):
    """Practice rounds run the check to help the candidate, but the server only insists for real rounds."""
    return bool(att) and not att.practice_user_id


def summary(att, role="candidate"):
    """One line for the report and the pipeline: "Camera OK · Mic OK · Internet weak (1.2 Mbps)"."""
    if not att:
        return None
    c = (SystemCheck.query.filter_by(attempt_id=att.id, role=role).order_by(SystemCheck.id.desc()).first())
    if not c:
        return None
    if c.help_step:
        label = {**STEPS, **HELP_ONLY}.get(c.help_step, (c.help_step,))[0]
        return {"state": "needs_help", "text": f"Asked for help with: {label}",
                "at": c.created_at.isoformat() + "Z", "steps": c.steps or {}, "device": c.device or {}}
    parts = []
    for k, v in (c.steps or {}).items():
        if k in ("device", "browser", "permissions", "room"):
            continue
        label = STEPS.get(k, (k,))[0]
        if v.get("status") == "pass":
            parts.append(f"{label} OK")
        elif v.get("status") == "warn":
            parts.append(f"{label} {v.get('detail') or 'weak'}")
        else:
            parts.append(f"{label} failed")
    return {"state": "tested" if c.passed else "failed", "text": " · ".join(parts) or "Checked", "at": c.created_at.isoformat() + "Z",
            "steps": c.steps or {}, "device": c.device or {}}


# ---------------------------------------------------------------- instructions

ROUND_WORDS = {"mcq": "a multiple-choice test", "ai_interview": "an AI interview with Hira", "f2f_isha": "a live video interview",
               "f2f_human": "a live video interview"}


def instructions(att):
    """The candidate instructions for one round, built from its real settings so the page, the PDF and the
    invite say the same thing."""
    from routes.recordings import must_record
    from services.pipeline import context, round_name
    from services.settings import resolve
    app, job, cand, _ = context(att)
    cfg = att.config or {}
    t = att.round_type
    n = needs(att)
    proctored = _proctored(att)
    live = t.startswith("f2f")
    if t == "mcq":
        what = f"{cfg.get('mcq.questions', 10)} questions in {cfg.get('mcq.minutes', 20)} minutes. You can flag a question and come back to it."
        if cfg.get("mcq.negative_marking"):
            what += " Wrong answers lose a quarter mark, so skip if you don't know."
    elif t == "ai_interview":
        what = (f"About {cfg.get('interview.questions', 5)} questions in {cfg.get('interview.minutes', 30)} minutes. Hira asks each "
                "question out loud and on screen, listens to your answer and may ask a follow-up. Speak naturally; there are no trick questions.")
    else:
        what = (f"A live video call with a person from the hiring team, about {cfg.get('f2f.questions', 7)} questions. "
                "The interviewer may use an assistant, Isha, to plan questions. The interviewer makes every decision.")
    need = ["A laptop or desktop computer. Phones and tablets can't be used."]
    need.append("Chrome or Edge (Safari 15 or newer on a Mac), updated to the latest version.")
    if n["camera"]:
        need.append("A working camera, with your face lit from the front.")
    if n["mic"]:
        need.append("A working microphone. Headphones with a microphone work best and stop echo.")
    if n["speaker"]:
        need.append("Speakers or headphones, so you can hear the questions.")
    need.append("A steady internet connection (at least 2 Mbps). Close video streaming and downloads.")
    if n["room"]:
        need.append("A quiet room where you are alone, with your phone away and your charger plugged in.")
    rules = []
    if proctored or live:
        if n["fullscreen"]:
            rules.append("Stay in fullscreen. Leaving fullscreen counts as a warning.")
        rules.append("Stay on this tab. Switching tabs or apps counts as a warning.")
        if cfg.get("integrity.block_paste", True):
            rules.append("Copying and pasting are switched off and count as a warning.")
        if n["face"] and cfg.get("integrity.face_check", True):
            rules.append("Keep your face in view and be the only person on camera.")
        if live:
            rules.append("Warnings are shown to the interviewer as they happen. The interviewer decides what to do.")
        else:
            rules.append(f"You get {cfg.get('integrity.warnings_allowed', 2)} warnings that explain what happened. After that the round "
                         "pauses until the recruiter checks.")
        rules.append("Notes, other people, and other apps or AI tools are not allowed unless the hiring team said so.")
    rec = []
    if must_record(att):
        days = resolve("recording.retention_days", company_id=job.company_id, team_id=job.team_id, job_id=job.id)[0] if job else 180
        rec.append("The round is recorded (video and sound). Only the hiring team can watch it, every viewing is logged, "
                   f"and it is deleted after {days} days.")
    rec.append("It is AI-assisted. A person on the hiring team reviews the result and makes every decision.")
    drop = ["If your internet drops, open the same link again. Your progress is saved and a dropped connection never counts as a warning."]
    if live:
        drop.append("If the interviewer steps out, stay on the page. You'll be reconnected when they're back.")
    if n["camera"] or n["mic"]:
        drop.append("If your camera or microphone stops, the round waits for you to fix it.")
    after = ["The hiring team reviews your round and you hear back on your Code2Hire home page."]
    sections = [{"heading": "What this round is", "items": [what]}, {"heading": "What you need", "items": need}]
    if rules:
        sections.append({"heading": "Rules and warnings", "items": rules})
    sections += [{"heading": "Recording and AI", "items": rec}, {"heading": "If something goes wrong", "items": drop},
                 {"heading": "After the round", "items": after}]
    extra = (cfg.get("instructions.extra") or "").strip()
    if not extra and job:
        extra = (resolve("instructions.extra", company_id=job.company_id, team_id=job.team_id, job_id=job.id)[0] or "").strip()
    return {"title": round_name(att, job), "kind": ROUND_WORDS.get(t, "a round"), "job": job.title if job else (cfg.get("title") or "Practice"),
            "minutes": cfg.get("mcq.minutes") if t == "mcq" else cfg.get("interview.minutes") if t == "ai_interview" else None,
            "scheduled_at": att.scheduled_at.isoformat() + "Z" if att.scheduled_at else None,
            "sections": sections, "extra": extra[:2000], "read_at": (att.result or {}).get("instructions_read_at"),
            "short": [what, need[0], "Test your setup before the day with “Test my setup”."]}


def mark_read(att):
    res = dict(att.result or {})
    if not res.get("instructions_read_at"):
        res["instructions_read_at"] = datetime.utcnow().isoformat() + "Z"
        att.result = res


def interviewer_guide():
    return [{"heading": "Joining", "items": ["Run the short check (camera, microphone, speaker), then press Join video call.",
                                              "Leave call steps out without ending: the candidate waits and you can rejoin."]},
            {"heading": "During the interview", "items": ["The Next question card shows the next question from the plan. Ask it, or skip it.",
                                                         "Captions of both of you appear in the transcript, and Isha suggests follow-ups.",
                                                         "Integrity warnings appear in the Integrity panel as they happen. You decide what to do."]},
            {"heading": "Ending", "items": ["End interview ends it for both of you and opens the scorecard. It can't be undone."]}]


def attach_to_attempt(check):
    """Keeps the newest result on the attempt too, so lists can show it without another query."""
    if not check.attempt_id:
        return
    att = db.session.get(RoundAttempt, check.attempt_id)
    if not att:
        return
    res = dict(att.result or {})
    key = "syscheck" if check.role == "candidate" else "syscheck_interviewer"
    res[key] = {"id": check.id, "passed": check.passed, "at": datetime.utcnow().isoformat() + "Z", "help": check.help_step}
    att.result = res


# ---------------------------------------------------------------- where the candidate is (V02.00.06, C2 / C3)

STAGES = {"opened": "Opened the round", "instructions": "Reading the instructions", "check": "Doing the system check",
          "passed": "Check passed, joining", "joined": "Joined", "help": "Asked for help", "stuck": "Stuck on an error"}


def set_progress(att, stage, step=None, index=None, total=None, note=None):
    res = dict(att.result or {})
    res["cand_progress"] = {"stage": stage if stage in STAGES else "opened", "step": (str(step)[:30] if step else None),
                            "index": index if isinstance(index, int) else None, "total": total if isinstance(total, int) else None,
                            "note": (str(note)[:200] if note else None), "at": datetime.utcnow().isoformat() + "Z"}
    att.result = res


def earlier_open(att):
    """C3: an earlier round of the same application that is still running. Warned about, not blocked."""
    if not att or not att.application_id:
        return None
    from services.pipeline import round_name
    prev = (RoundAttempt.query.filter(RoundAttempt.application_id == att.application_id, RoundAttempt.round_index < att.round_index,
                                      RoundAttempt.status.in_(("in_progress", "paused"))).order_by(RoundAttempt.round_index).first())
    if not prev:
        return None
    return {"attempt_id": prev.id, "name": round_name(prev), "status": prev.status, "type": prev.round_type}


def candidate_status(att):
    """What the interviewer sees before the candidate is connected: exactly where they are."""
    res = att.result or {}
    p = res.get("cand_progress") or {}
    c = SystemCheck.query.filter_by(attempt_id=att.id, role="candidate").order_by(SystemCheck.id.desc()).first()
    text, kind = "Hasn't opened the round yet", "warn"
    if p:
        label = {**STEPS, **HELP_ONLY}.get(p.get("step") or "", (p.get("step") or "",))[0]
        if p["stage"] == "instructions":
            text = "Reading the instructions"
        elif p["stage"] == "check":
            text = f"Doing the system check: step {p.get('index')} of {p.get('total')} ({label})" if p.get("index") else "Doing the system check"
        elif p["stage"] == "passed":
            text, kind = "System check passed, joining the call", "good"
        elif p["stage"] == "joined":
            text, kind = "Joined the call", "good"
        elif p["stage"] == "help":
            text, kind = f"Asked for help: {label}", "bad"
        elif p["stage"] == "stuck":
            text, kind = f"Stuck: {p.get('note') or 'an error screen'}", "bad"
        else:
            text = "Opened the round"
    at = p.get("at")
    stale = False
    if at:
        try:
            stale = (datetime.utcnow() - datetime.fromisoformat(at.rstrip("Z"))).total_seconds() > 120
        except ValueError:
            stale = False
    return {"text": text, "kind": kind, "at": at, "stale": stale, "check": summary(att), "earlier_open": earlier_open(att),
            "instructions_read": bool(res.get("instructions_read_at")), "check_passed": passed_recently(att)}
