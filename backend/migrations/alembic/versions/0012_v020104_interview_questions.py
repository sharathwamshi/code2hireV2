"""V02.01.04: the question bank also keeps interview questions.

questions.kind  "mcq" (every existing row) or "interview": a spoken question Isha or Claude wrote for a live interview
questions.meta  for interview questions: {"type", "good": [points a good answer covers], "model": model answer,
                "followups": [...], "section"}

MCQ tests only ever draw kind = "mcq". Safe to re-run.

Revision ID: 0012_v020104_interview_questions
Revises: 0011_v12_data_fixes
Create Date: 2026-11-24
"""
import sqlalchemy as sa
from alembic import op

revision = "0012_v020104_interview_questions"
down_revision = "0011_v12_data_fixes"
branch_labels = None
depends_on = None


def upgrade():
    insp = sa.inspect(op.get_bind())
    cols = {c["name"] for c in insp.get_columns("questions")}
    if "kind" not in cols:
        op.add_column("questions", sa.Column("kind", sa.String(20), nullable=False, server_default="mcq"))
        op.create_index("ix_questions_kind", "questions", ["kind"])
    if "meta" not in cols:
        op.add_column("questions", sa.Column("meta", sa.JSON, nullable=True))


def downgrade():
    insp = sa.inspect(op.get_bind())
    cols = {c["name"] for c in insp.get_columns("questions")}
    if "kind" in cols:
        op.execute("DELETE FROM question_versions WHERE question_id IN (SELECT id FROM questions WHERE kind = 'interview')")
        op.execute("DELETE FROM questions WHERE kind = 'interview'")
        op.drop_index("ix_questions_kind", table_name="questions")
        op.drop_column("questions", "kind")
    if "meta" in cols:
        op.drop_column("questions", "meta")
