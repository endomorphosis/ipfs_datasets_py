"""Reusable shell-wrapper rendering helpers for todo-daemon lifecycle commands."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Mapping, Sequence


_SAFE_RELATIVE_EXPR = re.compile(r"^[./A-Za-z0-9_-]+$")
_SAFE_COMMAND_PART = re.compile(r"^[A-Za-z0-9_.:/@%+=,-]+$")


@dataclass(frozen=True)
class LifecycleWrapperSpec:
    """Declarative shape for a thin shell wrapper around the package dispatcher."""

    daemon: str
    command: str
    repo_root_ancestor: str
    pythonpath_expr: str
    module: str = "ipfs_datasets_py.optimizers.todo_daemon"
    python_executable: str = "python3"
    env_defaults: Mapping[str, str] = field(
        default_factory=lambda: {
            "IPFS_DATASETS_PY_ENABLE_IPFS_ACCELERATE": "0",
            "IPFS_DATASETS_PY_MINIMAL_IMPORTS": "1",
        }
    )
    compatibility_markers: Sequence[str] = ()


def _require_safe_shell_token(value: str, *, label: str) -> str:
    if not value or not _SAFE_COMMAND_PART.fullmatch(value):
        raise ValueError(f"unsafe {label}: {value!r}")
    return value


def _require_safe_relative_expr(value: str, *, label: str) -> str:
    if not value or not _SAFE_RELATIVE_EXPR.fullmatch(value):
        raise ValueError(f"unsafe {label}: {value!r}")
    return value


def lifecycle_wrapper_core_lines(spec: LifecycleWrapperSpec) -> tuple[str, ...]:
    """Return the required shell lines for a lifecycle wrapper."""

    daemon = _require_safe_shell_token(spec.daemon, label="daemon")
    command = _require_safe_shell_token(spec.command, label="command")
    module = _require_safe_shell_token(spec.module, label="module")
    python_executable = _require_safe_shell_token(spec.python_executable, label="python executable")
    repo_root_ancestor = _require_safe_relative_expr(spec.repo_root_ancestor, label="repo-root ancestor")
    lines = [
        'SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"',
        f'REPO_ROOT="${{REPO_ROOT:-$(cd "$SCRIPT_DIR/{repo_root_ancestor}" && pwd)}}"',
        "export REPO_ROOT",
    ]
    for name, default in spec.env_defaults.items():
        _require_safe_shell_token(str(name), label="environment name")
        _require_safe_shell_token(str(default), label=f"{name} default")
        lines.append(f'export {name}="${{{name}:-{default}}}"')
    lines.extend(
        [
            f'export PYTHONPATH="{spec.pythonpath_expr}"',
            'cd "$REPO_ROOT" || exit 2',
            f"exec {python_executable} -m {module} {daemon} {command} \"$@\"",
        ]
    )
    return tuple(lines)


def render_lifecycle_wrapper(spec: LifecycleWrapperSpec) -> str:
    """Render a complete bash lifecycle wrapper for a package-dispatched daemon."""

    lines = ["#!/usr/bin/env bash", "set -uo pipefail", ""]
    core = list(lifecycle_wrapper_core_lines(spec))
    lines.extend(core[:3])
    lines.extend(core[3 : 3 + len(spec.env_defaults)])
    lines.append(core[3 + len(spec.env_defaults)])
    if spec.compatibility_markers:
        lines.append("")
        lines.extend(f"# {marker}" for marker in spec.compatibility_markers)
    lines.append("")
    lines.extend(core[-2:])
    return "\n".join(lines) + "\n"


def lifecycle_wrapper_payload(spec: LifecycleWrapperSpec) -> dict[str, object]:
    """Return a machine-readable wrapper description for docs/tests."""

    return {
        "daemon": spec.daemon,
        "command": spec.command,
        "repo_root_ancestor": spec.repo_root_ancestor,
        "pythonpath_expr": spec.pythonpath_expr,
        "module": spec.module,
        "python_executable": spec.python_executable,
        "env_defaults": dict(spec.env_defaults),
        "compatibility_markers": list(spec.compatibility_markers),
        "core_lines": list(lifecycle_wrapper_core_lines(spec)),
    }
