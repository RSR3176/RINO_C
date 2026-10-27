"""github installations, repo fields, repo_test_configs

Revision ID: 20260322_0002
Revises: 20260322_0001
Create Date: 2026-03-22

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260322_0002"
down_revision: Union[str, None] = "20260322_0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

repo_status = postgresql.ENUM(
    "pending",
    "ready",
    "needs_attention",
    "access_revoked",
    name="repo_status",
    create_type=False,
)
test_env = postgresql.ENUM(
    "github_actions",
    "dev_instance",
    "rino_sandbox",
    name="test_env",
    create_type=False,
)


def upgrade() -> None:
    op.execute(
        "CREATE TYPE repo_status AS ENUM "
        "('pending', 'ready', 'needs_attention', 'access_revoked')"
    )
    op.execute(
        "CREATE TYPE test_env AS ENUM "
        "('github_actions', 'dev_instance', 'rino_sandbox')"
    )

    op.create_table(
        "github_installations",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("installation_id", sa.BigInteger(), nullable=False),
        sa.Column("account_login", sa.String(length=255), nullable=False),
        sa.Column("account_type", sa.String(length=64), nullable=False),
        sa.Column("account_id", sa.String(length=64), nullable=True),
        sa.Column(
            "suspended",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["org_id"], ["orgs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("org_id"),
        sa.UniqueConstraint("installation_id"),
    )

    # repositories: replace stub columns with full fields
    op.add_column(
        "repositories",
        sa.Column("installation_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.add_column(
        "repositories",
        sa.Column(
            "github_repo_id",
            sa.String(length=64),
            nullable=False,
            server_default="0",
        ),
    )
    op.add_column(
        "repositories", sa.Column("html_url", sa.String(length=512), nullable=True)
    )
    op.add_column(
        "repositories",
        sa.Column(
            "is_private",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
    )
    op.add_column(
        "repositories",
        sa.Column("status_detail", sa.String(length=255), nullable=True),
    )
    op.add_column(
        "repositories",
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )

    # Drop old string status/test_env; add enum status
    op.drop_column("repositories", "test_env")
    op.drop_column("repositories", "status")
    op.add_column(
        "repositories",
        sa.Column(
            "status",
            repo_status,
            nullable=False,
            server_default="pending",
        ),
    )

    op.create_foreign_key(
        "fk_repositories_installation_id",
        "repositories",
        "github_installations",
        ["installation_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_unique_constraint(
        "uq_org_github_repo_id", "repositories", ["org_id", "github_repo_id"]
    )

    op.create_table(
        "repo_test_configs",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("repository_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("test_env", test_env, nullable=True),
        sa.Column("workflow_file", sa.String(length=512), nullable=True),
        sa.Column("setup_command", sa.Text(), nullable=True),
        sa.Column("test_command", sa.Text(), nullable=True),
        sa.Column("python_version", sa.String(length=32), nullable=True),
        sa.Column(
            "shared_dev_instance",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
        sa.Column("last_checked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_check_ok", sa.Boolean(), nullable=True),
        sa.Column("last_check_detail", sa.Text(), nullable=True),
        sa.Column("last_check_latency_ms", sa.Integer(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["repository_id"], ["repositories.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("repository_id"),
    )

    # Drop server defaults that were only for backfill
    op.alter_column("repositories", "github_repo_id", server_default=None)
    op.alter_column("repositories", "status", server_default=None)


def downgrade() -> None:
    op.drop_table("repo_test_configs")
    op.drop_constraint("uq_org_github_repo_id", "repositories", type_="unique")
    op.drop_constraint(
        "fk_repositories_installation_id", "repositories", type_="foreignkey"
    )
    op.drop_column("repositories", "status")
    op.drop_column("repositories", "updated_at")
    op.drop_column("repositories", "status_detail")
    op.drop_column("repositories", "is_private")
    op.drop_column("repositories", "html_url")
    op.drop_column("repositories", "github_repo_id")
    op.drop_column("repositories", "installation_id")
    op.add_column(
        "repositories",
        sa.Column(
            "test_env", sa.String(length=64), nullable=True
        ),
    )
    op.add_column(
        "repositories",
        sa.Column(
            "status",
            sa.String(length=64),
            nullable=False,
            server_default="pending",
        ),
    )
    op.drop_table("github_installations")
    op.execute("DROP TYPE test_env")
    op.execute("DROP TYPE repo_status")
