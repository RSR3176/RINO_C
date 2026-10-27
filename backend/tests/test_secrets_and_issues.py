"""Unit tests for secret masking + issue proposal fingerprint."""

from __future__ import annotations

import unittest
import uuid

from app.issues import build_issue_proposal, should_propose_issue
from app.llm.secrets import mask_secrets
from app.models import Finding, FindingCategory, FindingSeverity


class SecretMaskTests(unittest.TestCase):
    def test_masks_api_key_assignment(self) -> None:
        text = "export API_KEY=sk-ant-secretvalue1234567890abcd"
        out = mask_secrets(text)
        self.assertNotIn("sk-ant-secretvalue", out)
        self.assertIn("[REDACTED", out)

    def test_masks_github_pat(self) -> None:
        text = "token=ghp_abcdefghijklmnopqrstuvwxyz0123456789"
        out = mask_secrets(text)
        self.assertNotIn("ghp_abcdefghijklmnopqrstuvwxyz0123456789", out)

    def test_masks_bearer(self) -> None:
        out = mask_secrets("Authorization: Bearer abcdef.secret.token")
        self.assertIn("[REDACTED]", out)
        self.assertNotIn("abcdef.secret.token", out)

    def test_masks_pem(self) -> None:
        pem = "-----BEGIN RSA PRIVATE KEY-----\nMIIE\n-----END RSA PRIVATE KEY-----"
        out = mask_secrets(pem)
        self.assertEqual(out, "[REDACTED_PRIVATE_KEY]")


class IssueProposalTests(unittest.TestCase):
    def _finding(self, **kwargs) -> Finding:
        base = dict(
            id=uuid.uuid4(),
            run_id=uuid.uuid4(),
            source="bandit",
            rule_id="B602",
            file="shellutil.py",
            line=8,
            symbol="run_user_command",
            message="subprocess call with shell=True; API_KEY=supersecret",
            fingerprint="abc123fingerprint",
            severity=FindingSeverity.critical,
            category=FindingCategory.code_bug,
            is_code_bug=True,
            needs_attention=True,
            issue_status="none",
            fix_status="none",
            root_cause="[Summary] shell=True allows injection.",
        )
        base.update(kwargs)
        return Finding(**base)

    def test_body_includes_fingerprint_marker(self) -> None:
        title, body = build_issue_proposal(self._finding())
        self.assertIn("[Rino]", title)
        self.assertIn("<!-- rino:fingerprint=abc123fingerprint -->", body)
        self.assertIn("shell=True", body)
        # Secrets in message are masked in the issue body
        self.assertNotIn("supersecret", body)

    def test_should_propose_only_critical_code_bugs(self) -> None:
        self.assertTrue(should_propose_issue(self._finding()))
        self.assertFalse(
            should_propose_issue(
                self._finding(severity=FindingSeverity.high, issue_status="none")
            )
        )
        self.assertFalse(
            should_propose_issue(self._finding(is_code_bug=False))
        )


if __name__ == "__main__":
    unittest.main()
