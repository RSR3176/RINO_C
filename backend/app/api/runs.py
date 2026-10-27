from __future__ import annotations

import logging
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.database import get_db
from app.deps import AuthContext, require_developer
from app.jobs.sandbox_run import (
    ACTIONS_ENVS,
    STEP_ORDER_ACTIONS,
    STEP_ORDER_SANDBOX,
    run_sandbox_analysis,
)
from app.models import (
    AnalysisRun,
    FindingCategory,
    FindingSeverity,
    RepoStatus,
    Repository,
    RunnerType,
    RunStatus,
    RunStep,
    StepStatus,
    TestEnv,
)
from app.queue import get_queue
from app.schemas import (
    AnalysisRunOut,
    CreateRunIn,
    FindingOut,
    FindingSummaryOut,
    RepositorySummaryOut,
    RunStepOut,
    TestResultOut,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/developer", tags=["developer-runs"])

_RUN_LOAD = (
    joinedload(AnalysisRun.repository).joinedload(Repository.test_config),
    joinedload(AnalysisRun.steps),
    joinedload(AnalysisRun.test_results),
    joinedload(AnalysisRun.findings),
)


def _summary(run: AnalysisRun) -> FindingSummaryOut:
    summary = FindingSummaryOut()
    for f in run.findings or []:
        if f.category == FindingCategory.setup_failed:
            summary.setup_failed += 1
        elif f.category == FindingCategory.environment:
            summary.environment += 1
        elif f.category == FindingCategory.flaky:
            summary.flaky += 1
        if not f.is_code_bug:
            continue
        summary.code_bugs += 1
        if f.severity == FindingSeverity.critical:
            summary.critical += 1
        elif f.severity == FindingSeverity.high:
            summary.high += 1
        elif f.severity == FindingSeverity.medium:
            summary.medium += 1
        elif f.severity == FindingSeverity.low:
            summary.low += 1
        if f.needs_attention:
            summary.needs_attention += 1
    return summary


def _run_out(run: AnalysisRun) -> AnalysisRunOut:
    return AnalysisRunOut(
        id=run.id,
        repository_id=run.repository_id,
        repository_full_name=run.repository.github_full_name
        if run.repository
        else None,
        branch=run.branch,
        runner_type=run.runner_type,
        status=run.status,
        commit_sha=run.commit_sha,
        github_workflow_run_id=run.github_workflow_run_id,
        error_message=run.error_message,
        tests_total=run.tests_total,
        tests_passed=run.tests_passed,
        tests_failed=run.tests_failed,
        tests_errors=run.tests_errors,
        tests_skipped=run.tests_skipped,
        started_at=run.started_at,
        finished_at=run.finished_at,
        created_at=run.created_at,
        steps=[RunStepOut.model_validate(s) for s in (run.steps or [])],
        test_results=[
            TestResultOut.model_validate(t) for t in (run.test_results or [])
        ],
        findings=[FindingOut.model_validate(f) for f in (run.findings or [])],
        summary=_summary(run),
    )


@router.get("/repos", response_model=list[RepositorySummaryOut])
def list_sandbox_repos(
    auth: AuthContext = Depends(require_developer),
    db: Session = Depends(get_db),
) -> list[RepositorySummaryOut]:
    repos = db.scalars(
        select(Repository)
        .options(joinedload(Repository.test_config))
        .where(Repository.org_id == auth.org.id)
        .order_by(Repository.github_full_name.asc())
    ).unique()
    out: list[RepositorySummaryOut] = []
    for repo in repos:
        cfg = repo.test_config
        out.append(
            RepositorySummaryOut(
                id=repo.id,
                github_full_name=repo.github_full_name,
                default_branch=repo.default_branch,
                status=repo.status,
                test_env=cfg.test_env if cfg else None,
                sandbox_ready=_repo_analysis_ready(repo, cfg),
                analysis_ready=_repo_analysis_ready(repo, cfg),
            )
        )
    return out


def _repo_analysis_ready(repo: Repository, cfg) -> bool:
    if cfg is None or repo.status == RepoStatus.access_revoked:
        return False
    if cfg.test_env == TestEnv.rino_sandbox:
        return bool(cfg.setup_command and cfg.test_command and cfg.python_version)
    if cfg.test_env in ACTIONS_ENVS:
        return bool((cfg.workflow_file or "").strip())
    return False


@router.post("/repos/{repo_id}/runs", response_model=AnalysisRunOut, status_code=201)
def start_sandbox_run(
    repo_id: UUID,
    body: CreateRunIn,
    auth: AuthContext = Depends(require_developer),
    db: Session = Depends(get_db),
) -> AnalysisRunOut:
    repo = db.scalar(
        select(Repository)
        .options(joinedload(Repository.test_config))
        .where(Repository.id == repo_id, Repository.org_id == auth.org.id)
    )
    if repo is None:
        raise HTTPException(status_code=404, detail="Repository not found")
    cfg = repo.test_config
    if cfg is None or cfg.test_env is None:
        raise HTTPException(
            status_code=400,
            detail="Configure a test environment in Repository Setup first",
        )
    use_actions = cfg.test_env in ACTIONS_ENVS
    if cfg.test_env == TestEnv.rino_sandbox:
        if not (cfg.setup_command and cfg.test_command and cfg.python_version):
            raise HTTPException(
                status_code=400,
                detail="Sandbox setup/test commands and Python version must be configured",
            )
        runner_type = RunnerType.sandbox
        step_order = STEP_ORDER_SANDBOX
    elif use_actions:
        if not (cfg.workflow_file or "").strip():
            raise HTTPException(
                status_code=400,
                detail="Set a workflow file with workflow_dispatch for Actions / Dev instance",
            )
        runner_type = RunnerType.github_actions
        step_order = STEP_ORDER_ACTIONS
    else:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported test_env={cfg.test_env}",
        )

    branch = (body.branch or repo.default_branch or "main").strip()
    run = AnalysisRun(
        org_id=auth.org.id,
        repository_id=repo.id,
        triggered_by_user_id=auth.user.id,
        branch=branch,
        runner_type=runner_type,
        status=RunStatus.queued,
    )
    db.add(run)
    db.flush()
    for idx, name in enumerate(step_order):
        db.add(
            RunStep(
                run_id=run.id,
                name=name,
                sort_order=idx,
                status=StepStatus.pending,
            )
        )
    db.commit()

    try:
        job = get_queue().enqueue(
            run_sandbox_analysis,
            str(run.id),
            job_timeout=660,
            result_ttl=3600,
            failure_ttl=86400,
        )
        run.rq_job_id = job.id
        db.commit()
    except Exception:
        logger.exception("Failed to enqueue sandbox job")
        run.status = RunStatus.failed
        run.error_message = "Failed to enqueue background job"
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Job queue unavailable",
        ) from None

    run = db.scalar(
        select(AnalysisRun).options(*_RUN_LOAD).where(AnalysisRun.id == run.id)
    )
    assert run is not None
    return _run_out(run)


@router.get("/runs/{run_id}", response_model=AnalysisRunOut)
def get_run(
    run_id: UUID,
    auth: AuthContext = Depends(require_developer),
    db: Session = Depends(get_db),
) -> AnalysisRunOut:
    run = db.scalar(
        select(AnalysisRun)
        .options(*_RUN_LOAD)
        .where(AnalysisRun.id == run_id, AnalysisRun.org_id == auth.org.id)
    )
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")
    return _run_out(run)


@router.get("/runs", response_model=list[AnalysisRunOut])
def list_runs(
    auth: AuthContext = Depends(require_developer),
    db: Session = Depends(get_db),
    repository_id: UUID | None = Query(default=None),
) -> list[AnalysisRunOut]:
    stmt = (
        select(AnalysisRun)
        .options(*_RUN_LOAD)
        .where(AnalysisRun.org_id == auth.org.id)
        .order_by(AnalysisRun.created_at.desc())
        .limit(50)
    )
    if repository_id is not None:
        stmt = stmt.where(AnalysisRun.repository_id == repository_id)
    runs = db.scalars(stmt).unique()
    return [_run_out(r) for r in runs]
