"""Reusable LLM subprocess helpers for optimizer todo daemons."""

from __future__ import annotations

import os
import signal
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional, Sequence

from .engine import compact_message


@dataclass(frozen=True)
class LlmRouterInvocation:
    """Configuration for one isolated ``llm_router.generate_text`` call."""

    repo_root: Path
    model_name: str = "gpt-5.5"
    provider: Optional[str] = None
    allow_local_fallback: bool = False
    timeout_seconds: int = 300
    max_new_tokens: int = 2048
    max_prompt_chars: int = 60000
    temperature: float = 0.1
    backend_env_name: str = "TODO_DAEMON_LLM_BACKEND"
    backend_default: str = "llm_router"
    backend_label: str = "todo daemon LLM backend"
    env_prefix: str = "TODO_DAEMON_LLM"
    prompt_file_prefix: str = "todo-daemon-llm-prompt-"
    python_executable: str = "python3"
    timeout_grace_seconds: int = 30
    prompt_overage_allowance: str = "\n\n[truncated]\n"


_ACTIVE_LLM_PROCESS: Optional[subprocess.Popen[Any]] = None


def collect_descendant_pids(pid: int) -> list[int]:
    """Return all descendant pids for ``pid`` using ``pgrep -P`` recursion."""

    try:
        completed = subprocess.run(
            ["pgrep", "-P", str(pid)],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            check=False,
        )
    except OSError:
        return []
    descendants: list[int] = []
    for line in completed.stdout.splitlines():
        try:
            child = int(line.strip())
        except ValueError:
            continue
        descendants.append(child)
        descendants.extend(collect_descendant_pids(child))
    return descendants


def process_groups_for_family(root_pid: int) -> set[int]:
    """Return process groups owned by a process family rooted at ``root_pid``."""

    groups: set[int] = set()
    for pid in [root_pid, *collect_descendant_pids(root_pid)]:
        try:
            groups.add(os.getpgid(pid))
        except ProcessLookupError:
            continue
    return groups


def terminate_process_group(
    process: subprocess.Popen[Any],
    *,
    grace_seconds: float = 5.0,
) -> None:
    """Terminate a subprocess and descendant process groups when it owns a session."""

    if process.poll() is not None:
        return
    process_groups = process_groups_for_family(process.pid) or {process.pid}
    try:
        for pgid in process_groups:
            try:
                os.killpg(pgid, signal.SIGTERM)
            except ProcessLookupError:
                continue
            except PermissionError:
                continue
    except ProcessLookupError:
        pass
    try:
        process.communicate(timeout=grace_seconds)
        return
    except subprocess.TimeoutExpired:
        pass
    try:
        for pgid in process_groups:
            try:
                os.killpg(pgid, signal.SIGKILL)
            except ProcessLookupError:
                continue
            except PermissionError:
                continue
    except ProcessLookupError:
        pass
    try:
        process.communicate(timeout=grace_seconds)
    except subprocess.TimeoutExpired:
        pass


def _env_name(config: LlmRouterInvocation, suffix: str) -> str:
    return f"{config.env_prefix}_{suffix}"


def _llm_router_child_code(config: LlmRouterInvocation) -> str:
    prompt_file_env = _env_name(config, "PROMPT_FILE")
    model_env = _env_name(config, "MODEL_NAME")
    provider_env = _env_name(config, "PROVIDER")
    fallback_env = _env_name(config, "ALLOW_LOCAL_FALLBACK")
    timeout_env = _env_name(config, "TIMEOUT")
    max_tokens_env = _env_name(config, "MAX_NEW_TOKENS")
    temperature_env = _env_name(config, "TEMPERATURE")
    return f"""
import os
import pathlib
import sys

from ipfs_datasets_py import llm_router

prompt = pathlib.Path(os.environ[{prompt_file_env!r}]).read_text(encoding="utf-8")
provider = os.environ.get({provider_env!r}) or None
text = llm_router.generate_text(
    prompt,
    model_name=os.environ[{model_env!r}],
    provider=provider,
    allow_local_fallback=os.environ.get({fallback_env!r}) == "1",
    timeout=int(os.environ[{timeout_env!r}]),
    max_new_tokens=int(os.environ[{max_tokens_env!r}]),
    temperature=float(os.environ[{temperature_env!r}]),
)
sys.stdout.write("" if text is None else str(text))
"""


def call_llm_router(prompt: str, config: LlmRouterInvocation) -> str:
    """Call ``ipfs_datasets_py.llm_router.generate_text`` in an isolated child."""

    backend = os.environ.get(config.backend_env_name, config.backend_default)
    if backend != "llm_router":
        raise RuntimeError(f"Unsupported {config.backend_label} {backend!r}; expected 'llm_router'.")
    if len(prompt) > config.max_prompt_chars + len(config.prompt_overage_allowance):
        raise RuntimeError(
            f"LLM prompt exceeds configured budget before llm_router child launch: "
            f"{len(prompt)} > {config.max_prompt_chars}"
        )

    prompt_file: Optional[Path] = None
    completed: Optional[subprocess.CompletedProcess[str]] = None
    timeout_seconds = int(config.timeout_seconds) + int(config.timeout_grace_seconds)
    try:
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            delete=False,
            prefix=config.prompt_file_prefix,
            suffix=".txt",
        ) as handle:
            handle.write(prompt)
            prompt_file = Path(handle.name)
        env = os.environ.copy()
        env.update(
            {
                _env_name(config, "PROMPT_FILE"): str(prompt_file),
                _env_name(config, "MODEL_NAME"): config.model_name,
                _env_name(config, "PROVIDER"): config.provider or "",
                _env_name(config, "ALLOW_LOCAL_FALLBACK"): "1" if config.allow_local_fallback else "0",
                _env_name(config, "TIMEOUT"): str(config.timeout_seconds),
                _env_name(config, "MAX_NEW_TOKENS"): str(config.max_new_tokens),
                _env_name(config, "TEMPERATURE"): str(config.temperature),
            }
        )
        command = [config.python_executable, "-c", _llm_router_child_code(config)]
        process = subprocess.Popen(
            command,
            cwd=str(config.repo_root),
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env,
            start_new_session=True,
        )
        global _ACTIVE_LLM_PROCESS
        _ACTIVE_LLM_PROCESS = process
        try:
            stdout, stderr = process.communicate(timeout=timeout_seconds)
        except subprocess.TimeoutExpired as exc:
            terminate_process_group(process)
            raise RuntimeError(f"llm_router child timed out after {timeout_seconds} seconds") from exc
        finally:
            if _ACTIVE_LLM_PROCESS is process:
                _ACTIVE_LLM_PROCESS = None
        completed = subprocess.CompletedProcess(
            command,
            returncode=int(process.returncode or 0),
            stdout=stdout,
            stderr=stderr,
        )
    finally:
        if prompt_file is not None:
            try:
                prompt_file.unlink()
            except FileNotFoundError:
                pass
    if completed is None:
        raise RuntimeError("llm_router child did not produce a completed process result")
    if completed.returncode != 0:
        details = compact_message((completed.stdout or "") + " " + (completed.stderr or ""), limit=1200)
        raise RuntimeError(f"llm_router child exited with code {completed.returncode}: {details}")
    return completed.stdout


def active_llm_process() -> Optional[subprocess.Popen[Any]]:
    """Return the currently active LLM child process, if any."""

    return _ACTIVE_LLM_PROCESS


def terminate_active_llm_process(*, grace_seconds: float = 1.0) -> bool:
    """Terminate the active LLM child process, if one is running."""

    process = _ACTIVE_LLM_PROCESS
    if process is None or process.poll() is not None:
        return False
    terminate_process_group(process, grace_seconds=grace_seconds)
    return True


def handle_active_llm_signal(signum: int, _frame: object) -> None:
    """Signal handler that stops the active LLM child before exiting."""

    terminate_active_llm_process(grace_seconds=1.0)
    raise SystemExit(128 + signum)


def install_active_llm_signal_handlers(
    signals: Sequence[int] = (signal.SIGTERM, signal.SIGINT, signal.SIGHUP),
) -> None:
    """Install signal handlers that clean up the active LLM child process."""

    for signum in signals:
        signal.signal(signum, handle_active_llm_signal)
