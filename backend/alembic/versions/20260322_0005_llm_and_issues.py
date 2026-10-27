"""llm_calls + finding root_cause / github issue fields

Revision ID: 20260322_0005
Revises: 20260322_0004
Create Date: 2026-03-22

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260322_0005"
down_revision: Union[str, None] = "20260322_0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("findings", sa.Column("root_cause", sa.Text()))
    op.add_column("findings", sa.Column("issue_title", sa.String(512)))
    op.add_column("findings", sa.Column("issue_body", sa.Text()))
    op.add_column("findings", sa.Column("github_issue_number", sa.Integer()))
    op.add_column("findings", sa.Column("github_issue_url", sa.String(1024)))

    op.create_table(
        "llm_calls",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "org_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("orgs.id", ondelete="SET NULL"),
        ),
        sa.Column(
            "run_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("analysis_runs.id", ondelete="SET NULL"),
        ),
        sa.Column(
            "finding_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("findings.id", ondelete="SET NULL"),
        ),
        sa.Column("purpose", sa.String(64), nullable=False),
        sa.Column("model", sa.String(128), nullable=False),
        sa.Column("input_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("output_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("cost_usd", sa.Float(), nullable=False, server_default="0"),
        sa.Column("success", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("error_message", sa.String(512)),
        sa.Column("prompt_chars", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("response_chars", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.create_index("ix_llm_calls_run_id", "llm_calls", ["run_id"])
    op.create_index("ix_llm_calls_finding_id", "llm_calls", ["finding_id"])


def downgrade() -> None:
    op.drop_index("ix_llm_calls_finding_id", table_name="llm_calls")
    op.drop_index("ix_llm_calls_run_id", table_name="llm_calls")
    op.drop_table("llm_calls")
    op.drop_column("findings", "github_issue_url")
    op.drop_column("findings", "github_issue_number")
    op.drop_column("findings", "issue_body")
    op.drop_column("findings", "issue_title")
    op.drop_column("findings", "root_cause")
