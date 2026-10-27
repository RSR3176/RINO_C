from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import PurePosixPath


MAX_FILES_CHANGED = 3


def max_files_changed() -> int:
    """Read Settings → Fix limits (falls back to 3)."""
    try:
        from app.triage.load_rules import load_rules

        limits = (load_rules() or {}).get("fix_limits") or {}
        n = int(limits.get("max_files_changed") or MAX_FILES_CHANGED)
        return max(1, min(10, n))
    except Exception:
        return MAX_FILES_CHANGED


_TEST_PATH_RE = re.compile(
    r"(^|/)(tests?|testing)(/|$)|(^|/)test_[^/]+\.py$|(^|/).+_test\.py$",
    re.I,
)
_SKIP_RE = re.compile(
    r"@pytest\.mark\.(skip|skipif|xfail)\b|\bpytest\.skip\s*\(|\bpytest\.xfail\s*\(",
    re.M,
)
# bare `except:` or `except Exception:` / `except BaseException:` with only pass/ellipsis
_EMPTY_EXCEPT_RE = re.compile(
    r"except(?:\s+\w+(?:\s+as\s+\w+)?)?\s*:\s*(?:pass|\.\.\.|\#[^\n]*)\s*(?:\n|$)",
    re.M,
)


@dataclass
class SafetyResult:
    ok: bool
    violations: list[str] = field(default_factory=list)

    def reject(self, message: str) -> None:
        self.ok = False
        self.violations.append(message)


def is_test_path(path: str) -> bool:
    norm = path.replace("\\", "/").lstrip("./")
    return bool(_TEST_PATH_RE.search(norm))


def validate_patch_files(
    files: dict[str, str],
    *,
    originals: dict[str, str] | None = None,
) -> SafetyResult:
    """Reject unsafe patches before they are applied / verified.

    Rules (Step 6):
    - must not touch test files
    - must not add skip / xfail
    - must not introduce empty except bodies
    - must not change more than 3 files
    """
    result = SafetyResult(ok=True)
    originals = originals or {}

    if not files:
        result.reject("Patch is empty (no files changed)")
        return result

    limit = max_files_changed()
    if len(files) > limit:
        result.reject(f"Changes more than {limit} files ({len(files)} files)")

    for path, content in files.items():
        norm = path.replace("\\", "/").lstrip("./")
        if not norm or norm.startswith("/") or ".." in PurePosixPath(norm).parts:
            result.reject(f"Illegal path: {path}")
            continue
        if is_test_path(norm):
            result.reject(f"Touches test file: {norm}")
            continue

        old = originals.get(path) or originals.get(norm) or ""
        # Only flag skip/xfail newly introduced
        if _SKIP_RE.search(content) and not _SKIP_RE.search(old):
            result.reject(f"Adds skip/xfail in {norm}")

        if _has_new_empty_except(old, content):
            result.reject(f"Introduces empty except in {norm}")

    return result


def _has_new_empty_except(old: str, new: str) -> bool:
    old_hits = len(_EMPTY_EXCEPT_RE.findall(old))
    new_hits = len(_EMPTY_EXCEPT_RE.findall(new))
    return new_hits > old_hits
