"""Reusable allowlisted auto-commit helpers for todo daemons."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping, Optional, Sequence

from .engine import CommandResult, run_command
from .git_utils import paths_from_git_status_porcelain, unique_normalized_paths


RunCommand = Callable[..., CommandResult]
StatusWriter = Callable[..., None]


@dataclass(frozen=True)
class AutoCommitConfig:
    """Configuration for committing validated daemon work."""

    repo_root: Path
    enabled: bool = False
    dry_run: bool = True
    required_branch: str = "main"
    allowed_prefixes: tuple[str, ...] = ()
    allowed_exact_paths: tuple[str, ...] = ()
    command_timeout_seconds: int = 300
    subject_prefix: str = "chore(todo-daemon):"
    user_name: str = "Todo Daemon"
    user_email: str = "todo-daemon@local"


def slugify(value: str, *, limit: int = 80) -> str:
    """Return a conservative slug for commit subjects and artifact stems."""

    import re

    slug = re.sub(r"[^A-Za-z0-9._-]+", "-", str(value or "")).strip("-").lower()
    return (slug or "daemon-work")[:limit]


def repo_relative_pathspec(path: Path, *, repo_root: Path) -> str:
    """Return ``path`` as a POSIX Git pathspec relative to ``repo_root`` when possible."""

    path = Path(path)
    if path.is_absolute():
        try:
            return path.relative_to(repo_root).as_posix()
        except ValueError:
            return path.as_posix()
    return path.as_posix()


def _normalized_pathspecs(paths: Sequence[str]) -> list[str]:
    return [
        path[2:] if path.startswith("./") else path
        for path in unique_normalized_paths(paths)
    ]


def safe_auto_commit_pathspecs(
    paths: Sequence[str],
    *,
    allowed_prefixes: Sequence[str] = (),
    allowed_exact_paths: Sequence[str] = (),
) -> list[str]:
    """Filter candidate pathspecs to an allowlisted daemon-owned scope."""

    prefixes = tuple(path.rstrip("/") for path in _normalized_pathspecs(allowed_prefixes) if path)
    exact_paths = frozenset(_normalized_pathspecs(allowed_exact_paths))
    safe: list[str] = []
    seen: set[str] = set()
    for normalized in _normalized_pathspecs(paths):
        if not normalized:
            continue
        if normalized.startswith("/") or ".." in Path(normalized).parts:
            continue
        allowed = normalized in exact_paths or any(
            normalized == prefix or normalized.startswith(prefix + "/")
            for prefix in prefixes
        )
        if allowed and normalized not in seen:
            seen.add(normalized)
            safe.append(normalized)
    return safe


def build_auto_commit_subject(
    *,
    target_task: str = "",
    summary: str = "",
    reason: str = "",
    subject_prefix: str = "chore(todo-daemon):",
    slug_limit: int = 54,
) -> str:
    """Build a short deterministic daemon commit subject."""

    source = summary or target_task or reason or "todo daemon work"
    prefix = str(subject_prefix or "").strip()
    if prefix and not prefix.endswith(" "):
        prefix += " "
    return f"{prefix}{slugify(source, limit=slug_limit).replace('-', ' ')}".strip()


def _command_timeout(config: AutoCommitConfig, cap: int) -> int:
    return min(cap, max(1, int(config.command_timeout_seconds)))


def auto_commit_paths(
    config: AutoCommitConfig,
    paths: Sequence[str],
    *,
    reason: str,
    target_task: str = "",
    summary: str = "",
    run_command_fn: RunCommand = run_command,
    write_status_fn: Optional[StatusWriter] = None,
) -> dict[str, Any]:
    """Commit dirty allowlisted paths and return a machine-readable result."""

    if config.dry_run or not config.enabled:
        return {"attempted": False, "committed": False, "skipped_reason": "auto_commit_disabled"}

    pathspecs = safe_auto_commit_pathspecs(
        paths,
        allowed_prefixes=config.allowed_prefixes,
        allowed_exact_paths=config.allowed_exact_paths,
    )
    if not pathspecs:
        return {"attempted": False, "committed": False, "skipped_reason": "no_safe_pathspecs"}

    branch = run_command_fn(
        ("git", "branch", "--show-current"),
        cwd=config.repo_root,
        timeout_seconds=_command_timeout(config, 60),
    )
    branch_name = branch.stdout.strip() if branch.ok else ""
    required_branch = str(config.required_branch or "").strip()
    if required_branch and branch_name != required_branch:
        return {
            "attempted": True,
            "committed": False,
            "skipped_reason": "wrong_branch",
            "branch": branch_name,
            "required_branch": required_branch,
        }

    status = run_command_fn(
        ("git", "status", "--porcelain", "--", *pathspecs),
        cwd=config.repo_root,
        timeout_seconds=_command_timeout(config, 60),
    )
    if not status.ok:
        return {
            "attempted": True,
            "committed": False,
            "skipped_reason": "status_failed",
            "branch": branch_name,
            "stderr": status.stderr[-1000:],
        }

    dirty_paths = safe_auto_commit_pathspecs(
        paths_from_git_status_porcelain(status.stdout),
        allowed_prefixes=config.allowed_prefixes,
        allowed_exact_paths=config.allowed_exact_paths,
    )
    if not dirty_paths:
        return {"attempted": True, "committed": False, "skipped_reason": "clean", "branch": branch_name}

    if write_status_fn is not None:
        write_status_fn(
            "auto_commit_started",
            auto_commit_reason=reason,
            auto_commit_paths=dirty_paths,
            selected_task=target_task,
        )

    add = run_command_fn(
        ("git", "add", "--", *dirty_paths),
        cwd=config.repo_root,
        timeout_seconds=_command_timeout(config, 120),
    )
    if not add.ok:
        return {
            "attempted": True,
            "committed": False,
            "skipped_reason": "add_failed",
            "branch": branch_name,
            "changed_files": dirty_paths,
            "stderr": add.stderr[-1000:],
        }

    staged = run_command_fn(
        ("git", "diff", "--cached", "--name-only", "--", *dirty_paths),
        cwd=config.repo_root,
        timeout_seconds=_command_timeout(config, 60),
    )
    staged_paths = (
        safe_auto_commit_pathspecs(
            staged.stdout.splitlines(),
            allowed_prefixes=config.allowed_prefixes,
            allowed_exact_paths=config.allowed_exact_paths,
        )
        if staged.ok
        else []
    )
    if not staged_paths:
        return {
            "attempted": True,
            "committed": False,
            "skipped_reason": "nothing_staged",
            "branch": branch_name,
            "changed_files": dirty_paths,
        }

    subject = build_auto_commit_subject(
        target_task=target_task,
        summary=summary,
        reason=reason,
        subject_prefix=config.subject_prefix,
    )
    body_lines = [
        f"Reason: {reason}",
        f"Target task: {target_task or 'unknown'}",
        "",
        "Committed by an unattended todo daemon after validation so autonomous work can continue.",
        "",
        "Files:",
        *[f"- {path}" for path in staged_paths],
    ]
    commit = run_command_fn(
        (
            "git",
            "-c",
            f"user.name={config.user_name}",
            "-c",
            f"user.email={config.user_email}",
            "commit",
            "-m",
            subject,
            "-m",
            "\n".join(body_lines),
            "--",
            *staged_paths,
        ),
        cwd=config.repo_root,
        timeout_seconds=_command_timeout(config, 180),
    )
    record: dict[str, Any] = {
        "attempted": True,
        "committed": commit.ok,
        "branch": branch_name,
        "changed_files": staged_paths,
        "subject": subject,
        "stdout": commit.stdout[-1000:],
        "stderr": commit.stderr[-1000:],
    }
    if not commit.ok:
        record["skipped_reason"] = "commit_failed"
    if write_status_fn is not None:
        write_status_fn("auto_commit_completed", auto_commit=record, selected_task=target_task)
    return record


def auto_commit_result_payload(result: Mapping[str, Any]) -> dict[str, Any]:
    """Return a JSON-serializable copy of an auto-commit result mapping."""

    return dict(result)
