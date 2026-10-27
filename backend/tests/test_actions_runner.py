"""Unit/integration tests for GitHubActionsRunner (dry-run, no live GitHub)."""

from __future__ import annotations

import hashlib
import hmac
import tempfile
import unittest
from pathlib import Path

from app.git.base import (
    WorkflowDispatchResult,
    WorkflowResults,
    WorkflowRunStatus,
)
from app.git.webhooks import (
    WorkflowRunEvent,
    parse_webhook,
    verify_github_signature,
)
from app.runners.actions import GitHubActionsRunner
from app.runners.base import RunRequest


class FakeActionsProvider:
    """Minimal GitProvider surface used by GitHubActionsRunner."""

    def __init__(self) -> None:
        self.triggered = False
        self.pushed = False

    def trigger_workflow(self, full_name, *, workflow_file, ref, inputs=None):
        self.triggered = True
        return WorkflowDispatchResult(
            workflow_id="test.yml",
            ref=ref,
            dry_run=True,
            run_id=7001,
            html_url=f"dry-run://{full_name}/actions/runs/7001",
        )

    def get_workflow_run(self, full_name, run_id):
        return WorkflowRunStatus(
            run_id=run_id,
            status="completed",
            conclusion="success",
            html_url=f"dry-run://{full_name}/actions/runs/{run_id}",
            head_sha="abc123",
            head_branch="main",
            dry_run=True,
        )

    def find_latest_workflow_run(self, *args, **kwargs):
        return self.get_workflow_run("x/y", 7001)

    def get_workflow_results(self, full_name, run_id, *, artifact_name_hint=None):
        fixture = (
            Path(__file__).resolve().parents[1]
            / "app"
            / "runners"
            / "fixtures"
            / "sample-junit.xml"
        )
        return WorkflowResults(
            run_id=run_id,
            status="completed",
            conclusion="success",
            junit_xml=fixture.read_bytes(),
            artifact_names=["rino-junit"],
            dry_run=True,
        )

    def push_rino_branch(self, full_name, *, workspace, branch):
        self.pushed = True
        if not branch.startswith("rino/"):
            raise ValueError("not rino")
        return False  # dry-run push


class WebhookTests(unittest.TestCase):
    def test_signature_roundtrip(self) -> None:
        body = b'{"zen":"test"}'
        secret = "s3cr3t"
        digest = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
        self.assertTrue(
            verify_github_signature(body, "sha256=" + digest, secret)
        )
        self.assertFalse(
            verify_github_signature(body, "sha256=deadbeef", secret)
        )
        self.assertFalse(verify_github_signature(body, None, secret))

    def test_parse_workflow_run(self) -> None:
        payload = {
            "action": "completed",
            "workflow_run": {
                "id": 42,
                "status": "completed",
                "conclusion": "success",
                "html_url": "https://github.com/o/r/actions/runs/42",
                "head_branch": "rino/analysis",
                "head_sha": "deadbeef",
                "event": "workflow_dispatch",
                "path": ".github/workflows/test.yml",
            },
            "workflow": {"path": ".github/workflows/test.yml", "name": "test"},
            "repository": {"full_name": "acme/demo"},
        }
        parsed = parse_webhook("workflow_run", payload)
        self.assertIsInstance(parsed, WorkflowRunEvent)
        assert isinstance(parsed, WorkflowRunEvent)
        self.assertEqual(parsed.run_id, 42)
        self.assertEqual(parsed.repository_full_name, "acme/demo")
        self.assertEqual(parsed.conclusion, "success")


class ActionsRunnerDryRunTests(unittest.TestCase):
    def test_end_to_end_dry_run_parses_junit(self) -> None:
        provider = FakeActionsProvider()
        runner = GitHubActionsRunner(provider=provider)  # type: ignore[arg-type]
        with tempfile.TemporaryDirectory() as tmp:
            outcome = runner.run(
                RunRequest(
                    repository_full_name="local/junit-demo",
                    branch="main",
                    setup_command="true",
                    test_command="pytest",
                    workflow_file=".github/workflows/test.yml",
                    work_root=tmp,
                    actions_dry_run=True,
                    timeout_seconds=60,
                )
            )
        self.assertTrue(provider.triggered)
        names = [s.name for s in outcome.steps]
        self.assertIn("trigger_workflow", names)
        self.assertIn("poll_workflow", names)
        self.assertIn("download_artifact", names)
        self.assertIn("parse_junit", names)
        self.assertTrue(any(s.name == "parse_junit" and s.ok for s in outcome.steps))
        self.assertGreaterEqual(len(outcome.tests), 2)
        self.assertEqual(outcome.commit_sha, "abc123")

    def test_push_rino_branch_invoked_when_requested(self) -> None:
        provider = FakeActionsProvider()
        runner = GitHubActionsRunner(provider=provider)  # type: ignore[arg-type]
        with tempfile.TemporaryDirectory() as tmp:
            ws = Path(tmp) / "src"
            ws.mkdir()
            (ws / "README").write_text("x")
            outcome = runner.run(
                RunRequest(
                    repository_full_name="acme/demo",
                    branch="main",
                    setup_command="true",
                    test_command="pytest",
                    workflow_file="ci.yml",
                    push_workspace=str(ws),
                    push_branch="rino/analysis-1",
                    work_root=tmp,
                    actions_dry_run=True,
                    timeout_seconds=60,
                )
            )
        self.assertTrue(provider.pushed)
        push = next(s for s in outcome.steps if s.name == "push_branch")
        self.assertTrue(push.ok)
        self.assertEqual(push.detail.get("branch"), "rino/analysis-1")

    def test_rejects_missing_workflow_file(self) -> None:
        runner = GitHubActionsRunner(provider=FakeActionsProvider())  # type: ignore[arg-type]
        outcome = runner.run(
            RunRequest(
                repository_full_name="acme/demo",
                branch="main",
                setup_command="true",
                test_command="pytest",
                workflow_file="",
                actions_dry_run=True,
            )
        )
        self.assertFalse(outcome.ok)
        self.assertIn("workflow_file", (outcome.error_message or "").lower())


if __name__ == "__main__":
    unittest.main()
