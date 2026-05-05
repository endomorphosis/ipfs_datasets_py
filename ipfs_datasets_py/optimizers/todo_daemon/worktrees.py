"""Reusable Git worktree ownership and cleanup helpers for todo daemons."""

from __future__ import annotations

import json
import os
import re
import shutil
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterator, Mapping, Optional, Sequence

from .engine import CommandResult, run_command
from .git_utils import (
    git_worktree_paths_from_porcelain as _shared_git_worktree_paths_from_porcelain,
    paths_from_git_status_porcelain as _shared_paths_from_git_status_porcelain,
    untracked_paths_from_git_status_porcelain as _shared_untracked_paths_from_git_status_porcelain,
)


CommandRunner = Callable[..., CommandResult]
OwnerAlivePredicate = Callable[[int, Path, Path], bool]
TraceResultFormatter = Callable[[CommandResult, int], Any]
WorktreeOwnerWriter = Callable[[Path], None]


def _run_command_with_timeout(
    run_command_fn: CommandRunner,
    command: Sequence[str],
    *,
    cwd: Path,
    timeout_seconds: int,
) -> CommandResult:
    normalized_timeout = max(1, int(timeout_seconds))
    try:
        return run_command_fn(tuple(command), cwd=cwd, timeout_seconds=normalized_timeout)
    except TypeError as exc:
        if "timeout_seconds" not in str(exc):
            raise
        return run_command_fn(tuple(command), cwd=cwd, timeout=normalized_timeout)


def _trace_key(label: Optional[str], name: str) -> str:
    return name if not label else f"{label}_{name}"


def _compact_trace_result(result: CommandResult, limit: int) -> dict[str, Any]:
    return result.compact(limit=limit)


def git_status_paths(stdout: str) -> list[str]:
    """Return paths from ``git status --porcelain`` output."""

    return _shared_paths_from_git_status_porcelain(stdout)


def untracked_paths_from_git_status(stdout: str) -> list[str]:
    """Return untracked paths from ``git status --porcelain`` output."""

    return _shared_untracked_paths_from_git_status_porcelain(stdout)


def git_worktree_paths_from_porcelain(stdout: str) -> list[Path]:
    """Return registered Git worktree paths from porcelain output."""

    return _shared_git_worktree_paths_from_porcelain(stdout)


def normalize_worktree_path(path: str | Path) -> str:
    """Return a slash-normalized worktree-relative path string."""

    return str(path).replace("\\", "/").strip()


def unique_worktree_paths(paths: Sequence[str | Path]) -> list[str]:
    """Return non-empty worktree paths, slash-normalized and deduplicated in order."""

    ordered: list[str] = []
    seen: set[str] = set()
    for path in paths:
        normalized = normalize_worktree_path(path)
        if normalized and normalized not in seen:
            seen.add(normalized)
            ordered.append(normalized)
    return ordered


def repo_relative_worktree_path(path: str | Path, *, repo_root: Path) -> str:
    """Return ``path`` relative to ``repo_root`` when possible, normalized for Git pathspecs."""

    candidate = Path(path)
    absolute_candidate = candidate if candidate.is_absolute() else repo_root / candidate
    try:
        return absolute_candidate.relative_to(repo_root).as_posix()
    except ValueError:
        return normalize_worktree_path(candidate.as_posix())


def worktree_path_allowed(path: str | Path, *, allowed_prefixes: Sequence[str]) -> bool:
    """Return whether a normalized worktree path is inside one of the allowed prefixes."""

    normalized = normalize_worktree_path(path)
    return any(normalized.startswith(prefix) for prefix in allowed_prefixes)


def resolve_worktree_file_edit_path(
    root: Path,
    path: str | Path,
    *,
    allowed_prefixes: Sequence[str],
    error_prefix: str = "Worktree edit",
) -> Path:
    """Resolve a complete-file edit path under ``root`` after traversal and allowlist checks."""

    raw_path = str(path)
    normalized = normalize_worktree_path(raw_path)
    if not normalized or normalized.startswith("/") or ".." in Path(normalized).parts:
        raise ValueError(f"{error_prefix} path is unsafe: {raw_path!r}")
    if not worktree_path_allowed(normalized, allowed_prefixes=allowed_prefixes):
        raise ValueError(f"{error_prefix} path is outside daemon allowlist: {raw_path!r}")
    return root / normalized


def disallowed_worktree_paths(
    paths: Sequence[str | Path],
    *,
    allowed_prefixes: Sequence[str],
    ignored_paths: Sequence[str | Path] = (),
) -> list[str]:
    """Return changed worktree paths outside the daemon's write allowlist."""

    ignored = set(unique_worktree_paths(ignored_paths))
    disallowed: list[str] = []
    for path in unique_worktree_paths(paths):
        if path in ignored:
            continue
        if worktree_path_allowed(path, allowed_prefixes=allowed_prefixes):
            continue
        disallowed.append(path)
    return disallowed


def dirty_worktree_paths(
    *,
    repo_root: Path,
    paths: Sequence[str | Path],
    timeout_seconds: int = 60,
    run_command_fn: CommandRunner = run_command,
) -> list[str]:
    """Return dirty Git status paths for a normalized path subset."""

    normalized_paths = unique_worktree_paths(paths)
    if not normalized_paths:
        return []
    status = _run_command_with_timeout(
        run_command_fn,
        ("git", "status", "--porcelain", "--", *normalized_paths),
        cwd=repo_root,
        timeout_seconds=timeout_seconds,
    )
    if not status.ok:
        return []
    return git_status_paths(status.stdout)


def worktree_diff(
    *,
    worktree_path: Path,
    paths: Sequence[str | Path],
    raw_trace: Optional[dict[str, Any]] = None,
    label: str = "worktree",
    timeout_seconds: int = 60,
    run_command_fn: CommandRunner = run_command,
    trace_result_formatter: TraceResultFormatter = _compact_trace_result,
) -> str:
    """Return a binary Git diff for a normalized worktree path subset.

    Untracked files are staged with intent-to-add before diffing so callers can
    harvest new complete-file changes without accepting the whole worktree.
    """

    normalized_paths = unique_worktree_paths(paths)
    if not normalized_paths:
        if raw_trace is not None:
            raw_trace[_trace_key(label, "status")] = {"skipped": True, "reason": "no_paths"}
            raw_trace[_trace_key(label, "untracked_paths")] = []
            raw_trace[_trace_key(label, "git_diff")] = {"skipped": True, "reason": "no_paths"}
        return ""

    status_result = _run_command_with_timeout(
        run_command_fn,
        ("git", "status", "--porcelain", "--", *normalized_paths),
        cwd=worktree_path,
        timeout_seconds=timeout_seconds,
    )
    if raw_trace is not None:
        raw_trace[_trace_key(label, "status")] = trace_result_formatter(status_result, 12000)

    untracked_paths = untracked_paths_from_git_status(status_result.stdout)
    if raw_trace is not None:
        raw_trace[_trace_key(label, "untracked_paths")] = untracked_paths

    if untracked_paths:
        add_intent = _run_command_with_timeout(
            run_command_fn,
            ("git", "add", "-N", "--", *untracked_paths),
            cwd=worktree_path,
            timeout_seconds=timeout_seconds,
        )
        if raw_trace is not None:
            raw_trace[_trace_key(label, "git_add_intent_to_add")] = trace_result_formatter(
                add_intent,
                12000,
            )

    diff_result = _run_command_with_timeout(
        run_command_fn,
        ("git", "diff", "--binary", "--", *normalized_paths),
        cwd=worktree_path,
        timeout_seconds=timeout_seconds,
    )
    if raw_trace is not None:
        raw_trace[_trace_key(label, "git_diff")] = trace_result_formatter(diff_result, 20000)
    return diff_result.stdout if diff_result.ok else ""


def worktree_file_edits(
    worktree_path: Path,
    changed_files: Sequence[str | Path],
    *,
    allowed_prefixes: Sequence[str],
) -> list[dict[str, str]]:
    """Read complete UTF-8 file edits from an isolated worktree for allowed paths."""

    edits: list[dict[str, str]] = []
    for path_text in unique_worktree_paths(changed_files):
        if not worktree_path_allowed(path_text, allowed_prefixes=allowed_prefixes):
            continue
        path = worktree_path / path_text
        if not path.exists() or not path.is_file():
            continue
        try:
            content = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        edits.append({"path": path_text, "content": content})
    return edits


def write_worktree_file_edits_to_root(
    root: Path,
    edits: Sequence[Mapping[str, Any]],
    *,
    allowed_prefixes: Sequence[str],
    error_prefix: str = "Worktree edit",
) -> None:
    """Write complete file edits into ``root`` after allowlist and traversal checks."""

    for edit in edits:
        path = resolve_worktree_file_edit_path(
            root,
            str(edit.get("path", "")),
            allowed_prefixes=allowed_prefixes,
            error_prefix=error_prefix,
        )
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(str(edit.get("content", "")), encoding="utf-8")


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


@dataclass
class GitWorktreeSession:
    """State for a managed detached Git worktree lifecycle."""

    repo_root: Path
    path: Path
    metadata_rel: str
    owner_rel: str
    raw_trace: dict[str, Any] = field(default_factory=dict)
    add_result: Optional[CommandResult] = None

    @property
    def ready(self) -> bool:
        """Return whether the detached worktree was created successfully."""

        return bool(self.add_result and self.add_result.ok)


@contextmanager
def managed_git_worktree(
    *,
    repo_root: Path,
    worktree_path: Path,
    metadata_rel: str,
    owner_rel: str,
    trace_context: Optional[Mapping[str, Any]] = None,
    run_command_fn: CommandRunner = run_command,
    owner_writer: Optional[WorktreeOwnerWriter] = None,
    add_timeout_seconds: int = 60,
    remove_timeout_seconds: int = 60,
    prune_on_exit: bool = True,
) -> Iterator[GitWorktreeSession]:
    """Create a detached Git worktree and always remove/prune it on exit."""

    worktree_path.parent.mkdir(parents=True, exist_ok=True)
    raw_trace: dict[str, Any] = dict(trace_context or {})
    raw_trace.update(
        {
            "worktree_path": str(worktree_path),
            "metadata_path": metadata_rel,
            "owner_path": owner_rel,
        }
    )
    session = GitWorktreeSession(
        repo_root=repo_root,
        path=worktree_path,
        metadata_rel=metadata_rel,
        owner_rel=owner_rel,
        raw_trace=raw_trace,
    )
    try:
        add_result = run_command_fn(
            ("git", "worktree", "add", "--detach", str(worktree_path), "HEAD"),
            cwd=repo_root,
            timeout_seconds=max(1, int(add_timeout_seconds)),
        )
        session.add_result = add_result
        raw_trace["worktree_add"] = add_result.compact(limit=12000)
        if add_result.ok and owner_writer is not None:
            owner_writer(worktree_path / owner_rel)
        yield session
    finally:
        remove_result = run_command_fn(
            ("git", "worktree", "remove", "--force", str(worktree_path)),
            cwd=repo_root,
            timeout_seconds=max(1, int(remove_timeout_seconds)),
        )
        raw_trace["worktree_remove"] = remove_result.compact(limit=12000)
        if not remove_result.ok and worktree_path.exists():
            shutil.rmtree(worktree_path, ignore_errors=True)
        if prune_on_exit:
            prune_result = run_command_fn(
                ("git", "worktree", "prune", "--expire", "now"),
                cwd=repo_root,
                timeout_seconds=max(1, int(remove_timeout_seconds)),
            )
            raw_trace["worktree_prune_after_remove"] = prune_result.compact(limit=12000)


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
