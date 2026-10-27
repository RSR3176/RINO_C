from __future__ import annotations

import difflib
import json
from pathlib import Path


def unified_diff_for_files(
    originals: dict[str, str], updated: dict[str, str]
) -> str:
    chunks: list[str] = []
    for path in sorted(updated.keys()):
        old = originals.get(path, "")
        new = updated[path]
        if old == new:
            continue
        diff = difflib.unified_diff(
            old.splitlines(keepends=True),
            new.splitlines(keepends=True),
            fromfile=f"a/{path}",
            tofile=f"b/{path}",
        )
        chunks.append("".join(diff))
    return "\n".join(chunks).strip()


def side_by_side_payload(
    originals: dict[str, str], updated: dict[str, str]
) -> list[dict]:
    """Per-file original/modified text for the Code Review diff panes."""
    out: list[dict] = []
    for path in sorted(updated.keys()):
        old = originals.get(path, "")
        new = updated[path]
        if old == new:
            continue
        out.append(
            {
                "path": path,
                "original": old,
                "modified": new,
                "added_lines": _count_delta(old, new)[0],
                "removed_lines": _count_delta(old, new)[1],
            }
        )
    return out


def dumps_files(files: dict[str, str] | list) -> str:
    return json.dumps(files, ensure_ascii=False)


def load_files_json(raw: str | None) -> list[dict] | dict:
    if not raw:
        return []
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return []


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _count_delta(old: str, new: str) -> tuple[int, int]:
    old_lines = old.splitlines()
    new_lines = new.splitlines()
    matcher = difflib.SequenceMatcher(a=old_lines, b=new_lines)
    added = removed = 0
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "insert":
            added += j2 - j1
        elif tag == "delete":
            removed += i2 - i1
        elif tag == "replace":
            removed += i2 - i1
            added += j2 - j1
    return added, removed
