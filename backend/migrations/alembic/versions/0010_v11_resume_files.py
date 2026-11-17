"""V02.00.11: resume_files table (kept resume uploads, with versions) and jobs.history (edit history).

Revision ID: 0010_v11_resume_files
Revises: 0009_v10_candidate_portal
Create Date: 2026-11-17
"""
import sqlalchemy as sa
from alembic import op

revision = "0010_v11_resume_files"
down_revision = "0009_v10_candidate_portal"
branch_labels = None
depends_on = None


def upgrade():
    insp = sa.inspect(op.get_bind())
    if "resume_files" not in insp.get_table_names():
        op.create_table("resume_files",
                        sa.Column("id", sa.Integer, primary_key=True),
                        sa.Column("created_at", sa.DateTime, nullable=False),
                        sa.Column("user_id", sa.Integer, sa.ForeignKey("users.id"), nullable=False),
                        sa.Column("filename", sa.String(200), nullable=False),
                        sa.Column("kind", sa.String(8), nullable=False),
                        sa.Column("size", sa.Integer, nullable=True),
                        sa.Column("file_key", sa.String(80), nullable=False),
                        sa.Column("chars", sa.Integer, nullable=True),
                        sa.Column("status", sa.String(12), nullable=False),
                        sa.Column("uploaded_by", sa.Integer, nullable=True))
        op.create_index("ix_resume_files_user_id", "resume_files", ["user_id"])
        op.create_index("ix_resume_files_status", "resume_files", ["status"])
    if "history" not in {c["name"] for c in insp.get_columns("jobs")}:
        op.add_column("jobs", sa.Column("history", sa.JSON, nullable=True))


def downgrade():
    op.execute("UPDATE jobs SET status = 'closed' WHERE status = 'archived'")
    insp = sa.inspect(op.get_bind())
    if "resume_files" in insp.get_table_names():
        op.drop_table("resume_files")
    if "history" in {c["name"] for c in insp.get_columns("jobs")}:
        op.drop_column("jobs", "history")
