"""findings table for triaged pylint/bandit/pytest results

Revision ID: 20260322_0004
Revises: 20260322_0003
Create Date: 2026-03-22

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260322_0004"
down_revision: Union[str, None] = "20260322_0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

finding_severity = postgresql.ENUM(
    "critical",
    "high",
    "medium",
    "low",
    name="finding_severity",
    create_type=False,
)
finding_category = postgresql.ENUM(
    "code_bug",
    "setup_failed",
    "environment",
    "flaky",
    "ignored",
    name="finding_category",
    create_type=False,
)


def upgrade() -> None:
    op.execute(
        "CREATE TYPE finding_severity AS ENUM "
        "('critical', 'high', 'medium', 'low')"
    )
    op.execute(
        "CREATE TYPE finding_category AS ENUM "
        "('code_bug', 'setup_failed', 'environment', 'flaky', 'ignored')"
    )
    op.create_table(
        "findings",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "run_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("analysis_runs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("source", sa.String(32), nullable=False),
        sa.Column("rule_id", sa.String(128)),
        sa.Column("file", sa.String(1024)),
        sa.Column("line", sa.Integer()),
        sa.Column("symbol", sa.String(255)),
        sa.Column("message", sa.Text()),
        sa.Column("tool_severity", sa.String(64)),
        sa.Column("tool_confidence", sa.String(64)),
        sa.Column("test_id", sa.String(512)),
        sa.Column("exception_type", sa.String(255)),
        sa.Column("fingerprint", sa.String(64), nullable=False),
        sa.Column("severity", finding_severity, nullable=False),
        sa.Column(
            "category",
            finding_category,
            nullable=False,
            server_default="code_bug",
        ),
        sa.Column("is_code_bug", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column(
            "needs_attention", sa.Boolean(), nullable=False, server_default="false"
        ),
        sa.Column(
            "issue_status", sa.String(64), nullable=False, server_default="none"
        ),
        sa.Column("fix_status", sa.String(64), nullable=False, server_default="none"),
        sa.Column("action_tag", sa.String(128)),
        sa.Column("triage_notes", sa.Text()),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.UniqueConstraint("run_id", "fingerprint", name="uq_finding_run_fingerprint"),
    )
    op.create_index("ix_findings_run_id", "findings", ["run_id"])


def downgrade() -> None:
    op.drop_index("ix_findings_run_id", table_name="findings")
    op.drop_table("findings")
    op.execute("DROP TYPE IF EXISTS finding_category")
    op.execute("DROP TYPE IF EXISTS finding_severity")
