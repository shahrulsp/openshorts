"""Create the independent SaaS core schema."""

from typing import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "20260719_01"
down_revision: str | None = None
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def _is_postgres() -> bool:
    return op.get_bind().dialect.name == "postgresql"


def _uuid_type():
    return sa.UUID(as_uuid=True) if _is_postgres() else sa.Uuid()


def _json_type():
    return sa.JSON() if not _is_postgres() else postgresql.JSONB(astext_type=sa.Text())


def _timestamp_default():
    return sa.text("now()") if _is_postgres() else sa.text("CURRENT_TIMESTAMP")


def upgrade() -> None:
    op.create_table(
        "workspaces",
        sa.Column("id", _uuid_type(), primary_key=True, nullable=False),
        sa.Column("slug", sa.String(length=120), nullable=False),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("plan", sa.String(length=40), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=_timestamp_default(),
            nullable=False,
        ),
    )
    op.create_index("ix_workspaces_slug", "workspaces", ["slug"], unique=True)

    op.create_table(
        "users",
        sa.Column("id", _uuid_type(), primary_key=True, nullable=False),
        sa.Column("workspace_id", _uuid_type(), nullable=False),
        sa.Column("email", sa.String(length=255), nullable=False),
        sa.Column("full_name", sa.String(length=255), nullable=True),
        sa.Column("role", sa.String(length=40), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=_timestamp_default(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"]),
    )
    op.create_index("ix_users_workspace_id", "users", ["workspace_id"], unique=False)
    op.create_index("ix_users_email", "users", ["email"], unique=False)

    op.create_table(
        "projects",
        sa.Column("id", _uuid_type(), primary_key=True, nullable=False),
        sa.Column("workspace_id", _uuid_type(), nullable=False),
        sa.Column("kind", sa.String(length=40), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=True),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=_timestamp_default(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"]),
    )
    op.create_index("ix_projects_workspace_id", "projects", ["workspace_id"], unique=False)

    op.create_table(
        "assets",
        sa.Column("id", _uuid_type(), primary_key=True, nullable=False),
        sa.Column("workspace_id", _uuid_type(), nullable=False),
        sa.Column("project_id", _uuid_type(), nullable=True),
        sa.Column("storage_key", sa.String(length=500), nullable=False),
        sa.Column("mime_type", sa.String(length=255), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("kind", sa.String(length=40), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=_timestamp_default(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"]),
    )
    op.create_index("ix_assets_workspace_id", "assets", ["workspace_id"], unique=False)
    op.create_index("ix_assets_storage_key", "assets", ["storage_key"], unique=True)

    op.create_table(
        "jobs",
        sa.Column("id", _uuid_type(), primary_key=True, nullable=False),
        sa.Column("workspace_id", _uuid_type(), nullable=False),
        sa.Column("project_id", _uuid_type(), nullable=True),
        sa.Column("kind", sa.String(length=60), nullable=False),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("payload", _json_type(), nullable=False),
        sa.Column("result", _json_type(), nullable=True),
        sa.Column("error_text", sa.Text(), nullable=True),
        sa.Column("progress", sa.Integer(), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=_timestamp_default(),
            nullable=False,
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"]),
    )
    op.create_index("ix_jobs_workspace_id", "jobs", ["workspace_id"], unique=False)

    op.create_table(
        "usage_events",
        sa.Column("id", _uuid_type(), primary_key=True, nullable=False),
        sa.Column("workspace_id", _uuid_type(), nullable=False),
        sa.Column("job_id", _uuid_type(), nullable=True),
        sa.Column("metric", sa.String(length=60), nullable=False),
        sa.Column("quantity", sa.Numeric(precision=12, scale=3), nullable=False),
        sa.Column("unit", sa.String(length=30), nullable=False),
        sa.Column("source", sa.String(length=60), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=_timestamp_default(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["job_id"], ["jobs.id"]),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"]),
    )
    op.create_index("ix_usage_events_workspace_id", "usage_events", ["workspace_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_usage_events_workspace_id", table_name="usage_events")
    op.drop_table("usage_events")

    op.drop_index("ix_jobs_workspace_id", table_name="jobs")
    op.drop_table("jobs")

    op.drop_index("ix_assets_storage_key", table_name="assets")
    op.drop_index("ix_assets_workspace_id", table_name="assets")
    op.drop_table("assets")

    op.drop_index("ix_projects_workspace_id", table_name="projects")
    op.drop_table("projects")

    op.drop_index("ix_users_email", table_name="users")
    op.drop_index("ix_users_workspace_id", table_name="users")
    op.drop_table("users")

    op.drop_index("ix_workspaces_slug", table_name="workspaces")
    op.drop_table("workspaces")
