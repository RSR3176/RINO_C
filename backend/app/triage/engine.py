from __future__ import annotations

import re
from typing import Any

from app.triage.fingerprint import compute_fingerprint
from app.triage.load_rules import load_rules
from app.triage.types import SEVERITY_ORDER, RawFinding, TriagedFinding


def triage_findings(
    raw: list[RawFinding],
    *,
    rules: dict[str, Any] | None = None,
    rules_path: str | None = None,
) -> list[TriagedFinding]:
    """Apply the six rules.yaml policies and return deduplicated findings."""
    cfg = rules if rules is not None else load_rules(rules_path)
    dup = cfg.get("duplicate_merging") or {}
    key = dup.get("key") or "file_rule_message"
    merge_across = bool(dup.get("merge_across_tools", True))

    # Ensure fingerprints match merge policy
    prepared: list[RawFinding] = []
    for item in raw:
        item.fingerprint = compute_fingerprint(
            item, key=key, merge_across_tools=merge_across
        )
        prepared.append(item)

    # Rule 3 — merge duplicates (keep richest message / highest tool severity hint)
    merged = _merge_duplicates(prepared)

    triaged: list[TriagedFinding] = []
    for item in merged:
        # Rule 2 — ignored paths / suppressions
        if _is_ignored_path(item, cfg):
            triaged.append(
                _make(
                    item,
                    severity="low",
                    category="ignored",
                    is_code_bug=False,
                    needs_attention=False,
                    notes="Ignored path",
                )
            )
            continue
        if _is_suppressed(item, cfg):
            triaged.append(
                _make(
                    item,
                    severity="low",
                    category="ignored",
                    is_code_bug=False,
                    needs_attention=False,
                    notes="Inline suppression (noqa/nosec)",
                )
            )
            continue

        # Rule 1 — not a code bug
        ncb = _not_code_bug_category(item, cfg)
        if ncb:
            triaged.append(
                _make(
                    item,
                    severity="low",
                    category=ncb,
                    is_code_bug=False,
                    needs_attention=False,
                    notes=f"Not a code bug: {ncb}",
                )
            )
            continue

        # Rule 4 — base severity
        severity = _base_severity(item, cfg)

        # Core modules: failing tests always Critical
        if item.source == "pytest" and _in_core_module(item, cfg):
            severity = "critical"

        # Rule 5 — adjustments
        severity = _apply_adjustments(item, severity, cfg)

        # Rule 6 — actions
        action = _action_for(severity, cfg)
        triaged.append(
            _make(
                item,
                severity=severity,
                category="code_bug",
                is_code_bug=True,
                needs_attention=bool(action.get("needs_attention")),
                action_tag=action.get("tag"),
                notes=None,
            )
        )

    # Drop ignored from primary list? Keep them but dashboard filters code bugs.
    # Spec: ignored paths are suppressed — exclude from returned code-bug set,
    # but keep not-code-bug categories for the NCB section.
    return [t for t in triaged if t.category != "ignored"]


def _make(
    item: RawFinding,
    *,
    severity: str,
    category: str,
    is_code_bug: bool,
    needs_attention: bool,
    notes: str | None,
    action_tag: str | None = None,
) -> TriagedFinding:
    return TriagedFinding(
        source=item.source,
        rule_id=item.rule_id,
        file=item.file,
        line=item.line,
        symbol=item.symbol,
        message=item.message,
        tool_severity=item.tool_severity,
        tool_confidence=item.tool_confidence,
        test_id=item.test_id,
        exception_type=item.exception_type,
        fingerprint=item.fingerprint or compute_fingerprint(item),
        severity=severity,
        category=category,
        is_code_bug=is_code_bug,
        needs_attention=needs_attention,
        issue_status="none",
        fix_status="none",
        action_tag=action_tag,
        triage_notes=notes,
    )


def _merge_duplicates(items: list[RawFinding]) -> list[RawFinding]:
    by_fp: dict[str, RawFinding] = {}
    order: list[str] = []
    for item in items:
        fp = item.fingerprint or compute_fingerprint(item)
        item.fingerprint = fp
        if fp not in by_fp:
            by_fp[fp] = item
            order.append(fp)
            continue
        existing = by_fp[fp]
        # Prefer longer message; OR setup_failed / regression flags
        if (item.message or "") and len(item.message or "") > len(existing.message or ""):
            existing.message = item.message
        existing.setup_failed = existing.setup_failed or item.setup_failed
        existing.prior_pass_on_rerun = (
            existing.prior_pass_on_rerun or item.prior_pass_on_rerun
        )
        existing.is_regression = existing.is_regression or item.is_regression
        if not existing.exception_type and item.exception_type:
            existing.exception_type = item.exception_type
        if not existing.file and item.file:
            existing.file = item.file
            existing.line = item.line
    return [by_fp[fp] for fp in order]


def _is_ignored_path(item: RawFinding, cfg: dict[str, Any]) -> bool:
    path = (item.file or "").replace("\\", "/")
    if not path:
        return False
    for prefix in cfg.get("ignored_paths") or []:
        p = str(prefix).replace("\\", "/")
        if path == p.rstrip("/") or path.startswith(p):
            return True
    return False


def _is_suppressed(item: RawFinding, cfg: dict[str, Any]) -> bool:
    if not cfg.get("respect_inline_suppressions", True):
        return False
    markers = {m.lower() for m in (item.suppression_markers or [])}
    if item.source == "pylint" and "noqa" in markers:
        return True
    if item.source == "bandit" and "nosec" in markers:
        return True
    # Also honor markers embedded in the message text
    msg = (item.message or "").lower()
    if item.source == "pylint" and "# noqa" in msg:
        return True
    if item.source == "bandit" and "# nosec" in msg:
        return True
    return False


def _not_code_bug_category(item: RawFinding, cfg: dict[str, Any]) -> str | None:
    ncb = cfg.get("not_a_code_bug") or {}

    setup_cfg = ncb.get("setup_failed") or {}
    if setup_cfg.get("enabled", True):
        if item.setup_failed or item.source == "setup":
            return "setup_failed"
        if item.message and _matches_any(item.message, setup_cfg.get("message_patterns") or []):
            return "setup_failed"

    miss_cfg = ncb.get("missing_package") or {}
    if miss_cfg.get("enabled", True):
        exc_types = {t.lower() for t in (miss_cfg.get("exception_types") or [])}
        if (item.exception_type or "").lower() in exc_types:
            if _matches_any(
                item.message or "", miss_cfg.get("message_patterns") or []
            ) or not (miss_cfg.get("message_patterns") or []):
                # If patterns provided, require match; if ModuleNotFoundError for
                # clearly third-party-looking names, treat as environment.
                return "environment"
        if item.message and _matches_any(
            item.message, miss_cfg.get("message_patterns") or []
        ):
            return "environment"

    flaky_cfg = ncb.get("flaky") or {}
    if flaky_cfg.get("enabled", True) and item.prior_pass_on_rerun:
        return "flaky"

    return None


def _base_severity(item: RawFinding, cfg: dict[str, Any]) -> str:
    table = cfg.get("severity_table") or {}
    if item.source == "pytest":
        return _norm_sev(table.get("failing_test", "critical"))
    if item.source == "bandit":
        sev = (item.tool_severity or "").lower()
        if sev == "high":
            return _norm_sev(table.get("bandit_high", "critical"))
        if sev == "medium":
            return _norm_sev(table.get("bandit_medium", "high"))
        if sev == "low":
            return _norm_sev(table.get("bandit_low", "medium"))
        return _norm_sev(table.get("default", "medium"))
    if item.source == "pylint":
        typ = (item.tool_severity or "").lower()
        rule = (item.rule_id or item.symbol or "").upper()
        if typ == "fatal" or rule.startswith("F"):
            return _norm_sev(table.get("pylint_fatal", "critical"))
        if typ == "error" or rule.startswith("E"):
            return _norm_sev(table.get("pylint_error", "high"))
        if typ == "warning" or rule.startswith("W"):
            return _norm_sev(table.get("pylint_warning", "medium"))
        if typ in {"convention", "refactor"} or rule[:1] in {"C", "R"}:
            return _norm_sev(table.get("pylint_style", "low"))
        if typ == "info" or rule.startswith("I"):
            return _norm_sev(table.get("pylint_info", "low"))
        return _norm_sev(table.get("default", "medium"))
    return _norm_sev(table.get("default", "medium"))


def _apply_adjustments(
    item: RawFinding, severity: str, cfg: dict[str, Any]
) -> str:
    adj = cfg.get("adjustments") or {}
    if not adj.get("enabled", True):
        return severity
    delta = 0
    path = (item.file or "").replace("\\", "/")
    for prefix in adj.get("non_production_paths") or []:
        p = str(prefix).replace("\\", "/")
        if path.startswith(p) or f"/{p}" in f"/{path}":
            delta += int(adj.get("non_production_delta", -1))
            break
    if item.is_regression:
        delta += int(adj.get("regression_delta", 1))
    return _shift_severity(severity, delta)


def _in_core_module(item: RawFinding, cfg: dict[str, Any]) -> bool:
    path = (item.file or "").replace("\\", "/")
    test_id = item.test_id or ""
    for mod in cfg.get("core_modules") or []:
        m = str(mod).replace("\\", "/")
        if path.startswith(m) or m in path or m in test_id.replace(".", "/"):
            return True
    return False


def _action_for(severity: str, cfg: dict[str, Any]) -> dict[str, Any]:
    actions = cfg.get("actions") or {}
    return dict(actions.get(severity) or {})


def _matches_any(text: str, patterns: list[str]) -> bool:
    if not patterns:
        return False
    for pat in patterns:
        try:
            if re.search(pat, text):
                return True
        except re.error:
            continue
    return False


def _norm_sev(value: Any) -> str:
    s = str(value or "medium").lower().strip()
    return s if s in SEVERITY_ORDER else "medium"


def _shift_severity(severity: str, delta: int) -> str:
    if delta == 0:
        return severity
    try:
        idx = SEVERITY_ORDER.index(severity)
    except ValueError:
        idx = 1
    idx = max(0, min(len(SEVERITY_ORDER) - 1, idx + delta))
    return SEVERITY_ORDER[idx]
