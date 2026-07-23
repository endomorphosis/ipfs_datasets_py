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


@dataclass(frozen=True)
class LifecycleWrapperScriptSpec:
    """Repository path plus rendering spec for one maintained shell wrapper."""

    path: str
    wrapper: LifecycleWrapperSpec


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


def lifecycle_wrapper_script_payload(spec: LifecycleWrapperScriptSpec) -> dict[str, object]:
    """Return a machine-readable wrapper script description."""

    payload = lifecycle_wrapper_payload(spec.wrapper)
    payload["path"] = spec.path
    return payload


def missing_lifecycle_wrapper_core_lines(
    script_text: str,
    spec: LifecycleWrapperSpec,
) -> tuple[str, ...]:
    """Return required wrapper core lines missing from ``script_text``."""

    return tuple(line for line in lifecycle_wrapper_core_lines(spec) if line not in script_text)


def lifecycle_wrapper_matches_rendered(script_text: str, spec: LifecycleWrapperSpec) -> bool:
    """Return whether ``script_text`` exactly matches the rendered wrapper."""

    return script_text == render_lifecycle_wrapper(spec)


def default_lifecycle_wrapper_script_specs() -> tuple[LifecycleWrapperScriptSpec, ...]:
    """Return the maintained legacy shell wrappers dispatched by this package."""

    logic_port_pythonpath = "$REPO_ROOT/ipfs_datasets_py${PYTHONPATH:+:$PYTHONPATH}"
    legal_parser_pythonpath = "$REPO_ROOT${PYTHONPATH:+:$PYTHONPATH}"
    return (
        LifecycleWrapperScriptSpec(
            path="scripts/ops/legal_data/check_logic_port_daemon.sh",
            wrapper=LifecycleWrapperSpec(
                daemon="logic-port",
                command="check",
                repo_root_ancestor="../../../..",
                pythonpath_expr=logic_port_pythonpath,
                compatibility_markers=(
                    "Compatibility markers for older tests/docs that inspected this shell body:",
                    '"proposal_transport": status.get("proposal_transport")',
                    '"worktree_edit_timeout_seconds": status.get("worktree_edit_timeout_seconds")',
                    '"worktree_stale_after_seconds": status.get("worktree_stale_after_seconds")',
                    '"worktree_codex_sandbox": status.get("worktree_codex_sandbox")',
                    '"worktree_root": status.get("worktree_root")',
                    '"worktree_repair_attempts": status.get("worktree_repair_attempts")',
                    '"auto_commit": status.get("auto_commit")',
                    '"auto_commit_startup_dirty": status.get("auto_commit_startup_dirty")',
                    '"auto_commit_branch": status.get("auto_commit_branch")',
                ),
            ),
        ),
        LifecycleWrapperScriptSpec(
            path="scripts/ops/legal_data/ensure_logic_port_daemon.sh",
            wrapper=LifecycleWrapperSpec(
                daemon="logic-port",
                command="ensure",
                repo_root_ancestor="../../../..",
                pythonpath_expr=logic_port_pythonpath,
                compatibility_markers=(
                    "Compatibility markers for older maintenance checks that grepped this file:",
                    'launch_mode=\\"tmux\\"',
                    'SUPERVISOR_AGENTIC_STARTUP_FAILURE_MAINTENANCE="${SUPERVISOR_AGENTIC_STARTUP_FAILURE_MAINTENANCE:-1}"',
                    'SUPERVISOR_AGENTIC_STARTUP_FAILURE_MAINTENANCE="$SUPERVISOR_AGENTIC_STARTUP_FAILURE_MAINTENANCE"',
                    '"agentic_startup_failure_maintenance": startup_failure_maintenance',
                ),
            ),
        ),
        LifecycleWrapperScriptSpec(
            path="scripts/ops/legal_data/stop_logic_port_daemon.sh",
            wrapper=LifecycleWrapperSpec(
                daemon="logic-port",
                command="stop",
                repo_root_ancestor="../../../..",
                pythonpath_expr=logic_port_pythonpath,
                compatibility_markers=(
                    "Compatibility marker for supervisor maintenance validation:",
                    "pid_has_non_logic_port_daemon_ancestor",
                ),
            ),
        ),
        LifecycleWrapperScriptSpec(
            path="scripts/ops/legal_data/check_legal_parser_optimizer_daemon.sh",
            wrapper=LifecycleWrapperSpec(
                daemon="legal-parser",
                command="check",
                repo_root_ancestor="../../..",
                pythonpath_expr=legal_parser_pythonpath,
                compatibility_markers=(
                    "Compatibility markers for older tests/docs that inspected this shell body.",
                    "The implementation now lives in ipfs_datasets_py.optimizers.todo_daemon.legal_parser.",
                    '"proposal_transport": current.get("proposal_transport")',
                    '"worktree_edit_timeout_seconds": current.get("worktree_edit_timeout_seconds")',
                    '"worktree_stale_after_seconds": current.get("worktree_stale_after_seconds")',
                    '"worktree_codex_sandbox": current.get("worktree_codex_sandbox")',
                    '"repair_failed_tests_before_rollback": current.get("repair_failed_tests_before_rollback")',
                    '"failed_test_repair_attempts": current.get("failed_test_repair_attempts")',
                    '"worktree_no_child_stall_seconds": worktree_no_child_threshold',
                    '"worktree_phase_worker_status": worktree_worker_status',
                    "alive = bool(supervisor_alive and ((daemon_alive and daemon_fresh) or maintenance_fresh))",
                    "maintenance_running",
                    '"formal_logic_goal"',
                    "pid_is_legal_parser_wrapper",
                    "progress_dirty_legal_parser_targets_diff_summary",
                    '"agentic_acceptance_stall_cycles"',
                    '"ensure_status"',
                    '"ensure_wrapper_pid_alive"',
                ),
            ),
        ),
        LifecycleWrapperScriptSpec(
            path="scripts/ops/legal_data/ensure_legal_parser_optimizer_daemon.sh",
            wrapper=LifecycleWrapperSpec(
                daemon="legal-parser",
                command="ensure",
                repo_root_ancestor="../../..",
                pythonpath_expr=legal_parser_pythonpath,
                compatibility_markers=(
                    "Compatibility markers for older tests/docs that inspected this shell body.",
                    "The implementation now lives in ipfs_datasets_py.optimizers.todo_daemon.legal_parser.",
                    "legal_parser_daemon_ensure.status.json",
                    "legal_parser_daemon_supervisor_wrapper.pid",
                    "check_legal_parser_optimizer_daemon.sh",
                    "run_legal_parser_optimizer_daemon.sh",
                    'ENSURE_LAUNCH_MODE="${ENSURE_LAUNCH_MODE:-nohup_loop}"',
                    "while true; do MODEL_NAME=",
                    "legal-parser supervisor exited with code",
                    "cleanup_stale_supervisor_artifacts()",
                    "pid_is_legal_parser_supervisor()",
                    "pid_is_legal_parser_wrapper()",
                    "wrapper_alive()",
                    'pid_is_legal_parser_wrapper "$pid"',
                    "wrapped_existing_supervisor",
                    "wrapper_recovered_supervisor",
                    "SUPERVISOR_LOCK_PATH",
                    "tmux new-session",
                    "wait_for_supervisor",
                    '"schema": "ipfs_datasets_py.legal_parser_daemon.ensure"',
                    '"supervisor_pid_alive"',
                    '"wrapper_pid_alive"',
                ),
            ),
        ),
        LifecycleWrapperScriptSpec(
            path="scripts/ops/legal_data/stop_legal_parser_optimizer_daemon.sh",
            wrapper=LifecycleWrapperSpec(
                daemon="legal-parser",
                command="stop",
                repo_root_ancestor="../../..",
                pythonpath_expr=legal_parser_pythonpath,
            ),
        ),
    )
