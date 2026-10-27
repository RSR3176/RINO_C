"""Approve → push ``rino/fix-*`` branch + open draft PR (Step 7)."""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.config import Settings, get_settings
from app.fix.diffutil import write_text
from app.git import get_git_provider
from app.git.base import CreatedPullRequest
from app.models import (
    AnalysisRun,
    Finding,
    FixAttempt,
    FixAttemptStatus,
    PullRequest,
    Repository,
    TestResult,
)

logger = logging.getLogger(__name__)

RINO_BRANCH_PREFIX = "rino/"


def full_name_is_local(full_name: str) -> bool:
    return (full_name or "").startswith("local/")


@dataclass
class ApproveResult:
    ok: bool
    dry_run: bool
    pushed: bool
    pull_request_id: UUID | None
    github_pr_number: int | None
    github_pr_url: str | None
    branch: str | None
    detail: str
    body: str | None = None


def assert_rino_branch(branch: str) -> str:
    b = (branch or "").strip()
    if not b.startswith(RINO_BRANCH_PREFIX):
        raise ValueError(
            f"Rino only pushes branches under {RINO_BRANCH_PREFIX!r} (got {branch!r})"
        )
    suffix = b[len(RINO_BRANCH_PREFIX) :]
    if not suffix or ".." in b or b.startswith("-"):
        raise ValueError(f"Invalid rino branch name: {branch!r}")
    if any(ch in b for ch in (" ", "\n", "\0", "\\")):
        raise ValueError("Invalid branch name")
    return b


def test_case_key(classname: str | None, case_name: str) -> str:
    if classname:
        return f"{classname}::{case_name}"
    return case_name


def serialize_test_results(
    tests: list[TestResult] | list[dict],
) -> list[dict]:
    out: list[dict] = []
    for t in tests:
        if isinstance(t, dict):
            out.append(
                {
                    "suite_name": t.get("suite_name"),
                    "case_name": str(t.get("case_name") or ""),
                    "classname": t.get("classname"),
                    "status": str(t.get("status") or ""),
                    "message": t.get("message"),
                    "duration_seconds": t.get("duration_seconds"),
                }
            )
        else:
            status = t.status.value if hasattr(t.status, "value") else str(t.status)
            out.append(
                {
                    "suite_name": t.suite_name,
                    "case_name": t.case_name,
                    "classname": t.classname,
                    "status": status,
                    "message": t.message,
                    "duration_seconds": t.duration_seconds,
                }
            )
    return out


def summarize_tests(rows: list[dict]) -> dict:
    counts = {
        "total": len(rows),
        "passed": 0,
        "failed": 0,
        "error": 0,
        "skipped": 0,
    }
    for r in rows:
        st = str(r.get("status") or "")
        if st in counts:
            counts[st] += 1
        elif st == "passed":
            counts["passed"] += 1
    return counts


def build_pr_body(
    finding: Finding,
    *,
    before: list[dict],
    after: list[dict],
) -> str:
    issue_no = finding.github_issue_number
    before_s = summarize_tests(before)
    after_s = summarize_tests(after)
    lines = [
        f"Fixes #{issue_no}" if issue_no else "Fixes (issue pending)",
        "",
        "## Summary",
        finding.fix_explanation or finding.root_cause or "(no explanation)",
        "",
        "## Finding",
        f"- Severity: **{finding.severity.value if hasattr(finding.severity, 'value') else finding.severity}**",
        f"- Rule: `{finding.rule_id or finding.source}`",
        f"- Location: `{finding.file or '—'}"
        + (f":{finding.line}`" if finding.line is not None else "`"),
        "",
        "## Before / after tests",
        "",
        "| | Passed | Failed | Errors | Skipped | Total |",
        "|---|---:|---:|---:|---:|---:|",
        (
            f"| Before | {before_s['passed']} | {before_s['failed']} | "
            f"{before_s['error']} | {before_s['skipped']} | {before_s['total']} |"
        ),
        (
            f"| After | {after_s['passed']} | {after_s['failed']} | "
            f"{after_s['error']} | {after_s['skipped']} | {after_s['total']} |"
        ),
        "",
        "_Draft PR opened by Rino. Nothing merges automatically._",
        f"<!-- rino:fingerprint={finding.fingerprint} -->",
    ]
    return "\n".join(lines)


def approve_and_open_draft_pr(
    db: Session,
    finding: Finding,
    *,
    user_id: UUID | None,
    settings: Settings | None = None,
) -> ApproveResult:
    """Push ``rino/fix-<n>`` and open a draft PR. No-op push in dry-run."""
    settings = settings or get_settings()
    if finding.pr_status in {"open", "dry_run"} and finding.github_pr_url:
        existing = sorted(finding.pull_requests or [], key=lambda p: p.created_at)
        return ApproveResult(
            ok=True,
            dry_run=finding.pr_status == "dry_run"
            or (finding.github_pr_url or "").startswith("dry-run://"),
            pushed=bool(existing[-1].pushed) if existing else False,
            pull_request_id=existing[-1].id if existing else None,
            github_pr_number=finding.github_pr_number,
            github_pr_url=finding.github_pr_url,
            branch=finding.fix_branch,
            detail="Draft PR already recorded",
        )
    if finding.fix_status != "verified":
        return ApproveResult(
            ok=False,
            dry_run=False,
            pushed=False,
            pull_request_id=None,
            github_pr_number=None,
            github_pr_url=None,
            branch=finding.fix_branch,
            detail=f"Finding fix_status is {finding.fix_status!r}; need verified",
        )

    branch = assert_rino_branch(finding.fix_branch or "")
    run = finding.run
    repo = run.repository
    if repo is None:
        return ApproveResult(
            ok=False,
            dry_run=False,
            pushed=False,
            pull_request_id=None,
            github_pr_number=None,
            github_pr_url=None,
            branch=branch,
            detail="Repository missing",
        )

    before = serialize_test_results(list(run.test_results or []))
    verified_attempt = _verified_attempt(finding)
    after: list[dict] = []
    if verified_attempt and verified_attempt.tests_json:
        try:
            after = json.loads(verified_attempt.tests_json)
            if not isinstance(after, list):
                after = []
        except json.JSONDecodeError:
            after = []
    if not after:
        after = before

    title = finding.issue_title or f"Fix: {finding.rule_id or finding.source}"
    if finding.github_issue_number:
        title = f"{title} (Fixes #{finding.github_issue_number})"
    body = build_pr_body(finding, before=before, after=after)
    base = repo.default_branch or "main"

    installation = repo.installation
    provider = get_git_provider(
        settings,
        installation_id=installation.installation_id if installation else None,
    )

    work_parent = (
        Path(os.environ.get("RINO_SANDBOX_WORK_DIR", "/var/rino/sandbox"))
        / f"pr-{finding.id}"
    )
    pushed = False
    created: CreatedPullRequest | None = None
    err: str | None = None
    # Dry-run / local samples: record PR only — never push, no git required.
    will_live_push = not (
        getattr(provider, "dry_run", True)
        or full_name_is_local(repo.github_full_name)
        or not settings.github_app_configured()
    )
    try:
        if will_live_push:
            if work_parent.exists():
                shutil.rmtree(work_parent, ignore_errors=True)
            work_parent.mkdir(parents=True, exist_ok=True)
            src = work_parent / "src"
            _materialize_and_apply(repo.github_full_name, src, finding, branch)
            try:
                pushed = provider.push_rino_branch(
                    repo.github_full_name, workspace=src, branch=branch
                )
            except Exception as exc:
                logger.exception("push_rino_branch failed")
                err = str(exc)[:500]
                pushed = False

        created = provider.create_draft_pull_request(
            repo.github_full_name,
            title=title[:500],
            body=body,
            head_branch=branch,
            base_branch=base,
        )
    finally:
        if will_live_push and os.environ.get("RINO_SANDBOX_KEEP", "").strip() not in {
            "1",
            "true",
        }:
            shutil.rmtree(work_parent, ignore_errors=True)

    if created is None:
        return ApproveResult(
            ok=False,
            dry_run=False,
            pushed=pushed,
            pull_request_id=None,
            github_pr_number=None,
            github_pr_url=None,
            branch=branch,
            detail=err or "Failed to create draft PR",
        )

    pr = PullRequest(
        org_id=run.org_id,
        repository_id=repo.id,
        finding_id=finding.id,
        fix_attempt_id=verified_attempt.id if verified_attempt else None,
        created_by_user_id=user_id,
        branch_name=branch,
        base_branch=base,
        title=title[:500],
        body=body,
        github_pr_number=created.number,
        github_pr_url=created.url,
        draft=True,
        dry_run=created.dry_run,
        status="dry_run" if created.dry_run else "open",
        before_summary_json=json.dumps(summarize_tests(before)),
        after_summary_json=json.dumps(summarize_tests(after)),
        pushed=pushed and not created.dry_run,
        error_message=err,
    )
    db.add(pr)
    finding.github_pr_number = created.number
    finding.github_pr_url = created.url
    finding.pr_status = "dry_run" if created.dry_run else "open"
    finding.fix_status = "pr_opened"
    db.commit()
    db.refresh(pr)

    return ApproveResult(
        ok=True,
        dry_run=created.dry_run,
        pushed=pr.pushed,
        pull_request_id=pr.id,
        github_pr_number=created.number,
        github_pr_url=created.url,
        branch=branch,
        detail=(
            "Dry-run draft PR recorded (nothing pushed)"
            if created.dry_run
            else "Draft PR opened"
        ),
        body=body,
    )


def _verified_attempt(finding: Finding) -> FixAttempt | None:
    attempts = sorted(finding.fix_attempts or [], key=lambda a: a.attempt_number)
    for a in reversed(attempts):
        if a.status == FixAttemptStatus.verified:
            return a
    return attempts[-1] if attempts else None


def _materialize_and_apply(
    full_name: str, dest: Path, finding: Finding, branch: str
) -> None:
    dest.mkdir(parents=True, exist_ok=True)
    if full_name.startswith("local/"):
        name = full_name.split("/", 1)[1]
        root = Path(os.environ.get("RINO_SAMPLES_DIR", "/samples")) / name
        if not root.is_dir():
            raise RuntimeError(f"Local sample missing: {root}")
        for path in root.rglob("*"):
            if path.is_file():
                rel = path.relative_to(root)
                target = dest / rel
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(path, target)
    else:
        raise RuntimeError(
            "Approve currently supports local/* fixtures in this environment; "
            "remote clone+push requires GitHub App (non-dry-run)"
        )

    files: list[dict] = []
    if finding.verified_files_json:
        try:
            data = json.loads(finding.verified_files_json)
            if isinstance(data, list):
                files = [x for x in data if isinstance(x, dict)]
        except json.JSONDecodeError:
            files = []
    for item in files:
        path = str(item.get("path") or "")
        modified = item.get("modified")
        if not path or modified is None:
            continue
        write_text(dest / path, str(modified))

    def run(cmd: list[str]) -> None:
        subprocess.run(
            cmd, cwd=dest, check=False, capture_output=True, text=True, timeout=60
        )

    run(["git", "init"])
    run(["git", "config", "user.email", "rino@local"])
    run(["git", "config", "user.name", "Rino"])
    run(["git", "add", "-A"])
    run(["git", "commit", "-m", f"rino: fix {finding.rule_id or finding.id}"])
    run(["git", "checkout", "-B", branch])


def compare_tests(before: list[dict], after: list[dict]) -> list[dict]:
    """Build per-test rows for the Testing Dashboard."""
    before_map = {
        test_case_key(r.get("classname"), str(r.get("case_name") or "")): r
        for r in before
    }
    after_map = {
        test_case_key(r.get("classname"), str(r.get("case_name") or "")): r
        for r in after
    }
    keys = sorted(set(before_map) | set(after_map))
    rows: list[dict] = []
    for key in keys:
        b = before_map.get(key)
        a = after_map.get(key)
        b_status = (b or {}).get("status")
        a_status = (a or {}).get("status")
        tag = "unchanged"
        if b_status in {"failed", "error"} and a_status == "passed":
            tag = "fixed"
        elif b_status == "passed" and a_status in {"failed", "error"}:
            tag = "regression"
        elif b_status != a_status:
            tag = "changed"
        elif b_status == "skipped":
            tag = "skipped"
        rows.append(
            {
                "key": key,
                "case_name": (a or b or {}).get("case_name"),
                "classname": (a or b or {}).get("classname"),
                "before_status": b_status,
                "after_status": a_status,
                "before_message": (b or {}).get("message"),
                "after_message": (a or {}).get("message"),
                "duration_seconds": (a or b or {}).get("duration_seconds"),
                "tag": tag,
            }
        )
    return rows
