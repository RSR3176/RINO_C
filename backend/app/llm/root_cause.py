from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.llm.client import complete_text
from app.llm.secrets import mask_secrets
from app.models import Finding, FindingSeverity, LlmCall

SYSTEM = (
    "You explain software findings for developers. "
    "Write a short likely root cause (2–4 sentences) starting with [Summary]. "
    "Be specific to the evidence provided. "
    "Do NOT assign severity, priority, or recommend product actions "
    "(no 'create an issue', 'mark as critical', etc.). "
    "Do NOT invent files or stack frames that are not in the evidence."
)


@dataclass
class RootCauseOutcome:
    root_cause: str | None
    llm_call: LlmCall | None
    skipped: bool = False
    reason: str | None = None


def explain_root_cause(
    db: Session,
    finding: Finding,
    *,
    org_id,
    settings: Settings | None = None,
) -> RootCauseOutcome:
    """LLM root-cause for Critical/High code bugs only. Never sets severity."""
    settings = settings or get_settings()
    if not finding.is_code_bug:
        return RootCauseOutcome(None, None, skipped=True, reason="not_code_bug")
    if finding.severity not in {FindingSeverity.critical, FindingSeverity.high}:
        return RootCauseOutcome(None, None, skipped=True, reason="severity_below_high")

    user = _build_user_prompt(finding)
    result = complete_text(system=SYSTEM, user=user, settings=settings, max_tokens=280)

    call = LlmCall(
        org_id=org_id,
        run_id=finding.run_id,
        finding_id=finding.id,
        purpose="root_cause",
        model=result.model,
        input_tokens=result.input_tokens,
        output_tokens=result.output_tokens,
        cost_usd=result.cost_usd,
        success=result.success,
        error_message=result.error_message,
        prompt_chars=len(user),
        response_chars=len(result.text or ""),
    )
    db.add(call)

    if not result.success or not result.text.strip():
        return RootCauseOutcome(None, call, skipped=False, reason=result.error_message)

    text = result.text.strip()
    if not text.startswith("[Summary]"):
        text = f"[Summary] {text}"
    finding.root_cause = text[:4000]
    return RootCauseOutcome(finding.root_cause, call)


def _build_user_prompt(finding: Finding) -> str:
    loc = finding.file or "(unknown file)"
    if finding.line is not None:
        loc = f"{loc}:{finding.line}"
    parts = [
        f"Tool: {finding.source}",
        f"Rule: {finding.rule_id or '(none)'}",
        f"Location: {loc}",
        f"Symbol: {finding.symbol or '(none)'}",
        f"Exception: {finding.exception_type or '(none)'}",
        f"Test: {finding.test_id or '(none)'}",
        # Severity is included only as context from triage — model must not change it
        f"Triage severity (do not change): {finding.severity.value}",
        "Message / evidence:",
        mask_secrets(finding.message or "(no message)"),
    ]
    if finding.triage_notes:
        parts.append(f"Triage notes: {mask_secrets(finding.triage_notes)}")
    return "\n".join(parts)
