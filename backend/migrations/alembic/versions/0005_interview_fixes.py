"""Interview bug fixes (BUG-001 to 007) and interview videos (NEW-001): recordings table + data fixes.

Revision ID: 0005_interview_fixes
Revises: 0004_beta_fixes
Create Date: 2026-11-05
"""
import json

import sqlalchemy as sa
from alembic import op

revision = "0005_interview_fixes"
down_revision = "0004_beta_fixes"
branch_labels = None
depends_on = None

RANGES = {"voice.silence_seconds": (2, 30), "mcq.questions": (1, 100), "mcq.minutes": (1, 240), "interview.questions": (1, 20),
          "interview.followup_depth": (0, 5), "interview.minutes": (5, 180), "interview.attempts": (1, 5), "pass.advance": (0, 100),
          "pass.reject": (0, 100), "integrity.warnings_allowed": (0, 20), "isha.options": (2, 6), "f2f.questions": (1, 30),
          "call.join_early_minutes": (0, 120), "report.auto_share_days": (0, 90), "policy.reinterview_max": (0, 5),
          "policy.decision_sla_hours": (1, 720), "retention.days": (30, 3650), "recording.retention_days": (30, 730),
          "invite.link_days": (1, 90), "cert.validity_months": (1, 60), "cert.cooldown_days": (0, 365)}


def _load(v):
    if isinstance(v, (str, bytes)):
        try:
            return json.loads(v)
        except ValueError:
            return v
    return v


def upgrade():
    insp = sa.inspect(op.get_bind())
    if not insp.has_table("recordings"):
        op.create_table(
            "recordings",
            sa.Column("id", sa.Integer, primary_key=True),
            sa.Column("created_at", sa.DateTime, nullable=False),
            sa.Column("attempt_id", sa.Integer, sa.ForeignKey("round_attempts.id", name="fk_recordings_attempt"), nullable=False),
            sa.Column("side", sa.String(20), nullable=False),
            sa.Column("segment", sa.String(40), nullable=False),
            sa.Column("mime", sa.String(60)), sa.Column("started_at", sa.DateTime), sa.Column("last_at", sa.DateTime),
            sa.Column("seconds", sa.Float), sa.Column("bytes", sa.BigInteger), sa.Column("next_seq", sa.Integer),
            sa.Column("status", sa.String(20)), sa.Column("raw_key", sa.String(255)), sa.Column("file_key", sa.String(255)),
            sa.Column("storage", sa.String(20)), sa.Column("note", sa.String(255)), sa.Column("deleted_at", sa.DateTime),
            sa.UniqueConstraint("attempt_id", "segment", name="uq_recording_segment"),
            mysql_engine="InnoDB", mysql_charset="utf8mb4",
        )
        op.create_index("ix_recordings_attempt_id", "recordings", ["attempt_id"])
    b = op.get_bind()

    # legacy recordings (result.recording) -> rows
    have = {(a, s) for a, s in b.execute(sa.text("SELECT attempt_id, segment FROM recordings")).fetchall()}
    for aid, res, started, completed, created in b.execute(sa.text(
            "SELECT id, result, started_at, completed_at, created_at FROM round_attempts WHERE result IS NOT NULL")).fetchall():
        parts = (_load(res) or {}).get("recording") if isinstance(_load(res), dict) else None
        for i, p in enumerate(parts or []):
            if (aid, f"legacy{i}") in have or not p.get("file"):
                continue
            b.execute(sa.text("INSERT INTO recordings (created_at, attempt_id, side, segment, mime, started_at, last_at, seconds, bytes, "
                              "next_seq, status, file_key, storage, note) VALUES (:c, :a, 'interviewer', :seg, 'video/webm', :s, :l, :sec, "
                              ":by, 1, 'ready', :f, 'local', 'Recorded before V02.00.04')"),
                      {"c": completed or created, "a": aid, "seg": f"legacy{i}", "s": started, "l": completed or started,
                       "sec": p.get("seconds"), "by": p.get("bytes"), "f": p["file"]})

    # number settings inside their limits; non-numbers removed
    for sid, key, value in b.execute(sa.text("SELECT id, `key`, value FROM settings" if b.dialect.name == "mysql"
                                             else 'SELECT id, "key", value FROM settings')).fetchall():
        if key == "call.record":
            b.execute(sa.text("DELETE FROM settings WHERE id = :i"), {"i": sid})
            continue
        if key not in RANGES:
            continue
        lo, hi = RANGES[key]
        v = _load(value)
        try:
            n = int(float(v))
            if isinstance(v, bool) or float(v) != n:
                raise ValueError
        except (TypeError, ValueError):
            b.execute(sa.text("DELETE FROM settings WHERE id = :i"), {"i": sid})
            continue
        if not lo <= n <= hi:
            b.execute(sa.text("UPDATE settings SET value = :v WHERE id = :i"), {"v": json.dumps(min(hi, max(lo, n))), "i": sid})

    # duplicate questions (same text, same bank) archived, keeping the newest
    keep = {}
    rows = b.execute(sa.text("SELECT id, company_id, text FROM questions WHERE status <> 'archived' ORDER BY id DESC")).fetchall()
    for qid, cid, text in rows:
        k = (cid or 0, (text or "").strip().lower())
        if k in keep:
            b.execute(sa.text("UPDATE questions SET status = 'archived' WHERE id = :i"), {"i": qid})
        else:
            keep[k] = qid


def downgrade():
    insp = sa.inspect(op.get_bind())
    if insp.has_table("recordings"):
        op.drop_table("recordings")
