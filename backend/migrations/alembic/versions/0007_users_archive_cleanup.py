"""V02.00.08: users.archived_at / archived_by (deleted users are archived), applications.removed_* and pool_removals
(remove and restore candidates), filler questions back to review, and the seeded superadmin name without "Platform".

Revision ID: 0007_users_archive_cleanup
Revises: 0006_system_check_and_assistant
Create Date: 2026-11-11
"""
import sqlalchemy as sa
from alembic import op

revision = "0007_users_archive_cleanup"
down_revision = "0006_system_check_and_assistant"
branch_labels = None
depends_on = None

FILLER = [
    "Which statement about % is most accurate for a level % practitioner?",
    "A teammate's % work passes review but fails in production. What should you check first?",
    "What is the main benefit of writing automated tests for % code?",
    "You must learn a new part of % quickly for a project. What works best?",
    "When is it right to choose a simpler % solution over a more powerful one?",
    "How should a % decision with real trade-offs be recorded for the team?",
]


def upgrade():
    insp = sa.inspect(op.get_bind())
    cols = {c["name"] for c in insp.get_columns("users")}
    if "archived_at" not in cols:
        op.add_column("users", sa.Column("archived_at", sa.DateTime, nullable=True))
    if "archived_by" not in cols:
        op.add_column("users", sa.Column("archived_by", sa.Integer, nullable=True))
    acols = {c["name"] for c in insp.get_columns("applications")}
    for name, typ in (("removed_at", sa.DateTime), ("removed_by", sa.Integer), ("removed_stage", sa.String(30))):
        if name not in acols:
            op.add_column("applications", sa.Column(name, typ, nullable=True))
    if "pool_removals" not in insp.get_table_names():
        op.create_table("pool_removals",
                        sa.Column("id", sa.Integer, primary_key=True),
                        sa.Column("created_at", sa.DateTime, nullable=False),
                        sa.Column("company_id", sa.Integer, sa.ForeignKey("companies.id"), nullable=False),
                        sa.Column("user_id", sa.Integer, sa.ForeignKey("users.id"), nullable=False),
                        sa.Column("removed_by", sa.Integer, nullable=True),
                        sa.UniqueConstraint("company_id", "user_id", name="uq_pool_removal"))
        op.create_index("ix_pool_removals_company_id", "pool_removals", ["company_id"])
        op.create_index("ix_pool_removals_user_id", "pool_removals", ["user_id"])
    conn = op.get_bind()
    like = " OR ".join(f"text LIKE :p{i}" for i in range(len(FILLER)))
    conn.execute(sa.text(f"UPDATE questions SET status = 'pending' WHERE source = 'ai' AND status = 'approved' AND ({like})"),
                 {f"p{i}": p for i, p in enumerate(FILLER)})
    conn.execute(sa.text("UPDATE users SET name = 'Superadmin' WHERE is_superadmin = 1 AND name = 'Platform Superadmin'"))


def downgrade():
    conn = op.get_bind()
    conn.execute(sa.text("UPDATE users SET active = 0 WHERE archived_at IS NOT NULL"))
    conn.execute(sa.text("UPDATE applications SET stage = COALESCE(removed_stage, 'rejected') WHERE stage = 'removed'"))
    op.drop_table("pool_removals")
    for name in ("removed_stage", "removed_by", "removed_at"):
        op.drop_column("applications", name)
    op.drop_column("users", "archived_by")
    op.drop_column("users", "archived_at")
