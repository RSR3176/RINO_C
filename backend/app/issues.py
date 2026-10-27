from __future__ import annotations

from app.llm.secrets import mask_secrets
from app.models import Finding, FindingSeverity


def build_issue_proposal(finding: Finding) -> tuple[str, str]:
    """Draft GitHub Issue title + body for a Critical finding (not created yet)."""
    loc = finding.file or "unknown"
    if finding.line is not None:
        loc = f"{loc}:{finding.line}"
    rule = finding.rule_id or finding.symbol or finding.source
    title = f"[Rino] {rule} in {loc}"
    if len(title) > 240:
        title = title[:237] + "…"

    root = finding.root_cause or "(Root cause not yet generated)"
    msg = mask_secrets(finding.message or "")
    body = "\n".join(
        [
            "## Finding",
            f"- **Severity:** {finding.severity.value} (from triage rules — not LLM)",
            f"- **Tool:** {finding.source}",
            f"- **Rule:** {finding.rule_id or '—'}",
            f"- **Location:** `{loc}`",
            f"- **Symbol:** {finding.symbol or '—'}",
            f"- **Test:** {finding.test_id or '—'}",
            f"- **Exception:** {finding.exception_type or '—'}",
            "",
            "### Message",
            "```",
            msg[:4000],
            "```",
            "",
            "### Likely root cause (AI)",
            root,
            "",
            "---",
            f"<!-- rino:fingerprint={finding.fingerprint} -->",
        ]
    )
    return title, body


def should_propose_issue(finding: Finding) -> bool:
    return (
        finding.is_code_bug
        and finding.severity == FindingSeverity.critical
        and finding.issue_status in {"none", "skipped"}
    )
