from __future__ import annotations

from dataclasses import dataclass

from app.models import Finding
from app.runners.base import ParsedTestCase, RunOutcome
from app.triage import (
    findings_from_bandit,
    findings_from_pylint,
    findings_from_test_cases,
    triage_findings,
)
from app.triage.types import TriagedFinding


@dataclass
class VerifyResult:
    ok: bool
    original_failure_gone: bool
    tests_passed: bool
    new_failures: int
    detail: str
    triaged: list[TriagedFinding]


def verify_fix_outcome(
    finding: Finding,
    outcome: RunOutcome,
    *,
    baseline_fingerprints: set[str] | None = None,
) -> VerifyResult:
    """Verified only if original failure is gone and no *new* Critical/High bugs.

    ``baseline_fingerprints`` should be the other findings from the same analysis
    run (pre-fix). Pre-existing High/Critical issues are not treated as regressions.
    """
    raw = []
    raw.extend(
        findings_from_test_cases(outcome.tests, setup_failed=outcome.setup_failed)
    )
    raw.extend(findings_from_pylint(outcome.pylint_raw))
    raw.extend(findings_from_bandit(outcome.bandit_raw))
    triaged = [t for t in triage_findings(raw) if t.is_code_bug]

    original_gone = not _matches_original(finding, outcome.tests, triaged)
    baseline = set(baseline_fingerprints or set())
    baseline.add(finding.fingerprint)
    # Only count Critical/High that were not already present before this fix
    new_bugs = [
        t
        for t in triaged
        if t.fingerprint not in baseline and t.severity in {"critical", "high"}
    ]
    test_ok = _original_test_ok(finding, outcome.tests)

    tests_passed = all(c.status == "passed" for c in outcome.tests) or (
        finding.source != "pytest" and outcome.ok
    )
    if finding.source == "pytest":
        tests_passed = test_ok and not any(
            c.status in {"failed", "error"} for c in outcome.tests
        )

    ok = (
        original_gone
        and test_ok
        and len(new_bugs) == 0
        and not outcome.setup_failed
        and not outcome.timed_out
    )
    detail = (
        f"original_gone={original_gone} test_ok={test_ok} "
        f"new_high_critical={len(new_bugs)} setup_failed={outcome.setup_failed}"
    )
    return VerifyResult(
        ok=ok,
        original_failure_gone=original_gone,
        tests_passed=tests_passed,
        new_failures=len(new_bugs),
        detail=detail,
        triaged=triaged,
    )


def _original_test_ok(finding: Finding, tests: list[ParsedTestCase]) -> bool:
    if finding.source != "pytest" or not finding.test_id:
        return True
    # test_id like tests.test_mathutil.test_add
    for case in tests:
        tid = ".".join(p for p in (case.classname, case.case_name) if p)
        if tid == finding.test_id or case.case_name == (finding.symbol or ""):
            return case.status == "passed"
    # If we can't find the test anymore, treat as not ok
    return False


def _matches_original(
    finding: Finding,
    tests: list[ParsedTestCase],
    triaged: list[TriagedFinding],
) -> bool:
    """True if the original finding still appears."""
    for t in triaged:
        if t.fingerprint == finding.fingerprint:
            return True
        if (
            finding.rule_id
            and t.rule_id == finding.rule_id
            and (not finding.file or t.file and finding.file.lstrip("./") in (t.file or ""))
        ):
            return True
    if finding.source == "pytest":
        for case in tests:
            if case.status not in {"failed", "error"}:
                continue
            tid = ".".join(p for p in (case.classname, case.case_name) if p)
            if finding.test_id and tid == finding.test_id:
                return True
            if finding.symbol and case.case_name == finding.symbol:
                return True
    return False
