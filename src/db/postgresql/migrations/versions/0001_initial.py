"""PostgreSQL metadata and independent local/remote object delivery statuses."""

import sqlalchemy as sa
from alembic import op

revision = "pg_0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "database_target",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(100), nullable=False, unique=True),
        sa.Column("host", sa.String(253), nullable=False),
        sa.Column("port", sa.Integer(), nullable=False),
        sa.Column("database", sa.String(63), nullable=False),
        sa.Column("username", sa.String(63), nullable=False),
        sa.Column("password_encrypted", sa.Text(), nullable=False),
        sa.Column("sslmode", sa.String(20), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_table(
        "backup_plan",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(100), nullable=False, unique=True),
        sa.Column(
            "target_id", sa.Integer(), sa.ForeignKey("database_target.id"), nullable=False
        ),
        sa.Column("cron", sa.String(100), nullable=False),
        sa.Column("timezone", sa.String(100), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("max_dump_seconds", sa.Integer(), nullable=False),
        sa.Column("lock_wait_seconds", sa.Integer(), nullable=False),
        sa.Column("next_run_at", sa.DateTime()),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint("max_dump_seconds > 0"),
    )
    op.create_table(
        "backup_run",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "plan_id", sa.Integer(), sa.ForeignKey("backup_plan.id"), nullable=False
        ),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("trigger", sa.String(20), nullable=False),
        sa.Column("dump_path", sa.Text()),
        sa.Column("local_key", sa.Text()),
        sa.Column("local_status", sa.String(20), nullable=False),
        sa.Column("s3_key", sa.Text()),
        sa.Column("s3_status", sa.String(20), nullable=False),
        sa.Column("dump_bytes", sa.BigInteger()),
        sa.Column("error", sa.Text()),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("started_at", sa.DateTime()),
        sa.Column("finished_at", sa.DateTime()),
    )
    op.create_index(
        "uq_active_plan",
        "backup_run",
        ["plan_id"],
        unique=True,
        postgresql_where=sa.text("status IN ('queued', 'running')"),
    )
    op.create_index("ix_queue", "backup_run", ["status", "created_at"])


def downgrade():
    op.drop_table("backup_run")
    op.drop_table("backup_plan")
    op.drop_table("database_target")
