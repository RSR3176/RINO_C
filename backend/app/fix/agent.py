from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from pathlib import Path

from app.config import Settings, get_settings
from app.llm.client import complete_text
from app.llm.secrets import mask_secrets
from app.models import Finding

logger = logging.getLogger(__name__)

SYSTEM = (
    "You are a careful code-fix agent. "
    "Propose a minimal fix for the finding. "
    "You may ONLY edit non-test source files. "
    "Never edit tests/, test_*.py, *_test.py. "
    "Never add pytest.skip, skipif, or xfail. "
    "Never add empty except bodies. "
    "Change at most 3 files. "
    "Respond with ONLY JSON: "
    '{"explanation":"...","files":{"path/to/file.py":"full new file contents"}}'
)


@dataclass
class FixProposal:
    files: dict[str, str]
    explanation: str
    model: str
    input_tokens: int
    output_tokens: int
    cost_usd: float
    success: bool
    error_message: str | None = None
    stub: bool = False


def propose_fix(
    *,
    finding: Finding,
    workspace: Path,
    readable_files: dict[str, str],
    prior_feedback: str | None = None,
    settings: Settings | None = None,
) -> FixProposal:
    settings = settings or get_settings()

    if not settings.anthropic_configured():
        stub = _stub_fix(finding, readable_files)
        if stub is not None:
            return stub
        return FixProposal(
            files={},
            explanation="",
            model=f"stub:{settings.llm_model}",
            input_tokens=0,
            output_tokens=0,
            cost_usd=0.0,
            success=False,
            error_message="No stub fix available for this finding",
            stub=True,
        )

    user = _build_prompt(finding, readable_files, prior_feedback)
    result = complete_text(
        system=SYSTEM, user=user, settings=settings, max_tokens=4000
    )
    if not result.success or not result.text.strip():
        return FixProposal(
            files={},
            explanation="",
            model=result.model,
            input_tokens=result.input_tokens,
            output_tokens=result.output_tokens,
            cost_usd=result.cost_usd,
            success=False,
            error_message=result.error_message or "Empty LLM response",
        )

    parsed = _parse_files_json(result.text)
    if parsed is None:
        return FixProposal(
            files={},
            explanation="",
            model=result.model,
            input_tokens=result.input_tokens,
            output_tokens=result.output_tokens,
            cost_usd=result.cost_usd,
            success=False,
            error_message="Could not parse JSON fix proposal",
        )
    explanation, files = parsed
    return FixProposal(
        files=files,
        explanation=explanation,
        model=result.model,
        input_tokens=result.input_tokens,
        output_tokens=result.output_tokens,
        cost_usd=result.cost_usd,
        success=True,
    )


def collect_relevant_sources(workspace: Path, finding: Finding) -> dict[str, str]:
    """Read finding file + a few nearby non-test .py files for context."""
    out: dict[str, str] = {}
    candidates: list[Path] = []
    if finding.file:
        p = workspace / finding.file.lstrip("./")
        if p.is_file():
            candidates.append(p)
    # Always include top-level modules for small fixtures
    for p in sorted(workspace.glob("*.py")):
        if p.name.startswith("test_"):
            continue
        candidates.append(p)
    for p in candidates:
        rel = p.relative_to(workspace).as_posix()
        if rel in out:
            continue
        try:
            out[rel] = p.read_text(encoding="utf-8")
        except OSError:
            continue
        if len(out) >= 6:
            break
    return out


def _build_prompt(
    finding: Finding,
    files: dict[str, str],
    prior_feedback: str | None,
) -> str:
    loc = finding.file or "(unknown)"
    if finding.line is not None:
        loc = f"{loc}:{finding.line}"
    parts = [
        f"Finding tool={finding.source} rule={finding.rule_id} severity={finding.severity.value}",
        f"Location: {loc}",
        f"Message:\n{mask_secrets(finding.message or '')}",
        f"Root cause:\n{mask_secrets(finding.root_cause or '(none)')}",
        "Source files (edit only non-test files):",
    ]
    for path, content in files.items():
        parts.append(f"\n----- {path} -----\n{mask_secrets(content)}")
    if prior_feedback:
        parts.append(f"\nPrevious attempt feedback:\n{prior_feedback}")
    return "\n".join(parts)


def _parse_files_json(text: str) -> tuple[str, dict[str, str]] | None:
    text = text.strip()
    # Strip markdown fences if present
    fence = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
    if fence:
        text = fence.group(1).strip()
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        # try to find outermost object
        m = re.search(r"\{[\s\S]*\}", text)
        if not m:
            return None
        try:
            data = json.loads(m.group(0))
        except json.JSONDecodeError:
            return None
    if not isinstance(data, dict):
        return None
    explanation = str(data.get("explanation") or "").strip()
    files_raw = data.get("files") or {}
    if not isinstance(files_raw, dict):
        return None
    files = {str(k).lstrip("./"): str(v) for k, v in files_raw.items()}
    return explanation, files


def _stub_fix(
    finding: Finding, readable: dict[str, str]
) -> FixProposal | None:
    """Deterministic fixes for the junit-demo fixture (offline Step 6)."""
    rule = (finding.rule_id or "").upper()
    path = (finding.file or "").lstrip("./")

    if rule == "B602" or (finding.source == "bandit" and "shell" in path):
        target = path if path in readable else "shellutil.py"
        if target not in readable and "shellutil.py" in readable:
            target = "shellutil.py"
        if target not in readable:
            return None
        fixed = (
            '"""Intentional bandit finding for Step 4 demos — fixed."""\n\n'
            "import shlex\n"
            "import subprocess\n\n\n"
            "def run_user_command(cmd: str) -> str:\n"
            "    # Avoid shell=True (bandit B602)\n"
            "    args = shlex.split(cmd)\n"
            "    result = subprocess.run(\n"
            "        args, shell=False, capture_output=True, text=True, check=False\n"
            "    )\n"
            "    return result.stdout\n"
        )
        return FixProposal(
            files={target: fixed},
            explanation=(
                "[Explanation] Replaces shell=True with shlex.split + shell=False "
                "so the command still runs without a shell injection risk."
            ),
            model="stub:fix-b602",
            input_tokens=1,
            output_tokens=1,
            cost_usd=0.0,
            success=True,
            stub=True,
        )

    if rule == "E0602" or "messy" in path:
        target = "messy.py" if "messy.py" in readable else path
        if target not in readable:
            return None
        fixed = (
            '"""Intentional pylint findings for Step 4 demos — fixed."""\n\n\n'
            "def broken_add(a: int, b: int) -> int:\n"
            "    return a + b\n"
        )
        return FixProposal(
            files={target: fixed},
            explanation=(
                "[Explanation] Uses the intended variable b instead of undefined c, "
                "and drops the unused import."
            ),
            model="stub:fix-e0602",
            input_tokens=1,
            output_tokens=1,
            cost_usd=0.0,
            success=True,
            stub=True,
        )

    return None
