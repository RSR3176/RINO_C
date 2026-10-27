from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class IssueRef:
    number: int
    url: str
    title: str
    state: str  # open | closed
    fingerprint: str | None = None


@dataclass
class CreatedIssue:
    number: int
    url: str
    title: str
    dry_run: bool = False


@dataclass
class CreatedPullRequest:
    number: int
    url: str
    title: str
    draft: bool = True
    dry_run: bool = False
    pushed: bool = False
    branch: str = ""


@dataclass
class WorkflowDispatchResult:
    """Result of triggering ``workflow_dispatch``."""

    workflow_id: str
    ref: str
    dry_run: bool = False
    # Populated after we discover / poll the run
    run_id: int | None = None
    html_url: str | None = None


@dataclass
class WorkflowRunStatus:
    run_id: int
    status: str  # queued | in_progress | completed
    conclusion: str | None
    html_url: str
    head_sha: str | None = None
    head_branch: str | None = None
    dry_run: bool = False


@dataclass
class WorkflowResults:
    """Downloaded artifacts / JUnit from a completed workflow run."""

    run_id: int
    status: str
    conclusion: str | None
    junit_xml: bytes | None = None
    artifact_names: list[str] = field(default_factory=list)
    dry_run: bool = False
    detail: dict[str, Any] = field(default_factory=dict)


class GitProvider(ABC):
    """Issue + draft-PR + Actions workflow operations."""

    @abstractmethod
    def find_issue_by_fingerprint(
        self, full_name: str, fingerprint: str
    ) -> IssueRef | None:
        """Search open ai-found issues for a hidden rino fingerprint marker."""

    @abstractmethod
    def list_open_ai_found_issues(self, full_name: str) -> list[IssueRef]:
        raise NotImplementedError

    @abstractmethod
    def create_issue(
        self,
        full_name: str,
        *,
        title: str,
        body: str,
        labels: list[str],
    ) -> CreatedIssue:
        raise NotImplementedError

    @abstractmethod
    def comment_on_issue(
        self, full_name: str, issue_number: int, body: str
    ) -> str:
        """Post a comment; returns comment URL or dry-run:// token."""
        raise NotImplementedError

    @abstractmethod
    def push_rino_branch(
        self,
        full_name: str,
        *,
        workspace: Path,
        branch: str,
    ) -> bool:
        """Push only ``rino/*`` branches. Returns True if a real push happened."""

    @abstractmethod
    def create_draft_pull_request(
        self,
        full_name: str,
        *,
        title: str,
        body: str,
        head_branch: str,
        base_branch: str,
    ) -> CreatedPullRequest:
        """Open a draft PR from a ``rino/*`` head branch."""

    @abstractmethod
    def trigger_workflow(
        self,
        full_name: str,
        *,
        workflow_file: str,
        ref: str,
        inputs: dict[str, Any] | None = None,
    ) -> WorkflowDispatchResult:
        """Fire ``workflow_dispatch`` for the given workflow file on ``ref``."""

    @abstractmethod
    def get_workflow_run(
        self, full_name: str, run_id: int
    ) -> WorkflowRunStatus:
        """Fetch a single workflow run's status."""

    @abstractmethod
    def find_latest_workflow_run(
        self,
        full_name: str,
        *,
        workflow_file: str,
        branch: str,
        event: str = "workflow_dispatch",
        created_after_epoch: float | None = None,
    ) -> WorkflowRunStatus | None:
        """Locate the newest matching workflow run (post-dispatch)."""

    @abstractmethod
    def get_workflow_results(
        self,
        full_name: str,
        run_id: int,
        *,
        artifact_name_hint: str | None = "rino-junit",
    ) -> WorkflowResults:
        """Download JUnit XML from workflow artifacts when the run completed."""

    def parse_webhook(
        self, event_name: str, payload: dict[str, Any]
    ) -> Any:
        """Parse webhook payloads; default delegates to ``app.git.webhooks``."""
        from app.git.webhooks import parse_webhook as _parse

        return _parse(event_name, payload)
