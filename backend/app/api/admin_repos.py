from __future__ import annotations

import logging
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from itsdangerous import URLSafeTimedSerializer

from app.auth import github_app as ghapp
from app.config import Settings, get_settings
from app.database import get_db
from app.deps import AuthContext, require_admin
from app import repo_service
from app.models import RepoStatus, RepoTestConfig, Repository, TestEnv
from app.schemas import (
    AvailableRepoOut,
    ConnectRepoIn,
    GithubInstallationOut,
    InstallUrlOut,
    RepoTestConfigIn,
    RepositoryOut,
    TestConnectionOut,
    WorkflowOptionOut,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/admin", tags=["admin-repos"])


def _repo_out(repo) -> RepositoryOut:
    return RepositoryOut.model_validate(repo)


@router.get("/github-app", response_model=GithubInstallationOut)
def github_app_status(
    auth: AuthContext = Depends(require_admin),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> GithubInstallationOut:
    inst = repo_service.get_installation_for_org(db, auth.org.id)
    if inst is None:
        return GithubInstallationOut(
            installed=False,
            configured=settings.github_app_configured(),
            app_slug=settings.github_app_slug or None,
        )
    return GithubInstallationOut(
        installed=True,
        installation_id=inst.installation_id,
        account_login=inst.account_login,
        account_type=inst.account_type,
        suspended=inst.suspended,
        configured=settings.github_app_configured(),
        app_slug=settings.github_app_slug or None,
    )


@router.get("/github-app/install-url", response_model=InstallUrlOut)
def github_app_install_url(
    auth: AuthContext = Depends(require_admin),
    settings: Settings = Depends(get_settings),
) -> InstallUrlOut:
    if not settings.github_app_slug:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="GITHUB_APP_SLUG is not configured",
        )
    state = URLSafeTimedSerializer(
        settings.session_secret, salt="rino-ghapp-install-v1"
    ).dumps({"org": str(auth.org.id), "uid": str(auth.user.id)})
    try:
        url = settings.github_app_install_url(state=state)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)
        ) from exc
    return InstallUrlOut(url=url, configured=settings.github_app_configured())


@router.get("/github/available-repos", response_model=list[AvailableRepoOut])
async def available_repos(
    auth: AuthContext = Depends(require_admin),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> list[AvailableRepoOut]:
    if not settings.github_app_configured():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="GitHub App credentials are not configured",
        )
    inst = repo_service.get_installation_for_org(db, auth.org.id)
    if inst is None or inst.suspended:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Install the GitHub App first",
        )
    try:
        remote = await ghapp.list_installation_repositories(
            settings, inst.installation_id
        )
    except Exception:
        logger.exception("Failed to list installation repositories")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Could not list repositories from GitHub",
        ) from None

    connected_ids = {
        r.github_repo_id for r in repo_service.list_connected_repos(db, auth.org.id)
    }
    out: list[AvailableRepoOut] = []
    for r in remote:
        rid = str(r["id"])
        out.append(
            AvailableRepoOut(
                github_repo_id=rid,
                full_name=r["full_name"],
                default_branch=r.get("default_branch") or "main",
                html_url=r.get("html_url"),
                private=bool(r.get("private", True)),
                connected=rid in connected_ids,
            )
        )
    out.sort(key=lambda x: x.full_name.lower())
    return out


@router.get("/repos", response_model=list[RepositoryOut])
async def list_repos(
    auth: AuthContext = Depends(require_admin),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> list[RepositoryOut]:
    inst = repo_service.get_installation_for_org(db, auth.org.id)
    if inst and settings.github_app_configured():
        await repo_service.sync_access_flags(
            db, settings, org_id=auth.org.id, installation=inst
        )
    repos = repo_service.list_connected_repos(db, auth.org.id)
    return [_repo_out(r) for r in repos]


@router.post("/repos", response_model=RepositoryOut, status_code=201)
async def connect_repo(
    body: ConnectRepoIn,
    auth: AuthContext = Depends(require_admin),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> RepositoryOut:
    if not settings.github_app_configured():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="GitHub App credentials are not configured",
        )
    inst = repo_service.get_installation_for_org(db, auth.org.id)
    if inst is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Install the GitHub App first",
        )
    try:
        remote = await ghapp.list_installation_repositories(
            settings, inst.installation_id
        )
    except Exception:
        logger.exception("Failed to list repos while connecting")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Could not reach GitHub",
        ) from None

    match = next((r for r in remote if str(r["id"]) == body.github_repo_id), None)
    if match is None and body.full_name:
        match = next(
            (r for r in remote if r["full_name"] == body.full_name), None
        )
    if match is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Repository is not available to this GitHub App installation",
        )

    repo = repo_service.connect_repository(
        db,
        org_id=auth.org.id,
        installation=inst,
        gh_repo=match,
        actor_user_id=auth.user.id,
    )
    return _repo_out(repo)


@router.get("/repos/{repo_id}", response_model=RepositoryOut)
def get_repo(
    repo_id: UUID,
    auth: AuthContext = Depends(require_admin),
    db: Session = Depends(get_db),
) -> RepositoryOut:
    repo = repo_service.get_repo_for_org(db, auth.org.id, repo_id)
    if repo is None:
        raise HTTPException(status_code=404, detail="Repository not found")
    return _repo_out(repo)


@router.put("/repos/{repo_id}/test-config", response_model=RepositoryOut)
def update_test_config(
    repo_id: UUID,
    body: RepoTestConfigIn,
    auth: AuthContext = Depends(require_admin),
    db: Session = Depends(get_db),
) -> RepositoryOut:
    repo = repo_service.get_repo_for_org(db, auth.org.id, repo_id)
    if repo is None:
        raise HTTPException(status_code=404, detail="Repository not found")
    updated = repo_service.save_test_config(
        db,
        repo=repo,
        payload=body.model_dump(exclude_unset=True),
        actor_user_id=auth.user.id,
    )
    return _repo_out(updated)


@router.post("/repos/{repo_id}/test-connection", response_model=TestConnectionOut)
async def test_connection(
    repo_id: UUID,
    auth: AuthContext = Depends(require_admin),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> TestConnectionOut:
    repo = repo_service.get_repo_for_org(db, auth.org.id, repo_id)
    if repo is None:
        raise HTTPException(status_code=404, detail="Repository not found")
    inst = repo_service.get_installation_for_org(db, auth.org.id)
    if inst is None:
        raise HTTPException(
            status_code=400, detail="Install the GitHub App first"
        )
    try:
        updated = await repo_service.test_connection(
            db,
            settings,
            repo=repo,
            installation=inst,
            actor_user_id=auth.user.id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception:
        logger.exception("Test connection failed")
        raise HTTPException(
            status_code=502, detail="Connection test failed talking to GitHub"
        ) from None

    cfg = updated.test_config
    return TestConnectionOut(
        ok=bool(cfg and cfg.last_check_ok),
        detail=(cfg.last_check_detail if cfg else "") or "",
        latency_ms=cfg.last_check_latency_ms if cfg else None,
        repository=_repo_out(updated),
    )


@router.get("/repos/{repo_id}/workflows", response_model=list[WorkflowOptionOut])
async def list_workflows(
    repo_id: UUID,
    auth: AuthContext = Depends(require_admin),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> list[WorkflowOptionOut]:
    repo = repo_service.get_repo_for_org(db, auth.org.id, repo_id)
    if repo is None:
        raise HTTPException(status_code=404, detail="Repository not found")
    inst = repo_service.get_installation_for_org(db, auth.org.id)
    if inst is None or not settings.github_app_configured():
        return [
            WorkflowOptionOut(path=".github/workflows/test.yml", name="test.yml"),
            WorkflowOptionOut(path=".github/workflows/ci.yml", name="ci.yml"),
        ]
    try:
        workflows = await ghapp.list_repo_workflows(
            settings, inst.installation_id, repo.github_full_name
        )
    except Exception:
        logger.exception("Failed to list workflows")
        return []
    out: list[WorkflowOptionOut] = []
    for w in workflows:
        path = w.get("path") or ""
        if not path:
            continue
        out.append(WorkflowOptionOut(path=path, name=w.get("name") or path))
    if not out:
        out = [
            WorkflowOptionOut(path=".github/workflows/test.yml", name="test.yml"),
            WorkflowOptionOut(path=".github/workflows/ci.yml", name="ci.yml"),
        ]
    return out


_LOCAL_SAMPLES = (
    ("junit-demo", "Bandit shell + pylint + env ImportError"),
    ("payments-core", "Failing test in core module src/payments/"),
    ("auth-service", "Hardcoded password + import probe"),
)


def _seed_one_local(
    db,
    *,
    org_id,
    actor_user_id,
    sample_name: str,
    detail: str,
) -> Repository:
    full_name = f"local/{sample_name}"
    repo = db.scalar(
        select(Repository).where(
            Repository.org_id == org_id,
            Repository.github_full_name == full_name,
        )
    )
    if repo is None:
        repo = Repository(
            org_id=org_id,
            github_repo_id=f"local-{sample_name}",
            github_full_name=full_name,
            default_branch="main",
            html_url=None,
            is_private=False,
            status=RepoStatus.ready,
            status_detail=detail,
        )
        db.add(repo)
        db.flush()
        db.add(
            RepoTestConfig(
                repository_id=repo.id,
                test_env=TestEnv.rino_sandbox,
                setup_command="pip install -r requirements.txt",
                test_command="pytest",
                python_version="3.11",
                shared_dev_instance=True,
                last_check_ok=True,
                last_check_detail=f"Local fixture · {detail}",
            )
        )
        repo_service.write_audit(
            db,
            org_id=org_id,
            actor_user_id=actor_user_id,
            action="repo.seed_local_sample",
            detail=full_name,
        )
    else:
        cfg = repo.test_config
        if cfg is None:
            db.add(
                RepoTestConfig(
                    repository_id=repo.id,
                    test_env=TestEnv.rino_sandbox,
                    setup_command="pip install -r requirements.txt",
                    test_command="pytest",
                    python_version="3.11",
                    shared_dev_instance=True,
                    last_check_ok=True,
                    last_check_detail=detail,
                )
            )
        repo.status = RepoStatus.ready
        repo.status_detail = detail
    return repo


@router.post("/repos/seed-local-sample", response_model=RepositoryOut)
def seed_local_sample(
    auth: AuthContext = Depends(require_admin),
    db: Session = Depends(get_db),
) -> RepositoryOut:
    """Register all three local sample fixtures; return junit-demo."""
    primary = None
    for name, detail in _LOCAL_SAMPLES:
        repo = _seed_one_local(
            db,
            org_id=auth.org.id,
            actor_user_id=auth.user.id,
            sample_name=name,
            detail=detail,
        )
        if name == "junit-demo":
            primary = repo
    db.commit()
    assert primary is not None
    repo = repo_service.get_repo_for_org(db, auth.org.id, primary.id)
    assert repo is not None
    return _repo_out(repo)


@router.post("/repos/seed-local-samples", response_model=list[RepositoryOut])
def seed_local_samples(
    auth: AuthContext = Depends(require_admin),
    db: Session = Depends(get_db),
) -> list[RepositoryOut]:
    """Seed junit-demo, payments-core, and auth-service under local/*."""
    out: list[RepositoryOut] = []
    for name, detail in _LOCAL_SAMPLES:
        repo = _seed_one_local(
            db,
            org_id=auth.org.id,
            actor_user_id=auth.user.id,
            sample_name=name,
            detail=detail,
        )
        out.append(repo)
    db.commit()
    result: list[RepositoryOut] = []
    for repo in out:
        loaded = repo_service.get_repo_for_org(db, auth.org.id, repo.id)
        assert loaded is not None
        result.append(_repo_out(loaded))
    return result
