"""RQ job: TestRunner (sandbox or GitHub Actions) + triage + LLM root-cause."""

from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.auth import github_app as ghapp
from app.config import get_settings
from app.database import SessionLocal
from app.git import get_git_provider
from app.issues import build_issue_proposal, should_propose_issue
from app.jobs.fix_finding import enqueue_fix_job
from app.llm.root_cause import explain_root_cause
from app.models import (
    AnalysisRun,
    Finding,
    FindingCategory,
    FindingSeverity,
    Repository,
    RunnerType,
    RunStatus,
    RunStep,
    StepStatus,
    TestCaseStatus,
    TestEnv,
    TestResult,
)
from app.runners.actions import GitHubActionsRunner
from app.runners.base import RunRequest
from app.runners.sandbox import SandboxRunner
from app.triage import (
    findings_from_bandit,
    findings_from_pylint,
    findings_from_test_cases,
    triage_findings,
)

logger = logging.getLogger(__name__)

STEP_ORDER_SANDBOX = [
    "clone",
    "setup",
    "test",
    "parse_junit",
    "lint",
    "triage",
    "explain",
]

STEP_ORDER_ACTIONS = [
    "push_branch",
    "trigger_workflow",
    "discover_run",
    "poll_workflow",
    "download_artifact",
    "parse_junit",
    "lint",
    "triage",
    "explain",
]

# Back-compat alias for API imports
STEP_ORDER = STEP_ORDER_SANDBOX

ACTIONS_ENVS = {TestEnv.github_actions, TestEnv.dev_instance}


def run_sandbox_analysis(run_id: str) -> dict:
    """Entrypoint executed by the RQ worker (sandbox or Actions)."""
    db = SessionLocal()
    try:
        run = db.scalar(
            select(AnalysisRun)
            .options(
                joinedload(AnalysisRun.repository).joinedload(Repository.test_config),
                joinedload(AnalysisRun.repository).joinedload(Repository.installation),
                joinedload(AnalysisRun.steps),
                joinedload(AnalysisRun.test_results),
                joinedload(AnalysisRun.findings),
            )
            .where(AnalysisRun.id == UUID(run_id))
        )
        if run is None:
            logger.error("analysis_run not found: %s", run_id)
            return {"ok": False, "error": "not_found"}

        run.status = RunStatus.running
        run.started_at = datetime.now(timezone.utc)
        run.error_message = None
        _ensure_steps(db, run)
        db.commit()

        repo = run.repository
        config = repo.test_config
        if config is None or config.test_env is None:
            return _fail(db, run, "Repository has no test environment configured")

        settings = get_settings()
        use_actions = config.test_env in ACTIONS_ENVS

        if use_actions:
            if not (config.workflow_file or "").strip():
                return _fail(db, run, "GitHub Actions requires a workflow_file")
            installation_id = (
                repo.installation.installation_id if repo.installation else None
            )
            request = RunRequest(
                repository_full_name=repo.github_full_name,
                branch=run.branch or repo.default_branch or "main",
                setup_command=config.setup_command or "true",
                test_command=config.test_command or "pytest",
                python_version=config.python_version or "3.11",
                workflow_file=config.workflow_file,
                artifact_name_hint=os.environ.get(
                    "RINO_ACTIONS_JUNIT_ARTIFACT", "rino-junit"
                ),
                installation_id=installation_id,
                timeout_seconds=int(
                    os.environ.get("RINO_ACTIONS_TIMEOUT_SECONDS", "900")
                ),
                actions_dry_run=bool(settings.github_actions_dry_run)
                or repo.github_full_name.startswith("local/"),
            )
            outcome = GitHubActionsRunner().run(request)
        else:
            if config.test_env != TestEnv.rino_sandbox:
                return _fail(
                    db,
                    run,
                    f"Unsupported test_env={config.test_env}",
                )
            local_path = _resolve_local_sample(repo.github_full_name)
            clone_url = None
            if local_path is None:
                clone_url = _build_clone_url(db, settings, repo)
                if not clone_url:
                    return _fail(
                        db,
                        run,
                        "Cannot clone repository (no local sample mapping and no GitHub App token)",
                    )

            request = RunRequest(
                repository_full_name=repo.github_full_name,
                branch=run.branch or repo.default_branch or "main",
                setup_command=config.setup_command or "true",
                test_command=config.test_command or "pytest",
                python_version=config.python_version or "3.11",
                local_source_path=local_path,
                clone_url=clone_url,
                timeout_seconds=int(
                    os.environ.get("RINO_SANDBOX_TIMEOUT_SECONDS", "600")
                ),
                memory_limit=os.environ.get("RINO_SANDBOX_MEMORY", "1g"),
                cpus=os.environ.get("RINO_SANDBOX_CPUS", "1.0"),
            )
            outcome = SandboxRunner().run(request)

        by_name = {s.name: s for s in run.steps}
        for step_out in outcome.steps:
            row = by_name.get(step_out.name)
            if row is None:
                row = RunStep(
                    run_id=run.id,
                    name=step_out.name,
                    sort_order=len(by_name),
                )
                db.add(row)
                by_name[step_out.name] = row
            row.status = StepStatus.succeeded if step_out.ok else StepStatus.failed
            row.exit_code = step_out.exit_code
            row.log_text = step_out.log_text
            row.finished_at = datetime.now(timezone.utc)
            if row.started_at is None:
                row.started_at = run.started_at

        for existing in list(run.test_results):
            db.delete(existing)
        for existing in list(run.findings):
            db.delete(existing)
        db.flush()

        passed = failed = errors = skipped = 0
        for case in outcome.tests:
            status = TestCaseStatus(case.status)
            if status == TestCaseStatus.passed:
                passed += 1
            elif status == TestCaseStatus.failed:
                failed += 1
            elif status == TestCaseStatus.error:
                errors += 1
            elif status == TestCaseStatus.skipped:
                skipped += 1
            db.add(
                TestResult(
                    run_id=run.id,
                    suite_name=case.suite_name,
                    case_name=case.case_name,
                    classname=case.classname,
                    status=status,
                    message=case.message,
                    duration_seconds=case.duration_seconds,
                )
            )

        # Normalize + triage
        triage_row = by_name.get("triage")
        if triage_row is None:
            triage_row = RunStep(
                run_id=run.id,
                name="triage",
                sort_order=len(STEP_ORDER) - 1,
            )
            db.add(triage_row)
            by_name["triage"] = triage_row
        triage_row.started_at = triage_row.started_at or datetime.now(timezone.utc)

        raw = []
        raw.extend(
            findings_from_test_cases(
                outcome.tests, setup_failed=outcome.setup_failed
            )
        )
        raw.extend(findings_from_pylint(outcome.pylint_raw))
        raw.extend(findings_from_bandit(outcome.bandit_raw))
        triaged = triage_findings(raw)

        finding_rows: list[Finding] = []
        for tf in triaged:
            row = Finding(
                run_id=run.id,
                source=tf.source,
                rule_id=tf.rule_id,
                file=tf.file,
                line=tf.line,
                symbol=tf.symbol,
                message=tf.message,
                tool_severity=tf.tool_severity,
                tool_confidence=tf.tool_confidence,
                test_id=tf.test_id,
                exception_type=tf.exception_type,
                fingerprint=tf.fingerprint,
                severity=FindingSeverity(tf.severity),
                category=FindingCategory(tf.category),
                is_code_bug=tf.is_code_bug,
                needs_attention=tf.needs_attention,
                issue_status=tf.issue_status,
                fix_status=tf.fix_status,
                action_tag=tf.action_tag,
                triage_notes=tf.triage_notes,
            )
            db.add(row)
            finding_rows.append(row)
        db.flush()

        triage_row.status = StepStatus.succeeded
        triage_row.log_text = (
            f"Normalized {len(raw)} raw → {len(triaged)} triaged finding(s); "
            f"{sum(1 for t in triaged if t.is_code_bug)} code bug(s), "
            f"{sum(1 for t in triaged if not t.is_code_bug)} not-code-bug"
        )
        triage_row.finished_at = datetime.now(timezone.utc)

        # Step 5: LLM root-cause (Critical/High only) + propose Issues (Critical)
        explain_row = by_name.get("explain")
        if explain_row is None:
            explain_row = RunStep(
                run_id=run.id,
                name="explain",
                sort_order=len(STEP_ORDER) - 1,
            )
            db.add(explain_row)
            by_name["explain"] = explain_row
        explain_row.started_at = explain_row.started_at or datetime.now(timezone.utc)

        explained = proposed = linked = 0
        provider = get_git_provider(
            settings,
            installation_id=(
                repo.installation.installation_id if repo.installation else None
            ),
        )
        full_name = repo.github_full_name
        for finding in finding_rows:
            outcome_rc = explain_root_cause(
                db, finding, org_id=run.org_id, settings=settings
            )
            if outcome_rc.root_cause:
                explained += 1

            if not should_propose_issue(finding):
                continue

            # Dedupe against open ai-found issues with matching fingerprint
            existing = None
            try:
                existing = provider.find_issue_by_fingerprint(
                    full_name, finding.fingerprint
                )
            except Exception:
                logger.exception("find_issue_by_fingerprint failed (continuing)")

            if existing is not None:
                finding.github_issue_number = existing.number
                finding.github_issue_url = existing.url
                finding.issue_status = "linked"
                linked += 1
                continue

            title, body = build_issue_proposal(finding)
            finding.issue_title = title
            finding.issue_body = body
            finding.issue_status = "awaiting_confirm"
            # Provisional issue number so fix branches can be named rino/fix-<n>
            if finding.github_issue_number is None:
                finding.github_issue_number = (
                    abs(hash(finding.fingerprint)) % 9000 + 1000
                )
            proposed += 1

        db.flush()
        # Step 6: start fix jobs for Critical findings when proposed (or linked)
        fixes_queued = 0
        for finding in finding_rows:
            if (
                finding.is_code_bug
                and finding.severity == FindingSeverity.critical
                and finding.issue_status
                in {"awaiting_confirm", "linked", "open", "dry_run"}
                and finding.fix_status in {"none", ""}
            ):
                try:
                    job_id = enqueue_fix_job(finding.id)
                    finding.fix_status = "queued"
                    finding.fix_rq_job_id = job_id
                    fixes_queued += 1
                except Exception:
                    logger.exception("Failed to enqueue fix for %s", finding.id)

        explain_row.status = StepStatus.succeeded
        explain_row.log_text = (
            f"Root-cause explained={explained}; "
            f"issues proposed={proposed}, linked_existing={linked}; "
            f"fix jobs queued={fixes_queued} "
            f"(LLM never sets severity; issues not created until Confirm; "
            f"no PR push until Step 7)"
        )
        explain_row.finished_at = datetime.now(timezone.utc)

        run.tests_total = passed + failed + errors + skipped
        run.tests_passed = passed
        run.tests_failed = failed
        run.tests_errors = errors
        run.tests_skipped = skipped
        run.commit_sha = outcome.commit_sha
        # Capture Actions workflow run id when present
        for step_out in outcome.steps:
            rid = (step_out.detail or {}).get("run_id") or (
                step_out.detail or {}
            ).get("github_workflow_run_id")
            if rid is not None:
                try:
                    run.github_workflow_run_id = int(rid)
                except (TypeError, ValueError):
                    pass
        run.finished_at = datetime.now(timezone.utc)

        if outcome.timed_out:
            run.status = RunStatus.timed_out
            run.error_message = outcome.error_message or "Timed out"
        elif outcome.setup_failed:
            run.status = RunStatus.failed
            run.error_message = outcome.error_message or "Setup failed"
        elif not outcome.ok and not triaged:
            run.status = RunStatus.failed
            run.error_message = outcome.error_message or "Analysis run failed"
        else:
            # Parsed findings → treat as succeeded even if some tests failed
            run.status = RunStatus.succeeded
            run.error_message = None

        db.commit()
        return {
            "ok": run.status == RunStatus.succeeded,
            "run_id": str(run.id),
            "status": run.status.value,
            "tests_total": run.tests_total,
            "findings": len(triaged),
            "explained": explained,
            "issues_proposed": proposed,
            "runner": run.runner_type.value if run.runner_type else None,
            "github_workflow_run_id": run.github_workflow_run_id,
        }
    except Exception:
        logger.exception("run_sandbox_analysis crashed for %s", run_id)
        try:
            run = db.get(AnalysisRun, UUID(run_id))
            if run is not None:
                run.status = RunStatus.failed
                run.error_message = "Worker crashed while running analysis job"
                run.finished_at = datetime.now(timezone.utc)
                db.commit()
        except Exception:
            db.rollback()
        raise
    finally:
        db.close()


def _step_order_for(run: AnalysisRun) -> list[str]:
    if run.runner_type == RunnerType.github_actions:
        return STEP_ORDER_ACTIONS
    return STEP_ORDER_SANDBOX


def _ensure_steps(db: Session, run: AnalysisRun) -> None:
    order = _step_order_for(run)
    existing = {s.name for s in run.steps}
    for idx, name in enumerate(order):
        if name in existing:
            continue
        db.add(
            RunStep(
                run_id=run.id,
                name=name,
                sort_order=idx,
                status=StepStatus.pending,
            )
        )
    db.flush()


def _fail(db: Session, run: AnalysisRun, message: str) -> dict:
    run.status = RunStatus.failed
    run.error_message = message
    run.finished_at = datetime.now(timezone.utc)
    db.commit()
    return {"ok": False, "error": message, "run_id": str(run.id)}


def _resolve_local_sample(full_name: str) -> str | None:
    """Map `local/<name>` repos to `/samples/<name>` (or SAMPLE_ROOT)."""
    if not full_name.startswith("local/"):
        return None
    name = full_name.split("/", 1)[1]
    if not name or "/" in name or ".." in name:
        return None
    root = Path(os.environ.get("RINO_SAMPLES_DIR", "/samples"))
    path = root / name
    if path.is_dir():
        return str(path)
    return None


def _build_clone_url(db: Session, settings, repo: Repository) -> str | None:
    if not settings.github_app_configured():
        return None
    installation = repo.installation
    if installation is None or installation.suspended:
        return None
    try:
        token = ghapp.create_installation_token_sync(
            settings, installation.installation_id
        )
    except Exception:
        logger.exception("Failed to mint installation token for clone")
        return None

    return f"https://x-access-token:{token}@github.com/{repo.github_full_name}.git"
