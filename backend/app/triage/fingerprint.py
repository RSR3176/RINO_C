from __future__ import annotations

import hashlib
import re

from app.triage.types import RawFinding


def compute_fingerprint(
    finding: RawFinding,
    *,
    key: str = "file_rule_message",
    merge_across_tools: bool = True,
) -> str:
    """Stable fingerprint used for duplicate merging (rule 3)."""
    file_part = _norm_path(finding.file)
    rule_part = (finding.rule_id or finding.symbol or finding.exception_type or "").strip()
    msg_part = _norm_message(finding.message)
    source_part = "" if merge_across_tools else (finding.source or "")

    if key == "rule_only":
        parts = [source_part, rule_part]
    elif key == "file_rule":
        parts = [source_part, file_part, rule_part]
    else:  # file_rule_message
        parts = [source_part, file_part, rule_part, msg_part]

    material = "|".join(parts)
    return hashlib.sha256(material.encode("utf-8")).hexdigest()[:32]


def _norm_path(path: str | None) -> str:
    if not path:
        return ""
    return path.replace("\\", "/").lstrip("./").strip().lower()


def _norm_message(message: str | None) -> str:
    if not message:
        return ""
    # Collapse whitespace; drop volatile addresses / durations
    text = re.sub(r"\s+", " ", message).strip().lower()
    text = re.sub(r"0x[0-9a-f]+", "0x…", text)
    text = re.sub(r"\b\d+(\.\d+)?s\b", "…s", text)
    return text[:500]
