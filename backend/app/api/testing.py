"""Testing Dashboard — before/after existing tests for a fix attempt."""

from __future__ import annotations

import json
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.database import get_db
from app.deps import AuthContext, require_developer
from app.fix.pr import compare_tests, serialize_test_results, summarize_tests
from app.models import (
    AnalysisRun,
    Finding,
    FindingCategory,
    FixAttempt,
    FixAttemptStatus,
    Repository,
)
from app.schemas import TestingCountsOut, TestingDashboardOut, TestingRowOut

router = APIRouter(prefix="/api/developer", tags=["developer-testing"])


def _counts_from_summary(summary: dict, *, pylint: int = 0, bandit: int = 0) -> TestingCountsOut:
    return TestingCountsOut(
        total=int(summary.get("total") or 0),
        passed=int(summary.get("passed") or 0),
        failed=int(summary.get("failed") or 0),
        error=int(summary.get("error") or 0),
        skipped=int(summary.get("skipped") or 0),
        flaky=int(summary.get("flaky") or 0),
        pylint=pylint,
        bandit=bandit,
    )


def _static_from_findings(run: AnalysisRun) -> tuple[int, int]:
    pylint = bandit = 0
    for f in run.findings or []:
        if f.category == FindingCategory.ignored:
            continue
        if f.source == "pylint":
            pylint += 1
        elif f.source == "bandit":
            bandit += 1
    return pylint, bandit


def _pick_attempt(
    finding: Finding | None, attempt_id: UUID | None
) -> FixAttempt | None:
    if finding is None:
        return None
    attempts = sorted(finding.fix_attempts or [], key=lambda a: a.attempt_number)
    if attempt_id:
        for a in attempts:
            if a.id == attempt_id:
                return a
    for a in reversed(attempts):
        if a.status == FixAttemptStatus.verified and a.tests_json:
            return a
    for a in reversed(attempts):
        if a.tests_json:
            return a
    return attempts[-1] if attempts else None


@router.get("/testing", response_model=TestingDashboardOut)
def testing_dashboard(
    run_id: UUID = Query(...),
    finding_id: UUID | None = Query(None),
    attempt_id: UUID | None = Query(None),
    auth: AuthContext = Depends(require_developer),
    db: Session = Depends(get_db),
) -> TestingDashboardOut:
    """Compare original run tests vs a fix attempt's re-run (existing tests only)."""
    run = db.scalar(
        select(AnalysisRun)
        .options(
            joinedload(AnalysisRun.test_results),
            joinedload(AnalysisRun.findings).joinedload(Finding.fix_attempts),
            joinedload(AnalysisRun.repository).joinedload(Repository.test_config),
        )
        .where(AnalysisRun.id == run_id, AnalysisRun.org_id == auth.org.id)
    )
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")

    finding: Finding | None = None
    if finding_id:
        finding = next((f for f in (run.findings or []) if f.id == finding_id), None)
        if finding is None:
            raise HTTPException(status_code=404, detail="Finding not found on run")
    else:
        # Prefer verified Critical with tests, else any with fix attempts
        cands = [
            f
            for f in (run.findings or [])
            if f.fix_attempts
            and f.fix_status in {"verified", "pr_opened", "failed", "generating"}
        ]
        cands.sort(
            key=lambda f: (
                0 if f.fix_status in {"verified", "pr_opened"} else 1,
                f.file or "",
            )
        )
        finding = cands[0] if cands else None

    before_rows = serialize_test_results(list(run.test_results or []))
    before_pylint, before_bandit = _static_from_findings(run)

    attempt = _pick_attempt(finding, attempt_id)
    after_rows: list[dict] = []
    after_pylint = before_pylint
    after_bandit = before_bandit
    if attempt and attempt.tests_json:
        try:
            loaded = json.loads(attempt.tests_json)
            if isinstance(loaded, list):
                after_rows = serialize_test_results(loaded)
        except json.JSONDecodeError:
            after_rows = []
        if attempt.static_counts_json:
            try:
                sc = json.loads(attempt.static_counts_json)
                after_pylint = int(sc.get("pylint") or after_pylint)
                after_bandit = int(sc.get("bandit") or after_bandit)
            except (json.JSONDecodeError, TypeError, ValueError):
                pass
    if not after_rows:
        after_rows = list(before_rows)

    rows = compare_tests(before_rows, after_rows)
    fixed = sum(1 for r in rows if r["tag"] == "fixed")
    regressions = sum(1 for r in rows if r["tag"] == "regression")

    note = None
    if finding is None:
        note = "No fix attempt on this run yet — showing baseline tests only."
    elif attempt is None or not attempt.tests_json:
        note = "Fix attempt has no re-run snapshot yet."
    elif regressions:
        note = (
            f"{regressions} regression{'s' if regressions != 1 else ''} found. "
            "The original failing test may pass, but another test broke."
        )
        if finding.fix_status in {"generating", "failed"} and attempt:
            note += f" Attempt {attempt.attempt_number}."
    elif finding.fix_status in {"verified", "pr_opened"}:
        if fixed:
            note = f"{fixed} test{'s' if fixed != 1 else ''} fixed · no regressions."
        else:
            note = "No test regressions after the verified fix (existing tests)."

    before_s = summarize_tests(before_rows)
    after_s = summarize_tests(after_rows)
    cfg = run.repository.test_config if run.repository else None

    return TestingDashboardOut(
        run_id=run.id,
        repository_full_name=(
            run.repository.github_full_name if run.repository else None
        ),
        branch=run.branch,
        finding_id=finding.id if finding else None,
        fix_status=finding.fix_status if finding else None,
        fix_branch=finding.fix_branch if finding else None,
        attempt_number=attempt.attempt_number if attempt else None,
        before=_counts_from_summary(
            before_s, pylint=before_pylint, bandit=before_bandit
        ),
        after=_counts_from_summary(after_s, pylint=after_pylint, bandit=after_bandit),
        fixed_count=fixed,
        regression_count=regressions,
        note=note,
        rows=[TestingRowOut(**r) for r in rows],
        test_env=cfg.test_env.value if cfg and cfg.test_env else None,
        workflow_file=cfg.workflow_file if cfg else None,
        python_version=cfg.python_version if cfg else None,
    )
