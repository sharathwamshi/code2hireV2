"""V02.00.09: no time limits on joining (N5). Data only: open invites lose their deadline and unused, still-valid
candidate portal links work until used.

Revision ID: 0008_v09_no_time_limits
Revises: 0007_users_archive_cleanup
Create Date: 2026-11-13
"""
from alembic import op

revision = "0008_v09_no_time_limits"
down_revision = "0007_users_archive_cleanup"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("UPDATE round_attempts SET deadline_at = NULL WHERE status IN ('invited', 'scheduled') AND deadline_at IS NOT NULL")
    op.execute("UPDATE invite_links SET expires_at = '2099-12-31 00:00:00' WHERE used_at IS NULL AND revoked = 0 "
               "AND expires_at > CURRENT_TIMESTAMP")


def downgrade():
    pass  # the old deadlines aren't stored; see migrations/sql/007_v09_no_time_limits.down.sql for a best-effort undo
