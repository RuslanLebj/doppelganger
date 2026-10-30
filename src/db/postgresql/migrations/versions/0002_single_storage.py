"""Keep one S3 destination, preserving the previous local object history."""

import sqlalchemy as sa
from alembic import op

revision = "pg_0002"
down_revision = "pg_0001"
branch_labels = None
depends_on = None


def upgrade():
    # Refuse to discard metadata if the optional second destination was used.
    connection = op.get_bind()
    if connection.scalar(
        sa.text(
            "SELECT EXISTS (SELECT 1 FROM backup_run WHERE s3_key IS NOT NULL OR s3_status != 'not_requested')"
        )
    ):
        raise RuntimeError(
            "Second-destination history exists; migrate it before switching to one S3 destination"
        )
    op.execute("UPDATE backup_run SET s3_key = local_key, s3_status = local_status")
    op.drop_column("backup_run", "local_key")
    op.drop_column("backup_run", "local_status")


def downgrade():
    op.add_column("backup_run", sa.Column("local_key", sa.Text()))
    op.add_column(
        "backup_run",
        sa.Column(
            "local_status", sa.String(20), nullable=False, server_default="not_started"
        ),
    )
    op.execute(
        "UPDATE backup_run SET local_key = s3_key, local_status = s3_status, s3_key = NULL, s3_status = 'not_requested'"
    )
    op.alter_column("backup_run", "local_status", server_default=None)
