from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from app.models import (
    FindingCategory,
    FindingSeverity,
    FixAttemptStatus,
    RepoStatus,
    Role,
    RunnerType,
    RunStatus,
    StepStatus,
    TestCaseStatus,
    TestEnv,
)


class OrgOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    slug: str


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    github_login: str
    name: str | None
    email: str | None
    avatar_url: str | None
    role: Role
    org: OrgOut


class HealthOut(BaseModel):
    status: str
    service: str


class GithubInstallationOut(BaseModel):
    installed: bool
    installation_id: int | None = None
    account_login: str | None = None
    account_type: str | None = None
    suspended: bool = False
    app_slug: str | None = None
    configured: bool = False


class AvailableRepoOut(BaseModel):
    github_repo_id: str
    full_name: str
    default_branch: str
    html_url: str | None = None
    private: bool = True
    connected: bool = False


class RepoTestConfigOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    test_env: TestEnv | None = None
    workflow_file: str | None = None
    setup_command: str | None = None
    test_command: str | None = None
    python_version: str | None = None
    shared_dev_instance: bool = True
    last_checked_at: datetime | None = None
    last_check_ok: bool | None = None
    last_check_detail: str | None = None
    last_check_latency_ms: int | None = None


class RepositoryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    github_repo_id: str
    github_full_name: str
    default_branch: str
    html_url: str | None = None
    is_private: bool
    status: RepoStatus
    status_detail: str | None = None
    test_config: RepoTestConfigOut | None = None


class ConnectRepoIn(BaseModel):
    github_repo_id: str
    full_name: str | None = None


class RepoTestConfigIn(BaseModel):
    test_env: TestEnv | None = None
    workflow_file: str | None = None
    setup_command: str | None = None
    test_command: str | None = None
    python_version: str | None = None
    shared_dev_instance: bool | None = None


class TestConnectionOut(BaseModel):
    ok: bool
    detail: str
    latency_ms: int | None = None
    repository: RepositoryOut


class WorkflowOptionOut(BaseModel):
    path: str
    name: str


class InstallUrlOut(BaseModel):
    url: str
    configured: bool


class RepositorySummaryOut(BaseModel):
    id: UUID
    github_full_name: str
    default_branch: str
    status: RepoStatus
    test_env: TestEnv | None = None
    sandbox_ready: bool = False  # legacy alias for analysis_ready
    analysis_ready: bool = False


class CreateRunIn(BaseModel):
    branch: str | None = None


class RunStepOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    sort_order: int
    status: StepStatus
    exit_code: int | None = None
    log_text: str | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None


class TestResultOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    suite_name: str | None = None
    case_name: str
    classname: str | None = None
    status: TestCaseStatus
    message: str | None = None
    duration_seconds: float | None = None


class FindingOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    source: str
    rule_id: str | None = None
    file: str | None = None
    line: int | None = None
    symbol: str | None = None
    message: str | None = None
    tool_severity: str | None = None
    tool_confidence: str | None = None
    test_id: str | None = None
    exception_type: str | None = None
    fingerprint: str
    severity: FindingSeverity
    category: FindingCategory
    is_code_bug: bool
    needs_attention: bool
    issue_status: str
    fix_status: str
    action_tag: str | None = None
    triage_notes: str | None = None
    root_cause: str | None = None
    issue_title: str | None = None
    github_issue_number: int | None = None
    github_issue_url: str | None = None
    fix_branch: str | None = None
    fix_explanation: str | None = None
    github_pr_number: int | None = None
    github_pr_url: str | None = None
    pr_status: str = "none"


class LlmCallOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    purpose: str
    model: str
    input_tokens: int
    output_tokens: int
    cost_usd: float
    success: bool
    error_message: str | None = None
    created_at: datetime


class FixAttemptOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    attempt_number: int
    status: FixAttemptStatus
    branch_name: str | None = None
    files_changed_json: str | None = None
    unified_diff: str | None = None
    explanation: str | None = None
    safety_ok: bool | None = None
    safety_violations_json: str | None = None
    tests_passed: bool | None = None
    original_failure_gone: bool | None = None
    new_failures: int | None = None
    error_message: str | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None


class DiffFileOut(BaseModel):
    path: str
    original: str
    modified: str
    added_lines: int = 0
    removed_lines: int = 0


class PullRequestOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    finding_id: UUID
    branch_name: str
    base_branch: str
    title: str
    body: str | None = None
    github_pr_number: int | None = None
    github_pr_url: str | None = None
    draft: bool = True
    dry_run: bool = False
    status: str
    pushed: bool = False
    created_at: datetime


class FindingDetailOut(FindingOut):
    run_id: UUID
    repository_id: UUID | None = None
    repository_full_name: str | None = None
    branch: str | None = None
    issue_body: str | None = None
    llm_calls: list[LlmCallOut] = []
    fix_attempts: list[FixAttemptOut] = []
    verified_diff: str | None = None
    verified_files: list[DiffFileOut] = []
    pull_requests: list[PullRequestOut] = []


class ConfirmIssueOut(BaseModel):
    finding_id: UUID
    issue_status: str
    github_issue_number: int | None = None
    github_issue_url: str | None = None
    dry_run: bool = False
    detail: str | None = None
    fix_queued: bool = False


class DiscardFixOut(BaseModel):
    finding_id: UUID
    fix_status: str
    detail: str | None = None


class ApprovePrOut(BaseModel):
    finding_id: UUID
    fix_status: str
    pr_status: str
    github_pr_number: int | None = None
    github_pr_url: str | None = None
    branch: str | None = None
    dry_run: bool = False
    pushed: bool = False
    detail: str | None = None
    pull_request: PullRequestOut | None = None


class TestingCountsOut(BaseModel):
    total: int = 0
    passed: int = 0
    failed: int = 0
    error: int = 0
    skipped: int = 0
    flaky: int = 0
    pylint: int = 0
    bandit: int = 0


class TestingRowOut(BaseModel):
    key: str
    case_name: str | None = None
    classname: str | None = None
    before_status: str | None = None
    after_status: str | None = None
    before_message: str | None = None
    after_message: str | None = None
    duration_seconds: float | None = None
    tag: str  # fixed | regression | changed | skipped | unchanged


class TestingDashboardOut(BaseModel):
    run_id: UUID
    repository_full_name: str | None = None
    branch: str | None = None
    finding_id: UUID | None = None
    fix_status: str | None = None
    fix_branch: str | None = None
    attempt_number: int | None = None
    before: TestingCountsOut
    after: TestingCountsOut
    fixed_count: int = 0
    regression_count: int = 0
    note: str | None = None
    rows: list[TestingRowOut] = []
    test_env: str | None = None
    workflow_file: str | None = None
    python_version: str | None = None


class FindingSummaryOut(BaseModel):
    critical: int = 0
    high: int = 0
    medium: int = 0
    low: int = 0
    setup_failed: int = 0
    environment: int = 0
    flaky: int = 0
    needs_attention: int = 0
    code_bugs: int = 0


class AnalysisRunOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    repository_id: UUID
    repository_full_name: str | None = None
    branch: str
    runner_type: RunnerType
    status: RunStatus
    commit_sha: str | None = None
    github_workflow_run_id: int | None = None
    error_message: str | None = None
    tests_total: int = 0
    tests_passed: int = 0
    tests_failed: int = 0
    tests_errors: int = 0
    tests_skipped: int = 0
    started_at: datetime | None = None
    finished_at: datetime | None = None
    created_at: datetime
    steps: list[RunStepOut] = []
    test_results: list[TestResultOut] = []
    findings: list[FindingOut] = []
    summary: FindingSummaryOut | None = None
