"""Configuration inheritance: Platform -> Company -> Team -> Job -> Round.

Every key has a platform default below. Each level can override it (if not locked above),
and the resolver reports where the effective value comes from.
"""
from extensions import db
from models import Setting

# key: (default, group, label, type, options)
DEFAULTS = {
    # AI (Anthropic)
    "ai.model": ("claude-sonnet-5-5", "AI", "Anthropic model for all AI work", "select",
                 ["claude-opus-5-5", "claude-sonnet-5-5", "claude-haiku-5-5"]),
    "ai.summary_length": ("short", "AI", "Report summary length", "select", ["short", "medium", "long"]),
    "ai.language": ("English", "AI", "Interview language", "select", ["English", "Hindi", "Hinglish", "Tamil", "Telugu"]),
    "ai.banned_topics": (["age", "religion", "caste", "marital status", "pregnancy", "salary history"], "AI",
                         "Topics the AI must never ask about", "list", None),
    # Voice (Azure)
    "voice.enabled": (True, "Voice", "Use voice in AI interviews", "bool", None),
    "voice.name": ("en-IN-NeerjaNeural", "Voice", "Default voice for Hira", "voice", None),
    "voice.allowed": (["en-IN-NeerjaNeural", "en-IN-PrabhatNeural", "en-US-JennyNeural", "en-GB-RyanNeural",
                       "hi-IN-SwaraNeural"], "Voice", "Voices candidates may choose from", "voices", None),
    "voice.rate": ("0%", "Voice", "Speaking rate", "select", ["-20%", "-10%", "0%", "10%", "20%"]),
    "voice.candidate_can_choose": (True, "Voice", "Candidate can pick a voice before starting", "bool", None),
    "voice.silence_seconds": (6, "Voice", "Seconds of silence before Hira asks if the answer is finished", "int", None),
    # MCQ
    "mcq.questions": (10, "MCQ", "Number of questions", "int", None),
    "mcq.minutes": (20, "MCQ", "Time limit (minutes)", "int", None),
    "mcq.negative_marking": (False, "MCQ", "Negative marking", "bool", None),
    "mcq.randomise": (True, "MCQ", "Randomise question order", "bool", None),
    "mcq.ai_review": (True, "MCQ", "Questions written by AI wait in the question bank as drafts until someone approves them", "bool", None),
    "mcq.folder_ids": ([], "MCQ", "Question bank folders to draw from (empty = pick by the job's skills)", "folders", None),
    # AI interview
    "interview.questions": (5, "AI interview", "Main questions", "int", None),
    "interview.followup_depth": (1, "AI interview", "Follow-ups per question", "int", None),
    "interview.difficulty": ("medium", "AI interview", "Difficulty", "select", ["easy", "medium", "hard"]),
    "interview.minutes": (30, "AI interview", "Time limit (minutes)", "int", None),
    "interview.attempts": (1, "AI interview", "Attempts allowed", "int", None),
    # Pass rules
    "pass.advance": (70, "Pass rules", "Auto-advance at or above (%)", "int", None),
    "pass.reject": (40, "Pass rules", "Auto-reject below (%)", "int", None),
    "pass.auto": (False, "Pass rules", "Apply pass rules automatically", "bool", None),
    # Integrity
    "integrity.warnings_allowed": (2, "Integrity", "Warnings allowed before pause", "int", None),
    "integrity.fullscreen": (True, "Integrity", "Require fullscreen", "bool", None),
    "integrity.face_check": (True, "Integrity", "Face presence check", "bool", None),
    "integrity.block_paste": (True, "Integrity", "Block pasting", "bool", None),
    "integrity.instant_pause": (["multi_face", "devtools"], "Integrity", "Events that pause at once", "list", None),
    # Isha
    "isha.enabled": (True, "Isha", "Isha copilot in F2F rounds", "bool", None),
    "isha.options": (4, "Isha", "Question options shown at once", "int", None),
    "isha.hide_ai_scores_until_scorecard": (False, "Isha", "Hide AI scores until the interviewer submits", "bool", None),
    # Face-to-face rounds (Isha and human)
    "f2f.questions": (7, "F2F", "Questions in the interview plan", "int", None),
    "f2f.own_questions": ([], "F2F", "Your own questions (asked first, then Isha fills up to the number above)", "list", None),
    # Live video call (F2F rounds)
    "call.enabled": (True, "Video call", "Built-in video call for face-to-face rounds", "bool", None),
    "call.captions": (True, "Video call", "Candidate's browser sends live captions so Isha can analyse each sentence", "bool", None),
    "call.screen_share": (True, "Video call", "Allow screen sharing in the call", "bool", None),
    "call.chat": (True, "Video call", "In-call text chat", "bool", None),
    "call.watch_focus": (True, "Video call", "Tell the interviewer when the candidate leaves the call tab", "bool", None),
    "call.join_early_minutes": (15, "Video call", "Candidates can join this many minutes before the scheduled time (0 = any time)", "int", None),
    "call.stun_urls": (["stun:stun.l.google.com:19302", "stun:global.stun.twilio.com:3478"], "Video call", "STUN servers", "list", None),
    "call.turn_url": ("", "Video call", "TURN server URL (needed behind strict firewalls), e.g. turn:turn.example.com:3478", "text", None),
    "call.turn_username": ("", "Video call", "TURN username", "text", None),
    "call.turn_credential": ("", "Video call", "TURN password", "text", None),
    # Reports
    "report.scale": (5, "Reports", "Scoring scale (max)", "select", [5, 10, 100]),
    "report.review_before_share": (True, "Reports", "A person must review before sharing", "bool", None),
    "report.auto_share_days": (0, "Reports", "Share candidate feedback automatically after N days (0 = off)", "int", None),
    "report.client_hide": (["ai_scores", "salary", "integrity", "replay"], "Reports", "Hidden in client version", "list", None),
    "report.candidate_pdf": (True, "Reports", "Candidates can download their shared feedback as a PDF", "bool", None),
    "report.candidate_sections": (["strengths", "gaps", "learning_path"], "Reports", "Sections candidates can see", "list", None),
    # Policies and retention
    "policy.separation_of_duties": (True, "Policies", "Interviewer cannot give the final verdict for the same candidate", "bool", None),
    "policy.reinterview_max": (1, "Policies", "Re-interviews allowed per candidate per job", "int", None),
    "policy.decision_sla_hours": (48, "Policies", "Decision SLA after an interview (hours)", "int", None),
    "retention.days": (180, "Policies", "Delete candidate data N days after the job closes", "int", None),
    "recording.retention_days": (180, "Policies", "Keep interview videos for (days), then delete them", "int", None),
    # Candidates added by the hiring team
    "invite.link_days": (7, "Candidates", "Days a candidate's personal portal link stays valid", "int", None),
    "invite.require_password": (False, "Candidates", "Candidate must set a password before using the portal", "bool", None),
    # Certifications and badges
    "cert.validity_months": (12, "Certifications", "Default validity (months)", "int", None),
    "cert.cooldown_days": (14, "Certifications", "Retake cool-down (days)", "int", None),
    # Branding
    "brand.color": ("#5B3FFF", "Branding", "Brand colour", "color", None),
    "brand.email_footer": ("Sent by Code2Hire · Powered by AcknowledgerFirst", "Branding", "Email footer", "text", None),
}

# Limits for every number setting: (lowest, highest, unit). The server refuses anything outside them, the forms show
# them next to the box, and resolve() clamps old out-of-range values that were saved before the limits existed.
RANGES = {
    "voice.silence_seconds": (2, 30, "seconds"),
    "mcq.questions": (1, 100, "questions"),
    "mcq.minutes": (1, 240, "minutes"),
    "interview.questions": (1, 20, "questions"),
    "interview.followup_depth": (0, 5, "follow-ups"),
    "interview.minutes": (5, 180, "minutes"),
    "interview.attempts": (1, 5, "attempts"),
    "pass.advance": (0, 100, "%"),
    "pass.reject": (0, 100, "%"),
    "integrity.warnings_allowed": (0, 20, "warnings"),
    "isha.options": (2, 6, "options"),
    "f2f.questions": (1, 30, "questions"),
    "call.join_early_minutes": (0, 120, "minutes"),
    "report.auto_share_days": (0, 90, "days"),
    "policy.reinterview_max": (0, 5, "re-interviews"),
    "policy.decision_sla_hours": (1, 720, "hours"),
    "retention.days": (30, 3650, "days"),
    "recording.retention_days": (30, 730, "days"),
    "invite.link_days": (1, 90, "days"),
    "cert.validity_months": (1, 60, "months"),
    "cert.cooldown_days": (0, 365, "days"),
}
TEXT_MAX = {"call.turn_url": 300, "call.turn_username": 120, "call.turn_credential": 200, "brand.email_footer": 300}
LIST_MAX = {"f2f.own_questions": (30, 300), "ai.banned_topics": (40, 80), "integrity.instant_pause": (10, 40),
            "call.stun_urls": (10, 300), "report.client_hide": (20, 40), "report.candidate_sections": (20, 40)}
INSTANT_PAUSE = ["multi_face", "no_face", "devtools", "tab_switch", "fullscreen_exit", "paste"]
VOICE_NAME = __import__("re").compile(r"^[a-z]{2,3}-[A-Z]{2}-[A-Za-z]+Neural$")


def meta(key):
    """What a form needs to draw one setting: label, type, options and limits."""
    default, group, label, typ, options = DEFAULTS[key]
    m = {"key": key, "label": label, "group": group, "type": typ, "options": options, "default": default}
    if key in RANGES:
        m["min"], m["max"], m["unit"] = RANGES[key]
    if key in TEXT_MAX:
        m["max_length"] = TEXT_MAX[key]
    if key in LIST_MAX:
        m["max_items"], m["max_length"] = LIST_MAX[key]
    return m


def check_value(key, value):
    """Returns (clean_value, error). Every way of saving a setting (platform, company, team, job, round) goes through this."""
    if key not in DEFAULTS:
        return None, "Unknown setting."
    default, _, label, typ, options = DEFAULTS[key]
    if typ == "bool":
        if isinstance(value, bool):
            return value, None
        if value in (0, 1, "true", "false"):
            return value in (1, "true"), None
        return None, f"{label}: choose on or off."
    if typ == "int":
        from services.validate import integer
        lo, hi, unit = RANGES.get(key, (None, None, ""))
        n, e = integer(value, lo, hi, required=True, label=label)
        if e:
            return None, (f"{label} must be a whole number from {lo} to {hi} {unit}." if lo is not None else e).replace(" %", "%")
        return n, None
    if typ == "select":
        for o in options:
            if str(o) == str(value):
                return o, None
        return None, f"{label}: choose one of {', '.join(map(str, options))}."
    if typ in ("text", "voice"):
        v = "" if value is None else str(value).strip()
        if typ == "voice" and not VOICE_NAME.match(v):
            return None, f"{label}: choose a voice from the list."
        mx = TEXT_MAX.get(key, 200)
        if len(v) > mx:
            return None, f"{label} can be at most {mx} characters."
        return v, None
    if typ == "color":
        v = str(value or "")
        if not __import__("re").match(r"^#[0-9A-Fa-f]{6}$", v):
            return None, f"{label}: pick a colour."
        return v, None
    if typ in ("list", "voices", "folders"):
        if not isinstance(value, list):
            return None, f"{label}: expected a list."
        if typ == "folders":
            if not all(isinstance(x, int) and not isinstance(x, bool) and x > 0 for x in value):
                return None, f"{label}: pick folders from the list."
            return list(dict.fromkeys(value))[:50], None
        out = []
        for x in value:
            x = " ".join(str(x or "").split())
            if x and x.lower() not in [o.lower() for o in out]:
                out.append(x)
        if typ == "voices":
            if not out or not all(VOICE_NAME.match(x) for x in out):
                return None, f"{label}: pick at least one voice from the list."
            return out, None
        mi, ml = LIST_MAX.get(key, (40, 120))
        if len(out) > mi:
            return None, f"{label}: at most {mi} items."
        if any(len(x) > ml for x in out):
            return None, f"{label}: each item can be at most {ml} characters."
        if key == "integrity.instant_pause" and any(x not in INSTANT_PAUSE for x in out):
            return None, f"{label}: choose from {', '.join(INSTANT_PAUSE)}."
        return out, None
    return value, None


def _clamp(key, value):
    """Old values saved before the limits existed are read back inside the limits, never as -5 or 99999."""
    if key in RANGES:
        lo, hi, _ = RANGES[key]
        try:
            return min(hi, max(lo, int(float(value))))
        except (TypeError, ValueError):
            return DEFAULTS[key][0]
    return value


def cross_errors(values):
    """Settings that only make sense together. `values` is the effective value of each key after the change."""
    errs = {}
    adv, rej = values.get("pass.advance"), values.get("pass.reject")
    if isinstance(adv, int) and isinstance(rej, int) and rej > adv:
        errs["pass.reject"] = f"Auto-reject ({rej}%) must not be above auto-advance ({adv}%)."
    q, m = values.get("mcq.questions"), values.get("mcq.minutes")
    if isinstance(q, int) and isinstance(m, int) and m * 2 < q:
        errs["mcq.minutes"] = f"Allow at least {-(-q // 2)} minutes for {q} questions (30 seconds each)."
    own, n = values.get("f2f.own_questions"), values.get("f2f.questions")
    if isinstance(own, list) and isinstance(n, int) and len(own) > n:
        errs["f2f.own_questions"] = f"You listed {len(own)} questions but the plan has {n}. Raise the number of questions or remove some."
    return errs


CROSS_KEYS = ["pass.advance", "pass.reject", "mcq.questions", "mcq.minutes", "f2f.questions", "f2f.own_questions"]


def check_change(key, value, **scope):
    """Validate one setting change, including the cross-checks against the other values it will sit with."""
    clean, e = check_value(key, value)
    if e:
        return None, e
    if key in CROSS_KEYS:
        vals = resolve_many(CROSS_KEYS, **scope)
        vals[key] = clean
        ce = cross_errors(vals)
        if ce:
            return None, next(iter(ce.values()))
    return clean, None


def check_round_config(cfg, **scope):
    """Validate a round's own overrides. Returns (clean_cfg, {key: error})."""
    out, errs = {}, {}
    for k, v in (cfg or {}).items():
        if k not in DEFAULTS:
            continue
        clean, e = check_value(k, v)
        if e:
            errs[k] = e
        else:
            out[k] = clean
    if not errs:
        vals = resolve_many(CROSS_KEYS, **scope)
        vals.update({k: v for k, v in out.items() if k in CROSS_KEYS})
        errs.update(cross_errors(vals))
    return out, errs


LEVELS = ["platform", "company", "team", "job"]


def _get(scope_type, scope_id, key):
    return Setting.query.filter_by(scope_type=scope_type, scope_id=scope_id or 0, key=key).first()


def resolve(key, company_id=None, team_id=None, job_id=None, round_cfg=None):
    """Returns (value, source, locked_at)."""
    default = DEFAULTS.get(key, (None,))[0]
    value, source, locked_at = default, "default", None
    chain = [("platform", 0), ("company", company_id), ("team", team_id), ("job", job_id)]
    for scope_type, scope_id in chain:
        if scope_type != "platform" and not scope_id:
            continue
        s = _get(scope_type, scope_id, key)
        if s is not None:
            if locked_at is None:
                value, source = _clamp(key, s.value), scope_type
            if s.locked and locked_at is None:
                locked_at = scope_type
    if round_cfg and key in round_cfg and locked_at is None:
        value, source = _clamp(key, round_cfg[key]), "round"
    return value, source, locked_at


def resolve_many(keys, **scope):
    return {k: resolve(k, **scope)[0] for k in keys}


def effective_table(scope_type, scope_id, company_id=None, team_id=None, job_id=None):
    """Everything a settings screen needs: value, source, locked, editable at this level."""
    rows = []
    idx = LEVELS.index(scope_type)
    for key, (default, group, label, typ, options) in DEFAULTS.items():
        value, source, locked_at = resolve(key, company_id=company_id, team_id=team_id, job_id=job_id)
        own = _get(scope_type, scope_id if scope_type != "platform" else 0, key)
        editable = locked_at is None or LEVELS.index(locked_at) >= idx
        rows.append({**meta(key), "key": key, "group": group, "label": label, "type": typ, "options": options,
                     "value": value, "source": source, "default": default,
                     "overridden_here": own is not None, "locked_here": bool(own and own.locked),
                     "locked_at": locked_at, "editable": editable})
    return rows


def set_value(scope_type, scope_id, key, value, locked=False):
    """Callers validate with check_change() first; this refuses anything that still isn't valid."""
    if key not in DEFAULTS:
        raise ValueError(f"Unknown setting {key}")
    value, e = check_value(key, value)
    if e:
        raise ValueError(e)
    s = _get(scope_type, scope_id if scope_type != "platform" else 0, key)
    if s is None:
        s = Setting(scope_type=scope_type, scope_id=scope_id if scope_type != "platform" else 0, key=key)
        db.session.add(s)
    s.value = value
    s.locked = bool(locked)
    return s


def reset_value(scope_type, scope_id, key):
    s = _get(scope_type, scope_id if scope_type != "platform" else 0, key)
    if s:
        db.session.delete(s)


def platform_secret(key, fallback=""):
    """Secrets stored at platform level (API keys) under a separate namespace."""
    s = Setting.query.filter_by(scope_type="secret", scope_id=0, key=key).first()
    return (s.value if s and s.value else fallback) or ""


def set_secret(key, value):
    s = Setting.query.filter_by(scope_type="secret", scope_id=0, key=key).first()
    if s is None:
        s = Setting(scope_type="secret", scope_id=0, key=key)
        db.session.add(s)
    s.value = value


def report_scale(job):
    """The company's display scale for scores (5, 10 or 100). Scores themselves are always stored out of 5."""
    if not job:
        return 5
    v = resolve("report.scale", company_id=job.company_id, team_id=job.team_id, job_id=job.id)[0]
    try:
        v = int(v)
    except (TypeError, ValueError):
        return 5
    return v if v in (5, 10, 100) else 5
