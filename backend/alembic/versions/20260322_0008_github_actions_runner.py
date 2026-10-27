"""github_actions runner_type + workflow_run_id on analysis_runs

Revision ID: 20260322_0008
Revises: 20260322_0007
Create Date: 2026-03-22

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20260322_0008"
down_revision: Union[str, None] = "20260322_0007"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TYPE runner_type ADD VALUE IF NOT EXISTS 'github_actions'")
    op.add_column(
        "analysis_runs",
        sa.Column("github_workflow_run_id", sa.BigInteger(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("analysis_runs", "github_workflow_run_id")
    # Cannot easily remove enum value in PostgreSQL
