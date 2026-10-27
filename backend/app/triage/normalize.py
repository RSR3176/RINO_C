from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Iterable

from app.runners.base import ParsedTestCase
from app.triage.fingerprint import compute_fingerprint
from app.triage.types import RawFinding

_EXCEPTION_RE = re.compile(
    r"(?P<type>[A-Za-z_][\w.]*(?:Error|Exception|Warning))\b(?::\s*(?P<msg>.*))?"
)


def findings_from_test_cases(
    cases: Iterable[ParsedTestCase],
    *,
    setup_failed: bool = False,
) -> list[RawFinding]:
    out: list[RawFinding] = []
    if setup_failed:
        finding = RawFinding(
            source="setup",
            rule_id="setup_failed",
            message="Setup command failed",
            tool_severity="critical",
            setup_failed=True,
        )
        finding.fingerprint = compute_fingerprint(finding)
        out.append(finding)

    for case in cases:
        if case.status not in {"failed", "error"}:
            continue
        exc_type, exc_msg = _parse_exception(case.message)
        test_id = ".".join(
            p for p in (case.classname, case.case_name) if p
        ) or case.case_name
        file_hint, line_hint = _file_line_from_message(case.message)
        finding = RawFinding(
            source="pytest",
            rule_id="test_failure" if case.status == "failed" else "test_error",
            file=file_hint,
            line=line_hint,
            symbol=case.case_name,
            message=(case.message or f"{case.case_name} {case.status}").strip(),
            tool_severity="critical",
            test_id=test_id,
            exception_type=exc_type,
            extra={"status": case.status, "suite": case.suite_name},
        )
        if exc_msg and not finding.message:
            finding.message = exc_msg
        finding.fingerprint = compute_fingerprint(finding)
        out.append(finding)
    return out


def findings_from_pylint(data: Any) -> list[RawFinding]:
    """Parse pylint ``--output-format=json`` payload (list or JSON string)."""
    payload = _as_json(data)
    if not isinstance(payload, list):
        return []
    out: list[RawFinding] = []
    for item in payload:
        if not isinstance(item, dict):
            continue
        msg_id = item.get("message-id") or item.get("message_id") or item.get("symbol")
        symbol = item.get("symbol")
        path = item.get("path") or item.get("module")
        line = item.get("line")
        message = item.get("message")
        typ = (item.get("type") or "").lower()  # error, warning, convention, refactor, fatal
        finding = RawFinding(
            source="pylint",
            rule_id=str(msg_id) if msg_id else None,
            file=str(path) if path else None,
            line=int(line) if isinstance(line, int) else _maybe_int(line),
            symbol=str(symbol) if symbol else None,
            message=str(message) if message else None,
            tool_severity=typ or None,
            tool_confidence=None,
            suppression_markers=_markers_from_text(message),
        )
        finding.fingerprint = compute_fingerprint(finding)
        out.append(finding)
    return out


def findings_from_bandit(data: Any) -> list[RawFinding]:
    """Parse bandit ``-f json`` payload."""
    payload = _as_json(data)
    if not isinstance(payload, dict):
        return []
    results = payload.get("results") or []
    out: list[RawFinding] = []
    for item in results:
        if not isinstance(item, dict):
            continue
        test_id = item.get("test_id") or item.get("test_name")
        severity = (item.get("issue_severity") or "").lower() or None
        confidence = (item.get("issue_confidence") or "").lower() or None
        finding = RawFinding(
            source="bandit",
            rule_id=str(test_id) if test_id else None,
            file=item.get("filename"),
            line=_maybe_int(item.get("line_number")),
            symbol=item.get("test_name"),
            message=item.get("issue_text"),
            tool_severity=severity,
            tool_confidence=confidence,
            suppression_markers=_markers_from_text(
                item.get("issue_text")
            ) + (["nosec"] if item.get("issue_text") and "nosec" in str(item).lower() else []),
        )
        finding.fingerprint = compute_fingerprint(finding)
        out.append(finding)
    return out


def load_json_file(path: str | Path) -> Any:
    p = Path(path)
    if not p.is_file():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _as_json(data: Any) -> Any:
    if data is None:
        return None
    if isinstance(data, (dict, list)):
        return data
    if isinstance(data, (str, bytes, bytearray)):
        text = data.decode("utf-8") if isinstance(data, (bytes, bytearray)) else data
        text = text.strip()
        if not text:
            return None
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return None
    return None


def _maybe_int(value: Any) -> int | None:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _parse_exception(message: str | None) -> tuple[str | None, str | None]:
    if not message:
        return None, None
    # Prefer the last exception-looking line (pytest traces put it near the end)
    matches = list(_EXCEPTION_RE.finditer(message))
    if not matches:
        return None, None
    m = matches[-1]
    return m.group("type"), (m.group("msg") or "").strip() or None


def _file_line_from_message(message: str | None) -> tuple[str | None, int | None]:
    if not message:
        return None, None
    # e.g. File "src/foo.py", line 12
    m = re.search(r'File "([^"]+)", line (\d+)', message)
    if m:
        return m.group(1), int(m.group(2))
    m = re.search(r"([\w./\\-]+\.py):(\d+)", message)
    if m:
        return m.group(1), int(m.group(2))
    return None, None


def _markers_from_text(text: str | None) -> list[str]:
    if not text:
        return []
    markers: list[str] = []
    lower = text.lower()
    if "noqa" in lower:
        markers.append("noqa")
    if "nosec" in lower:
        markers.append("nosec")
    return markers
