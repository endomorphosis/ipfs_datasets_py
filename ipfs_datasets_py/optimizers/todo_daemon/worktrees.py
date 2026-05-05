"""Reusable Git worktree ownership and cleanup helpers for todo daemons."""

from __future__ import annotations

import json
import os
import re
import shutil
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping, Optional, Sequence

from .engine import CommandResult, run_command
from .git_utils import (
    git_worktree_paths_from_porcelain as _shared_git_worktree_paths_from_porcelain,
    paths_from_git_status_porcelain as _shared_paths_from_git_status_porcelain,
    untracked_paths_from_git_status_porcelain as _shared_untracked_paths_from_git_status_porcelain,
)


CommandRunner = Callable[..., CommandResult]
OwnerAlivePredicate = Callable[[int, Path, Path], bool]


def git_status_paths(stdout: str) -> list[str]:
    """Return paths from ``git status --porcelain`` output."""

    return _shared_paths_from_git_status_porcelain(stdout)


def untracked_paths_from_git_status(stdout: str) -> list[str]:
    """Return untracked paths from ``git status --porcelain`` output."""

    return _shared_untracked_paths_from_git_status_porcelain(stdout)


def git_worktree_paths_from_porcelain(stdout: str) -> list[Path]:
    """Return registered Git worktree paths from porcelain output."""

    return _shared_git_worktree_paths_from_porcelain(stdout)


def pid_is_alive(pid: int) -> bool:
    """Return whether ``pid`` appears live and signalable."""

    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def pid_command_line(pid: int) -> str:
    """Return a process command line from procfs when available."""

    try:
        raw = Path(f"/proc/{pid}/cmdline").read_bytes()
    except OSError:
        return ""
    return raw.replace(b"\0", b" ").decode("utf-8", errors="replace").strip()


def pid_looks_like_worktree_owner(
    pid: int,
    *,
    repo_root: Path,
    worktree_path: Path,
    daemon_process_fragment: str = "",
    daemon_repo_hint_fragment: str = "--repo-root",
    worker_process_fragment: str = "codex",
) -> bool:
    """Return whether a live process plausibly owns a daemon worktree."""

    if not pid_is_alive(pid):
        return False
    command_line = pid_command_line(pid)
    if not command_line:
        return True
    normalized_repo = str(repo_root.resolve())
    normalized_worktree = str(worktree_path.resolve())
    if daemon_process_fragment and daemon_process_fragment in command_line:
        return normalized_repo in command_line or daemon_repo_hint_fragment in command_line
    if worker_process_fragment and worker_process_fragment in command_line and normalized_worktree in command_line:
        return True
    return False


def owner_pid_from_worktree(path: Path, owner: Mapping[str, Any]) -> Optional[int]:
    """Return the owner pid from metadata or a trailing ``_<pid>`` worktree name."""

    try:
        pid = int(owner.get("pid") or 0)
    except (TypeError, ValueError):
        pid = 0
    if pid > 0:
        return pid
    match = re.search(r"_(\d+)$", path.name)
    if not match:
        return None
    try:
        return int(match.group(1))
    except ValueError:
        return None


def read_json_object(path: Path) -> dict[str, Any]:
    """Read a JSON object from disk, returning ``{}`` on missing or malformed input."""

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def write_worktree_owner_file(
    path: Path,
    *,
    schema: str,
    repo_root: Path,
    pid: Optional[int] = None,
    attempt: int = 0,
    extra: Optional[Mapping[str, Any]] = None,
) -> dict[str, Any]:
    """Write a reusable daemon worktree-owner metadata file."""

    payload: dict[str, Any] = {
        "schema": schema,
        "pid": os.getpid() if pid is None else int(pid),
        "attempt": int(attempt),
        "repo_root": str(repo_root),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "created_at_epoch": time.time(),
    }
    if extra:
        payload.update(dict(extra))
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return payload


def cleanup_stale_daemon_worktrees(
    *,
    repo_root: Path,
    worktree_root: Path,
    stale_after_seconds: int,
    owner_filename: str,
    patterns: Sequence[str] = ("cycle_*", "repair_*"),
    run_command_fn: CommandRunner = run_command,
    owner_alive: Optional[OwnerAlivePredicate] = None,
    now_epoch: Optional[float] = None,
) -> dict[str, Any]:
    """Remove daemon-created worktrees whose owner is gone and whose age is stale."""

    stale_after = max(1, int(stale_after_seconds))
    result: dict[str, Any] = {
        "valid": True,
        "worktree_root": str(worktree_root),
        "stale_after_seconds": stale_after,
        "patterns": list(patterns),
        "removed": [],
        "skipped": [],
        "errors": [],
    }
    prune_before = run_command_fn(
        ("git", "worktree", "prune", "--expire", "now"),
        cwd=repo_root,
        timeout_seconds=60,
    )
    result["prune_before"] = prune_before.compact(limit=12000)
    if not worktree_root.exists():
        return result

    root_resolved = worktree_root.resolve()
    list_result = run_command_fn(
        ("git", "worktree", "list", "--porcelain"),
        cwd=repo_root,
        timeout_seconds=60,
    )
    result["worktree_list"] = list_result.compact(limit=12000)
    registered_paths = {str(path) for path in git_worktree_paths_from_porcelain(list_result.stdout)}
    now = time.time() if now_epoch is None else float(now_epoch)

    candidates: list[Path] = []
    seen_candidates: set[Path] = set()
    for pattern in patterns:
        for candidate in worktree_root.glob(pattern):
            resolved_candidate = candidate.resolve()
            if resolved_candidate in seen_candidates:
                continue
            seen_candidates.add(resolved_candidate)
            candidates.append(candidate)

    for candidate in sorted(candidates):
        if not candidate.exists():
            continue
        try:
            resolved = candidate.resolve()
            if not resolved.is_relative_to(root_resolved):
                result["skipped"].append({"path": str(candidate), "reason": "outside_worktree_root"})
                continue
            if not candidate.is_dir():
                result["skipped"].append({"path": str(candidate), "reason": "not_directory"})
                continue
            owner = read_json_object(candidate / owner_filename)
            owner_pid = owner_pid_from_worktree(candidate, owner)
            owner_is_alive = bool(owner_pid and owner_alive is not None and owner_alive(owner_pid, repo_root, candidate))
            try:
                created_at = float(owner.get("created_at_epoch") or candidate.stat().st_mtime)
            except (OSError, TypeError, ValueError):
                created_at = candidate.stat().st_mtime
            age_seconds = max(0.0, now - created_at)
            if owner_is_alive:
                result["skipped"].append(
                    {
                        "path": str(candidate),
                        "reason": "owner_pid_alive",
                        "owner_pid": owner_pid,
                        "age_seconds": round(age_seconds, 3),
                    }
                )
                continue
            if age_seconds < stale_after:
                result["skipped"].append(
                    {
                        "path": str(candidate),
                        "reason": "not_stale_yet",
                        "owner_pid": owner_pid,
                        "age_seconds": round(age_seconds, 3),
                    }
                )
                continue

            registered = str(resolved) in registered_paths
            if registered:
                remove_result = run_command_fn(
                    ("git", "worktree", "remove", "--force", str(resolved)),
                    cwd=repo_root,
                    timeout_seconds=60,
                )
                if not remove_result.ok and candidate.exists():
                    shutil.rmtree(candidate, ignore_errors=True)
            else:
                shutil.rmtree(candidate, ignore_errors=True)
                remove_result = CommandResult(
                    ("shutil.rmtree", str(resolved)),
                    0 if not candidate.exists() else 1,
                    "",
                    "" if not candidate.exists() else "directory still exists after rmtree",
                )
            record = {
                "path": str(candidate),
                "registered": registered,
                "owner_pid": owner_pid,
                "age_seconds": round(age_seconds, 3),
                "remove": remove_result.compact(limit=12000),
            }
            if remove_result.ok:
                result["removed"].append(record)
            else:
                result["valid"] = False
                result["errors"].append(record)
        except Exception as exc:
            result["valid"] = False
            result["errors"].append({"path": str(candidate), "exception": f"{type(exc).__name__}: {exc}"})

    prune_after = run_command_fn(
        ("git", "worktree", "prune", "--expire", "now"),
        cwd=repo_root,
        timeout_seconds=60,
    )
    result["prune_after"] = prune_after.compact(limit=12000)
    if not prune_after.ok:
        result["valid"] = False
    return result
