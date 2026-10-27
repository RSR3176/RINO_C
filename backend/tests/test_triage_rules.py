"""Unit tests for the six rules.yaml triage policies (stdlib unittest)."""

from __future__ import annotations

import unittest

from app.runners.base import ParsedTestCase
from app.triage.engine import triage_findings
from app.triage.load_rules import clear_rules_cache, load_rules
from app.triage.normalize import (
    findings_from_bandit,
    findings_from_pylint,
    findings_from_test_cases,
)
from app.triage.types import RawFinding


class TriageRulesTests(unittest.TestCase):
    def setUp(self) -> None:
        clear_rules_cache()

    def test_rules_yaml_loads_six_sections(self) -> None:
        rules = load_rules()
        for key in (
            "not_a_code_bug",
            "ignored_paths",
            "duplicate_merging",
            "severity_table",
            "adjustments",
            "actions",
        ):
            self.assertIn(key, rules)

    def test_rule1_setup_failed_is_not_code_bug(self) -> None:
        raw = [
            RawFinding(
                source="setup",
                rule_id="setup_failed",
                message="Setup command failed",
                setup_failed=True,
            )
        ]
        out = triage_findings(raw)
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0].category, "setup_failed")
        self.assertFalse(out[0].is_code_bug)

    def test_rule1_missing_package_is_environment(self) -> None:
        cases = [
            ParsedTestCase(
                suite_name="tests",
                case_name="test_import",
                classname="tests.test_import",
                status="error",
                message="ModuleNotFoundError: No module named 'requests'",
            )
        ]
        raw = findings_from_test_cases(cases)
        out = triage_findings(raw)
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0].category, "environment")
        self.assertFalse(out[0].is_code_bug)
        self.assertEqual(out[0].exception_type, "ModuleNotFoundError")

    def test_rule1_flaky_when_rerun_passes(self) -> None:
        raw = [
            RawFinding(
                source="pytest",
                rule_id="test_failure",
                test_id="tests.test_flaky.test_x",
                message="AssertionError: flaky",
                exception_type="AssertionError",
                prior_pass_on_rerun=True,
            )
        ]
        out = triage_findings(raw)
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0].category, "flaky")
        self.assertFalse(out[0].is_code_bug)

    def test_rule2_ignored_paths_dropped(self) -> None:
        raw = [
            RawFinding(
                source="pylint",
                rule_id="C0114",
                file="migrations/0001_initial.py",
                line=1,
                message="missing-module-docstring",
                tool_severity="convention",
            )
        ]
        self.assertEqual(triage_findings(raw), [])

    def test_rule2_noqa_suppression_dropped(self) -> None:
        raw = [
            RawFinding(
                source="pylint",
                rule_id="W0611",
                file="app/main.py",
                line=3,
                message="Unused import os",
                tool_severity="warning",
                suppression_markers=["noqa"],
            )
        ]
        self.assertEqual(triage_findings(raw), [])

    def test_rule3_duplicate_merge_across_tools(self) -> None:
        raw = [
            RawFinding(
                source="pylint",
                rule_id="B602",
                file="src/utils/shell.py",
                line=21,
                message="subprocess with shell=True",
            ),
            RawFinding(
                source="bandit",
                rule_id="B602",
                file="src/utils/shell.py",
                line=21,
                message="subprocess with shell=True",
                tool_severity="high",
            ),
        ]
        out = triage_findings(raw)
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0].rule_id, "B602")

    def test_rule4_severity_table_mapping(self) -> None:
        raw = [
            RawFinding(
                source="pytest",
                rule_id="test_failure",
                file="src/x.py",
                message="AssertionError",
                exception_type="AssertionError",
            ),
            RawFinding(
                source="bandit",
                rule_id="B602",
                file="src/utils/shell.py",
                line=21,
                message="shell=True",
                tool_severity="high",
            ),
            RawFinding(
                source="pylint",
                rule_id="E0602",
                file="messy.py",
                line=8,
                message="undefined-variable",
                tool_severity="error",
            ),
            RawFinding(
                source="pylint",
                rule_id="W0611",
                file="messy.py",
                line=3,
                message="unused-import",
                tool_severity="warning",
            ),
            RawFinding(
                source="pylint",
                rule_id="C0114",
                file="messy.py",
                line=1,
                message="missing-module-docstring",
                tool_severity="convention",
            ),
        ]
        out = {f.rule_id: f for f in triage_findings(raw)}
        self.assertEqual(out["test_failure"].severity, "critical")
        self.assertEqual(out["B602"].severity, "critical")
        self.assertEqual(out["E0602"].severity, "high")
        self.assertEqual(out["W0611"].severity, "medium")
        self.assertEqual(out["C0114"].severity, "low")

    def test_rule5_non_production_path_lowers_severity(self) -> None:
        raw = [
            RawFinding(
                source="pylint",
                rule_id="E0602",
                file="scripts/migrate.py",
                line=10,
                message="undefined-variable",
                tool_severity="error",
            )
        ]
        out = triage_findings(raw)
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0].severity, "medium")

    def test_rule5_regression_raises_severity(self) -> None:
        raw = [
            RawFinding(
                source="pylint",
                rule_id="W0611",
                file="app/main.py",
                line=1,
                message="unused-import",
                tool_severity="warning",
                is_regression=True,
            )
        ]
        out = triage_findings(raw)
        self.assertEqual(out[0].severity, "high")

    def test_rule6_actions_needs_attention(self) -> None:
        raw = [
            RawFinding(
                source="pytest",
                rule_id="test_failure",
                file="src/auth/token.py",
                message="AssertionError",
                exception_type="AssertionError",
            ),
            RawFinding(
                source="pylint",
                rule_id="E0602",
                file="app/x.py",
                message="undefined",
                tool_severity="error",
            ),
            RawFinding(
                source="pylint",
                rule_id="C0114",
                file="app/y.py",
                message="missing docstring",
                tool_severity="convention",
            ),
        ]
        out = {f.rule_id: f for f in triage_findings(raw)}
        self.assertTrue(out["test_failure"].needs_attention)
        self.assertTrue(out["E0602"].needs_attention)
        self.assertEqual(out["E0602"].action_tag, "Needs attention")
        self.assertFalse(out["C0114"].needs_attention)

    def test_core_module_failing_test_always_critical(self) -> None:
        raw = [
            RawFinding(
                source="pytest",
                rule_id="test_failure",
                file="src/payments/refund.py",
                line=88,
                message="ZeroDivisionError",
                exception_type="ZeroDivisionError",
            )
        ]
        rules = load_rules()
        rules = {
            **rules,
            "severity_table": {**rules["severity_table"], "failing_test": "medium"},
        }
        out = triage_findings(raw, rules=rules)
        self.assertEqual(out[0].severity, "critical")

    def test_normalize_pylint_and_bandit_roundtrip(self) -> None:
        pylint = [
            {
                "type": "error",
                "module": "messy",
                "obj": "",
                "line": 8,
                "column": 11,
                "path": "messy.py",
                "symbol": "undefined-variable",
                "message": "Undefined variable 'c'",
                "message-id": "E0602",
            }
        ]
        bandit = {
            "results": [
                {
                    "filename": "shellutil.py",
                    "line_number": 8,
                    "issue_severity": "HIGH",
                    "issue_confidence": "HIGH",
                    "issue_text": "subprocess call with shell=True identified.",
                    "test_id": "B602",
                    "test_name": "subprocess_popen_with_shell_equals_true",
                }
            ]
        }
        raw = findings_from_pylint(pylint) + findings_from_bandit(bandit)
        self.assertEqual(raw[0].source, "pylint")
        self.assertEqual(raw[0].rule_id, "E0602")
        self.assertEqual(raw[1].source, "bandit")
        self.assertEqual(raw[1].tool_severity, "high")
        out = triage_findings(raw)
        self.assertEqual({f.rule_id for f in out}, {"E0602", "B602"})


if __name__ == "__main__":
    unittest.main()
