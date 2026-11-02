"""Question bank folders and versions; candidates added by hiring teams; personal portal links.

Revision ID: 0003_qbank_links
Revises: 0002_video_call
Create Date: 2026-10-29
"""
import sqlalchemy as sa
from alembic import op

revision = "0003_qbank_links"
down_revision = "0002_video_call"
branch_labels = None
depends_on = None


def _insp():
    return sa.inspect(op.get_bind())


def _cols(table):
    return {c["name"] for c in _insp().get_columns(table)}


def _idx(table):
    return {i["name"] for i in _insp().get_indexes(table)}


def upgrade():
    insp = _insp()
    if not insp.has_table("question_folders"):
        op.create_table(
            "question_folders",
            sa.Column("id", sa.Integer, primary_key=True),
            sa.Column("created_at", sa.DateTime, nullable=False),
            sa.Column("company_id", sa.Integer),
            sa.Column("parent_id", sa.Integer),
            sa.Column("name", sa.String(120), nullable=False),
            sa.Column("description", sa.String(255)),
            sa.Column("created_by", sa.Integer),
            mysql_engine="InnoDB", mysql_charset="utf8mb4",
        )
        op.create_index("ix_question_folders_company_id", "question_folders", ["company_id"])
        op.create_index("ix_question_folders_parent_id", "question_folders", ["parent_id"])

    have = _cols("questions")
    for name, typ in [("folder_id", sa.Integer), ("version", sa.Integer), ("tags", sa.JSON), ("time_seconds", sa.Integer),
                      ("updated_by", sa.Integer), ("updated_at", sa.DateTime)]:
        if name not in have:
            op.add_column("questions", sa.Column(name, typ, nullable=True))
    if "ix_questions_folder_id" not in _idx("questions"):
        op.create_index("ix_questions_folder_id", "questions", ["folder_id"])

    if not insp.has_table("question_versions"):
        op.create_table(
            "question_versions",
            sa.Column("id", sa.Integer, primary_key=True),
            sa.Column("created_at", sa.DateTime, nullable=False),
            sa.Column("question_id", sa.Integer, sa.ForeignKey("questions.id", name="fk_question_versions_question"), nullable=False),
            sa.Column("version", sa.Integer, nullable=False),
            sa.Column("snapshot", sa.JSON),
            sa.Column("note", sa.String(255)),
            sa.Column("changed_by", sa.Integer),
            mysql_engine="InnoDB", mysql_charset="utf8mb4",
        )
        op.create_index("ix_question_versions_question_id", "question_versions", ["question_id"])

    have = _cols("candidate_profiles")
    for name in ("source_company_id", "added_by"):
        if name not in have:
            op.add_column("candidate_profiles", sa.Column(name, sa.Integer, nullable=True))
    if "ix_candidate_profiles_source_company_id" not in _idx("candidate_profiles"):
        op.create_index("ix_candidate_profiles_source_company_id", "candidate_profiles", ["source_company_id"])

    if not insp.has_table("invite_links"):
        op.create_table(
            "invite_links",
            sa.Column("id", sa.Integer, primary_key=True),
            sa.Column("created_at", sa.DateTime, nullable=False),
            sa.Column("token_hash", sa.String(64), nullable=False),
            sa.Column("user_id", sa.Integer, sa.ForeignKey("users.id", name="fk_invite_links_user"), nullable=False),
            sa.Column("company_id", sa.Integer),
            sa.Column("job_id", sa.Integer),
            sa.Column("purpose", sa.String(20)),
            sa.Column("created_by", sa.Integer),
            sa.Column("expires_at", sa.DateTime, nullable=False),
            sa.Column("opened_at", sa.DateTime),
            sa.Column("used_at", sa.DateTime),
            sa.Column("revoked", sa.Boolean),
            mysql_engine="InnoDB", mysql_charset="utf8mb4",
        )
        op.create_index("ix_invite_links_token_hash", "invite_links", ["token_hash"], unique=True)
        op.create_index("ix_invite_links_user_id", "invite_links", ["user_id"])
        op.create_index("ix_invite_links_company_id", "invite_links", ["company_id"])

    # data: existing questions become version 1 with a history entry (portable, done in Python)
    bind = op.get_bind()
    bind.execute(sa.text("UPDATE questions SET version = 1 WHERE version IS NULL"))
    bind.execute(sa.text("UPDATE questions SET updated_at = created_at WHERE updated_at IS NULL"))
    q = sa.table("questions", sa.column("id"), sa.column("text"), sa.column("code"), sa.column("options", sa.JSON), sa.column("answer"),
                 sa.column("explanation"), sa.column("skill"), sa.column("level"), sa.column("tags", sa.JSON))
    v = sa.table("question_versions", sa.column("created_at"), sa.column("question_id"), sa.column("version"),
                 sa.column("snapshot", sa.JSON), sa.column("note"))
    done = {r[0] for r in bind.execute(sa.text("SELECT DISTINCT question_id FROM question_versions"))}
    rows, now = [], sa.func.now()
    for r in bind.execute(sa.select(q)).mappings():
        if r["tags"] is None:
            bind.execute(sa.update(q).where(q.c.id == r["id"]).values(tags=[]))
        if r["id"] in done:
            continue
        rows.append({"question_id": r["id"], "version": 1, "note": "Original (before versioning)",
                     "snapshot": {"text": r["text"], "code": r["code"], "options": r["options"], "answer": r["answer"],
                                  "explanation": r["explanation"], "skill": r["skill"], "level": r["level"], "tags": [], "time_seconds": None}})
    if rows:
        from datetime import datetime
        for x in rows:
            x["created_at"] = datetime.utcnow()
        op.bulk_insert(v, rows)


def downgrade():
    op.drop_table("invite_links")
    op.drop_table("question_versions")
    op.drop_index("ix_candidate_profiles_source_company_id", table_name="candidate_profiles")
    op.drop_column("candidate_profiles", "added_by")
    op.drop_column("candidate_profiles", "source_company_id")
    op.drop_index("ix_questions_folder_id", table_name="questions")
    for c in ("updated_at", "updated_by", "time_seconds", "tags", "version", "folder_id"):
        op.drop_column("questions", c)
    op.drop_table("question_folders")
