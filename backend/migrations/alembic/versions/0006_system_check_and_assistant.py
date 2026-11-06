"""System check before interviews and "Ask Hira" (V02.00.05): system_checks and assistant_messages tables.

Revision ID: 0006_system_check_and_assistant
Revises: 0005_interview_fixes
Create Date: 2026-11-06
"""
import sqlalchemy as sa
from alembic import op

revision = "0006_system_check_and_assistant"
down_revision = "0005_interview_fixes"
branch_labels = None
depends_on = None


def upgrade():
    insp = sa.inspect(op.get_bind())
    if not insp.has_table("system_checks"):
        op.create_table(
            "system_checks",
            sa.Column("id", sa.Integer, primary_key=True),
            sa.Column("created_at", sa.DateTime, nullable=False),
            sa.Column("attempt_id", sa.Integer, sa.ForeignKey("round_attempts.id", name="fk_system_checks_attempt")),
            sa.Column("user_id", sa.Integer, sa.ForeignKey("users.id", name="fk_system_checks_user"), nullable=False),
            sa.Column("role", sa.String(20), nullable=False),
            sa.Column("mode", sa.String(20)),
            sa.Column("passed", sa.Boolean, nullable=False),
            sa.Column("steps", sa.JSON), sa.Column("device", sa.JSON),
            sa.Column("user_agent", sa.String(400)), sa.Column("help_step", sa.String(30)), sa.Column("help_note", sa.String(500)),
            mysql_engine="InnoDB", mysql_charset="utf8mb4",
        )
        op.create_index("ix_system_checks_attempt_id", "system_checks", ["attempt_id"])
        op.create_index("ix_system_checks_user_id", "system_checks", ["user_id"])
    if not insp.has_table("assistant_messages"):
        op.create_table(
            "assistant_messages",
            sa.Column("id", sa.Integer, primary_key=True),
            sa.Column("created_at", sa.DateTime, nullable=False),
            sa.Column("user_id", sa.Integer, sa.ForeignKey("users.id", name="fk_assistant_messages_user"), nullable=False),
            sa.Column("company_id", sa.Integer),
            sa.Column("role", sa.String(10), nullable=False),
            sa.Column("text", sa.Text, nullable=False),
            sa.Column("intent", sa.String(40)),
            sa.Column("data", sa.JSON),
            mysql_engine="InnoDB", mysql_charset="utf8mb4",
        )
        op.create_index("ix_assistant_messages_user_id", "assistant_messages", ["user_id"])
        op.create_index("ix_assistant_messages_company_id", "assistant_messages", ["company_id"])


def downgrade():
    insp = sa.inspect(op.get_bind())
    for t in ("assistant_messages", "system_checks"):
        if insp.has_table(t):
            op.drop_table(t)
