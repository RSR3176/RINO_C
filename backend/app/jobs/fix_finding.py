"""RQ job: generate + verify a fix for a Critical finding (no push/PR)."""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import joinedload

from app.config import get_settings
from app.database import SessionLocal
from app.fix.agent import collect_relevant_sources, propose_fix
from app.fix.diffutil import (
    dumps_files,
    side_by_side_payload,
    unified_diff_for_files,
    write_text,
)
from app.fix.safety import validate_patch_files
from app.fix.verify import verify_fix_outcome
from app.git import get_git_provider
from app.models import (
    AnalysisRun,
    Finding,
    FindingSeverity,
    FixAttempt,
    FixAttemptStatus,
    LlmCall,
    Repository,
)
from app.runners.base import RunRequest
from app.runners.sandbox import SandboxRunner

logger = logging.getLogger(__name__)

MAX_ATTEMPTS = 3


def _max_attempts() -> int:
    try:
        from app.triage.load_rules import load_rules

        limits = (load_rules() or {}).get("fix_limits") or {}
        n = int(limits.get("max_attempts") or MAX_ATTEMPTS)
        return max(1, min(10, n))
    except Exception:
        return MAX_ATTEMPTS


def run_fix_finding(finding_id: str) -> dict:
    db = SessionLocal()
    try:
        finding = db.scalar(
            select(Finding)
            .options(
                joinedload(Finding.run)
                .joinedload(AnalysisRun.repository)
                .joinedload(Repository.test_config),
                joinedload(Finding.run)
                .joinedload(AnalysisRun.repository)
                .joinedload(Repository.installation),
                joinedload(Finding.fix_attempts),
            )
            .where(Finding.id == UUID(finding_id))
        )
        if finding is None:
            return {"ok": False, "error": "not_found"}
        if finding.severity != FindingSeverity.critical or not finding.is_code_bug:
            return {"ok": False, "error": "not_critical"}
        if finding.fix_status == "discarded":
            return {"ok": False, "error": "discarded"}
        if finding.fix_status == "verified":
            return {"ok": True, "status": "verified", "already": True}

        settings = get_settings()
        run = finding.run
        repo = run.repository
        config = repo.test_config
        issue_no = finding.github_issue_number or (
            abs(hash(finding.fingerprint)) % 9000 + 1000
        )
        if finding.github_issue_number is None:
            finding.github_issue_number = issue_no
        branch = f"rino/fix-{issue_no}"
        finding.fix_branch = branch
        finding.fix_status = "generating"
        db.commit()

        work_parent = (
            Path(os.environ.get("RINO_SANDBOX_WORK_DIR", "/var/rino/sandbox"))
            / f"fix-{finding.id}"
        )
        if work_parent.exists():
            shutil.rmtree(work_parent, ignore_errors=True)
        work_parent.mkdir(parents=True, exist_ok=True)

        prior_feedback: str | None = None
        verified = False
        max_attempts = _max_attempts()
        try:
            for attempt_num in range(1, max_attempts + 1):
                db.refresh(finding)
                if finding.fix_status == "discarded":
                    break

                attempt = FixAttempt(
                    finding_id=finding.id,
                    attempt_number=attempt_num,
                    status=FixAttemptStatus.running,
                    branch_name=branch,
                    started_at=datetime.now(timezone.utc),
                )
                db.add(attempt)
                db.commit()

                src = work_parent / f"attempt-{attempt_num}"
                if src.exists():
                    shutil.rmtree(src, ignore_errors=True)
                _materialize_source(repo.github_full_name, src)
                _git_init_branch(src, branch)

                readable = collect_relevant_sources(src, finding)
                proposal = propose_fix(
                    finding=finding,
                    workspace=src,
                    readable_files=readable,
                    prior_feedback=prior_feedback,
                    settings=settings,
                )
                db.add(
                    LlmCall(
                        org_id=run.org_id,
                        run_id=run.id,
                        finding_id=finding.id,
                        purpose="fix",
                        model=proposal.model,
                        input_tokens=proposal.input_tokens,
                        output_tokens=proposal.output_tokens,
                        cost_usd=proposal.cost_usd,
                        success=proposal.success,
                        error_message=proposal.error_message,
                        prompt_chars=0,
                        response_chars=len(proposal.explanation or ""),
                    )
                )

                if not proposal.success or not proposal.files:
                    attempt.status = FixAttemptStatus.failed
                    attempt.error_message = proposal.error_message or "No files proposed"
                    attempt.finished_at = datetime.now(timezone.utc)
                    prior_feedback = attempt.error_message
                    db.commit()
                    continue

                safety = validate_patch_files(proposal.files, originals=readable)
                attempt.safety_ok = safety.ok
                attempt.safety_violations_json = json.dumps(safety.violations)
                attempt.explanation = proposal.explanation
                attempt.files_changed_json = dumps_files(list(proposal.files.keys()))
                attempt.unified_diff = unified_diff_for_files(readable, proposal.files)

                if not safety.ok:
                    attempt.status = FixAttemptStatus.rejected
                    attempt.error_message = "; ".join(safety.violations)
                    attempt.finished_at = datetime.now(timezone.utc)
                    prior_feedback = attempt.error_message
                    db.commit()
                    continue

                for rel, content in proposal.files.items():
                    write_text(src / rel, content)

                req = RunRequest(
                    repository_full_name=repo.github_full_name,
                    branch=branch,
                    setup_command=(config.setup_command if config else None) or "true",
                    test_command=(config.test_command if config else None)
                    or "pytest -q",
                    python_version=(config.python_version if config else None)
                    or "3.12",
                    local_source_path=str(src),
                    timeout_seconds=int(
                        os.environ.get("RINO_SANDBOX_TIMEOUT_SECONDS", "600")
                    ),
                    memory_limit=os.environ.get("RINO_SANDBOX_MEMORY", "1g"),
                    cpus=os.environ.get("RINO_SANDBOX_CPUS", "1.0"),
                )
                outcome = SandboxRunner().run(req)
                baseline = {
                    f.fingerprint
                    for f in (run.findings or [])
                    if f.id != finding.id
                }
                # run.findings may not be loaded — query siblings
                if not baseline:
                    siblings = db.scalars(
                        select(Finding).where(
                            Finding.run_id == run.id, Finding.id != finding.id
                        )
                    ).all()
                    baseline = {f.fingerprint for f in siblings}
                verify = verify_fix_outcome(
                    finding, outcome, baseline_fingerprints=baseline
                )
                attempt.tests_passed = verify.tests_passed
                attempt.original_failure_gone = verify.original_failure_gone
                attempt.new_failures = verify.new_failures
                attempt.tests_json = json.dumps(
                    [
                        {
                            "suite_name": c.suite_name,
                            "case_name": c.case_name,
                            "classname": c.classname,
                            "status": c.status,
                            "message": c.message,
                            "duration_seconds": c.duration_seconds,
                        }
                        for c in outcome.tests
                    ]
                )
                pylint_n = 0
                bandit_n = 0
                for t in verify.triaged:
                    if t.source == "pylint":
                        pylint_n += 1
                    elif t.source == "bandit":
                        bandit_n += 1
                attempt.static_counts_json = json.dumps(
                    {"pylint": pylint_n, "bandit": bandit_n}
                )
                log_bits = []
                for step in outcome.steps:
                    if step.name in {"test", "lint"} and step.log_text:
                        log_bits.append(step.log_text)
                attempt.test_log = "\n".join(log_bits)[:20000]
                attempt.finished_at = datetime.now(timezone.utc)

                if verify.ok:
                    attempt.status = FixAttemptStatus.verified
                    finding.fix_status = "verified"
                    finding.fix_explanation = proposal.explanation
                    finding.verified_diff = attempt.unified_diff
                    finding.verified_files_json = dumps_files(
                        side_by_side_payload(readable, proposal.files)
                    )
                    finding.fix_branch = branch
                    db.commit()
                    verified = True
                    break

                attempt.status = FixAttemptStatus.failed
                attempt.error_message = verify.detail
                prior_feedback = (
                    f"Verification failed: {verify.detail}. "
                    "Do not touch tests. Keep changes minimal."
                )
                db.commit()

            if not verified and finding.fix_status not in {"discarded", "verified"}:
                finding.fix_status = "failed"
                db.commit()
                _comment_failure(db, finding, repo)
        finally:
            if os.environ.get("RINO_SANDBOX_KEEP", "").strip() not in {"1", "true"}:
                shutil.rmtree(work_parent, ignore_errors=True)

        return {
            "ok": verified,
            "finding_id": str(finding.id),
            "fix_status": finding.fix_status,
            "branch": finding.fix_branch,
        }
    except Exception:
        logger.exception("run_fix_finding crashed for %s", finding_id)
        try:
            finding = db.get(Finding, UUID(finding_id))
            if finding and finding.fix_status not in {"verified", "discarded"}:
                finding.fix_status = "failed"
                db.commit()
        except Exception:
            db.rollback()
        raise
    finally:
        db.close()


def enqueue_fix_job(finding_id: UUID | str) -> str | None:
    from app.queue import get_queue

    job = get_queue().enqueue(
        run_fix_finding,
        str(finding_id),
        job_timeout=900,
        result_ttl=3600,
        failure_ttl=86400,
    )
    return job.id


def _materialize_source(full_name: str, dest: Path) -> None:
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
        return
    raise RuntimeError(
        "Step 6 fix job currently supports local/* fixtures in this environment"
    )


def _git_init_branch(src: Path, branch: str) -> None:
    def run(cmd: list[str]) -> None:
        subprocess.run(
            cmd, cwd=src, check=False, capture_output=True, text=True, timeout=30
        )

    run(["git", "init"])
    run(["git", "config", "user.email", "rino@local"])
    run(["git", "config", "user.name", "Rino"])
    run(["git", "add", "-A"])
    run(["git", "commit", "-m", "rino baseline"])
    run(["git", "checkout", "-B", branch])


def _comment_failure(db, finding: Finding, repo: Repository) -> None:
    attempts = sorted(finding.fix_attempts, key=lambda a: a.attempt_number)
    lines = [
        "## Rino fix attempts exhausted",
        f"Could not verify a safe fix for `{finding.rule_id}` after {_max_attempts()} attempts.",
        "",
    ]
    for a in attempts:
        lines.append(
            f"- Attempt {a.attempt_number}: **{a.status.value}**"
            + (f" — {a.error_message}" if a.error_message else "")
        )
    body = "\n".join(lines)
    settings = get_settings()
    provider = get_git_provider(
        settings,
        installation_id=(
            repo.installation.installation_id if repo.installation else None
        ),
    )
    try:
        provider.comment_on_issue(
            repo.github_full_name,
            int(finding.github_issue_number or 0),
            body,
        )
    except Exception:
        logger.exception("issue comment failed")
    finding.fix_explanation = ((finding.fix_explanation or "") + "\n\n" + body).strip()
    db.commit()
