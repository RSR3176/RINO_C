"""GitHub webhook signature verification + workflow_run parsing."""

from __future__ import annotations

import hashlib
import hmac
from dataclasses import dataclass
from typing import Any


def verify_github_signature(
    body: bytes,
    signature_header: str | None,
    secret: str,
) -> bool:
    """Validate ``X-Hub-Signature-256`` (sha256=…). Empty secret → reject."""
    if not secret:
        return False
    if not signature_header or not signature_header.startswith("sha256="):
        return False
    digest = hmac.new(
        secret.encode("utf-8"), body, hashlib.sha256
    ).hexdigest()
    expected = "sha256=" + digest
    return hmac.compare_digest(expected, signature_header)


@dataclass
class WorkflowRunEvent:
    """Normalized ``workflow_run`` webhook payload."""

    action: str
    run_id: int
    status: str  # queued | in_progress | completed
    conclusion: str | None  # success | failure | cancelled | …
    html_url: str
    head_branch: str
    head_sha: str
    workflow_path: str | None
    workflow_name: str | None
    repository_full_name: str
    event: str  # workflow_dispatch | push | …


def parse_webhook(
    event_name: str, payload: dict[str, Any]
) -> WorkflowRunEvent | dict[str, Any] | None:
    """Parse GitHub webhook events Rino cares about.

    Returns a ``WorkflowRunEvent`` for ``workflow_run``, a small dict for
    ``ping`` / ``installation``, or ``None`` when ignored.
    """
    if event_name == "ping":
        return {"type": "ping", "zen": payload.get("zen")}

    if event_name == "installation":
        installation = payload.get("installation") or {}
        account = installation.get("account") or {}
        return {
            "type": "installation",
            "action": payload.get("action"),
            "installation_id": installation.get("id"),
            "account_login": account.get("login"),
        }

    if event_name == "workflow_run":
        wr = payload.get("workflow_run") or {}
        repo = payload.get("repository") or {}
        workflow = payload.get("workflow") or {}
        run_id = wr.get("id")
        if run_id is None:
            return None
        path = workflow.get("path") or wr.get("path")
        return WorkflowRunEvent(
            action=str(payload.get("action") or ""),
            run_id=int(run_id),
            status=str(wr.get("status") or ""),
            conclusion=(
                str(wr["conclusion"]) if wr.get("conclusion") is not None else None
            ),
            html_url=str(wr.get("html_url") or ""),
            head_branch=str(wr.get("head_branch") or ""),
            head_sha=str(wr.get("head_sha") or ""),
            workflow_path=str(path) if path else None,
            workflow_name=str(workflow.get("name") or wr.get("name") or "")
            or None,
            repository_full_name=str(repo.get("full_name") or ""),
            event=str(wr.get("event") or ""),
        )

    if event_name == "check_suite":
        # Related but unused for dispatch polling — acknowledge parse shape only
        cs = payload.get("check_suite") or {}
        return {
            "type": "check_suite",
            "action": payload.get("action"),
            "status": cs.get("status"),
            "conclusion": cs.get("conclusion"),
        }

    return None
