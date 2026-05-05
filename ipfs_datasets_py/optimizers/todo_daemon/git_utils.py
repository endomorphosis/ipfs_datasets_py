"""Reusable Git parsing helpers for todo daemon proposal flows."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Sequence


def paths_from_git_status_porcelain(stdout: str) -> list[str]:
    """Return unique paths from plain ``git status --porcelain`` output."""

    paths: list[str] = []
    for line in str(stdout or "").splitlines():
        if len(line) < 3:
            continue
        path = line[3:].strip()
        if " -> " in path:
            path = path.rsplit(" -> ", 1)[1].strip()
        if path and path not in paths:
            paths.append(path)
    return paths


def untracked_paths_from_git_status_porcelain(stdout: str) -> list[str]:
    """Return unique untracked paths from plain ``git status --porcelain`` output."""

    paths: list[str] = []
    for line in str(stdout or "").splitlines():
        if not line.startswith("?? "):
            continue
        path = line[3:].strip()
        if " -> " in path:
            path = path.rsplit(" -> ", 1)[1].strip()
        if path and path not in paths:
            paths.append(path)
    return paths


def git_worktree_paths_from_porcelain(stdout: str) -> list[Path]:
    """Return worktree paths from ``git worktree list --porcelain`` output."""

    paths: list[Path] = []
    for line in str(stdout or "").splitlines():
        if not line.startswith("worktree "):
            continue
        path_text = line[len("worktree ") :].strip()
        if path_text:
            paths.append(Path(path_text).resolve())
    return paths


def paths_from_unified_diff(unified_diff: str) -> list[str]:
    """Return unique file paths touched by a Git-style unified diff."""

    paths: list[str] = []
    for match in re.finditer(r"^diff --git a/(.+?) b/(.+?)$", str(unified_diff or ""), flags=re.MULTILINE):
        for candidate in (match.group(1), match.group(2)):
            if candidate == "/dev/null":
                continue
            if candidate not in paths:
                paths.append(candidate)
    return paths


def _prefixed_paths(
    paths: Sequence[str],
    *,
    prefixes: Sequence[str],
    exclude_prefixes: Sequence[str] = (),
) -> list[str]:
    if not prefixes:
        return []
    return [
        path
        for path in paths
        if any(path.startswith(prefix) for prefix in prefixes)
        and not any(path.startswith(prefix) for prefix in exclude_prefixes)
    ]


def unified_diff_stats(
    unified_diff: str,
    *,
    test_file_prefixes: Sequence[str] = (),
    production_file_prefixes: Sequence[str] = (),
    production_exclude_prefixes: Sequence[str] = (),
) -> dict[str, Any]:
    """Return reusable changed-file and insertion/deletion statistics for a diff."""

    text = str(unified_diff or "")
    files = paths_from_unified_diff(text)
    insertions = 0
    deletions = 0
    per_file: list[dict[str, Any]] = []
    current_file: dict[str, Any] | None = None
    for line in text.splitlines():
        match = re.match(r"^diff --git a/(.+?) b/(.+?)$", line)
        if match:
            path = match.group(2) if match.group(2) != "/dev/null" else match.group(1)
            current_file = {
                "path": path,
                "insertions": 0,
                "deletions": 0,
                "deletion_heavy": False,
            }
            per_file.append(current_file)
            continue
        if line.startswith("+++") or line.startswith("---"):
            continue
        if line.startswith("+"):
            insertions += 1
            if current_file is not None:
                current_file["insertions"] = int(current_file["insertions"]) + 1
        elif line.startswith("-"):
            deletions += 1
            if current_file is not None:
                current_file["deletions"] = int(current_file["deletions"]) + 1
    for item in per_file:
        item["deletion_heavy"] = int(item["deletions"]) > int(item["insertions"]) and int(item["deletions"]) > 0
    deletion_heavy_files = [str(item["path"]) for item in per_file if item.get("deletion_heavy")]
    return {
        "files_changed": len(files),
        "insertions": insertions,
        "deletions": deletions,
        "changed_files": files,
        "deletion_heavy": deletions > insertions and deletions > 0,
        "deletion_heavy_files": deletion_heavy_files,
        "test_deletion_heavy_files": _prefixed_paths(
            deletion_heavy_files,
            prefixes=test_file_prefixes,
        ),
        "production_deletion_heavy_files": _prefixed_paths(
            deletion_heavy_files,
            prefixes=production_file_prefixes,
            exclude_prefixes=production_exclude_prefixes,
        ),
        "per_file": per_file,
    }
