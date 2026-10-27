"""Unit tests for rino/ branch gate and PR body helpers."""

from __future__ import annotations

import unittest
from types import SimpleNamespace

from app.fix.pr import (
    assert_rino_branch,
    build_pr_body,
    compare_tests,
    summarize_tests,
)


class RinoBranchTests(unittest.TestCase):
    def test_allows_rino_fix_branch(self) -> None:
        self.assertEqual(assert_rino_branch("rino/fix-412"), "rino/fix-412")

    def test_rejects_non_rino(self) -> None:
        with self.assertRaises(ValueError):
            assert_rino_branch("main")
        with self.assertRaises(ValueError):
            assert_rino_branch("feature/rino/fix-1")
        with self.assertRaises(ValueError):
            assert_rino_branch("rino/")


class CompareTests(unittest.TestCase):
    def test_detects_regression_and_fix(self) -> None:
        before = [
            {
                "classname": "tests.test_a",
                "case_name": "test_ok",
                "status": "passed",
                "message": None,
                "duration_seconds": 0.1,
            },
            {
                "classname": "tests.test_a",
                "case_name": "test_bad",
                "status": "failed",
                "message": "boom",
                "duration_seconds": 0.2,
            },
        ]
        after = [
            {
                "classname": "tests.test_a",
                "case_name": "test_ok",
                "status": "failed",
                "message": "regressed",
                "duration_seconds": 0.1,
            },
            {
                "classname": "tests.test_a",
                "case_name": "test_bad",
                "status": "passed",
                "message": None,
                "duration_seconds": 0.2,
            },
        ]
        rows = {r["key"]: r for r in compare_tests(before, after)}
        self.assertEqual(rows["tests.test_a::test_ok"]["tag"], "regression")
        self.assertEqual(rows["tests.test_a::test_bad"]["tag"], "fixed")
        self.assertEqual(summarize_tests(after)["passed"], 1)

    def test_pr_body_includes_fixes(self) -> None:
        finding = SimpleNamespace(
            github_issue_number=412,
            fix_explanation="Use shell=False",
            root_cause=None,
            severity=SimpleNamespace(value="critical"),
            rule_id="B602",
            source="bandit",
            file="shellutil.py",
            line=10,
            fingerprint="abc123",
        )
        body = build_pr_body(
            finding,  # type: ignore[arg-type]
            before=[{"status": "passed"}, {"status": "failed"}],
            after=[{"status": "passed"}, {"status": "passed"}],
        )
        self.assertIn("Fixes #412", body)
        self.assertIn("Before / after tests", body)
        self.assertIn("rino:fingerprint=abc123", body)


if __name__ == "__main__":
    unittest.main()
