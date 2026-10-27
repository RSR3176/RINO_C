from __future__ import annotations

import enum
import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class Role(str, enum.Enum):
    admin = "admin"
    developer = "developer"


class TestEnv(str, enum.Enum):
    github_actions = "github_actions"
    dev_instance = "dev_instance"
    rino_sandbox = "rino_sandbox"


class RepoStatus(str, enum.Enum):
    pending = "pending"
    ready = "ready"
    needs_attention = "needs_attention"
    access_revoked = "access_revoked"


class Org(Base):
    __tablename__ = "orgs"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    slug: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    memberships: Mapped[list[OrgMembership]] = relationship(back_populates="org")
    repositories: Mapped[list[Repository]] = relationship(back_populates="org")
    github_installation: Mapped[GithubInstallation | None] = relationship(
        back_populates="org", uselist=False
    )


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    github_id: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    github_login: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    name: Mapped[str | None] = mapped_column(String(255))
    email: Mapped[str | None] = mapped_column(String(320))
    avatar_url: Mapped[str | None] = mapped_column(String(512))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    memberships: Mapped[list[OrgMembership]] = relationship(back_populates="user")


class OrgMembership(Base):
    __tablename__ = "org_memberships"
    __table_args__ = (UniqueConstraint("org_id", "user_id", name="uq_org_user"),)

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("orgs.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    role: Mapped[Role] = mapped_column(
        Enum(Role, name="user_role", native_enum=True), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    org: Mapped[Org] = relationship(back_populates="memberships")
    user: Mapped[User] = relationship(back_populates="memberships")


class GithubInstallation(Base):
    __tablename__ = "github_installations"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("orgs.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    installation_id: Mapped[int] = mapped_column(BigInteger, nullable=False, unique=True)
    account_login: Mapped[str] = mapped_column(String(255), nullable=False)
    account_type: Mapped[str] = mapped_column(String(64), nullable=False)
    account_id: Mapped[str | None] = mapped_column(String(64))
    suspended: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    org: Mapped[Org] = relationship(back_populates="github_installation")
    repositories: Mapped[list[Repository]] = relationship(back_populates="installation")


class Repository(Base):
    __tablename__ = "repositories"
    __table_args__ = (
        UniqueConstraint("org_id", "github_full_name", name="uq_org_repo_fullname"),
        UniqueConstraint("org_id", "github_repo_id", name="uq_org_github_repo_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("orgs.id", ondelete="CASCADE"), nullable=False
    )
    installation_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("github_installations.id", ondelete="SET NULL"),
    )
    github_repo_id: Mapped[str] = mapped_column(String(64), nullable=False)
    github_full_name: Mapped[str] = mapped_column(String(255), nullable=False)
    default_branch: Mapped[str] = mapped_column(String(255), default="main")
    html_url: Mapped[str | None] = mapped_column(String(512))
    is_private: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    status: Mapped[RepoStatus] = mapped_column(
        Enum(RepoStatus, name="repo_status", native_enum=True),
        default=RepoStatus.pending,
        nullable=False,
    )
    status_detail: Mapped[str | None] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    org: Mapped[Org] = relationship(back_populates="repositories")
    installation: Mapped[GithubInstallation | None] = relationship(
        back_populates="repositories"
    )
    test_config: Mapped[RepoTestConfig | None] = relationship(
        back_populates="repository", uselist=False
    )
    analysis_runs: Mapped[list[AnalysisRun]] = relationship(back_populates="repository")


class RepoTestConfig(Base):
    __tablename__ = "repo_test_configs"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    repository_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("repositories.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    test_env: Mapped[TestEnv | None] = mapped_column(
        Enum(TestEnv, name="test_env", native_enum=True)
    )
    workflow_file: Mapped[str | None] = mapped_column(String(512))
    setup_command: Mapped[str | None] = mapped_column(Text)
    test_command: Mapped[str | None] = mapped_column(Text)
    python_version: Mapped[str | None] = mapped_column(String(32))
    shared_dev_instance: Mapped[bool] = mapped_column(
        Boolean, default=True, nullable=False
    )
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_check_ok: Mapped[bool | None] = mapped_column(Boolean)
    last_check_detail: Mapped[str | None] = mapped_column(Text)
    last_check_latency_ms: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    repository: Mapped[Repository] = relationship(back_populates="test_config")


class RunStatus(str, enum.Enum):
    queued = "queued"
    running = "running"
    succeeded = "succeeded"
    failed = "failed"
    timed_out = "timed_out"
    cancelled = "cancelled"


class StepStatus(str, enum.Enum):
    pending = "pending"
    running = "running"
    succeeded = "succeeded"
    failed = "failed"
    skipped = "skipped"


class TestCaseStatus(str, enum.Enum):
    passed = "passed"
    failed = "failed"
    error = "error"
    skipped = "skipped"


class RunnerType(str, enum.Enum):
    sandbox = "sandbox"
    github_actions = "github_actions"


class AnalysisRun(Base):
    __tablename__ = "analysis_runs"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("orgs.id", ondelete="CASCADE"), nullable=False
    )
    repository_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("repositories.id", ondelete="CASCADE"),
        nullable=False,
    )
    triggered_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    branch: Mapped[str] = mapped_column(String(255), nullable=False, default="main")
    runner_type: Mapped[RunnerType] = mapped_column(
        Enum(RunnerType, name="runner_type", native_enum=True),
        default=RunnerType.sandbox,
        nullable=False,
    )
    status: Mapped[RunStatus] = mapped_column(
        Enum(RunStatus, name="run_status", native_enum=True),
        default=RunStatus.queued,
        nullable=False,
    )
    commit_sha: Mapped[str | None] = mapped_column(String(64))
    github_workflow_run_id: Mapped[int | None] = mapped_column(BigInteger)
    error_message: Mapped[str | None] = mapped_column(Text)
    rq_job_id: Mapped[str | None] = mapped_column(String(128))
    tests_total: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    tests_passed: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    tests_failed: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    tests_errors: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    tests_skipped: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    repository: Mapped[Repository] = relationship(back_populates="analysis_runs")
    steps: Mapped[list[RunStep]] = relationship(
        back_populates="run", order_by="RunStep.sort_order"
    )
    test_results: Mapped[list[TestResult]] = relationship(back_populates="run")
    findings: Mapped[list[Finding]] = relationship(back_populates="run")


class RunStep(Base):
    __tablename__ = "run_steps"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("analysis_runs.id", ondelete="CASCADE"),
        nullable=False,
    )
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    status: Mapped[StepStatus] = mapped_column(
        Enum(StepStatus, name="step_status", native_enum=True),
        default=StepStatus.pending,
        nullable=False,
    )
    exit_code: Mapped[int | None] = mapped_column(Integer)
    log_text: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    run: Mapped[AnalysisRun] = relationship(back_populates="steps")


class TestResult(Base):
    __tablename__ = "test_results"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("analysis_runs.id", ondelete="CASCADE"),
        nullable=False,
    )
    suite_name: Mapped[str | None] = mapped_column(String(512))
    case_name: Mapped[str] = mapped_column(String(512), nullable=False)
    classname: Mapped[str | None] = mapped_column(String(512))
    status: Mapped[TestCaseStatus] = mapped_column(
        Enum(TestCaseStatus, name="test_case_status", native_enum=True),
        nullable=False,
    )
    message: Mapped[str | None] = mapped_column(Text)
    duration_seconds: Mapped[float | None] = mapped_column(Float)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    run: Mapped[AnalysisRun] = relationship(back_populates="test_results")


class FindingSeverity(str, enum.Enum):
    critical = "critical"
    high = "high"
    medium = "medium"
    low = "low"


class FindingCategory(str, enum.Enum):
    code_bug = "code_bug"
    setup_failed = "setup_failed"
    environment = "environment"
    flaky = "flaky"
    ignored = "ignored"


class Finding(Base):
    """Normalized + triaged finding from pytest / pylint / bandit."""

    __tablename__ = "findings"
    __table_args__ = (
        UniqueConstraint("run_id", "fingerprint", name="uq_finding_run_fingerprint"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("analysis_runs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    source: Mapped[str] = mapped_column(String(32), nullable=False)
    rule_id: Mapped[str | None] = mapped_column(String(128))
    file: Mapped[str | None] = mapped_column(String(1024))
    line: Mapped[int | None] = mapped_column(Integer)
    symbol: Mapped[str | None] = mapped_column(String(255))
    message: Mapped[str | None] = mapped_column(Text)
    tool_severity: Mapped[str | None] = mapped_column(String(64))
    tool_confidence: Mapped[str | None] = mapped_column(String(64))
    test_id: Mapped[str | None] = mapped_column(String(512))
    exception_type: Mapped[str | None] = mapped_column(String(255))
    fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)

    severity: Mapped[FindingSeverity] = mapped_column(
        Enum(FindingSeverity, name="finding_severity", native_enum=True),
        nullable=False,
    )
    category: Mapped[FindingCategory] = mapped_column(
        Enum(FindingCategory, name="finding_category", native_enum=True),
        default=FindingCategory.code_bug,
        nullable=False,
    )
    is_code_bug: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    needs_attention: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    issue_status: Mapped[str] = mapped_column(String(64), default="none", nullable=False)
    # none | awaiting_confirm | open | linked | dry_run | skipped
    fix_status: Mapped[str] = mapped_column(String(64), default="none", nullable=False)
    action_tag: Mapped[str | None] = mapped_column(String(128))
    triage_notes: Mapped[str | None] = mapped_column(Text)
    root_cause: Mapped[str | None] = mapped_column(Text)
    issue_title: Mapped[str | None] = mapped_column(String(512))
    issue_body: Mapped[str | None] = mapped_column(Text)
    github_issue_number: Mapped[int | None] = mapped_column(Integer)
    github_issue_url: Mapped[str | None] = mapped_column(String(1024))
    # Step 6–7 fix flow
    # fix_status: none | queued | generating | verified | failed | discarded | pr_opened
    fix_branch: Mapped[str | None] = mapped_column(String(255))
    fix_explanation: Mapped[str | None] = mapped_column(Text)
    verified_diff: Mapped[str | None] = mapped_column(Text)  # unified diff
    verified_files_json: Mapped[str | None] = mapped_column(Text)  # JSON list
    fix_rq_job_id: Mapped[str | None] = mapped_column(String(128))
    github_pr_number: Mapped[int | None] = mapped_column(Integer)
    github_pr_url: Mapped[str | None] = mapped_column(String(1024))
    pr_status: Mapped[str] = mapped_column(String(64), default="none", nullable=False)
    # pr_status: none | dry_run | open
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    run: Mapped[AnalysisRun] = relationship(back_populates="findings")
    llm_calls: Mapped[list[LlmCall]] = relationship(back_populates="finding")
    fix_attempts: Mapped[list[FixAttempt]] = relationship(
        back_populates="finding", order_by="FixAttempt.attempt_number"
    )
    pull_requests: Mapped[list[PullRequest]] = relationship(
        back_populates="finding", order_by="PullRequest.created_at"
    )


class LlmCall(Base):
    """Token usage + cost for one Anthropic (or stub) call. Never stores secrets."""

    __tablename__ = "llm_calls"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    org_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("orgs.id", ondelete="SET NULL")
    )
    run_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("analysis_runs.id", ondelete="SET NULL"),
        index=True,
    )
    finding_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("findings.id", ondelete="SET NULL"),
        index=True,
    )
    purpose: Mapped[str] = mapped_column(String(64), nullable=False)  # root_cause
    model: Mapped[str] = mapped_column(String(128), nullable=False)
    input_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    cost_usd: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    success: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    error_message: Mapped[str | None] = mapped_column(String(512))
    # Redacted prompt/response fingerprints only — never raw secrets
    prompt_chars: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    response_chars: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    finding: Mapped[Finding | None] = relationship(back_populates="llm_calls")


class FixAttemptStatus(str, enum.Enum):
    pending = "pending"
    running = "running"
    rejected = "rejected"  # safety check failed
    failed = "failed"  # tests still failing / new findings
    verified = "verified"


class FixAttempt(Base):
    """One LLM fix attempt for a Critical finding (max 3)."""

    __tablename__ = "fix_attempts"
    __table_args__ = (
        UniqueConstraint(
            "finding_id", "attempt_number", name="uq_fix_attempt_finding_num"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    finding_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("findings.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    attempt_number: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[FixAttemptStatus] = mapped_column(
        Enum(FixAttemptStatus, name="fix_attempt_status", native_enum=True),
        default=FixAttemptStatus.pending,
        nullable=False,
    )
    branch_name: Mapped[str | None] = mapped_column(String(255))
    files_changed_json: Mapped[str | None] = mapped_column(Text)
    unified_diff: Mapped[str | None] = mapped_column(Text)
    explanation: Mapped[str | None] = mapped_column(Text)
    safety_ok: Mapped[bool | None] = mapped_column(Boolean)
    safety_violations_json: Mapped[str | None] = mapped_column(Text)
    tests_passed: Mapped[bool | None] = mapped_column(Boolean)
    original_failure_gone: Mapped[bool | None] = mapped_column(Boolean)
    new_failures: Mapped[int | None] = mapped_column(Integer)
    test_log: Mapped[str | None] = mapped_column(Text)
    # Structured after-fix cases for Testing Dashboard (JSON list)
    tests_json: Mapped[str | None] = mapped_column(Text)
    # {"pylint": int, "bandit": int} warning counts after this attempt
    static_counts_json: Mapped[str | None] = mapped_column(Text)
    error_message: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    finding: Mapped[Finding] = relationship(back_populates="fix_attempts")


class PullRequest(Base):
    """Draft PR opened only after developer Approve (Step 7)."""

    __tablename__ = "pull_requests"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("orgs.id", ondelete="CASCADE"), nullable=False
    )
    repository_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("repositories.id", ondelete="CASCADE"),
        nullable=False,
    )
    finding_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("findings.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    fix_attempt_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("fix_attempts.id", ondelete="SET NULL"),
    )
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    branch_name: Mapped[str] = mapped_column(String(255), nullable=False)
    base_branch: Mapped[str] = mapped_column(String(255), nullable=False, default="main")
    title: Mapped[str] = mapped_column(String(512), nullable=False)
    body: Mapped[str | None] = mapped_column(Text)
    github_pr_number: Mapped[int | None] = mapped_column(Integer)
    github_pr_url: Mapped[str | None] = mapped_column(String(1024))
    draft: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    dry_run: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    # status: open | dry_run | failed
    status: Mapped[str] = mapped_column(String(64), default="dry_run", nullable=False)
    before_summary_json: Mapped[str | None] = mapped_column(Text)
    after_summary_json: Mapped[str | None] = mapped_column(Text)
    pushed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    error_message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    finding: Mapped[Finding] = relationship(back_populates="pull_requests")


class TriageRule(Base):
    __tablename__ = "triage_rules"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("orgs.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    pattern: Mapped[str] = mapped_column(Text, nullable=False)
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    org_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("orgs.id", ondelete="SET NULL")
    )
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    action: Mapped[str] = mapped_column(String(128), nullable=False)
    detail: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
