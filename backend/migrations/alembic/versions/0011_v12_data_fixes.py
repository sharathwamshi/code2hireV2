"""V02.00.12: data fixes only, no schema change.

Rebalances the question bank's answer positions (the right answer was nearly always B), freezes the questions of old
MCQ attempts first so their grading can't change, and records who sent each round invite (from the audit log).
See services/data_v12.py. Safe to re-run.

Revision ID: 0011_v12_data_fixes
Revises: 0010_v11_resume_files
Create Date: 2026-11-18
"""
from alembic import op

revision = "0011_v12_data_fixes"
down_revision = "0010_v11_resume_files"
branch_labels = None
depends_on = None


def upgrade():
    from services.data_v12 import run
    print("V02.00.12 data fixes:", run(op.get_bind()))


def downgrade():
    # Data only. The reordered questions keep their new order (every earlier version is in question_versions), and
    # invited_by is an extra key nobody older reads.
    pass
