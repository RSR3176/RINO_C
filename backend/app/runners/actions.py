"""GitHub Actions / Dev-instance TestRunner (Step 8)."""

from __future__ import annotations

import logging
import os
import tempfile
import time
from pathlib import Path

from app.config import get_settings
from app.git import get_git_provider
from app.git.base import GitProvider
from app.runners.base import RunOutcome, RunRequest, StepOutcome, TestRunner
from app.runners.junit import parse_junit_xml

logger = logging.getLogger(__name__)

DEFAULT_POLL_SECONDS = 5.0


class GitHubActionsRunner(TestRunner):
    """Trigger ``workflow_dispatch``, poll, download JUnit artifact.

    Used when ``RepoTestConfig.test_env`` is ``github_actions`` or
    ``dev_instance`` (self-hosted runners still go through Actions workflows).

    With ``GITHUB_ACTIONS_DRY_RUN=true`` (default) or missing GitHub App /
    ``local/*`` repos, uses the GitProvider dry-run path and a fixture JUnit
    XML — no live GitHub calls.
    """

    def __init__(self, provider: GitProvider | None = None) -> None:
        self._provider = provider

    def run(self, request: RunRequest) -> RunOutcome:
        settings = get_settings()
        provider = self._provider or get_git_provider(
            settings,
            installation_id=request.installation_id,
            force_dry_run=request.actions_dry_run,
        )
        outcome = RunOutcome(ok=False)
        deadline = time.monotonic() + max(60, request.timeout_seconds)
        workflow = (request.workflow_file or "").strip()
        if not workflow:
            outcome.error_message = "No workflow_file configured"
            outcome.steps.append(
                StepOutcome(
                    name="trigger_workflow",
                    ok=False,
                    log_text=outcome.error_message,
                )
            )
            return outcome

        ref = request.branch
        # Optional: push a rino/* analysis branch before dispatch
        push_step = self._maybe_push(provider, request)
        outcome.steps.append(push_step)
        if push_step.detail.get("branch"):
            ref = str(push_step.detail["branch"])
        if not push_step.ok and push_step.detail.get("required"):
            outcome.error_message = "Failed to push analysis branch"
            return outcome

        # 1) workflow_dispatch
        trigger_step = StepOutcome(name="trigger_workflow", ok=False)
        try:
            dispatched = provider.trigger_workflow(
                request.repository_full_name,
                workflow_file=workflow,
                ref=ref,
            )
            trigger_step.ok = True
            trigger_step.log_text = (
                f"Dispatched {dispatched.workflow_id} on {dispatched.ref}"
                + (" (dry-run)" if dispatched.dry_run else "")
            )
            trigger_step.detail = {
                "workflow_id": dispatched.workflow_id,
                "ref": dispatched.ref,
                "dry_run": dispatched.dry_run,
                "run_id": dispatched.run_id,
                "html_url": dispatched.html_url,
            }
        except Exception as exc:
            logger.exception("trigger_workflow failed")
            trigger_step.log_text = f"workflow_dispatch failed: {exc}"
            outcome.error_message = "workflow_dispatch failed"
            outcome.steps.append(trigger_step)
            return outcome
        outcome.steps.append(trigger_step)

        run_id = dispatched.run_id
        created_at = time.time()

        # 2) Discover run id if live dispatch returned 204
        if run_id is None:
            discover = StepOutcome(name="discover_run", ok=False)
            for _ in range(12):
                if time.monotonic() > deadline:
                    break
                found = provider.find_latest_workflow_run(
                    request.repository_full_name,
                    workflow_file=workflow,
                    branch=ref,
                    event="workflow_dispatch",
                    created_after_epoch=created_at - 5,
                )
                if found is not None:
                    run_id = found.run_id
                    discover.ok = True
                    discover.log_text = f"Found workflow run {run_id}"
                    discover.detail = {
                        "run_id": run_id,
                        "html_url": found.html_url,
                    }
                    if found.head_sha:
                        outcome.commit_sha = found.head_sha
                    break
                time.sleep(DEFAULT_POLL_SECONDS)
            outcome.steps.append(discover)
            if run_id is None:
                discover.log_text = "Could not find workflow run after dispatch"
                outcome.error_message = discover.log_text
                return outcome
        else:
            outcome.steps.append(
                StepOutcome(
                    name="discover_run",
                    ok=True,
                    log_text=f"Using run id {run_id}",
                    detail={"run_id": run_id, "html_url": dispatched.html_url},
                )
            )

        # 3) Poll until completed (webhook can accelerate via Redis — optional)
        poll_step = StepOutcome(name="poll_workflow", ok=False)
        poll_logs: list[str] = []
        final_status = None
        while time.monotonic() < deadline:
            # Prefer Redis signal from webhook if present
            cached = _redis_workflow_status(run_id)
            if cached:
                status_name = cached.get("status") or ""
                conclusion = cached.get("conclusion")
                poll_logs.append(
                    f"webhook signal status={status_name} conclusion={conclusion}"
                )
                if status_name == "completed":
                    final_status = provider.get_workflow_run(
                        request.repository_full_name, run_id
                    )
                    break
            try:
                st = provider.get_workflow_run(
                    request.repository_full_name, run_id
                )
            except Exception as exc:
                poll_logs.append(f"poll error: {exc}")
                time.sleep(DEFAULT_POLL_SECONDS)
                continue
            poll_logs.append(
                f"status={st.status} conclusion={st.conclusion}"
            )
            if st.head_sha:
                outcome.commit_sha = st.head_sha
            if st.status == "completed":
                final_status = st
                break
            if st.dry_run:
                final_status = st
                break
            time.sleep(DEFAULT_POLL_SECONDS)

        if final_status is None:
            poll_step.log_text = "Timed out waiting for workflow_run\n" + "\n".join(
                poll_logs[-20:]
            )
            outcome.timed_out = True
            outcome.error_message = "Timed out waiting for GitHub Actions"
            outcome.steps.append(poll_step)
            return outcome

        poll_step.ok = final_status.conclusion in {
            "success",
            None,
        } or final_status.conclusion == "success"
        # Treat failure conclusion as ok=False for the step but still parse JUnit
        if final_status.conclusion == "success":
            poll_step.ok = True
        elif final_status.conclusion in {"failure", "timed_out", "cancelled"}:
            poll_step.ok = False
        else:
            poll_step.ok = final_status.status == "completed"
        poll_step.log_text = "\n".join(poll_logs[-30:])
        poll_step.detail = {
            "run_id": run_id,
            "status": final_status.status,
            "conclusion": final_status.conclusion,
            "html_url": final_status.html_url,
            "dry_run": final_status.dry_run,
        }
        outcome.steps.append(poll_step)

        # 4) Download JUnit artifact
        dl_step = StepOutcome(name="download_artifact", ok=False)
        try:
            results = provider.get_workflow_results(
                request.repository_full_name,
                run_id,
                artifact_name_hint=request.artifact_name_hint or "rino-junit",
            )
            if results.junit_xml:
                work = Path(
                    request.work_root
                    or tempfile.mkdtemp(prefix="rino-actions-")
                )
                work.mkdir(parents=True, exist_ok=True)
                junit_path = work / "rino-junit.xml"
                junit_path.write_bytes(results.junit_xml)
                outcome.junit_xml_path = str(junit_path)
                dl_step.ok = True
                dl_step.log_text = (
                    f"Downloaded JUnit ({len(results.junit_xml)} bytes) "
                    f"from artifacts={results.artifact_names}"
                    + (" (dry-run fixture)" if results.dry_run else "")
                )
                dl_step.detail = {
                    "artifacts": results.artifact_names,
                    "dry_run": results.dry_run,
                    "run_id": run_id,
                }
            else:
                dl_step.log_text = (
                    f"No JUnit XML in artifacts {results.artifact_names}"
                )
                outcome.error_message = "JUnit artifact missing"
        except Exception as exc:
            logger.exception("get_workflow_results failed")
            dl_step.log_text = f"Artifact download failed: {exc}"
            outcome.error_message = "Artifact download failed"
            outcome.steps.append(dl_step)
            return outcome
        outcome.steps.append(dl_step)

        # 5) Parse JUnit
        parse_step = StepOutcome(name="parse_junit", ok=False)
        if outcome.junit_xml_path and Path(outcome.junit_xml_path).is_file():
            try:
                tests = parse_junit_xml(outcome.junit_xml_path)
                outcome.tests = tests
                parse_step.ok = True
                parse_step.log_text = f"Parsed {len(tests)} test case(s)"
                parse_step.detail = {"count": len(tests)}
            except Exception as exc:
                parse_step.log_text = f"JUnit parse failed: {exc}"
                outcome.error_message = "JUnit parse failed"
        else:
            parse_step.log_text = "No JUnit file to parse"
        outcome.steps.append(parse_step)

        # Actions path does not run local pylint/bandit (sandbox does).
        outcome.steps.append(
            StepOutcome(
                name="lint",
                ok=True,
                log_text="Skipped (GitHub Actions runner — static analysis not fetched)",
            )
        )

        failed = any(t.status in {"failed", "error"} for t in outcome.tests)
        outcome.ok = (
            parse_step.ok
            and final_status.conclusion == "success"
            and not failed
        ) or (
            # Dry-run fixture may include a deliberate failure — still a successful
            # runner invocation if we parsed results.
            parse_step.ok and bool(final_status.dry_run)
        )
        if not outcome.ok and not outcome.error_message:
            if final_status.conclusion and final_status.conclusion != "success":
                outcome.error_message = (
                    f"Workflow conclusion={final_status.conclusion}"
                )
            elif failed:
                outcome.error_message = "One or more tests failed"
        # Store workflow run id for webhook correlation
        outcome.steps[-1].detail = {
            **(outcome.steps[-1].detail or {}),
            "github_workflow_run_id": run_id,
        }
        return outcome

    def _maybe_push(
        self, provider: GitProvider, request: RunRequest
    ) -> StepOutcome:
        step = StepOutcome(name="push_branch", ok=True, log_text="No push requested")
        workspace = request.push_workspace
        branch = request.push_branch
        if not workspace or not branch:
            step.detail = {"skipped": True}
            return step
        if not branch.startswith("rino/"):
            step.ok = False
            step.log_text = f"Refusing non-rino branch {branch!r}"
            step.detail = {"required": True}
            return step
        try:
            pushed = provider.push_rino_branch(
                request.repository_full_name,
                workspace=Path(workspace),
                branch=branch,
            )
            step.ok = True
            step.log_text = (
                f"Pushed {branch}" if pushed else f"Dry-run skip push {branch}"
            )
            step.detail = {"branch": branch, "pushed": pushed}
        except Exception as exc:
            step.ok = False
            step.log_text = f"Push failed: {exc}"
            step.detail = {"required": True, "branch": branch}
        return step


def _redis_workflow_status(run_id: int) -> dict | None:
    """Optional webhook→Redis bridge (set by /webhooks/github)."""
    try:
        import redis

        url = os.environ.get("REDIS_URL") or get_settings().redis_url
        client = redis.Redis.from_url(url, decode_responses=True)
        key = f"rino:workflow_run:{run_id}"
        data = client.hgetall(key)
        return data or None
    except Exception:
        return None
