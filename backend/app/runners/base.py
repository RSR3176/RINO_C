from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass
class RunRequest:
    """Inputs for a single test-runner invocation."""

    repository_full_name: str
    branch: str
    setup_command: str
    test_command: str
    python_version: str = "3.11"
    # Local fixture path (host path visible to the worker), e.g. /samples/junit-demo
    local_source_path: str | None = None
    # git clone URL (may embed a short-lived token — never log it)
    clone_url: str | None = None
    work_root: str | None = None
    timeout_seconds: int = 600
    memory_limit: str = "1g"
    cpus: str = "1.0"
    # --- GitHub Actions / Dev instance (Step 8) ---
    workflow_file: str | None = None
    artifact_name_hint: str = "rino-junit"
    # Local workspace to push as a rino/* branch before dispatch (optional)
    push_workspace: str | None = None
    push_branch: str | None = None
    installation_id: int | None = None
    # Force dry-run (no live GitHub calls) — also auto when App missing
    actions_dry_run: bool | None = None


@dataclass
class StepOutcome:
    name: str
    ok: bool
    exit_code: int | None = None
    log_text: str = ""
    detail: dict[str, Any] = field(default_factory=dict)


@dataclass
class ParsedTestCase:
    suite_name: str | None
    case_name: str
    classname: str | None
    status: str  # passed | failed | error | skipped
    message: str | None = None
    duration_seconds: float | None = None


@dataclass
class RunOutcome:
    ok: bool
    timed_out: bool = False
    commit_sha: str | None = None
    error_message: str | None = None
    steps: list[StepOutcome] = field(default_factory=list)
    tests: list[ParsedTestCase] = field(default_factory=list)
    junit_xml_path: str | None = None
    pylint_json_path: str | None = None
    bandit_json_path: str | None = None
    pylint_raw: object | None = None
    bandit_raw: object | None = None
    setup_failed: bool = False


class TestRunner(ABC):
    """Interface for executing a repository's tests."""

    @abstractmethod
    def run(self, request: RunRequest) -> RunOutcome:
        raise NotImplementedError
