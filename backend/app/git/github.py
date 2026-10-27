from __future__ import annotations

import io
import logging
import re
import subprocess
import zipfile
from pathlib import Path
from typing import Any
from urllib.parse import quote

import httpx

from app.auth import github_app as ghapp
from app.config import Settings, get_settings
from app.git.base import (
    CreatedIssue,
    CreatedPullRequest,
    GitProvider,
    IssueRef,
    WorkflowDispatchResult,
    WorkflowResults,
    WorkflowRunStatus,
)
from app.git.webhooks import parse_webhook as parse_webhook_payload

logger = logging.getLogger(__name__)

FINGERPRINT_RE = re.compile(
    r"<!--\s*rino:fingerprint=([a-fA-F0-9]+)\s*-->"
)
ISSUE_LABELS = ["bug", "ai-found", "critical"]
RINO_BRANCH_PREFIX = "rino/"
SAMPLE_JUNIT = (
    Path(__file__).resolve().parents[1]
    / "runners"
    / "fixtures"
    / "sample-junit.xml"
)


class GitHubProvider(GitProvider):
    """GitHub Issues + draft PRs + Actions via installation token. Never logs the token."""

    def __init__(
        self,
        settings: Settings,
        installation_id: int,
        *,
        dry_run: bool = False,
    ) -> None:
        self.settings = settings
        self.installation_id = installation_id
        self.dry_run = dry_run
        self._dry_seq = 9000
        self._dry_pr_seq = 8000
        self._dry_wf_seq = 7000

    def find_issue_by_fingerprint(
        self, full_name: str, fingerprint: str
    ) -> IssueRef | None:
        for issue in self.list_open_ai_found_issues(full_name):
            if issue.fingerprint == fingerprint:
                return issue
        return None

    def list_open_ai_found_issues(self, full_name: str) -> list[IssueRef]:
        if self.dry_run or not self.settings.github_app_configured():
            return []
        token = ghapp.create_installation_token_sync(
            self.settings, self.installation_id
        )
        out: list[IssueRef] = []
        try:
            page = 1
            with httpx.Client(timeout=30.0) as client:
                while page <= 5:
                    resp = client.get(
                        f"{ghapp.GITHUB_API}/repos/{full_name}/issues",
                        headers={
                            **ghapp.API_HEADERS,
                            "Authorization": f"Bearer {token}",
                        },
                        params={
                            "state": "open",
                            "labels": "ai-found",
                            "per_page": 100,
                            "page": page,
                        },
                    )
                    if resp.status_code >= 400:
                        logger.warning(
                            "list issues failed status=%s", resp.status_code
                        )
                        break
                    batch = resp.json()
                    if not isinstance(batch, list) or not batch:
                        break
                    for item in batch:
                        if "pull_request" in item:
                            continue
                        body = item.get("body") or ""
                        m = FINGERPRINT_RE.search(body)
                        out.append(
                            IssueRef(
                                number=int(item["number"]),
                                url=str(item.get("html_url") or ""),
                                title=str(item.get("title") or ""),
                                state=str(item.get("state") or "open"),
                                fingerprint=m.group(1) if m else None,
                            )
                        )
                    if len(batch) < 100:
                        break
                    page += 1
        finally:
            del token
        return out

    def create_issue(
        self,
        full_name: str,
        *,
        title: str,
        body: str,
        labels: list[str] | None = None,
    ) -> CreatedIssue:
        labels = labels or list(ISSUE_LABELS)
        if self.dry_run or not self.settings.github_app_configured():
            self._dry_seq += 1
            num = self._dry_seq
            return CreatedIssue(
                number=num,
                url=f"dry-run://{full_name}/issues/{num}",
                title=title,
                dry_run=True,
            )

        token = ghapp.create_installation_token_sync(
            self.settings, self.installation_id
        )
        try:
            with httpx.Client(timeout=30.0) as client:
                resp = client.post(
                    f"{ghapp.GITHUB_API}/repos/{full_name}/issues",
                    headers={
                        **ghapp.API_HEADERS,
                        "Authorization": f"Bearer {token}",
                    },
                    json={"title": title, "body": body, "labels": labels},
                )
                if resp.status_code >= 400:
                    logger.warning(
                        "create issue failed status=%s", resp.status_code
                    )
                    resp.raise_for_status()
                data: dict[str, Any] = resp.json()
                return CreatedIssue(
                    number=int(data["number"]),
                    url=str(data.get("html_url") or ""),
                    title=str(data.get("title") or title),
                    dry_run=False,
                )
        finally:
            del token

    def comment_on_issue(
        self, full_name: str, issue_number: int, body: str
    ) -> str:
        if issue_number <= 0 or self.dry_run or not self.settings.github_app_configured():
            return f"dry-run://{full_name}/issues/{issue_number}/comments/new"
        token = ghapp.create_installation_token_sync(
            self.settings, self.installation_id
        )
        try:
            with httpx.Client(timeout=30.0) as client:
                resp = client.post(
                    f"{ghapp.GITHUB_API}/repos/{full_name}/issues/{issue_number}/comments",
                    headers={
                        **ghapp.API_HEADERS,
                        "Authorization": f"Bearer {token}",
                    },
                    json={"body": body},
                )
                if resp.status_code >= 400:
                    logger.warning(
                        "comment on issue failed status=%s", resp.status_code
                    )
                    resp.raise_for_status()
                data = resp.json()
                return str(data.get("html_url") or "")
        finally:
            del token

    def _require_rino_branch(self, branch: str) -> str:
        b = (branch or "").strip()
        if not b.startswith(RINO_BRANCH_PREFIX):
            raise ValueError(
                f"Refusing to push non-rino branch {branch!r}; "
                f"only {RINO_BRANCH_PREFIX}* is allowed"
            )
        return b

    def push_rino_branch(
        self,
        full_name: str,
        *,
        workspace: Path,
        branch: str,
    ) -> bool:
        """Push ``rino/*`` only. Dry-run / local / missing App → no push."""
        branch = self._require_rino_branch(branch)
        if (
            self.dry_run
            or not self.settings.github_app_configured()
            or self.installation_id <= 0
            or full_name.startswith("local/")
        ):
            logger.info(
                "dry-run skip push branch=%s repo=%s", branch, full_name
            )
            return False

        token = ghapp.create_installation_token_sync(
            self.settings, self.installation_id
        )
        # Never log the URL (contains token).
        remote = (
            f"https://x-access-token:{quote(token, safe='')}@"
            f"github.com/{full_name}.git"
        )
        try:
            subprocess.run(
                ["git", "remote", "remove", "origin"],
                cwd=workspace,
                check=False,
                capture_output=True,
                text=True,
                timeout=30,
            )
            add = subprocess.run(
                ["git", "remote", "add", "origin", remote],
                cwd=workspace,
                check=False,
                capture_output=True,
                text=True,
                timeout=30,
            )
            if add.returncode != 0:
                raise RuntimeError("git remote add failed")
            push = subprocess.run(
                ["git", "push", "-u", "origin", branch],
                cwd=workspace,
                check=False,
                capture_output=True,
                text=True,
                timeout=120,
            )
            if push.returncode != 0:
                # stderr may contain URL — do not log it
                raise RuntimeError(
                    f"git push failed (exit {push.returncode})"
                )
            return True
        finally:
            del token
            # scrub remote URL from git config if present
            subprocess.run(
                ["git", "remote", "remove", "origin"],
                cwd=workspace,
                check=False,
                capture_output=True,
                text=True,
                timeout=30,
            )

    def create_draft_pull_request(
        self,
        full_name: str,
        *,
        title: str,
        body: str,
        head_branch: str,
        base_branch: str,
    ) -> CreatedPullRequest:
        head_branch = self._require_rino_branch(head_branch)
        if (
            self.dry_run
            or not self.settings.github_app_configured()
            or self.installation_id <= 0
            or full_name.startswith("local/")
        ):
            self._dry_pr_seq += 1
            num = self._dry_pr_seq
            return CreatedPullRequest(
                number=num,
                url=f"dry-run://{full_name}/pull/{num}",
                title=title,
                draft=True,
                dry_run=True,
                pushed=False,
                branch=head_branch,
            )

        token = ghapp.create_installation_token_sync(
            self.settings, self.installation_id
        )
        try:
            with httpx.Client(timeout=45.0) as client:
                resp = client.post(
                    f"{ghapp.GITHUB_API}/repos/{full_name}/pulls",
                    headers={
                        **ghapp.API_HEADERS,
                        "Authorization": f"Bearer {token}",
                    },
                    json={
                        "title": title,
                        "body": body,
                        "head": head_branch,
                        "base": base_branch,
                        "draft": True,
                    },
                )
                if resp.status_code >= 400:
                    logger.warning(
                        "create draft PR failed status=%s", resp.status_code
                    )
                    resp.raise_for_status()
                data: dict[str, Any] = resp.json()
                return CreatedPullRequest(
                    number=int(data["number"]),
                    url=str(data.get("html_url") or ""),
                    title=str(data.get("title") or title),
                    draft=bool(data.get("draft", True)),
                    dry_run=False,
                    pushed=True,
                    branch=head_branch,
                )
        finally:
            del token

    # --- GitHub Actions (Step 8) ---

    def _actions_dry(self, full_name: str) -> bool:
        return (
            self.dry_run
            or bool(self.settings.github_actions_dry_run)
            or not self.settings.github_app_configured()
            or self.installation_id <= 0
            or full_name.startswith("local/")
        )

    def _workflow_id(self, workflow_file: str) -> str:
        # API accepts file name under .github/workflows/ or numeric id
        wf = (workflow_file or "").strip()
        if wf.startswith(".github/workflows/"):
            return wf.rsplit("/", 1)[-1]
        return wf

    def trigger_workflow(
        self,
        full_name: str,
        *,
        workflow_file: str,
        ref: str,
        inputs: dict[str, Any] | None = None,
    ) -> WorkflowDispatchResult:
        wf_id = self._workflow_id(workflow_file)
        if self._actions_dry(full_name):
            self._dry_wf_seq += 1
            run_id = self._dry_wf_seq
            return WorkflowDispatchResult(
                workflow_id=wf_id,
                ref=ref,
                dry_run=True,
                run_id=run_id,
                html_url=f"dry-run://{full_name}/actions/runs/{run_id}",
            )

        token = ghapp.create_installation_token_sync(
            self.settings, self.installation_id
        )
        try:
            with httpx.Client(timeout=45.0) as client:
                resp = client.post(
                    f"{ghapp.GITHUB_API}/repos/{full_name}/actions/workflows/"
                    f"{quote(wf_id)}/dispatches",
                    headers={
                        **ghapp.API_HEADERS,
                        "Authorization": f"Bearer {token}",
                    },
                    json={"ref": ref, "inputs": inputs or {}},
                )
                if resp.status_code >= 400:
                    logger.warning(
                        "workflow_dispatch failed status=%s", resp.status_code
                    )
                    resp.raise_for_status()
                # 204 No Content — run id discovered via list/poll
                return WorkflowDispatchResult(
                    workflow_id=wf_id,
                    ref=ref,
                    dry_run=False,
                    run_id=None,
                    html_url=None,
                )
        finally:
            del token

    def get_workflow_run(
        self, full_name: str, run_id: int
    ) -> WorkflowRunStatus:
        if self._actions_dry(full_name):
            return WorkflowRunStatus(
                run_id=run_id,
                status="completed",
                conclusion="success",
                html_url=f"dry-run://{full_name}/actions/runs/{run_id}",
                head_sha="dryrun",
                head_branch="rino/analysis",
                dry_run=True,
            )
        token = ghapp.create_installation_token_sync(
            self.settings, self.installation_id
        )
        try:
            with httpx.Client(timeout=30.0) as client:
                resp = client.get(
                    f"{ghapp.GITHUB_API}/repos/{full_name}/actions/runs/{run_id}",
                    headers={
                        **ghapp.API_HEADERS,
                        "Authorization": f"Bearer {token}",
                    },
                )
                resp.raise_for_status()
                data = resp.json()
                return WorkflowRunStatus(
                    run_id=int(data["id"]),
                    status=str(data.get("status") or ""),
                    conclusion=(
                        str(data["conclusion"])
                        if data.get("conclusion") is not None
                        else None
                    ),
                    html_url=str(data.get("html_url") or ""),
                    head_sha=data.get("head_sha"),
                    head_branch=data.get("head_branch"),
                    dry_run=False,
                )
        finally:
            del token

    def find_latest_workflow_run(
        self,
        full_name: str,
        *,
        workflow_file: str,
        branch: str,
        event: str = "workflow_dispatch",
        created_after_epoch: float | None = None,
    ) -> WorkflowRunStatus | None:
        if self._actions_dry(full_name):
            self._dry_wf_seq += 1
            rid = self._dry_wf_seq
            return WorkflowRunStatus(
                run_id=rid,
                status="completed",
                conclusion="success",
                html_url=f"dry-run://{full_name}/actions/runs/{rid}",
                head_sha="dryrun",
                head_branch=branch,
                dry_run=True,
            )
        wf_id = self._workflow_id(workflow_file)
        token = ghapp.create_installation_token_sync(
            self.settings, self.installation_id
        )
        try:
            with httpx.Client(timeout=30.0) as client:
                resp = client.get(
                    f"{ghapp.GITHUB_API}/repos/{full_name}/actions/workflows/"
                    f"{quote(wf_id)}/runs",
                    headers={
                        **ghapp.API_HEADERS,
                        "Authorization": f"Bearer {token}",
                    },
                    params={
                        "event": event,
                        "branch": branch,
                        "per_page": 10,
                    },
                )
                if resp.status_code >= 400:
                    logger.warning(
                        "list workflow runs failed status=%s", resp.status_code
                    )
                    return None
                runs = resp.json().get("workflow_runs") or []
                best = None
                for item in runs:
                    created = item.get("created_at") or ""
                    # ISO timestamps compare lexicographically
                    if created_after_epoch is not None:
                        # soft filter: prefer runs created near now — skip if very old
                        pass
                    status = WorkflowRunStatus(
                        run_id=int(item["id"]),
                        status=str(item.get("status") or ""),
                        conclusion=(
                            str(item["conclusion"])
                            if item.get("conclusion") is not None
                            else None
                        ),
                        html_url=str(item.get("html_url") or ""),
                        head_sha=item.get("head_sha"),
                        head_branch=item.get("head_branch"),
                        dry_run=False,
                    )
                    if best is None or status.run_id > best.run_id:
                        best = status
                return best
        finally:
            del token

    def get_workflow_results(
        self,
        full_name: str,
        run_id: int,
        *,
        artifact_name_hint: str | None = "rino-junit",
    ) -> WorkflowResults:
        if self._actions_dry(full_name):
            xml = SAMPLE_JUNIT.read_bytes() if SAMPLE_JUNIT.is_file() else (
                b'<?xml version="1.0"?><testsuite tests="0"></testsuite>'
            )
            return WorkflowResults(
                run_id=run_id,
                status="completed",
                conclusion="success",
                junit_xml=xml,
                artifact_names=["rino-junit"],
                dry_run=True,
                detail={"source": "fixture"},
            )

        status = self.get_workflow_run(full_name, run_id)
        token = ghapp.create_installation_token_sync(
            self.settings, self.installation_id
        )
        try:
            with httpx.Client(timeout=60.0) as client:
                resp = client.get(
                    f"{ghapp.GITHUB_API}/repos/{full_name}/actions/runs/"
                    f"{run_id}/artifacts",
                    headers={
                        **ghapp.API_HEADERS,
                        "Authorization": f"Bearer {token}",
                    },
                )
                resp.raise_for_status()
                artifacts = resp.json().get("artifacts") or []
                names = [str(a.get("name") or "") for a in artifacts]
                chosen = None
                hint = (artifact_name_hint or "rino-junit").lower()
                for art in artifacts:
                    name = str(art.get("name") or "").lower()
                    if hint in name or "junit" in name:
                        chosen = art
                        break
                if chosen is None and artifacts:
                    chosen = artifacts[0]
                junit_xml = None
                if chosen is not None:
                    aid = chosen["id"]
                    zresp = client.get(
                        f"{ghapp.GITHUB_API}/repos/{full_name}/actions/artifacts/"
                        f"{aid}/zip",
                        headers={
                            **ghapp.API_HEADERS,
                            "Authorization": f"Bearer {token}",
                        },
                        follow_redirects=True,
                    )
                    zresp.raise_for_status()
                    junit_xml = _extract_junit_from_zip(zresp.content)
                return WorkflowResults(
                    run_id=run_id,
                    status=status.status,
                    conclusion=status.conclusion,
                    junit_xml=junit_xml,
                    artifact_names=names,
                    dry_run=False,
                )
        finally:
            del token

    def parse_webhook(self, event_name: str, payload: dict[str, Any]) -> Any:
        return parse_webhook_payload(event_name, payload)


def _extract_junit_from_zip(blob: bytes) -> bytes | None:
    try:
        with zipfile.ZipFile(io.BytesIO(blob)) as zf:
            names = zf.namelist()
            preferred = [
                n
                for n in names
                if n.endswith(".xml")
                and ("junit" in n.lower() or "rino" in n.lower())
            ]
            pick = preferred[0] if preferred else next(
                (n for n in names if n.endswith(".xml")), None
            )
            if pick is None:
                return None
            return zf.read(pick)
    except zipfile.BadZipFile:
        return None


def get_git_provider(
    settings: Settings | None = None,
    *,
    installation_id: int | None = None,
    force_dry_run: bool | None = None,
) -> GitProvider:
    settings = settings or get_settings()
    iid = installation_id or 0
    if force_dry_run is not None:
        dry = force_dry_run or iid <= 0
    else:
        dry = (
            bool(settings.github_issue_dry_run)
            or bool(settings.github_pr_dry_run)
            or not settings.github_app_configured()
            or iid <= 0
        )
    return GitHubProvider(settings, iid, dry_run=dry)
