"""Built-in video call for F2F rounds: call_signals.

Revision ID: 0002_video_call
Revises: 0001_baseline
Create Date: 2026-10-24
"""
import sqlalchemy as sa
from alembic import op

revision = "0002_video_call"
down_revision = "0001_baseline"
branch_labels = None
depends_on = None


def _has_table(name):
    return sa.inspect(op.get_bind()).has_table(name)


def upgrade():
    if _has_table("call_signals"):  # created earlier by the app's automatic upgrade
        return
    op.create_table(
        "call_signals",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("created_at", sa.DateTime, nullable=False),
        sa.Column("attempt_id", sa.Integer, sa.ForeignKey("round_attempts.id", name="fk_call_signals_attempt"), nullable=False),
        sa.Column("sender", sa.String(20), nullable=False),
        sa.Column("kind", sa.String(20), nullable=False),
        sa.Column("payload", sa.JSON),
        mysql_engine="InnoDB", mysql_charset="utf8mb4",
    )
    op.create_index("ix_call_signals_attempt_id", "call_signals", ["attempt_id"])


def downgrade():
    op.drop_table("call_signals")
