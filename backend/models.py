"""All Code2Hire tables. Portable across MySQL 8 (production) and SQLite (local tests)."""
from datetime import datetime
import secrets

from extensions import db


def now():
    return datetime.utcnow()


class Base(db.Model):
    __abstract__ = True
    id = db.Column(db.Integer, primary_key=True)
    created_at = db.Column(db.DateTime, default=now, nullable=False)

    def to_dict(self, exclude=()):
        out = {}
        for c in self.__table__.columns:
            if c.name in exclude:
                continue
            v = getattr(self, c.name)
            out[c.name] = v.isoformat() + "Z" if isinstance(v, datetime) else v
        return out


# ---------------------------------------------------------------- tenancy

class Company(Base):
    __tablename__ = "companies"
    name = db.Column(db.String(160), nullable=False)
    domain = db.Column(db.String(160))
    country = db.Column(db.String(60), default="India")
    timezone = db.Column(db.String(60), default="Asia/Kolkata")
    gst = db.Column(db.String(40))
    plan = db.Column(db.String(30), default="trial")  # trial | employer | agency | enterprise
    status = db.Column(db.String(20), default="trial")  # trial | active | suspended
    credits_total = db.Column(db.Integer, default=500)
    credits_used = db.Column(db.Integer, default=0)
    limits = db.Column(db.JSON, default=dict)   # seats, active_jobs, ai_minutes, isha_hours, storage_days
    flags = db.Column(db.JSON, default=dict)    # public_jobs, ai_interviews, isha, coding, white_label, api
    branding = db.Column(db.JSON, default=dict)  # logo_url, color, email_footer


class Team(Base):
    __tablename__ = "teams"
    company_id = db.Column(db.Integer, db.ForeignKey("companies.id"), nullable=False, index=True)
    name = db.Column(db.String(120), nullable=False)


class User(Base):
    __tablename__ = "users"
    email = db.Column(db.String(190), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(200), nullable=False)
    name = db.Column(db.String(160), nullable=False)
    kind = db.Column(db.String(20), default="staff")  # staff | candidate
    is_superadmin = db.Column(db.Boolean, default=False)
    company_id = db.Column(db.Integer, db.ForeignKey("companies.id"), index=True)
    active = db.Column(db.Boolean, default=True)
    must_change_password = db.Column(db.Boolean, default=False)
    last_login_at = db.Column(db.DateTime)
    skills_meta = db.Column(db.JSON, default=dict)  # interviewer skills and availability

    def public(self):
        return {"id": self.id, "email": self.email, "name": self.name, "kind": self.kind,
                "is_superadmin": self.is_superadmin, "company_id": self.company_id, "active": self.active}


class CustomRole(Base):
    __tablename__ = "custom_roles"
    company_id = db.Column(db.Integer, db.ForeignKey("companies.id"), nullable=False, index=True)
    name = db.Column(db.String(80), nullable=False)
    base_role = db.Column(db.String(40))
    permissions = db.Column(db.JSON, default=list)


class RoleAssignment(Base):
    __tablename__ = "role_assignments"
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    company_id = db.Column(db.Integer, db.ForeignKey("companies.id"), nullable=False, index=True)
    role = db.Column(db.String(60), nullable=False)  # company_admin|manager|recruiter|interviewer|hiring_manager|custom:<id>
    scope_type = db.Column(db.String(20), default="company")  # company | team | job
    scope_id = db.Column(db.Integer)


class Grant(Base):
    __tablename__ = "grants"
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    company_id = db.Column(db.Integer, db.ForeignKey("companies.id"), nullable=False)
    permission = db.Column(db.String(60), nullable=False)
    scope_type = db.Column(db.String(20), default="company")
    scope_id = db.Column(db.Integer)
    expires_at = db.Column(db.DateTime)
    reason = db.Column(db.String(255))
    granted_by = db.Column(db.Integer)
    status = db.Column(db.String(20), default="active")  # active | pending | revoked


class Setting(Base):
    """Configuration that inherits Platform -> Company -> Team -> Job (rounds hold their own config)."""
    __tablename__ = "settings"
    scope_type = db.Column(db.String(20), nullable=False)  # platform | company | team | job
    scope_id = db.Column(db.Integer, default=0)
    key = db.Column(db.String(80), nullable=False)
    value = db.Column(db.JSON)
    locked = db.Column(db.Boolean, default=False)
    __table_args__ = (db.UniqueConstraint("scope_type", "scope_id", "key", name="uq_setting"),)


class Policy(Base):
    __tablename__ = "policies"
    company_id = db.Column(db.Integer, db.ForeignKey("companies.id"), nullable=False, index=True)
    name = db.Column(db.String(160), nullable=False)
    event = db.Column(db.String(60), nullable=False)
    conditions = db.Column(db.JSON, default=list)  # [{field, op, value}]
    action = db.Column(db.String(30), nullable=False)  # require_approval | block | notify
    params = db.Column(db.JSON, default=dict)  # approvals: 2, notify_roles: [...], message
    enabled = db.Column(db.Boolean, default=True)


class Approval(Base):
    __tablename__ = "approvals"
    company_id = db.Column(db.Integer, db.ForeignKey("companies.id"), nullable=False, index=True)
    kind = db.Column(db.String(60), nullable=False)
    ref_type = db.Column(db.String(40))
    ref_id = db.Column(db.Integer)
    title = db.Column(db.String(255))
    requested_by = db.Column(db.Integer)
    approvals_needed = db.Column(db.Integer, default=1)
    approvers = db.Column(db.JSON, default=list)
    status = db.Column(db.String(20), default="pending")  # pending | approved | rejected
    note = db.Column(db.Text)
    payload = db.Column(db.JSON, default=dict)


class AuditLog(Base):
    __tablename__ = "audit_logs"
    company_id = db.Column(db.Integer, index=True)
    actor_id = db.Column(db.Integer, index=True)
    action = db.Column(db.String(80), nullable=False)
    target_type = db.Column(db.String(40))
    target_id = db.Column(db.Integer)
    detail = db.Column(db.JSON, default=dict)


class Notification(Base):
    __tablename__ = "notifications"
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    title = db.Column(db.String(200), nullable=False)
    body = db.Column(db.Text)
    link = db.Column(db.String(255))
    read = db.Column(db.Boolean, default=False)


# ---------------------------------------------------------------- hiring

class HiringTemplate(Base):
    __tablename__ = "hiring_templates"
    company_id = db.Column(db.Integer, index=True)  # null = global (Superadmin) template
    team_id = db.Column(db.Integer)
    name = db.Column(db.String(160), nullable=False)
    description = db.Column(db.Text)
    rounds = db.Column(db.JSON, default=list)  # [{type, name, config:{}, pass:{advance, reject}}]
    rubric = db.Column(db.JSON, default=list)  # [{name, weight, levels:{strong, meets, weak}}]
    created_by = db.Column(db.Integer)
    updated_by = db.Column(db.Integer)
    updated_at = db.Column(db.DateTime)
    archived = db.Column(db.Boolean, default=False)  # hidden from "start from a template"; jobs made from it are untouched


class Job(Base):
    __tablename__ = "jobs"
    company_id = db.Column(db.Integer, db.ForeignKey("companies.id"), nullable=False, index=True)
    team_id = db.Column(db.Integer, db.ForeignKey("teams.id"))
    title = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text)
    skills = db.Column(db.JSON, default=list)  # [{name, level, must}]
    level = db.Column(db.String(60))
    location = db.Column(db.String(120))
    work_mode = db.Column(db.String(30), default="hybrid")
    salary_min = db.Column(db.Integer)
    salary_max = db.Column(db.Integer)
    salary_visible = db.Column(db.Boolean, default=False)
    visibility = db.Column(db.String(20), default="private")  # public | private | internal
    status = db.Column(db.String(30), default="draft")  # draft | pending_approval | live | closed
    rounds = db.Column(db.JSON, default=list)
    rubric = db.Column(db.JSON, default=list)
    plan = db.Column(db.JSON, default=dict)  # AI draft: questions, summary
    client_name = db.Column(db.String(160))
    client_hidden = db.Column(db.Boolean, default=False)
    invite_token = db.Column(db.String(40), default=lambda: secrets.token_urlsafe(12), index=True)
    hires_target = db.Column(db.Integer, default=1)
    deadline = db.Column(db.Date)
    credit_budget = db.Column(db.Integer)
    created_by = db.Column(db.Integer)


class JobAssignment(Base):
    __tablename__ = "job_assignments"
    job_id = db.Column(db.Integer, db.ForeignKey("jobs.id"), nullable=False, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    role = db.Column(db.String(30), default="recruiter")  # recruiter | interviewer | hiring_manager


class CandidateProfile(Base):
    __tablename__ = "candidate_profiles"
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), unique=True, nullable=False)
    headline = db.Column(db.String(200))
    location = db.Column(db.String(120))
    phone = db.Column(db.String(40))
    resume_text = db.Column(db.Text)
    experience_years = db.Column(db.Float)
    skills = db.Column(db.JSON, default=list)  # [{name, level, verified, source}]
    target_roles = db.Column(db.JSON, default=list)
    visibility = db.Column(db.String(20), default="applied")  # everyone | applied | nobody
    source_company_id = db.Column(db.Integer, index=True)  # company whose team added this candidate
    added_by = db.Column(db.Integer)


class InviteLink(Base):
    """Personal link that opens a person's portal without a password, until they set one or it expires."""
    __tablename__ = "invite_links"
    token_hash = db.Column(db.String(64), unique=True, nullable=False, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    company_id = db.Column(db.Integer, index=True)
    job_id = db.Column(db.Integer)
    purpose = db.Column(db.String(20), default="candidate")  # candidate | staff
    created_by = db.Column(db.Integer)
    expires_at = db.Column(db.DateTime, nullable=False)
    opened_at = db.Column(db.DateTime)
    used_at = db.Column(db.DateTime)  # password set; link no longer works
    revoked = db.Column(db.Boolean, default=False)
    shared_at = db.Column(db.DateTime)  # the hiring team copied or sent it (so "Sent" is never shown before anything goes out)
    shared_via = db.Column(db.String(20))  # copy | message | email | manual


class LoginThrottle(Base):
    """Failed sign-in counter per key ("email:<address>" or "ip:<address>"), shared by every server worker."""
    __tablename__ = "login_throttles"
    key = db.Column(db.String(190), unique=True, nullable=False, index=True)
    failures = db.Column(db.Integer, default=0, nullable=False)
    window_start = db.Column(db.DateTime)
    locked_until = db.Column(db.DateTime)


class Application(Base):
    __tablename__ = "applications"
    job_id = db.Column(db.Integer, db.ForeignKey("jobs.id"), nullable=False, index=True)
    candidate_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    stage = db.Column(db.String(30), default="applied")
    # applied | shortlisted | in_round | awaiting_review | decision | offer | hired | rejected | on_hold | withdrawn
    current_round = db.Column(db.Integer, default=-1)
    match_score = db.Column(db.Integer)
    match_reasons = db.Column(db.JSON, default=dict)
    source = db.Column(db.String(30), default="applied")  # applied | invited | bulk | pool
    owner_id = db.Column(db.Integer)
    verdict = db.Column(db.String(30))
    verdict_by = db.Column(db.Integer)
    verdict_note = db.Column(db.Text)
    notes = db.Column(db.JSON, default=list)
    updated_at = db.Column(db.DateTime, default=now, onupdate=now)
    __table_args__ = (db.UniqueConstraint("job_id", "candidate_id", name="uq_app"),)


class RoundAttempt(Base):
    __tablename__ = "round_attempts"
    application_id = db.Column(db.Integer, db.ForeignKey("applications.id"), index=True)
    cert_attempt_id = db.Column(db.Integer)  # set when the attempt belongs to a certification exam
    practice_user_id = db.Column(db.Integer)  # set for practice / mock interviews
    round_index = db.Column(db.Integer, default=0)
    round_type = db.Column(db.String(30), nullable=False)  # mcq | ai_interview | f2f_isha | f2f_human
    config = db.Column(db.JSON, default=dict)  # resolved settings at invite time
    status = db.Column(db.String(30), default="invited")
    # invited | scheduled | in_progress | paused | completed | reviewed | expired
    score = db.Column(db.Float)
    result = db.Column(db.JSON, default=dict)
    interviewer_id = db.Column(db.Integer)
    scheduled_at = db.Column(db.DateTime)
    deadline_at = db.Column(db.DateTime)
    started_at = db.Column(db.DateTime)
    completed_at = db.Column(db.DateTime)
    warnings = db.Column(db.Integer, default=0)
    consent_at = db.Column(db.DateTime)
    pause_reason = db.Column(db.String(200))
    voice = db.Column(db.String(80))
    brief = db.Column(db.JSON, default=dict)  # Isha plan for F2F


class QuestionFolder(Base):
    """Category folders for the question bank. Nested through parent_id. company_id null = global bank."""
    __tablename__ = "question_folders"
    company_id = db.Column(db.Integer, index=True)
    parent_id = db.Column(db.Integer, index=True)
    name = db.Column(db.String(120), nullable=False)
    description = db.Column(db.String(255))
    created_by = db.Column(db.Integer)


class Question(Base):
    __tablename__ = "questions"
    company_id = db.Column(db.Integer, index=True)  # null = global bank
    folder_id = db.Column(db.Integer, index=True)
    version = db.Column(db.Integer, default=1)
    tags = db.Column(db.JSON, default=list)
    time_seconds = db.Column(db.Integer)  # suggested time; informational
    updated_by = db.Column(db.Integer)
    updated_at = db.Column(db.DateTime, default=now, onupdate=now)
    skill = db.Column(db.String(80), index=True)
    level = db.Column(db.Integer, default=2)
    text = db.Column(db.Text, nullable=False)
    code = db.Column(db.Text)
    options = db.Column(db.JSON, default=list)
    answer = db.Column(db.Integer, default=0)
    explanation = db.Column(db.Text)
    status = db.Column(db.String(20), default="approved")  # approved | pending | rejected | archived
    source = db.Column(db.String(20), default="manual")  # manual | ai | import

    CONTENT = ("text", "code", "options", "answer", "explanation", "skill", "level", "tags", "time_seconds")

    def snapshot(self):
        return {k: getattr(self, k) for k in self.CONTENT}


class QuestionVersion(Base):
    """Every saved version of a question's content, so edits never change history."""
    __tablename__ = "question_versions"
    question_id = db.Column(db.Integer, db.ForeignKey("questions.id"), nullable=False, index=True)
    version = db.Column(db.Integer, nullable=False)
    snapshot = db.Column(db.JSON, default=dict)
    note = db.Column(db.String(255))
    changed_by = db.Column(db.Integer)


class Turn(Base):
    __tablename__ = "turns"
    attempt_id = db.Column(db.Integer, db.ForeignKey("round_attempts.id"), nullable=False, index=True)
    seq = db.Column(db.Integer, default=0)
    speaker = db.Column(db.String(20))  # ai | candidate | interviewer | system
    text = db.Column(db.Text)
    topic = db.Column(db.String(120))
    analysis = db.Column(db.JSON, default=dict)
    at_seconds = db.Column(db.Integer)


class IntegrityEvent(Base):
    __tablename__ = "integrity_events"
    attempt_id = db.Column(db.Integer, db.ForeignKey("round_attempts.id"), nullable=False, index=True)
    event_type = db.Column(db.String(30), nullable=False)
    severity = db.Column(db.String(10), default="medium")
    counted = db.Column(db.Boolean, default=True)
    question_index = db.Column(db.Integer)
    note = db.Column(db.String(255))


class CallSignal(Base):
    """WebRTC signalling and in-call messages for live F2F rounds (offer, answer, ice, join, ready, bye, chat, caption, focus)."""
    __tablename__ = "call_signals"
    attempt_id = db.Column(db.Integer, db.ForeignKey("round_attempts.id"), nullable=False, index=True)
    sender = db.Column(db.String(20), nullable=False)  # candidate | interviewer
    kind = db.Column(db.String(20), nullable=False)
    payload = db.Column(db.JSON, default=dict)


class Recording(Base):
    """One continuous piece of an interview video from one side. A new piece starts whenever recording restarts
    (rejoin, reconnect, reload). Chunks are appended to `raw_key` as they arrive; when the piece is finished the server
    remuxes it into `file_key` so it can be scrubbed."""
    __tablename__ = "recordings"
    attempt_id = db.Column(db.Integer, db.ForeignKey("round_attempts.id"), nullable=False, index=True)
    side = db.Column(db.String(20), nullable=False)  # interviewer | candidate
    segment = db.Column(db.String(40), nullable=False)  # chosen by the recording browser, unique per attempt
    mime = db.Column(db.String(60), default="video/webm")
    started_at = db.Column(db.DateTime)  # UTC wall clock of the first chunk
    last_at = db.Column(db.DateTime)  # UTC wall clock of the newest chunk
    seconds = db.Column(db.Float, default=0)
    bytes = db.Column(db.BigInteger, default=0)
    next_seq = db.Column(db.Integer, default=0)
    status = db.Column(db.String(20), default="recording")  # recording | processing | ready | failed | deleted
    raw_key = db.Column(db.String(255))
    file_key = db.Column(db.String(255))
    storage = db.Column(db.String(20), default="local")  # local | azure
    note = db.Column(db.String(255))
    deleted_at = db.Column(db.DateTime)
    __table_args__ = (db.UniqueConstraint("attempt_id", "segment", name="uq_recording_segment"),)


class SystemCheck(Base):
    """One run of the system check before an interview (V02.00.05), or of "Test my setup" (attempt_id empty).
    steps: {key: {"status": "pass" | "fail" | "warn" | "skip", "detail": "..."}}.
    device: camera / microphone / speaker names, browser, OS and the internet measurement."""
    __tablename__ = "system_checks"
    attempt_id = db.Column(db.Integer, db.ForeignKey("round_attempts.id"), index=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    role = db.Column(db.String(20), nullable=False, default="candidate")  # candidate | interviewer
    mode = db.Column(db.String(20), default="full")  # full | recheck | test
    passed = db.Column(db.Boolean, default=False, nullable=False)
    steps = db.Column(db.JSON, default=dict)
    device = db.Column(db.JSON, default=dict)
    user_agent = db.Column(db.String(400))
    help_step = db.Column(db.String(30))  # set when the person pressed "I need help"
    help_note = db.Column(db.String(500))


class AssistantMessage(Base):
    """The "Ask Hira" chat for hiring teams: one row per question or answer, kept per person."""
    __tablename__ = "assistant_messages"
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    company_id = db.Column(db.Integer, index=True)
    role = db.Column(db.String(10), nullable=False)  # user | hira
    text = db.Column(db.Text, nullable=False)
    intent = db.Column(db.String(40))
    data = db.Column(db.JSON, default=dict)  # items and links shown under an answer


class Report(Base):
    __tablename__ = "reports"
    attempt_id = db.Column(db.Integer, db.ForeignKey("round_attempts.id"), unique=True, nullable=False)
    status = db.Column(db.String(30), default="awaiting_review")  # awaiting_review | reviewed | shared
    overall = db.Column(db.Float)
    recommendation = db.Column(db.String(30))
    confidence = db.Column(db.String(20))
    sections = db.Column(db.JSON, default=dict)
    original = db.Column(db.JSON, default=dict)
    version = db.Column(db.Integer, default=1)
    history = db.Column(db.JSON, default=list)
    reviewer_id = db.Column(db.Integer)
    verdict = db.Column(db.String(30))
    note = db.Column(db.Text)
    reviewed_at = db.Column(db.DateTime)
    shared_with_candidate = db.Column(db.Boolean, default=False)
    share_token = db.Column(db.String(40))
    share_expires_at = db.Column(db.DateTime)
    share_audience = db.Column(db.String(20))
    candidate_feedback = db.Column(db.JSON, default=dict)
    disputed = db.Column(db.Boolean, default=False)
    dispute_note = db.Column(db.Text)
    disputed_at = db.Column(db.DateTime)
    dispute_status = db.Column(db.String(20))  # open | reinterview | changed | dismissed
    dispute_resolution = db.Column(db.Text)  # what the reviewer decided, sent to the candidate
    dispute_resolved_by = db.Column(db.Integer)
    dispute_resolved_at = db.Column(db.DateTime)


# ---------------------------------------------------------------- certifications and growth

class Certification(Base):
    __tablename__ = "certifications"
    company_id = db.Column(db.Integer, index=True)  # null = Code2Hire Verified
    name = db.Column(db.String(200), nullable=False)
    skills = db.Column(db.JSON, default=list)
    level = db.Column(db.Integer, default=3)
    issuer = db.Column(db.String(160))
    sections = db.Column(db.JSON, default=list)  # [{type, weight, questions, minutes, minimum}]
    pass_rules = db.Column(db.JSON, default=dict)  # {cutoff, merit, distinction}
    proctoring = db.Column(db.String(20), default="ai")  # none | ai | ai_human
    id_check = db.Column(db.Boolean, default=False)
    eligibility = db.Column(db.JSON, default=dict)  # {prerequisite_skill, prerequisite_level, audience}
    fee = db.Column(db.Integer, default=0)
    attempts_allowed = db.Column(db.Integer, default=2)
    cooldown_days = db.Column(db.Integer, default=14)
    validity_months = db.Column(db.Integer, default=12)
    output = db.Column(db.JSON, default=dict)  # {verification_page, linkedin, badge, revoke_on_integrity}
    status = db.Column(db.String(20), default="draft")  # draft | review | published | retired
    created_by = db.Column(db.Integer)


class CertAttempt(Base):
    __tablename__ = "cert_attempts"
    cert_id = db.Column(db.Integer, db.ForeignKey("certifications.id"), nullable=False, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    status = db.Column(db.String(20), default="in_progress")  # in_progress | completed | review
    score = db.Column(db.Float)
    section_scores = db.Column(db.JSON, default=dict)
    grade = db.Column(db.String(20))
    passed = db.Column(db.Boolean)


class Credential(Base):
    __tablename__ = "credentials"
    code = db.Column(db.String(40), unique=True, nullable=False, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    cert_id = db.Column(db.Integer)
    kind = db.Column(db.String(20), default="badge")  # badge | certificate | course
    title = db.Column(db.String(200))
    skill = db.Column(db.String(80))
    level = db.Column(db.Integer)
    grade = db.Column(db.String(20))
    issuer = db.Column(db.String(160))
    expires_at = db.Column(db.DateTime)
    revoked = db.Column(db.Boolean, default=False)
    revoke_reason = db.Column(db.String(255))


class LearningPath(Base):
    __tablename__ = "learning_paths"
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    title = db.Column(db.String(200))
    skill = db.Column(db.String(80))
    topics = db.Column(db.JSON, default=list)  # [{title, summary, practice:[...], done}]
    reason = db.Column(db.String(255))


class SavedView(Base):
    __tablename__ = "saved_views"
    user_id = db.Column(db.Integer, nullable=False, index=True)
    table = db.Column(db.String(40), nullable=False)
    name = db.Column(db.String(80), nullable=False)
    params = db.Column(db.JSON, default=dict)
    shared_team_id = db.Column(db.Integer)


class SavedReport(Base):
    __tablename__ = "saved_reports"
    company_id = db.Column(db.Integer, index=True)
    user_id = db.Column(db.Integer)
    name = db.Column(db.String(160))
    spec = db.Column(db.JSON, default=dict)  # {source, measure, group_by, filters, chart, hide_fields, schedule}
