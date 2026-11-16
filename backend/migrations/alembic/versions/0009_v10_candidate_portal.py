"""V02.00.10: candidate portal and accounts. candidate_profiles.saved_jobs, learning_paths.meta, product_feedback table.

Revision ID: 0009_v10_candidate_portal
Revises: 0008_v09_no_time_limits
Create Date: 2026-11-16
"""
import sqlalchemy as sa
from alembic import op

revision = "0009_v10_candidate_portal"
down_revision = "0008_v09_no_time_limits"
branch_labels = None
depends_on = None


def _cols(insp, table):
    return {c["name"] for c in insp.get_columns(table)}


def upgrade():
    insp = sa.inspect(op.get_bind())
    if "saved_jobs" not in _cols(insp, "candidate_profiles"):
        op.add_column("candidate_profiles", sa.Column("saved_jobs", sa.JSON, nullable=True))
    if "meta" not in _cols(insp, "learning_paths"):
        op.add_column("learning_paths", sa.Column("meta", sa.JSON, nullable=True))
    if "product_feedback" not in insp.get_table_names():
        op.create_table("product_feedback",
                        sa.Column("id", sa.Integer, primary_key=True),
                        sa.Column("created_at", sa.DateTime, nullable=False),
                        sa.Column("user_id", sa.Integer, sa.ForeignKey("users.id"), nullable=True),
                        sa.Column("topics", sa.JSON, nullable=True),
                        sa.Column("rating", sa.Integer, nullable=True),
                        sa.Column("text", sa.Text, nullable=True),
                        sa.Column("page", sa.String(120), nullable=True),
                        sa.Column("status", sa.String(20), nullable=True))
        op.create_index("ix_product_feedback_user_id", "product_feedback", ["user_id"])


def downgrade():
    insp = sa.inspect(op.get_bind())
    if "product_feedback" in insp.get_table_names():
        op.drop_table("product_feedback")
    if "meta" in _cols(insp, "learning_paths"):
        op.drop_column("learning_paths", "meta")
    if "saved_jobs" in _cols(insp, "candidate_profiles"):
        op.drop_column("candidate_profiles", "saved_jobs")
    op.execute("UPDATE invite_links SET revoked = 1 WHERE purpose = 'reset' AND used_at IS NULL")
