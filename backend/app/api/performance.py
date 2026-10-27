"""Agent Performance Dashboard aggregates."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.database import get_db
from app.deps import AuthContext, require_developer
from app.models import (
    AnalysisRun,
    Finding,
    FindingSeverity,
    FixAttempt,
    FixAttemptStatus,
    LlmCall,
    PullRequest,
    Repository,
    RunStatus,
)

router = APIRouter(prefix="/api/developer", tags=["developer-performance"])


class PerfTotals(BaseModel):
    bugs_found: int = 0
    fixes_suggested: int = 0
    fixes_verified: int = 0
    fixes_approved: int = 0
    prs_opened: int = 0
    failed_fix_attempts: int = 0
    avg_run_seconds: float | None = None
    avg_time_to_fix_seconds: float | None = None
    tokens_per_run: float | None = None
    cost_per_run: float | None = None
    total_tokens: int = 0
    total_cost_usd: float = 0.0


class SeverityWeek(BaseModel):
    label: str
    critical: int = 0
    high: int = 0
    medium: int = 0
    low: int = 0


class SuccessWeek(BaseModel):
    label: str
    suggested: int = 0
    approved: int = 0
    rate: float = 0.0  # 0–100


class RecentRunRow(BaseModel):
    id: UUID
    repository_full_name: str | None = None
    branch: str
    test_env: str | None = None
    bugs_found: int = 0
    fixes_verified: int = 0
    status: str
    duration_seconds: float | None = None
    tokens: int = 0
    cost_usd: float = 0.0
    created_at: datetime


class PerformanceOut(BaseModel):
    range: str
    totals: PerfTotals
    severity_by_week: list[SeverityWeek]
    success_by_week: list[SuccessWeek]
    recent_runs: list[RecentRunRow]


def _range_start(range_key: str) -> datetime | None:
    now = datetime.now(timezone.utc)
    if range_key == "7d":
        return now - timedelta(days=7)
    if range_key == "30d":
        return now - timedelta(days=30)
    if range_key == "all":
        return None
    return now - timedelta(days=30)


@router.get("/performance", response_model=PerformanceOut)
def performance_dashboard(
    range: str = Query("30d", pattern="^(7d|30d|all)$"),
    repository_id: UUID | None = Query(None),
    auth: AuthContext = Depends(require_developer),
    db: Session = Depends(get_db),
) -> PerformanceOut:
    since = _range_start(range)
    run_q = (
        select(AnalysisRun)
        .options(
            joinedload(AnalysisRun.repository).joinedload(Repository.test_config),
            joinedload(AnalysisRun.findings),
        )
        .where(AnalysisRun.org_id == auth.org.id)
        .order_by(AnalysisRun.created_at.desc())
    )
    if since is not None:
        run_q = run_q.where(AnalysisRun.created_at >= since)
    if repository_id is not None:
        run_q = run_q.where(AnalysisRun.repository_id == repository_id)
    runs = list(db.scalars(run_q).unique().all())

    finding_ids: list[UUID] = []
    bugs = 0
    suggested = 0
    verified = 0
    approved = 0
    durations: list[float] = []
    for run in runs:
        for f in run.findings or []:
            if f.is_code_bug:
                bugs += 1
                finding_ids.append(f.id)
                if f.fix_status and f.fix_status not in {"none", ""}:
                    suggested += 1
                if f.fix_status in {"verified", "pr_opened"}:
                    verified += 1
                if f.fix_status == "pr_opened" or (
                    f.pr_status in {"open", "dry_run"}
                ):
                    approved += 1
        if run.started_at and run.finished_at:
            durations.append(
                (run.finished_at - run.started_at).total_seconds()
            )

    pr_q = select(PullRequest).where(PullRequest.org_id == auth.org.id)
    if since is not None:
        pr_q = pr_q.where(PullRequest.created_at >= since)
    prs = list(db.scalars(pr_q).all())
    if repository_id is not None:
        prs = [p for p in prs if p.repository_id == repository_id]
    prs_opened = len(prs)

    failed_attempts = 0
    time_to_fix: list[float] = []
    if finding_ids:
        attempts = db.scalars(
            select(FixAttempt).where(FixAttempt.finding_id.in_(finding_ids))
        ).all()
        for a in attempts:
            if a.status in {FixAttemptStatus.failed, FixAttemptStatus.rejected}:
                failed_attempts += 1
            if (
                a.status == FixAttemptStatus.verified
                and a.started_at
                and a.finished_at
            ):
                time_to_fix.append(
                    (a.finished_at - a.started_at).total_seconds()
                )

    run_ids = [r.id for r in runs]
    llm_calls: list[LlmCall] = []
    if run_ids:
        llm_calls = list(
            db.scalars(select(LlmCall).where(LlmCall.run_id.in_(run_ids))).all()
        )
    total_tokens = sum(c.input_tokens + c.output_tokens for c in llm_calls)
    total_cost = sum(float(c.cost_usd or 0) for c in llm_calls)
    n_runs = max(len(runs), 1)

    totals = PerfTotals(
        bugs_found=bugs,
        fixes_suggested=suggested,
        fixes_verified=verified,
        fixes_approved=approved,
        prs_opened=prs_opened,
        failed_fix_attempts=failed_attempts,
        avg_run_seconds=(sum(durations) / len(durations)) if durations else None,
        avg_time_to_fix_seconds=(
            sum(time_to_fix) / len(time_to_fix) if time_to_fix else None
        ),
        tokens_per_run=total_tokens / n_runs if runs else None,
        cost_per_run=total_cost / n_runs if runs else None,
        total_tokens=total_tokens,
        total_cost_usd=round(total_cost, 6),
    )

    severity_by_week = _severity_weeks(runs)
    success_by_week = _success_weeks(runs, prs)

    # LLM tokens/cost per run for table
    tokens_by_run: dict[UUID, int] = defaultdict(int)
    cost_by_run: dict[UUID, float] = defaultdict(float)
    for c in llm_calls:
        if c.run_id:
            tokens_by_run[c.run_id] += c.input_tokens + c.output_tokens
            cost_by_run[c.run_id] += float(c.cost_usd or 0)

    recent: list[RecentRunRow] = []
    for run in runs[:25]:
        dur = None
        if run.started_at and run.finished_at:
            dur = (run.finished_at - run.started_at).total_seconds()
        cfg = run.repository.test_config if run.repository else None
        recent.append(
            RecentRunRow(
                id=run.id,
                repository_full_name=(
                    run.repository.github_full_name if run.repository else None
                ),
                branch=run.branch,
                test_env=cfg.test_env.value if cfg and cfg.test_env else None,
                bugs_found=sum(1 for f in (run.findings or []) if f.is_code_bug),
                fixes_verified=sum(
                    1
                    for f in (run.findings or [])
                    if f.fix_status in {"verified", "pr_opened"}
                ),
                status=run.status.value if isinstance(run.status, RunStatus) else str(run.status),
                duration_seconds=dur,
                tokens=tokens_by_run.get(run.id, 0),
                cost_usd=round(cost_by_run.get(run.id, 0.0), 6),
                created_at=run.created_at,
            )
        )

    return PerformanceOut(
        range=range,
        totals=totals,
        severity_by_week=severity_by_week,
        success_by_week=success_by_week,
        recent_runs=recent,
    )


def _week_label(dt: datetime, idx_from_end: int, total: int) -> str:
    return f"Wk {total - idx_from_end}"


def _severity_weeks(runs: list[AnalysisRun], weeks: int = 4) -> list[SeverityWeek]:
    now = datetime.now(timezone.utc)
    buckets: list[SeverityWeek] = []
    for i in range(weeks):
        end = now - timedelta(days=7 * i)
        start = end - timedelta(days=7)
        label = _week_label(start, i, weeks)
        row = SeverityWeek(label=label)
        for run in runs:
            if run.created_at is None:
                continue
            created = run.created_at
            if created.tzinfo is None:
                created = created.replace(tzinfo=timezone.utc)
            if not (start <= created < end if i > 0 else start <= created):
                # For i==0 (most recent week): start <= created <= now
                if i == 0:
                    if not (start <= created <= now):
                        continue
                else:
                    if not (start <= created < end):
                        continue
            for f in run.findings or []:
                if not f.is_code_bug:
                    continue
                sev = f.severity
                if sev == FindingSeverity.critical:
                    row.critical += 1
                elif sev == FindingSeverity.high:
                    row.high += 1
                elif sev == FindingSeverity.medium:
                    row.medium += 1
                elif sev == FindingSeverity.low:
                    row.low += 1
        buckets.append(row)
    buckets.reverse()  # Wk 1 oldest → Wk 4 newest visually as Wk1..Wk4
    # Relabel after reverse
    for idx, b in enumerate(buckets):
        b.label = f"Wk {idx + 1}"
    return buckets


def _success_weeks(
    runs: list[AnalysisRun], prs: list[PullRequest], weeks: int = 4
) -> list[SuccessWeek]:
    now = datetime.now(timezone.utc)
    buckets: list[SuccessWeek] = []
    for i in range(weeks):
        end = now - timedelta(days=7 * i)
        start = end - timedelta(days=7)
        row = SuccessWeek(label=f"Wk {weeks - i}")
        for run in runs:
            created = run.created_at
            if created is None:
                continue
            if created.tzinfo is None:
                created = created.replace(tzinfo=timezone.utc)
            if i == 0:
                if not (start <= created <= now):
                    continue
            elif not (start <= created < end):
                continue
            for f in run.findings or []:
                if f.fix_status and f.fix_status not in {"none", ""}:
                    row.suggested += 1
                if f.fix_status == "pr_opened" or f.pr_status in {
                    "open",
                    "dry_run",
                }:
                    row.approved += 1
        row.rate = (
            round(100.0 * row.approved / row.suggested, 1) if row.suggested else 0.0
        )
        buckets.append(row)
    buckets.reverse()
    for idx, b in enumerate(buckets):
        b.label = f"Wk {idx + 1}"
    return buckets
