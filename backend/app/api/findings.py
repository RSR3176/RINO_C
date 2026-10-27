from __future__ import annotations

import json
import logging
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.config import get_settings
from app.database import get_db
from app.deps import AuthContext, require_developer
from app.fix.pr import approve_and_open_draft_pr
from app.git import get_git_provider
from app.git.github import ISSUE_LABELS
from app.issues import build_issue_proposal
from app.jobs.fix_finding import enqueue_fix_job
from app.models import (
    AnalysisRun,
    Finding,
    FindingSeverity,
    LlmCall,
    PullRequest,
    Repository,
)
from app.repo_service import write_audit
from app.schemas import (
    ApprovePrOut,
    ConfirmIssueOut,
    DiffFileOut,
    DiscardFixOut,
    FindingDetailOut,
    FixAttemptOut,
    LlmCallOut,
    PullRequestOut,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/developer", tags=["developer-findings"])


def _verified_files(finding: Finding) -> list[DiffFileOut]:
    if not finding.verified_files_json:
        return []
    try:
        data = json.loads(finding.verified_files_json)
    except json.JSONDecodeError:
        return []
    out: list[DiffFileOut] = []
    if isinstance(data, list):
        for item in data:
            if not isinstance(item, dict):
                continue
            out.append(
                DiffFileOut(
                    path=str(item.get("path") or ""),
                    original=str(item.get("original") or ""),
                    modified=str(item.get("modified") or ""),
                    added_lines=int(item.get("added_lines") or 0),
                    removed_lines=int(item.get("removed_lines") or 0),
                )
            )
    return out


def _detail(finding: Finding, llm_calls: list[LlmCall] | None = None) -> FindingDetailOut:
    run = finding.run
    repo = run.repository if run else None
    attempts = sorted(finding.fix_attempts or [], key=lambda a: a.attempt_number)
    prs = sorted(finding.pull_requests or [], key=lambda p: p.created_at)
    return FindingDetailOut(
        id=finding.id,
        run_id=finding.run_id,
        repository_id=run.repository_id if run else None,
        repository_full_name=repo.github_full_name if repo else None,
        branch=run.branch if run else None,
        source=finding.source,
        rule_id=finding.rule_id,
        file=finding.file,
        line=finding.line,
        symbol=finding.symbol,
        message=finding.message,
        tool_severity=finding.tool_severity,
        tool_confidence=finding.tool_confidence,
        test_id=finding.test_id,
        exception_type=finding.exception_type,
        fingerprint=finding.fingerprint,
        severity=finding.severity,
        category=finding.category,
        is_code_bug=finding.is_code_bug,
        needs_attention=finding.needs_attention,
        issue_status=finding.issue_status,
        fix_status=finding.fix_status,
        action_tag=finding.action_tag,
        triage_notes=finding.triage_notes,
        root_cause=finding.root_cause,
        issue_title=finding.issue_title,
        issue_body=finding.issue_body,
        github_issue_number=finding.github_issue_number,
        github_issue_url=finding.github_issue_url,
        fix_branch=finding.fix_branch,
        fix_explanation=finding.fix_explanation,
        github_pr_number=finding.github_pr_number,
        github_pr_url=finding.github_pr_url,
        pr_status=finding.pr_status or "none",
        llm_calls=[LlmCallOut.model_validate(c) for c in (llm_calls or [])],
        fix_attempts=[FixAttemptOut.model_validate(a) for a in attempts],
        verified_diff=finding.verified_diff,
        verified_files=_verified_files(finding),
        pull_requests=[PullRequestOut.model_validate(p) for p in prs],
    )


def _load_finding(db: Session, finding_id: UUID, org_id: UUID) -> Finding:
    finding = db.scalar(
        select(Finding)
        .options(
            joinedload(Finding.run)
            .joinedload(AnalysisRun.repository)
            .joinedload(Repository.installation),
            joinedload(Finding.run).joinedload(AnalysisRun.test_results),
            joinedload(Finding.llm_calls),
            joinedload(Finding.fix_attempts),
            joinedload(Finding.pull_requests),
        )
        .where(Finding.id == finding_id)
    )
    if finding is None or finding.run is None or finding.run.org_id != org_id:
        raise HTTPException(status_code=404, detail="Finding not found")
    return finding


def _maybe_enqueue_fix(finding: Finding, db: Session) -> bool:
    if finding.severity != FindingSeverity.critical or not finding.is_code_bug:
        return False
    if finding.fix_status in {"generating", "verified", "discarded", "queued"}:
        return False
    try:
        job_id = enqueue_fix_job(finding.id)
        finding.fix_status = "queued"
        finding.fix_rq_job_id = job_id
        db.commit()
        return True
    except Exception:
        logger.exception("Failed to enqueue fix job")
        return False


@router.get("/findings/{finding_id}", response_model=FindingDetailOut)
def get_finding(
    finding_id: UUID,
    auth: AuthContext = Depends(require_developer),
    db: Session = Depends(get_db),
) -> FindingDetailOut:
    finding = _load_finding(db, finding_id, auth.org.id)
    return _detail(finding, list(finding.llm_calls or []))


@router.get("/runs/{run_id}/review-findings", response_model=list[FindingDetailOut])
def list_review_findings(
    run_id: UUID,
    auth: AuthContext = Depends(require_developer),
    db: Session = Depends(get_db),
) -> list[FindingDetailOut]:
    """Critical + High code bugs for the Code Review screen."""
    run = db.scalar(
        select(AnalysisRun)
        .options(
            joinedload(AnalysisRun.findings).joinedload(Finding.llm_calls),
            joinedload(AnalysisRun.findings).joinedload(Finding.fix_attempts),
            joinedload(AnalysisRun.findings).joinedload(Finding.pull_requests),
            joinedload(AnalysisRun.repository),
        )
        .where(AnalysisRun.id == run_id, AnalysisRun.org_id == auth.org.id)
    )
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")
    out: list[FindingDetailOut] = []
    for f in run.findings or []:
        if not f.is_code_bug:
            continue
        if f.severity not in {FindingSeverity.critical, FindingSeverity.high}:
            continue
        out.append(_detail(f, list(f.llm_calls or [])))
    out.sort(
        key=lambda x: (0 if x.severity == FindingSeverity.critical else 1, x.file or "")
    )
    return out


@router.post(
    "/findings/{finding_id}/confirm-issue",
    response_model=ConfirmIssueOut,
)
def confirm_github_issue(
    finding_id: UUID,
    auth: AuthContext = Depends(require_developer),
    db: Session = Depends(get_db),
) -> ConfirmIssueOut:
    """Create the proposed GitHub Issue (or dry-run) after developer Confirm."""
    finding = _load_finding(db, finding_id, auth.org.id)
    if finding.severity != FindingSeverity.critical:
        raise HTTPException(
            status_code=400,
            detail="Only Critical findings propose GitHub Issues in Step 5",
        )
    if finding.issue_status in {"open", "linked", "dry_run"} and finding.github_issue_url:
        fix_queued = _maybe_enqueue_fix(finding, db)
        return ConfirmIssueOut(
            finding_id=finding.id,
            issue_status=finding.issue_status,
            github_issue_number=finding.github_issue_number,
            github_issue_url=finding.github_issue_url,
            dry_run=finding.issue_status == "dry_run"
            or (finding.github_issue_url or "").startswith("dry-run://"),
            detail="Issue already confirmed",
            fix_queued=fix_queued,
        )
    if finding.issue_status not in {"awaiting_confirm", "none"}:
        raise HTTPException(
            status_code=400,
            detail=f"Finding issue_status is {finding.issue_status}",
        )

    if not finding.issue_title or not finding.issue_body:
        title, body = build_issue_proposal(finding)
        finding.issue_title = title
        finding.issue_body = body

    settings = get_settings()
    repo = finding.run.repository
    installation = repo.installation if repo else None
    provider = get_git_provider(
        settings,
        installation_id=installation.installation_id if installation else None,
    )

    existing = provider.find_issue_by_fingerprint(
        repo.github_full_name, finding.fingerprint
    )
    if existing is not None:
        finding.github_issue_number = existing.number
        finding.github_issue_url = existing.url
        finding.issue_status = "linked"
        write_audit(
            db,
            org_id=auth.org.id,
            actor_user_id=auth.user.id,
            action="issue.linked_existing",
            detail=f"{repo.github_full_name}#{existing.number} fp={finding.fingerprint}",
        )
        db.commit()
        fix_queued = _maybe_enqueue_fix(finding, db)
        return ConfirmIssueOut(
            finding_id=finding.id,
            issue_status=finding.issue_status,
            github_issue_number=finding.github_issue_number,
            github_issue_url=finding.github_issue_url,
            dry_run=False,
            detail="Linked to existing open ai-found issue",
            fix_queued=fix_queued,
        )

    created = provider.create_issue(
        repo.github_full_name,
        title=finding.issue_title,
        body=finding.issue_body,
        labels=list(ISSUE_LABELS),
    )
    finding.github_issue_number = created.number
    finding.github_issue_url = created.url
    finding.issue_status = "dry_run" if created.dry_run else "open"
    write_audit(
        db,
        org_id=auth.org.id,
        actor_user_id=auth.user.id,
        action="issue.confirmed",
        detail=(
            f"{repo.github_full_name}#{created.number} "
            f"dry_run={created.dry_run} fp={finding.fingerprint}"
        ),
    )
    db.commit()
    fix_queued = _maybe_enqueue_fix(finding, db)
    return ConfirmIssueOut(
        finding_id=finding.id,
        issue_status=finding.issue_status,
        github_issue_number=finding.github_issue_number,
        github_issue_url=finding.github_issue_url,
        dry_run=created.dry_run,
        detail="Dry-run issue recorded (GitHub App not configured)"
        if created.dry_run
        else "GitHub Issue created",
        fix_queued=fix_queued,
    )


@router.post(
    "/findings/{finding_id}/discard-fix",
    response_model=DiscardFixOut,
)
def discard_fix(
    finding_id: UUID,
    auth: AuthContext = Depends(require_developer),
    db: Session = Depends(get_db),
) -> DiscardFixOut:
    """Discard the suggested fix — nothing is pushed."""
    finding = _load_finding(db, finding_id, auth.org.id)
    finding.fix_status = "discarded"
    # Keep attempts for history; clear verified payload so UI shows discarded
    finding.verified_diff = None
    finding.verified_files_json = None
    write_audit(
        db,
        org_id=auth.org.id,
        actor_user_id=auth.user.id,
        action="fix.discarded",
        detail=f"finding={finding.id} branch={finding.fix_branch}",
    )
    db.commit()
    return DiscardFixOut(
        finding_id=finding.id,
        fix_status=finding.fix_status,
        detail="Fix discarded — nothing pushed to GitHub",
    )


@router.post("/findings/{finding_id}/start-fix")
def start_fix(
    finding_id: UUID,
    auth: AuthContext = Depends(require_developer),
    db: Session = Depends(get_db),
) -> dict:
    """Manually enqueue a fix job for a Critical finding (also auto after confirm)."""
    finding = _load_finding(db, finding_id, auth.org.id)
    if finding.severity != FindingSeverity.critical:
        raise HTTPException(status_code=400, detail="Only Critical findings get fixes")
    if finding.fix_status == "discarded":
        raise HTTPException(status_code=400, detail="Fix was discarded")
    queued = _maybe_enqueue_fix(finding, db)
    if not queued and finding.fix_status not in {
        "queued",
        "generating",
        "verified",
        "pr_opened",
    }:
        raise HTTPException(status_code=503, detail="Could not enqueue fix job")
    return {
        "finding_id": str(finding.id),
        "fix_status": finding.fix_status,
        "fix_rq_job_id": finding.fix_rq_job_id,
    }


@router.post(
    "/findings/{finding_id}/approve-pr",
    response_model=ApprovePrOut,
)
def approve_draft_pr(
    finding_id: UUID,
    auth: AuthContext = Depends(require_developer),
    db: Session = Depends(get_db),
) -> ApprovePrOut:
    """Push ``rino/fix-<n>`` (if live) and open a draft PR — only on Approve."""
    finding = _load_finding(db, finding_id, auth.org.id)
    if finding.severity != FindingSeverity.critical:
        raise HTTPException(status_code=400, detail="Only Critical findings open PRs")
    if finding.fix_status == "discarded":
        raise HTTPException(status_code=400, detail="Fix was discarded")
    if finding.fix_status not in {"verified", "pr_opened"}:
        raise HTTPException(
            status_code=400,
            detail=f"Need a verified fix before Approve (status={finding.fix_status})",
        )

    # Idempotent: already opened (or dry-run recorded)
    if finding.fix_status == "pr_opened" and finding.github_pr_url:
        prs = sorted(finding.pull_requests or [], key=lambda p: p.created_at)
        pr_out = PullRequestOut.model_validate(prs[-1]) if prs else None
        return ApprovePrOut(
            finding_id=finding.id,
            fix_status=finding.fix_status,
            pr_status=finding.pr_status,
            github_pr_number=finding.github_pr_number,
            github_pr_url=finding.github_pr_url,
            branch=finding.fix_branch,
            dry_run=finding.pr_status == "dry_run"
            or (finding.github_pr_url or "").startswith("dry-run://"),
            pushed=bool(pr_out.pushed) if pr_out else False,
            detail="Draft PR already recorded",
            pull_request=pr_out,
        )

    result = approve_and_open_draft_pr(db, finding, user_id=auth.user.id)
    if not result.ok:
        raise HTTPException(status_code=400, detail=result.detail)

    write_audit(
        db,
        org_id=auth.org.id,
        actor_user_id=auth.user.id,
        action="pr.approved",
        detail=(
            f"finding={finding.id} branch={result.branch} "
            f"pr={result.github_pr_number} dry_run={result.dry_run} "
            f"pushed={result.pushed}"
        ),
    )
    db.commit()

    pr_out = None
    if result.pull_request_id:
        pr = db.get(PullRequest, result.pull_request_id)
        if pr:
            pr_out = PullRequestOut.model_validate(pr)

    db.refresh(finding)
    return ApprovePrOut(
        finding_id=finding.id,
        fix_status=finding.fix_status,
        pr_status=finding.pr_status,
        github_pr_number=result.github_pr_number,
        github_pr_url=result.github_pr_url,
        branch=result.branch,
        dry_run=result.dry_run,
        pushed=result.pushed,
        detail=result.detail,
        pull_request=pr_out,
    )
