from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


SEVERITY_ORDER = ("low", "medium", "high", "critical")


@dataclass
class RawFinding:
    """Normalized tool output before triage."""

    source: str  # pytest | pylint | bandit | setup
    rule_id: str | None = None
    file: str | None = None
    line: int | None = None
    symbol: str | None = None
    message: str | None = None
    tool_severity: str | None = None
    tool_confidence: str | None = None
    test_id: str | None = None
    exception_type: str | None = None
    fingerprint: str | None = None
    # Engine hints (not persisted as columns unless mapped)
    suppression_markers: list[str] = field(default_factory=list)
    prior_pass_on_rerun: bool = False
    is_regression: bool = False
    setup_failed: bool = False
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass
class TriagedFinding:
    """Finding after applying rules.yaml."""

    source: str
    rule_id: str | None
    file: str | None
    line: int | None
    symbol: str | None
    message: str | None
    tool_severity: str | None
    tool_confidence: str | None
    test_id: str | None
    exception_type: str | None
    fingerprint: str

    # Triage outputs
    severity: str  # critical|high|medium|low
    category: str  # code_bug | setup_failed | environment | flaky | ignored
    is_code_bug: bool
    needs_attention: bool
    issue_status: str  # none | awaiting_confirm | open | …
    fix_status: str  # none | suggested | verified | …
    action_tag: str | None = None
    triage_notes: str | None = None
