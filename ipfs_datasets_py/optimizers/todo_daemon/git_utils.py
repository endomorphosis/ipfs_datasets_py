"""Reusable Git parsing helpers for todo daemon proposal flows."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Optional, Sequence


SNAPSHOT_ERROR_PREFIX = "__SNAPSHOT_ERROR__:"


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


def git_apply_commands(*, check: bool) -> list[tuple[str, list[str]]]:
    """Return increasingly tolerant ``git apply`` strategies for daemon patches."""

    check_flag = ["--check"] if check else []
    return [
        ("strict", ["git", "apply", *check_flag, "--recount", "-"]),
        (
            "whitespace_fix",
            ["git", "apply", *check_flag, "--recount", "--whitespace=fix", "-"],
        ),
        ("three_way", ["git", "apply", *check_flag, "--recount", "--3way", "-"]),
    ]


def git_apply_command_for_strategy(strategy: str, *, check: bool) -> list[str]:
    """Return the configured ``git apply`` command for ``strategy``."""

    commands = git_apply_commands(check=check)
    for candidate_strategy, command in commands:
        if candidate_strategy == strategy:
            return command
    return commands[0][1]


def git_apply_check_with_fallbacks(
    unified_diff: str,
    *,
    repo_root: Path,
    run_command_fn: Callable[..., Mapping[str, Any]],
    timeout: int = 30,
) -> dict[str, Any]:
    """Run ``git apply --check`` with reusable fallback strategies."""

    if not unified_diff.strip():
        return {"valid": False, "returncode": 1, "stdout": "", "stderr": "empty unified diff"}
    attempts: list[dict[str, Any]] = []
    for strategy, command in git_apply_commands(check=True):
        result = dict(
            run_command_fn(
                command,
                cwd=repo_root,
                input_text=unified_diff,
                timeout=timeout,
            )
        )
        result["apply_strategy"] = strategy
        attempts.append(result)
        if result.get("valid"):
            return {
                **result,
                "fallback_attempts": attempts,
                "strict_check": attempts[0],
            }
    stderr = "\n".join(
        f"[{item.get('apply_strategy')}] {str(item.get('stderr') or '').strip()}"
        for item in attempts
        if str(item.get("stderr") or "").strip()
    )
    final = dict(attempts[-1] if attempts else {})
    final.update(
        {
            "valid": False,
            "apply_strategy": "none",
            "fallback_attempts": attempts,
            "strict_check": attempts[0] if attempts else {},
            "stderr": stderr or str(final.get("stderr") or ""),
        }
    )
    return final


def git_apply_with_strategy(
    unified_diff: str,
    *,
    repo_root: Path,
    strategy: str,
    run_command_fn: Callable[..., Mapping[str, Any]],
    timeout: int = 30,
) -> dict[str, Any]:
    """Apply ``unified_diff`` with a named reusable ``git apply`` strategy."""

    result = dict(
        run_command_fn(
            git_apply_command_for_strategy(strategy, check=False),
            cwd=repo_root,
            input_text=unified_diff,
            timeout=timeout,
        )
    )
    result["apply_strategy"] = strategy
    return result


def snapshot_paths(repo_root: Path, paths: Iterable[str]) -> dict[str, Optional[str]]:
    """Snapshot UTF-8 file contents for repo-relative paths before risky edits."""

    snapshots: dict[str, Optional[str]] = {}
    for rel_path in unique_normalized_paths(paths):
        path = repo_root / rel_path
        try:
            snapshots[rel_path] = path.read_text(encoding="utf-8")
        except FileNotFoundError:
            snapshots[rel_path] = None
        except OSError as exc:
            snapshots[rel_path] = f"{SNAPSHOT_ERROR_PREFIX}{exc}"
    return snapshots


def snapshot_patch_paths(repo_root: Path, unified_diff: str) -> dict[str, Optional[str]]:
    """Snapshot the repo-relative paths touched by a unified diff."""

    return snapshot_paths(repo_root, paths_from_unified_diff(unified_diff))


def restore_path_snapshots(repo_root: Path, snapshots: Mapping[str, Optional[str]]) -> dict[str, Any]:
    """Restore files captured by :func:`snapshot_paths`."""

    errors: list[str] = []
    restored: list[str] = []
    for rel_path, content in snapshots.items():
        normalized = str(rel_path or "").replace("\\", "/").strip()
        if not normalized:
            continue
        path = repo_root / normalized
        try:
            if isinstance(content, str) and content.startswith(SNAPSHOT_ERROR_PREFIX):
                errors.append(f"{normalized}: {content}")
                continue
            if content is None:
                if path.exists():
                    path.unlink()
                    restored.append(normalized)
                continue
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
            restored.append(normalized)
        except OSError as exc:
            errors.append(f"{normalized}: {exc}")
    return {"valid": not errors, "restored": restored, "errors": errors}


def retained_change_summary(repo_root: Path, snapshots: Mapping[str, Optional[str]]) -> dict[str, Any]:
    """Summarize whether snapshotted files still differ after apply/rollback work."""

    changed_files: list[str] = []
    deleted_files: list[str] = []
    created_files: list[str] = []
    for rel_path, before in snapshots.items():
        normalized = str(rel_path or "").replace("\\", "/").strip()
        if not normalized or (isinstance(before, str) and before.startswith(SNAPSHOT_ERROR_PREFIX)):
            continue
        path = repo_root / normalized
        try:
            after: Optional[str] = path.read_text(encoding="utf-8")
        except FileNotFoundError:
            after = None
        except OSError:
            continue
        if before != after:
            changed_files.append(normalized)
            if before is None and after is not None:
                created_files.append(normalized)
            elif before is not None and after is None:
                deleted_files.append(normalized)
    return {
        "has_retained_changes": bool(changed_files),
        "changed_files": changed_files,
        "created_files": created_files,
        "deleted_files": deleted_files,
        "reason": "content_changed" if changed_files else "no_file_content_changed_after_apply",
    }


def unique_normalized_paths(paths: Iterable[str]) -> list[str]:
    """Return unique non-empty paths normalized to POSIX separators."""

    seen: set[str] = set()
    ordered: list[str] = []
    for path in paths:
        normalized = str(path or "").replace("\\", "/").strip()
        if normalized and normalized not in seen:
            seen.add(normalized)
            ordered.append(normalized)
    return ordered


def paths_from_file_edits(edits: Iterable[Mapping[str, Any]], *, path_key: str = "path") -> list[str]:
    """Return unique paths from complete-file edit records."""

    return unique_normalized_paths(str(edit.get(path_key) or "") for edit in edits if isinstance(edit, Mapping))


def paths_from_patch_and_file_edits(patch: str, edits: Iterable[Mapping[str, Any]]) -> list[str]:
    """Return unique paths from file replacements followed by unified-diff paths."""

    return unique_normalized_paths([*paths_from_file_edits(edits), *paths_from_unified_diff(patch)])


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
