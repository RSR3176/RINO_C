from __future__ import annotations

import re

# Patterns for common secrets — replacements never include the original value.
_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (
        re.compile(
            r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----[\s\S]*?"
            r"-----END (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"
        ),
        "[REDACTED_PRIVATE_KEY]",
    ),
    (
        re.compile(r"(?i)bearer\s+[A-Za-z0-9\-._~+/]+=*"),
        "Bearer [REDACTED]",
    ),
    (
        re.compile(r"(?i)(x-access-token:)([^@\s]+)(@)"),
        r"\1[REDACTED]\3",
    ),
    (
        re.compile(r"(?i)\b(ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9_]{20,}\b"),
        "[REDACTED_GITHUB_TOKEN]",
    ),
    (
        re.compile(r"(?i)\bsk-ant-[A-Za-z0-9\-_]{20,}\b"),
        "[REDACTED_ANTHROPIC_KEY]",
    ),
    (
        re.compile(r"(?i)\bsk-[A-Za-z0-9]{20,}\b"),
        "[REDACTED_API_KEY]",
    ),
    (
        re.compile(
            r"(?i)(api[_-]?key|secret|token|password|passwd|authorization)\s*[=:]\s*['\"]?([^\s'\"\\]+)"
        ),
        r"\1=[REDACTED]",
    ),
]


def mask_secrets(text: str | None) -> str:
    """Return a copy of text with secrets replaced. Safe to send to an LLM."""
    if not text:
        return ""
    out = text
    for pattern, repl in _PATTERNS:
        out = pattern.sub(repl, out)
    return out
