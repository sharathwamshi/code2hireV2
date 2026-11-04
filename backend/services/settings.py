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
    # Live video call (F2F rounds)
    "call.enabled": (True, "Video call", "Built-in video call for face-to-face rounds", "bool", None),
    "call.captions": (True, "Video call", "Candidate's browser sends live captions so Isha can analyse each sentence", "bool", None),
    "call.record": (True, "Video call", "Record the call (candidate is told before joining)", "bool", None),
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
    "report.candidate_sections": (["strengths", "gaps", "learning_path"], "Reports", "Sections candidates can see", "list", None),
    # Policies and retention
    "policy.separation_of_duties": (True, "Policies", "Interviewer cannot give the final verdict for the same candidate", "bool", None),
    "policy.reinterview_max": (1, "Policies", "Re-interviews allowed per candidate per job", "int", None),
    "policy.decision_sla_hours": (48, "Policies", "Decision SLA after an interview (hours)", "int", None),
    "retention.days": (180, "Policies", "Delete candidate data N days after the job closes", "int", None),
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
                value, source = s.value, scope_type
            if s.locked and locked_at is None:
                locked_at = scope_type
    if round_cfg and key in round_cfg and locked_at is None:
        value, source = round_cfg[key], "round"
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
        rows.append({"key": key, "group": group, "label": label, "type": typ, "options": options,
                     "value": value, "source": source, "default": default,
                     "overridden_here": own is not None, "locked_here": bool(own and own.locked),
                     "locked_at": locked_at, "editable": editable})
    return rows


def set_value(scope_type, scope_id, key, value, locked=False):
    if key not in DEFAULTS:
        raise ValueError(f"Unknown setting {key}")
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
