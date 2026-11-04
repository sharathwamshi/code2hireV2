"""Beta bug fixes (BETACODE2-1 to 48): sign-in throttle, link sharing status, disputes, template archive + data fixes.

Revision ID: 0004_beta_fixes
Revises: 0003_qbank_links
Create Date: 2026-11-04
"""
import sqlalchemy as sa
from alembic import op

revision = "0004_beta_fixes"
down_revision = "0003_qbank_links"
branch_labels = None
depends_on = None


def _insp():
    return sa.inspect(op.get_bind())


def _cols(table):
    return {c["name"] for c in _insp().get_columns(table)}


def _add(table, cols):
    have = _cols(table)
    for name, typ in cols:
        if name not in have:
            op.add_column(table, sa.Column(name, typ, nullable=True))


def upgrade():
    if not _insp().has_table("login_throttles"):
        op.create_table(
            "login_throttles",
            sa.Column("id", sa.Integer, primary_key=True),
            sa.Column("created_at", sa.DateTime, nullable=False),
            sa.Column("key", sa.String(190), nullable=False),
            sa.Column("failures", sa.Integer, nullable=False, server_default="0"),
            sa.Column("window_start", sa.DateTime),
            sa.Column("locked_until", sa.DateTime),
            mysql_engine="InnoDB", mysql_charset="utf8mb4",
        )
        op.create_index("ix_login_throttles_key", "login_throttles", ["key"], unique=True)
    _add("invite_links", [("shared_at", sa.DateTime), ("shared_via", sa.String(20))])
    _add("reports", [("disputed_at", sa.DateTime), ("dispute_status", sa.String(20)), ("dispute_resolution", sa.Text),
                     ("dispute_resolved_by", sa.Integer), ("dispute_resolved_at", sa.DateTime)])
    _add("hiring_templates", [("updated_by", sa.Integer), ("updated_at", sa.DateTime), ("archived", sa.Boolean)])

    b = op.get_bind()
    x = lambda q: b.execute(sa.text(q))  # noqa: E731
    x("UPDATE hiring_templates SET archived = :f WHERE archived IS NULL".replace(":f", "0" if b.dialect.name != "postgresql" else "false"))
    x("UPDATE hiring_templates SET updated_at = created_at WHERE updated_at IS NULL")
    x("UPDATE reports SET dispute_status = 'open', disputed_at = created_at WHERE disputed = 1 AND dispute_status IS NULL")
    x("UPDATE invite_links SET shared_at = created_at, shared_via = 'manual' WHERE shared_at IS NULL AND revoked = 0")
    x("UPDATE jobs SET hires_target = 1 WHERE hires_target IS NULL OR hires_target < 1")
    x("UPDATE jobs SET salary_min = NULL WHERE salary_min < 0")
    x("UPDATE jobs SET salary_max = NULL WHERE salary_max < 0")
    # swap upside-down salary bands (portable: row by row)
    for jid, lo, hi in b.execute(sa.text("SELECT id, salary_min, salary_max FROM jobs WHERE salary_min IS NOT NULL AND salary_max IS NOT NULL AND salary_min > salary_max")).fetchall():
        b.execute(sa.text("UPDATE jobs SET salary_min = :lo, salary_max = :hi WHERE id = :id"), {"lo": hi, "hi": lo, "id": jid})
    # one live invite per candidate per round: cancel duplicates (keep a running round, else the newest invite)
    rows = b.execute(sa.text("SELECT id, application_id, round_index, status FROM round_attempts "
                             "WHERE application_id IS NOT NULL AND status IN ('invited','scheduled','in_progress','paused') "
                             "ORDER BY application_id, round_index, id")).fetchall()
    groups = {}
    for rid, aid, idx, st in rows:
        groups.setdefault((aid, idx), []).append((rid, st))
    cancel = []
    for items in groups.values():
        if len(items) < 2:
            continue
        running = [r for r, st in items if st in ("in_progress", "paused")]
        keep = running[-1] if running else items[-1][0]
        cancel += [r for r, st in items if r != keep and st in ("invited", "scheduled")]
    for rid in cancel:
        b.execute(sa.text("UPDATE round_attempts SET status = 'cancelled' WHERE id = :id"), {"id": rid})


def downgrade():
    op.drop_column("hiring_templates", "archived")
    op.drop_column("hiring_templates", "updated_at")
    op.drop_column("hiring_templates", "updated_by")
    for c in ("dispute_resolved_at", "dispute_resolved_by", "dispute_resolution", "dispute_status", "disputed_at"):
        op.drop_column("reports", c)
    op.drop_column("invite_links", "shared_via")
    op.drop_column("invite_links", "shared_at")
    op.drop_table("login_throttles")
