"""Test runners: SandboxRunner + GitHubActionsRunner."""

from app.runners.base import RunOutcome, RunRequest, TestRunner

# Concrete runners imported lazily by callers / jobs.

__all__ = [
    "RunRequest",
    "RunOutcome",
    "TestRunner",
    "SandboxRunner",
    "GitHubActionsRunner",
]
