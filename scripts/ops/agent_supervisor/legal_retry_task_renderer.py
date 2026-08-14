#!/usr/bin/env python3
"""Project-scoped repairs for strict legal configured-board runtimes.

The pinned generic accelerator deliberately supports small taskboards, while
the legal boards require a richer, file-ownership-aware task contract.  This
module adapts retry-budget follow-ups only for the Open US Law namespace and
fixes compatibility with checkout leases that identify a linked worktree by
``worktree_root``/``repository_id`` instead of the legacy ``repo_root`` field.

The entry-point wrappers attest these exact bytes before installing either
repair.  Nothing in this module launches a process or mutates a taskboard.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shlex
from collections.abc import Callable, Mapping
from pathlib import Path, PurePosixPath
from typing import Any


OPEN_US_LAW_BOARD_NAMESPACE = "open-us-law-reindex-v1"
RETRY_REPAIR_SCHEMA = (
    "ipfs_accelerate_py.agent_supervisor.retry-budget-repair@1"
)
_RETRY_FUNCTIONS = {
    "validation_retry_task_block": "validation",
    "implementation_retry_task_block": "implementation",
    "merge_retry_task_block": "merge",
}


def _one_line(value: Any) -> str:
    """Return a task-parser-safe single physical line."""

    return re.sub(r"\s+", " ", str(value or "")).strip()


def _csv(value: Any) -> list[str]:
    return [
        item.strip()
        for item in str(value or "").split(",")
        if item.strip() and item.strip().lower() not in {"none", "n/a"}
    ]


def _safe_relative_path(value: str) -> bool:
    if not value or "\x00" in value or "\\" in value:
        return False
    path = PurePosixPath(value)
    return (
        not path.is_absolute()
        and ".." not in path.parts
        and path.as_posix() == value
    )


def _task_metadata(task: Any) -> dict[str, str]:
    raw = getattr(task, "metadata", {}) or {}
    if not isinstance(raw, Mapping):
        return {}
    return {
        _one_line(key).lower().replace("_", " "): _one_line(value)
        for key, value in raw.items()
    }


def _parse_rendered_block(text: str) -> tuple[str, dict[str, str]]:
    heading = ""
    fields: dict[str, str] = {}
    for line in str(text or "").splitlines():
        if not heading and line.startswith("## "):
            heading = line.strip()
            continue
        if line.startswith("- ") and ":" in line:
            key, value = line[2:].split(":", 1)
            fields[key.strip().lower()] = _one_line(value)
    return heading, fields


def _lane(task_id: str) -> int:
    return int(hashlib.sha256(task_id.encode("utf-8")).hexdigest()[:8], 16) % 4


def _discovery_relative(path: Any, repo_root: Path) -> str:
    try:
        candidate = Path(path).resolve()
        return candidate.relative_to(repo_root.resolve()).as_posix()
    except (OSError, RuntimeError, TypeError, ValueError):
        return ""


def _repair_report_path(task_id: str, source_task_id: str, kind: str) -> str:
    return (
        "docs/reports/open_us_law_reindex/retry/"
        f"{task_id.lower()}-{source_task_id.lower()}-{kind}.json"
    )


def _render_open_us_law_retry(
    rendered: str,
    *,
    task_id: str,
    source_task: Any,
    failure_kind: str,
    discovery_path: Any,
    repo_root: Path,
) -> str:
    """Enrich one generic retry task without weakening its real validation."""

    metadata = _task_metadata(source_task)
    namespace = _one_line(
        metadata.get("board namespace")
        or getattr(source_task, "board_namespace", "")
    )
    if namespace != OPEN_US_LAW_BOARD_NAMESPACE:
        return rendered

    heading, fields = _parse_rendered_block(rendered)
    source_task_id = _one_line(getattr(source_task, "task_id", ""))
    goal_id = metadata.get("goal id", "")
    if not heading or not source_task_id or not goal_id:
        # Fail closed: the strict board validator must reject an incomplete
        # generic block instead of this adapter inventing authority.
        return rendered

    report_path = _repair_report_path(task_id, source_task_id, failure_kind)
    outputs: list[str] = []
    for value in [
        *(getattr(source_task, "outputs", []) or []),
        *_csv(fields.get("validation failure paths", "")),
        report_path,
    ]:
        normalized = _one_line(value)
        if _safe_relative_path(normalized) and normalized not in outputs:
            outputs.append(normalized)

    source_validation = [
        _one_line(value)
        for value in (getattr(source_task, "validation", []) or [])
        if _one_line(value)
    ]
    validation = fields.get("validation", "")
    discovery_relative = _discovery_relative(discovery_path, repo_root)
    if (
        not validation
        or "validation_pre_dispatch:" in validation
        or "workspace/agent-supervisor/" in validation
        or (discovery_relative and discovery_relative in validation)
        or str(discovery_path or "") in validation
    ) and source_validation:
        validation = "; ".join(source_validation)
    report_gate = f"test -f {shlex.quote(report_path)}"
    validation = f"{validation}; {report_gate}" if validation else report_gate

    depends_on = fields.get("depends on") or ", ".join(
        getattr(source_task, "depends_on", []) or []
    )
    acceptance = fields.get("acceptance", "")
    acceptance = (
        f"{acceptance} Write {report_path} with the discovery digest, exact "
        "commands, current task identity, changed paths, and passing validation "
        "evidence; file existence or a fixture alone never repairs live evidence."
    ).strip()
    discovery_field = discovery_relative or _one_line(discovery_path)

    lines = [
        heading,
        "",
        "- Status: todo",
        "- Completion: manual",
        "- Is schedulable: true",
        "- Review only: false",
        f"- Priority: {metadata.get('priority') or fields.get('priority') or 'P1'}",
        "- Track: retry-repair",
        f"- Depends on: {_one_line(depends_on)}",
        f"- Goal id: {goal_id}",
        f"- Outputs: {', '.join(outputs)}",
        f"- Validation: {_one_line(validation)}",
        f"- Board namespace: {OPEN_US_LAW_BOARD_NAMESPACE}",
        f"- Bundle: retry-{source_task_id.lower()}",
        f"- Parallel lane: {_lane(task_id)}",
        f"- Resource class: {metadata.get('resource class') or 'cpu-network'}",
        f"- Token class: {metadata.get('token class') or 'medium'}",
        f"- Estimated tokens: {metadata.get('estimated tokens') or '24000'}",
        f"- Predicted files: {', '.join(outputs)}",
        "- Allow concurrent with: Any file-disjoint ready task assigned by strict SHA-256 sharding; the retry source remains runtime-fenced until this repair completes.",
        f"- Conflict policy: This repair may overlap only its strategy-fenced source {source_task_id}; all other output ownership remains dependency ordered.",
        f"- Preconditions: Retry discovery evidence for {source_task_id} exists and its current source dependencies are complete.",
        f"- Effects: Repair the {failure_kind} blocker with durable tracked evidence and release exactly {source_task_id} after successful validation.",
        f"- Acceptance: {_one_line(acceptance)}",
        f"- Generated by: {RETRY_REPAIR_SCHEMA}",
        f"- Retry repair source: {source_task_id}",
        f"- Retry failure kind: {failure_kind}",
        "- Canonical board task: false",
        f"- Discovery evidence: {discovery_field}",
        "",
    ]
    return "\n".join(lines)


def owned_generated_repair_lock(
    metadata: Any,
    *,
    expected_repo_root: Path,
    current_pid: int,
    repository_matches: Callable[[Mapping[str, Any], Path], bool | None],
) -> bool:
    """Return true only for this process's conclusively matching repair lease."""

    if not isinstance(metadata, Mapping):
        return False
    try:
        lock_pid = int(metadata.get("pid") or 0)
    except (TypeError, ValueError):
        return False
    if (
        lock_pid != current_pid
        or _one_line(metadata.get("kind")) != "merge"
        or _one_line(metadata.get("operation")) != "generated_dirty_repair"
    ):
        return False
    # ``None`` is indeterminate and remains a blocker.  Only a conclusive
    # physical-repository match may bypass the incumbent lease check.
    return repository_matches(metadata, expected_repo_root) is True


def install_legal_runtime_repairs(
    backlog_refinery: Any,
    checkout_lock: Any,
    *,
    repo_root: Path,
) -> None:
    """Install idempotent project adapters into the attested paired runtime."""

    if getattr(backlog_refinery, "_legal_retry_renderer_installed", False):
        return

    for function_name, failure_kind in _RETRY_FUNCTIONS.items():
        original = getattr(backlog_refinery, function_name)

        def wrapper(
            *args: Any,
            __original: Callable[..., str] = original,
            __kind: str = failure_kind,
            **kwargs: Any,
        ) -> str:
            rendered = __original(*args, **kwargs)
            return _render_open_us_law_retry(
                rendered,
                task_id=_one_line(kwargs.get("task_id")),
                source_task=kwargs.get("source_task"),
                failure_kind=__kind,
                discovery_path=kwargs.get("discovery_path"),
                repo_root=repo_root,
            )

        wrapper.__name__ = function_name
        wrapper.__doc__ = getattr(original, "__doc__", None)
        setattr(backlog_refinery, function_name, wrapper)

    original_blocker = backlog_refinery.generated_dirty_commit_blocker

    def generated_dirty_commit_blocker(repo: Path) -> dict[str, Any] | None:
        merge_head = backlog_refinery.git_merge_head_path(repo)
        if merge_head is not None and merge_head.exists():
            return original_blocker(repo)
        lock_path = backlog_refinery.checkout_mutation_lock_path(repo)
        if lock_path.exists():
            try:
                metadata = json.loads(lock_path.read_text(encoding="utf-8"))
            except (OSError, TypeError, ValueError):
                metadata = None
            if owned_generated_repair_lock(
                metadata,
                expected_repo_root=repo,
                current_pid=os.getpid(),
                repository_matches=checkout_lock.checkout_lock_repository_matches,
            ):
                return None
        return original_blocker(repo)

    generated_dirty_commit_blocker.__name__ = (
        "generated_dirty_commit_blocker"
    )
    backlog_refinery.generated_dirty_commit_blocker = (
        generated_dirty_commit_blocker
    )
    backlog_refinery._legal_retry_renderer_installed = True


__all__ = [
    "OPEN_US_LAW_BOARD_NAMESPACE",
    "RETRY_REPAIR_SCHEMA",
    "install_legal_runtime_repairs",
    "owned_generated_repair_lock",
]
