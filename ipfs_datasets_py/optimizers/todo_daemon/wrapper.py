"""Reusable restart-wrapper launcher for todo daemon supervisors."""

from __future__ import annotations

import os
import shlex
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Optional, Sequence

from .core import pid_alive, process_args


@dataclass(frozen=True)
class RestartingWrapperLaunch:
    """Result from launching an unattended restart wrapper."""

    mode: str
    pid: int
    command_text: str


def quoted_env_assignments(env: Mapping[str, Any], keys: Sequence[str]) -> str:
    """Return shell-safe ``KEY=value`` assignments for selected environment keys."""

    parts: list[str] = []
    for key in keys:
        if key in env:
            parts.append(f"{key}={shlex.quote(str(env[key]))}")
    return " ".join(parts)


def build_restart_loop_command(
    command: Sequence[str],
    *,
    env: Optional[Mapping[str, Any]] = None,
    env_keys: Sequence[str] = (),
    restart_delay_seconds: int = 5,
    restart_message: str = "supervisor exited with code",
) -> str:
    """Build a shell restart loop for a supervisor command.

    This is intentionally generic: domain-specific lifecycle modules can pass
    their command, environment keys, delay, and message while sharing the same
    unattended wrapper behavior.
    """

    env_prefix = quoted_env_assignments(env or {}, env_keys)
    command_text = " ".join(shlex.quote(str(part)) for part in command)
    if env_prefix:
        command_text = f"{env_prefix} {command_text}"
    restart_delay = shlex.quote(str(int(restart_delay_seconds)))
    printf_format = shlex.quote(
        f"%s {str(restart_message)} %s; wrapper restarting in %ss\\n"
    )
    return (
        f"while true; do {command_text}; "
        "rc=$?; "
        f"printf {printf_format} "
        f"\"$(date -u +%Y-%m-%dT%H:%M:%SZ)\" \"$rc\" {restart_delay}; "
        f"sleep {restart_delay}; done"
    )


def _tmux_available() -> bool:
    return (
        subprocess.run(
            ("bash", "-lc", "command -v tmux >/dev/null 2>&1"),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        ).returncode
        == 0
    )


def _tmux_has_session(name: str) -> bool:
    return (
        subprocess.run(
            ("tmux", "has-session", "-t", name),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        ).returncode
        == 0
    )


def launch_restarting_wrapper(
    *,
    repo_root: Path,
    command: Sequence[str],
    out_path: Path,
    pid_path: Path,
    env: Optional[Mapping[str, str]] = None,
    env_keys: Sequence[str] = (),
    launch_mode: str = "nohup_loop",
    restart_delay_seconds: int = 5,
    restart_message: str = "supervisor exited with code",
    tmux_session_name: str = "",
) -> RestartingWrapperLaunch:
    """Launch a supervisor under an unattended restart loop."""

    launch_env = dict(os.environ)
    if env:
        launch_env.update({key: str(value) for key, value in env.items()})
    launch_env["REPO_ROOT"] = str(repo_root)
    command_text = build_restart_loop_command(
        command,
        env=launch_env,
        env_keys=env_keys,
        restart_delay_seconds=restart_delay_seconds,
        restart_message=restart_message,
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    pid_path.parent.mkdir(parents=True, exist_ok=True)

    if launch_mode == "tmux" and tmux_session_name and _tmux_available():
        if _tmux_has_session(tmux_session_name):
            subprocess.run(
                ("tmux", "kill-session", "-t", tmux_session_name),
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
            )
        result = subprocess.run(
            ("tmux", "new-session", "-d", "-s", tmux_session_name, "-c", str(repo_root), command_text),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
        if result.returncode == 0:
            pid_path.write_text("0\n", encoding="utf-8")
            return RestartingWrapperLaunch(mode="tmux", pid=0, command_text=command_text)

    out_handle = out_path.open("wb")
    process = subprocess.Popen(
        ("bash", "-lc", command_text),
        cwd=str(repo_root),
        env=launch_env,
        stdin=subprocess.DEVNULL,
        stdout=out_handle,
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )
    out_handle.close()
    pid_path.write_text(f"{process.pid}\n", encoding="utf-8")
    return RestartingWrapperLaunch(mode="nohup_loop", pid=int(process.pid), command_text=command_text)


def pid_matches_command_fragments(pid: Any, fragments: Sequence[str]) -> bool:
    """Return whether a live process command line contains every fragment."""

    try:
        pid_int = int(pid)
    except Exception:
        return False
    if not pid_alive(pid_int):
        return False
    args = process_args(pid_int)
    return all(fragment in args for fragment in fragments)
