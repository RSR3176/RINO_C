from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.auth import github_app as ghapp
from app.config import Settings
from app.models import (
    AuditLog,
    GithubInstallation,
    RepoStatus,
    RepoTestConfig,
    Repository,
    TestEnv,
)


def write_audit(
    db: Session,
    *,
    org_id: UUID,
    actor_user_id: UUID | None,
    action: str,
    detail: str | None = None,
) -> None:
    db.add(
        AuditLog(
            org_id=org_id,
            actor_user_id=actor_user_id,
            action=action,
            detail=detail,
        )
    )


def get_installation_for_org(
    db: Session, org_id: UUID
) -> GithubInstallation | None:
    return db.scalar(
        select(GithubInstallation).where(GithubInstallation.org_id == org_id)
    )


def upsert_installation(
    db: Session,
    *,
    org_id: UUID,
    installation_id: int,
    account_login: str,
    account_type: str,
    account_id: str | None,
    suspended: bool = False,
) -> GithubInstallation:
    row = get_installation_for_org(db, org_id)
    if row is None:
        # Installation might already be linked to another org — reassign carefully.
        existing = db.scalar(
            select(GithubInstallation).where(
                GithubInstallation.installation_id == installation_id
            )
        )
        if existing is not None:
            existing.org_id = org_id
            row = existing
        else:
            row = GithubInstallation(
                org_id=org_id,
                installation_id=installation_id,
                account_login=account_login,
                account_type=account_type,
                account_id=account_id,
                suspended=suspended,
            )
            db.add(row)
    row.installation_id = installation_id
    row.account_login = account_login
    row.account_type = account_type
    row.account_id = account_id
    row.suspended = suspended
    db.commit()
    db.refresh(row)
    return row


def compute_repo_status(
    config: RepoTestConfig | None, *, accessible: bool
) -> tuple[RepoStatus, str | None]:
    if not accessible:
        return RepoStatus.access_revoked, "Access revoked"

    if config is None or config.test_env is None:
        return RepoStatus.needs_attention, "Needs attention · no test env"

    env = config.test_env
    if env in {TestEnv.github_actions, TestEnv.dev_instance}:
        if not (config.workflow_file or "").strip():
            return RepoStatus.needs_attention, "Needs attention · no workflow"
        if config.last_check_ok is False:
            return RepoStatus.needs_attention, "Needs attention"
        if config.last_check_ok is True:
            return RepoStatus.ready, "Ready"
        return RepoStatus.needs_attention, "Needs attention · not verified"

    if env == TestEnv.rino_sandbox:
        missing = []
        if not (config.setup_command or "").strip():
            missing.append("setup")
        if not (config.test_command or "").strip():
            missing.append("test")
        if not (config.python_version or "").strip():
            missing.append("python")
        if missing:
            return (
                RepoStatus.needs_attention,
                "Needs attention · incomplete sandbox config",
            )
        if config.last_check_ok is False:
            return RepoStatus.needs_attention, "Needs attention"
        return RepoStatus.ready, "Ready"

    return RepoStatus.needs_attention, "Needs attention"


def apply_status(repo: Repository, config: RepoTestConfig | None, *, accessible: bool) -> None:
    status, detail = compute_repo_status(config, accessible=accessible)
    repo.status = status
    repo.status_detail = detail


def list_connected_repos(db: Session, org_id: UUID) -> list[Repository]:
    return list(
        db.scalars(
            select(Repository)
            .options(joinedload(Repository.test_config))
            .where(Repository.org_id == org_id)
            .order_by(Repository.github_full_name.asc())
        ).unique()
    )


def get_repo_for_org(
    db: Session, org_id: UUID, repo_id: UUID
) -> Repository | None:
    return db.scalar(
        select(Repository)
        .options(joinedload(Repository.test_config))
        .where(Repository.org_id == org_id, Repository.id == repo_id)
    )


def connect_repository(
    db: Session,
    *,
    org_id: UUID,
    installation: GithubInstallation,
    gh_repo: dict[str, Any],
    actor_user_id: UUID | None,
) -> Repository:
    github_repo_id = str(gh_repo["id"])
    full_name = gh_repo["full_name"]
    repo = db.scalar(
        select(Repository)
        .options(joinedload(Repository.test_config))
        .where(Repository.org_id == org_id, Repository.github_repo_id == github_repo_id)
    )
    if repo is None:
        repo = Repository(
            org_id=org_id,
            installation_id=installation.id,
            github_repo_id=github_repo_id,
            github_full_name=full_name,
            default_branch=gh_repo.get("default_branch") or "main",
            html_url=gh_repo.get("html_url"),
            is_private=bool(gh_repo.get("private", True)),
            status=RepoStatus.needs_attention,
            status_detail="Needs attention · no test env",
        )
        db.add(repo)
        db.flush()
        config = RepoTestConfig(
            repository_id=repo.id,
            shared_dev_instance=True,
        )
        db.add(config)
    else:
        repo.installation_id = installation.id
        repo.github_full_name = full_name
        repo.default_branch = gh_repo.get("default_branch") or repo.default_branch
        repo.html_url = gh_repo.get("html_url") or repo.html_url
        repo.is_private = bool(gh_repo.get("private", repo.is_private))
        if repo.test_config is None:
            db.add(RepoTestConfig(repository_id=repo.id, shared_dev_instance=True))
            db.flush()

    apply_status(repo, repo.test_config, accessible=True)
    write_audit(
        db,
        org_id=org_id,
        actor_user_id=actor_user_id,
        action="repo.connected",
        detail=full_name,
    )
    db.commit()
    db.refresh(repo)
    return get_repo_for_org(db, org_id, repo.id)  # type: ignore[return-value]


def save_test_config(
    db: Session,
    *,
    repo: Repository,
    payload: dict[str, Any],
    actor_user_id: UUID | None,
) -> Repository:
    config = repo.test_config
    if config is None:
        config = RepoTestConfig(repository_id=repo.id)
        db.add(config)
        db.flush()
        repo.test_config = config

    if "test_env" in payload:
        raw = payload["test_env"]
        config.test_env = TestEnv(raw) if raw else None
    if "workflow_file" in payload:
        config.workflow_file = payload["workflow_file"] or None
    if "setup_command" in payload:
        config.setup_command = payload["setup_command"] or None
    if "test_command" in payload:
        config.test_command = payload["test_command"] or None
    if "python_version" in payload:
        config.python_version = payload["python_version"] or None
    if "shared_dev_instance" in payload:
        config.shared_dev_instance = bool(payload["shared_dev_instance"])

    # Changing config invalidates prior connection check until re-tested
    # (except sandbox which can be ready without remote check once complete).
    if config.test_env in {TestEnv.github_actions, TestEnv.dev_instance}:
        if config.last_check_ok and config.workflow_file:
            pass  # keep last check; UI can re-test
        apply_status(repo, config, accessible=repo.status != RepoStatus.access_revoked)
    else:
        apply_status(repo, config, accessible=repo.status != RepoStatus.access_revoked)

    write_audit(
        db,
        org_id=repo.org_id,
        actor_user_id=actor_user_id,
        action="repo.test_config.saved",
        detail=f"{repo.github_full_name} env={config.test_env}",
    )
    db.commit()
    return get_repo_for_org(db, repo.org_id, repo.id)  # type: ignore[return-value]


async def test_connection(
    db: Session,
    settings: Settings,
    *,
    repo: Repository,
    installation: GithubInstallation,
    actor_user_id: UUID | None,
) -> Repository:
    config = repo.test_config
    if config is None or config.test_env is None:
        raise ValueError("Choose where tests run before testing the connection")

    started = time.perf_counter()
    ok = False
    detail = ""

    if config.test_env in {TestEnv.github_actions, TestEnv.dev_instance}:
        path = (config.workflow_file or "").strip()
        if not path:
            raise ValueError("Set a workflow file first")
        file_info = await ghapp.get_repo_file(
            settings,
            installation.installation_id,
            repo.github_full_name,
            path,
            ref=repo.default_branch,
        )
        if file_info is None:
            ok = False
            detail = f"Workflow not found: {path}"
        else:
            ok = True
            detail = f"Found {path}"
            if config.test_env == TestEnv.dev_instance:
                runners = await ghapp.list_repo_runners(
                    settings,
                    installation.installation_id,
                    repo.github_full_name,
                )
                online = [
                    r
                    for r in runners
                    if r.get("status") == "online"
                    or "self-hosted" in (r.get("labels") or [])
                ]
                # Soft signal — still OK if workflow exists; note runner state.
                if online:
                    detail += f" · runner online ({len(online)})"
                elif runners:
                    detail += " · runners offline"
                else:
                    detail += " · no self-hosted runners visible (label: self-hosted, rino-dev)"

    elif config.test_env == TestEnv.rino_sandbox:
        missing = []
        if not (config.setup_command or "").strip():
            missing.append("setup command")
        if not (config.test_command or "").strip():
            missing.append("test command")
        if not (config.python_version or "").strip():
            missing.append("Python version")
        if missing:
            ok = False
            detail = "Missing: " + ", ".join(missing)
        else:
            ok = True
            detail = (
                f"Sandbox config looks valid (Python {config.python_version}). "
                "Container runs land in a later step."
            )
    else:
        raise ValueError("Unknown test environment")

    latency_ms = int((time.perf_counter() - started) * 1000)
    config.last_checked_at = datetime.now(timezone.utc)
    config.last_check_ok = ok
    config.last_check_detail = detail
    config.last_check_latency_ms = latency_ms
    apply_status(repo, config, accessible=True)
    write_audit(
        db,
        org_id=repo.org_id,
        actor_user_id=actor_user_id,
        action="repo.test_connection",
        detail=f"{repo.github_full_name}: {'ok' if ok else 'fail'} — {detail}",
    )
    db.commit()
    return get_repo_for_org(db, repo.org_id, repo.id)  # type: ignore[return-value]


async def sync_access_flags(
    db: Session,
    settings: Settings,
    *,
    org_id: UUID,
    installation: GithubInstallation,
) -> None:
    """Mark connected repos access_revoked if missing from the installation."""
    try:
        remote = await ghapp.list_installation_repositories(
            settings, installation.installation_id
        )
    except Exception:
        return
    remote_ids = {str(r["id"]) for r in remote}
    for repo in list_connected_repos(db, org_id):
        accessible = repo.github_repo_id in remote_ids
        apply_status(repo, repo.test_config, accessible=accessible)
    db.commit()
