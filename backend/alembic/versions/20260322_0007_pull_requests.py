"""pull_requests + fix attempt test snapshots + finding PR columns

Revision ID: 20260322_0007
Revises: 20260322_0006
Create Date: 2026-03-22

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260322_0007"
down_revision: Union[str, None] = "20260322_0006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("findings", sa.Column("github_pr_number", sa.Integer()))
    op.add_column("findings", sa.Column("github_pr_url", sa.String(1024)))
    op.add_column(
        "findings",
        sa.Column(
            "pr_status",
            sa.String(64),
            server_default="none",
            nullable=False,
        ),
    )
    op.add_column("fix_attempts", sa.Column("tests_json", sa.Text()))
    op.add_column("fix_attempts", sa.Column("static_counts_json", sa.Text()))

    op.create_table(
        "pull_requests",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "org_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("orgs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "repository_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("repositories.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "finding_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("findings.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "fix_attempt_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("fix_attempts.id", ondelete="SET NULL"),
        ),
        sa.Column(
            "created_by_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
        ),
        sa.Column("branch_name", sa.String(255), nullable=False),
        sa.Column("base_branch", sa.String(255), nullable=False, server_default="main"),
        sa.Column("title", sa.String(512), nullable=False),
        sa.Column("body", sa.Text()),
        sa.Column("github_pr_number", sa.Integer()),
        sa.Column("github_pr_url", sa.String(1024)),
        sa.Column("draft", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column(
            "dry_run", sa.Boolean(), nullable=False, server_default=sa.text("false")
        ),
        sa.Column("status", sa.String(64), nullable=False, server_default="dry_run"),
        sa.Column("before_summary_json", sa.Text()),
        sa.Column("after_summary_json", sa.Text()),
        sa.Column(
            "pushed", sa.Boolean(), nullable=False, server_default=sa.text("false")
        ),
        sa.Column("error_message", sa.Text()),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.create_index("ix_pull_requests_finding_id", "pull_requests", ["finding_id"])


def downgrade() -> None:
    op.drop_index("ix_pull_requests_finding_id", table_name="pull_requests")
    op.drop_table("pull_requests")
    op.drop_column("fix_attempts", "static_counts_json")
    op.drop_column("fix_attempts", "tests_json")
    op.drop_column("findings", "pr_status")
    op.drop_column("findings", "github_pr_url")
    op.drop_column("findings", "github_pr_number")
