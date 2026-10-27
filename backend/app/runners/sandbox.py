from __future__ import annotations

import json
import logging
import os
import re
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

import docker
from docker.errors import ImageNotFound

from app.runners.base import RunOutcome, RunRequest, StepOutcome, TestRunner
from app.runners.junit import parse_junit_xml

logger = logging.getLogger(__name__)

JUNIT_FILE = "rino-junit.xml"
PYLINT_FILE = "rino-pylint.json"
BANDIT_FILE = "rino-bandit.json"
MAX_LOG_CHARS = 80_000


class SandboxRunner(TestRunner):
    """Clone a repo into a workdir and run setup/tests in a Docker container.

    Workdir lives on a Docker named volume shared with sandbox containers
    (avoids host bind-path / FUSE permission issues). Setup runs with network;
    tests run with ``network_mode=none``. CPU/memory limits + wall timeout apply.
    """

    def run(self, request: RunRequest) -> RunOutcome:
        deadline = time.monotonic() + max(30, request.timeout_seconds)
        work_root = Path(
            request.work_root
            or tempfile.mkdtemp(prefix="rino-sandbox-", dir=_default_work_parent())
        )
        src = work_root / "src"
        outcome = RunOutcome(ok=False)
        try:
            remaining = _remaining(deadline)
            if remaining <= 0:
                return _timed_out(outcome, "Timed out before clone")
            clone_step = self._clone(request, src, remaining)
            outcome.steps.append(clone_step)
            if not clone_step.ok:
                outcome.error_message = "Clone failed"
                return outcome
            outcome.commit_sha = clone_step.detail.get("commit_sha")

            remaining = _remaining(deadline)
            if remaining <= 0:
                return _timed_out(outcome, "Timed out before setup")
            setup_step = self._docker_phase(
                name="setup",
                request=request,
                src=src,
                command=_setup_shell(request.setup_command),
                network=True,
                timeout=remaining,
            )
            outcome.steps.append(setup_step)
            if not setup_step.ok:
                outcome.setup_failed = True
                outcome.error_message = "Setup command failed"
                return outcome

            remaining = _remaining(deadline)
            if remaining <= 0:
                return _timed_out(outcome, "Timed out before tests")
            test_step = self._docker_phase(
                name="test",
                request=request,
                src=src,
                command=_test_shell(request.test_command),
                network=False,
                timeout=remaining,
            )
            outcome.steps.append(test_step)

            junit_path = src / JUNIT_FILE
            outcome.junit_xml_path = str(junit_path) if junit_path.exists() else None
            parse_step = StepOutcome(name="parse_junit", ok=False)
            if junit_path.exists():
                try:
                    tests = parse_junit_xml(junit_path)
                    outcome.tests = tests
                    parse_step.ok = True
                    parse_step.log_text = f"Parsed {len(tests)} test case(s)"
                    parse_step.detail = {"count": len(tests)}
                except Exception as exc:
                    parse_step.log_text = f"Failed to parse JUnit XML: {exc}"
                    outcome.error_message = "JUnit parse failed"
            else:
                parse_step.log_text = (
                    f"{JUNIT_FILE} not found after tests "
                    f"(exit_code={test_step.exit_code})"
                )
                if not outcome.error_message and not test_step.ok:
                    outcome.error_message = "Tests failed and no JUnit XML was produced"
                elif not outcome.error_message:
                    outcome.error_message = "No JUnit XML produced"
            outcome.steps.append(parse_step)

            # Always run pylint + bandit after tests (offline; tools installed in setup)
            remaining = _remaining(deadline)
            if remaining <= 0:
                return _timed_out(outcome, "Timed out before lint")
            lint_step = self._docker_phase(
                name="lint",
                request=request,
                src=src,
                command=_lint_shell(),
                network=False,
                timeout=remaining,
            )
            # Lint tools often exit non-zero when they report issues — still OK for Rino
            pylint_path = src / PYLINT_FILE
            bandit_path = src / BANDIT_FILE
            outcome.pylint_json_path = (
                str(pylint_path) if pylint_path.exists() else None
            )
            outcome.bandit_json_path = (
                str(bandit_path) if bandit_path.exists() else None
            )
            outcome.pylint_raw = _load_json(pylint_path) if pylint_path.exists() else None
            outcome.bandit_raw = _load_json(bandit_path) if bandit_path.exists() else None
            lint_ok = pylint_path.exists() or bandit_path.exists() or lint_step.ok
            lint_step.ok = bool(lint_ok)
            if lint_ok and not lint_step.log_text:
                lint_step.log_text = "pylint/bandit finished"
            elif lint_ok:
                lint_step.log_text = (
                    (lint_step.log_text or "")
                    + f"\npylint_json={pylint_path.exists()} "
                    f"bandit_json={bandit_path.exists()}"
                )
            outcome.steps.append(lint_step)

            if parse_step.ok or lint_ok:
                outcome.ok = True
                if not test_step.ok:
                    outcome.error_message = None
            return outcome
        except _Timeout:
            return _timed_out(outcome, "Sandbox run exceeded time limit")
        except Exception as exc:
            logger.exception("SandboxRunner failed")
            outcome.error_message = f"SandboxRunner error: {type(exc).__name__}: {exc}"
            return outcome
        finally:
            if os.environ.get("RINO_SANDBOX_KEEP", "").strip() not in {"1", "true"}:
                shutil.rmtree(work_root, ignore_errors=True)

    def _clone(
        self, request: RunRequest, src: Path, timeout: float
    ) -> StepOutcome:
        src.parent.mkdir(parents=True, exist_ok=True)
        if request.local_source_path:
            source = Path(request.local_source_path)
            if not source.is_dir():
                return StepOutcome(
                    name="clone",
                    ok=False,
                    log_text=f"Local source not found: {source}",
                )
            try:
                _copytree_content(source, src)
            except Exception as exc:
                return StepOutcome(
                    name="clone",
                    ok=False,
                    log_text=f"Failed to copy local fixture: {exc}",
                )
            sha = _git_rev_parse(src) or "local"
            return StepOutcome(
                name="clone",
                ok=True,
                log_text=f"Copied local fixture from {source}",
                detail={"commit_sha": sha, "mode": "local"},
            )

        if not request.clone_url:
            return StepOutcome(
                name="clone",
                ok=False,
                log_text="No clone_url or local_source_path provided",
            )

        cmd = [
            "git",
            "clone",
            "--depth",
            "1",
            "--branch",
            request.branch,
            request.clone_url,
            str(src),
        ]
        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout,
                check=False,
                env={**os.environ, "GIT_TERMINAL_PROMPT": "0"},
            )
        except subprocess.TimeoutExpired as exc:
            raise _Timeout from exc

        log = _redact_tokens(_combine(proc.stdout, proc.stderr))
        if proc.returncode != 0:
            return StepOutcome(
                name="clone",
                ok=False,
                exit_code=proc.returncode,
                log_text=log or "git clone failed",
            )
        sha = _git_rev_parse(src)
        return StepOutcome(
            name="clone",
            ok=True,
            exit_code=0,
            log_text=log or "git clone ok",
            detail={"commit_sha": sha, "mode": "git"},
        )

    def _docker_phase(
        self,
        *,
        name: str,
        request: RunRequest,
        src: Path,
        command: str,
        network: bool,
        timeout: float,
    ) -> StepOutcome:
        image = f"python:{request.python_version}-slim"
        client = docker.from_env()
        try:
            if network:
                try:
                    client.images.pull(image)
                except Exception as exc:
                    return StepOutcome(
                        name=name,
                        ok=False,
                        log_text=f"Failed to pull {image}: {exc}",
                    )

            volume_name = _sandbox_volume_name()
            work = Path(
                os.environ.get("RINO_SANDBOX_WORK_DIR", "/var/rino/sandbox")
            ).resolve()
            rel = src.resolve().relative_to(work).as_posix()
            # Named volume is mounted at /rino in the sandbox container.
            working_dir = f"/rino/{rel}"

            nano_cpus = int(float(request.cpus) * 1_000_000_000)
            kwargs: dict = {
                "image": image,
                "command": ["bash", "-lc", command],
                "volumes": {volume_name: {"bind": "/rino", "mode": "rw"}},
                "working_dir": working_dir,
                "mem_limit": request.memory_limit,
                "nano_cpus": nano_cpus,
                "detach": True,
                "remove": False,
            }
            if not network:
                kwargs["network_mode"] = "none"

            try:
                container = client.containers.run(**kwargs)
            except ImageNotFound:
                client.images.pull(image)
                container = client.containers.run(**kwargs)

            deadline = time.monotonic() + timeout
            while time.monotonic() < deadline:
                container.reload()
                if container.status in {"exited", "dead"}:
                    break
                time.sleep(0.5)
            else:
                try:
                    container.kill()
                except Exception:
                    pass
                try:
                    container.remove(force=True)
                except Exception:
                    pass
                raise _Timeout()

            exit_code = int(container.attrs.get("State", {}).get("ExitCode", 1))
            try:
                raw = container.logs(stdout=True, stderr=True)
                log = (
                    raw.decode("utf-8", errors="replace")
                    if isinstance(raw, bytes)
                    else str(raw)
                )
            except Exception:
                log = ""
            try:
                container.remove(force=True)
            except Exception:
                pass

            return StepOutcome(
                name=name,
                ok=exit_code == 0,
                exit_code=exit_code,
                log_text=_truncate(log),
            )
        except _Timeout:
            raise
        except Exception as exc:
            return StepOutcome(
                name=name,
                ok=False,
                log_text=f"Docker phase failed: {type(exc).__name__}: {exc}",
            )


class _Timeout(Exception):
    pass


def _load_json(path: Path) -> object | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _sandbox_volume_name() -> str:
    # Compose project "rino" + volume "sandbox_data" => "rino_sandbox_data"
    return os.environ.get("RINO_SANDBOX_VOLUME", "rino_sandbox_data")


def _default_work_parent() -> str:
    parent = os.environ.get("RINO_SANDBOX_WORK_DIR", "/var/rino/sandbox")
    Path(parent).mkdir(parents=True, exist_ok=True)
    return parent


def _copytree_content(source: Path, dest: Path) -> None:
    """Copy files without preserving mode/owner (FUSE-friendly)."""

    def _copy(src: str, dst: str, *, follow_symlinks: bool = True) -> None:
        shutil.copyfile(src, dst, follow_symlinks=follow_symlinks)

    if dest.exists():
        shutil.rmtree(dest, ignore_errors=True)
    shutil.copytree(source, dest, copy_function=_copy)


def _remaining(deadline: float) -> float:
    return max(0.0, deadline - time.monotonic())


def _timed_out(outcome: RunOutcome, message: str) -> RunOutcome:
    outcome.ok = False
    outcome.timed_out = True
    outcome.error_message = message
    outcome.steps.append(StepOutcome(name="timeout", ok=False, log_text=message))
    return outcome


def _setup_shell(setup_command: str) -> str:
    """Install into a workspace venv so the offline test container can reuse it.

    Uses relative paths — the container working directory is the repo root.
    Always installs pytest, pylint, and bandit for Step 4 analysis.
    """
    setup = (setup_command or "true").strip() or "true"
    return (
        "set -euo pipefail; "
        "python -m venv .rino-venv; "
        ". .rino-venv/bin/activate; "
        "python -m pip install --no-cache-dir -U pip; "
        "python -m pip install --no-cache-dir pytest pylint bandit; "
        f"({setup})"
    )


def _test_shell(test_command: str) -> str:
    base = (test_command or "pytest").strip() or "pytest"
    if "--junitxml" not in base and "--junit-xml" not in base:
        base = f"{base} --junitxml={JUNIT_FILE}"
    # Prefer the venv created during setup (persisted on the shared volume).
    # PYTHONPATH=. keeps flat modules importable under pytest's importlib mode.
    return (
        "set -uo pipefail; "
        "if [ -f .rino-venv/bin/activate ]; then "
        ". .rino-venv/bin/activate; "
        "fi; "
        "export PYTHONPATH=\"${PYTHONPATH:-.}\"; "
        f"{base}"
    )


def _lint_shell() -> str:
    """Run pylint (JSON) and bandit (JSON). Non-zero exits are expected when issues exist."""
    # Lint top-level *.py plus common package dirs; skip tests/venv via find filters.
    return (
        "set -uo pipefail; "
        "if [ -f .rino-venv/bin/activate ]; then . .rino-venv/bin/activate; fi; "
        "export PYTHONPATH=\"${PYTHONPATH:-.}\"; "
        "mapfile -t TARGETS < <(find . -maxdepth 2 -type f -name '*.py' "
        "! -path './.rino-venv/*' ! -path './tests/*' ! -path './test/*' "
        "! -path './migrations/*' ! -path './vendor/*' ! -path './.git/*' "
        "| sed 's|^\\./||' | sort -u); "
        "if [ ${#TARGETS[@]} -eq 0 ]; then TARGETS=(.); fi; "
        "echo lint_targets=\"${TARGETS[*]}\"; "
        f"pylint --output-format=json \"${{TARGETS[@]}}\" > {PYLINT_FILE} "
        "2>/tmp/rino-pylint.err || true; "
        f"bandit -q -r -f json -o {BANDIT_FILE} \"${{TARGETS[@]}}\" "
        "2>/tmp/rino-bandit.err || true; "
        f"if [ ! -s {PYLINT_FILE} ]; then echo '[]' > {PYLINT_FILE}; fi; "
        f"if [ ! -s {BANDIT_FILE} ]; then echo '{{\"results\":[]}}' > {BANDIT_FILE}; fi; "
        f"echo pylint_bytes=$(wc -c < {PYLINT_FILE}); "
        f"echo bandit_bytes=$(wc -c < {BANDIT_FILE}); "
        "exit 0"
    )


def _git_rev_parse(src: Path) -> str | None:
    try:
        proc = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=src,
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        if proc.returncode == 0:
            return proc.stdout.strip() or None
    except Exception:
        return None
    return None


def _combine(stdout: str | None, stderr: str | None) -> str:
    parts = [p.strip() for p in (stdout or "", stderr or "") if p and p.strip()]
    return "\n".join(parts)


def _truncate(text: str) -> str:
    if len(text) <= MAX_LOG_CHARS:
        return text
    return text[: MAX_LOG_CHARS - 20] + "\n…[truncated]…"


def _redact_tokens(text: str) -> str:
    return re.sub(
        r"x-access-token:[^@\s]+@",
        "x-access-token:[redacted]@",
        text,
    )
