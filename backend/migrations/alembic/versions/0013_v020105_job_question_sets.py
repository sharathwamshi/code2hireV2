"""V02.01.05: a job's own set of interview questions.

questions.job_id  set on interview questions the hiring team kept for a job ("Keep for this job"). The next
                  candidates for that job get these first, already selected; Claude only writes what's missing.
Safe to re-run.

Revision ID: 0013_v020105_job_question_sets
Revises: 0012_v020104_interview_questions
Create Date: 2026-11-24
"""
import sqlalchemy as sa
from alembic import op

revision = "0013_v020105_job_question_sets"
down_revision = "0012_v020104_interview_questions"
branch_labels = None
depends_on = None


def upgrade():
    insp = sa.inspect(op.get_bind())
    cols = {c["name"] for c in insp.get_columns("questions")}
    if "job_id" not in cols:
        op.add_column("questions", sa.Column("job_id", sa.Integer, nullable=True))
        op.create_index("ix_questions_job_id", "questions", ["job_id"])


def downgrade():
    insp = sa.inspect(op.get_bind())
    cols = {c["name"] for c in insp.get_columns("questions")}
    if "job_id" in cols:
        op.drop_index("ix_questions_job_id", table_name="questions")
        op.drop_column("questions", "job_id")
