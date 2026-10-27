"""fix_attempts + finding fix columns

Revision ID: 20260322_0006
Revises: 20260322_0005
Create Date: 2026-03-22

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260322_0006"
down_revision: Union[str, None] = "20260322_0005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

fix_attempt_status = postgresql.ENUM(
    "pending",
    "running",
    "rejected",
    "failed",
    "verified",
    name="fix_attempt_status",
    create_type=False,
)


def upgrade() -> None:
    op.execute(
        "CREATE TYPE fix_attempt_status AS ENUM "
        "('pending', 'running', 'rejected', 'failed', 'verified')"
    )
    op.add_column("findings", sa.Column("fix_branch", sa.String(255)))
    op.add_column("findings", sa.Column("fix_explanation", sa.Text()))
    op.add_column("findings", sa.Column("verified_diff", sa.Text()))
    op.add_column("findings", sa.Column("verified_files_json", sa.Text()))
    op.add_column("findings", sa.Column("fix_rq_job_id", sa.String(128)))

    op.create_table(
        "fix_attempts",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "finding_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("findings.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("attempt_number", sa.Integer(), nullable=False),
        sa.Column("status", fix_attempt_status, nullable=False),
        sa.Column("branch_name", sa.String(255)),
        sa.Column("files_changed_json", sa.Text()),
        sa.Column("unified_diff", sa.Text()),
        sa.Column("explanation", sa.Text()),
        sa.Column("safety_ok", sa.Boolean()),
        sa.Column("safety_violations_json", sa.Text()),
        sa.Column("tests_passed", sa.Boolean()),
        sa.Column("original_failure_gone", sa.Boolean()),
        sa.Column("new_failures", sa.Integer()),
        sa.Column("test_log", sa.Text()),
        sa.Column("error_message", sa.Text()),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.UniqueConstraint(
            "finding_id", "attempt_number", name="uq_fix_attempt_finding_num"
        ),
    )
    op.create_index("ix_fix_attempts_finding_id", "fix_attempts", ["finding_id"])


def downgrade() -> None:
    op.drop_index("ix_fix_attempts_finding_id", table_name="fix_attempts")
    op.drop_table("fix_attempts")
    op.drop_column("findings", "fix_rq_job_id")
    op.drop_column("findings", "verified_files_json")
    op.drop_column("findings", "verified_diff")
    op.drop_column("findings", "fix_explanation")
    op.drop_column("findings", "fix_branch")
    op.execute("DROP TYPE IF EXISTS fix_attempt_status")
