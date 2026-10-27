"""analysis_runs, run_steps, test_results

Revision ID: 20260322_0003
Revises: 20260322_0002
Create Date: 2026-03-22

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260322_0003"
down_revision: Union[str, None] = "20260322_0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

run_status = postgresql.ENUM(
    "queued",
    "running",
    "succeeded",
    "failed",
    "timed_out",
    "cancelled",
    name="run_status",
    create_type=False,
)
step_status = postgresql.ENUM(
    "pending",
    "running",
    "succeeded",
    "failed",
    "skipped",
    name="step_status",
    create_type=False,
)
test_case_status = postgresql.ENUM(
    "passed",
    "failed",
    "error",
    "skipped",
    name="test_case_status",
    create_type=False,
)
runner_type = postgresql.ENUM("sandbox", name="runner_type", create_type=False)


def upgrade() -> None:
    op.execute(
        "CREATE TYPE run_status AS ENUM "
        "('queued', 'running', 'succeeded', 'failed', 'timed_out', 'cancelled')"
    )
    op.execute(
        "CREATE TYPE step_status AS ENUM "
        "('pending', 'running', 'succeeded', 'failed', 'skipped')"
    )
    op.execute(
        "CREATE TYPE test_case_status AS ENUM "
        "('passed', 'failed', 'error', 'skipped')"
    )
    op.execute("CREATE TYPE runner_type AS ENUM ('sandbox')")

    op.create_table(
        "analysis_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("repository_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("triggered_by_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("branch", sa.String(length=255), nullable=False, server_default="main"),
        sa.Column("runner_type", runner_type, nullable=False, server_default="sandbox"),
        sa.Column("status", run_status, nullable=False, server_default="queued"),
        sa.Column("commit_sha", sa.String(length=64), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("rq_job_id", sa.String(length=128), nullable=True),
        sa.Column("tests_total", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("tests_passed", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("tests_failed", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("tests_errors", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("tests_skipped", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["org_id"], ["orgs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["repository_id"], ["repositories.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["triggered_by_user_id"], ["users.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "run_steps",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(length=64), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("status", step_status, nullable=False, server_default="pending"),
        sa.Column("exit_code", sa.Integer(), nullable=True),
        sa.Column("log_text", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["run_id"], ["analysis_runs.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "test_results",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("suite_name", sa.String(length=512), nullable=True),
        sa.Column("case_name", sa.String(length=512), nullable=False),
        sa.Column("classname", sa.String(length=512), nullable=True),
        sa.Column("status", test_case_status, nullable=False),
        sa.Column("message", sa.Text(), nullable=True),
        sa.Column("duration_seconds", sa.Float(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["run_id"], ["analysis_runs.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("test_results")
    op.drop_table("run_steps")
    op.drop_table("analysis_runs")
    op.execute("DROP TYPE runner_type")
    op.execute("DROP TYPE test_case_status")
    op.execute("DROP TYPE step_status")
    op.execute("DROP TYPE run_status")
