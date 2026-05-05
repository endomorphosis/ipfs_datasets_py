"""Reusable artifact persistence helpers for todo daemons."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Optional

from .engine import Proposal, compact_message, utc_now, workspace_artifact_payload


DEFAULT_ACCEPTED_WORK_LEDGER_FILENAME = "accepted-work.jsonl"
ACCEPTED_WORK_LEDGER_SCHEMA_VERSION = 2


@dataclass(frozen=True)
class WorkSidecarPaths:
    """Sidecar files written for one accepted or failed daemon work item."""

    manifest: Path
    workspace: Path
    diff: Path
    stat: Path


def slugify_artifact_name(value: str, *, fallback: str, limit: int = 80) -> str:
    """Return a filesystem-friendly slug for daemon artifact filenames."""

    slug = re.sub(r"[^A-Za-z0-9._-]+", "-", str(value or "").lower()).strip("-")
    return (slug[:limit].strip("-") or fallback)


def timestamped_artifact_base(
    directory: Path,
    *,
    summary: str,
    fallback: str,
    reason: str = "",
    now: Any = None,
) -> Path:
    """Return the standard timestamped artifact base path."""

    stamp = (now or utc_now)().replace("-", "").replace(":", "")
    stamp = stamp.removesuffix("Z").split(".", 1)[0] + "Z"
    slug = slugify_artifact_name(summary, fallback=fallback)
    prefix = f"{reason}-" if reason else ""
    return directory / f"{stamp}-{prefix}{slug}"


def sidecar_paths(base: Path) -> WorkSidecarPaths:
    """Return standard sidecar paths for an artifact base path."""

    return WorkSidecarPaths(
        manifest=base.with_suffix(".json"),
        workspace=base.with_suffix(".workspace.json"),
        diff=base.with_suffix(".diff.txt"),
        stat=base.with_suffix(".stat.txt"),
    )


def write_json(path: Path, payload: dict[str, Any]) -> None:
    """Write pretty JSON with the todo-daemon standard formatting."""

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def write_work_sidecars(
    *,
    base: Path,
    manifest: dict[str, Any],
    workspace: dict[str, Any],
    diff_text: str,
    changed_files: Iterable[str],
) -> WorkSidecarPaths:
    """Write manifest, workspace, diff, and stat sidecars for one work item."""

    paths = sidecar_paths(base)
    write_json(paths.manifest, manifest)
    write_json(paths.workspace, workspace)
    paths.diff.parent.mkdir(parents=True, exist_ok=True)
    paths.diff.write_text(diff_text, encoding="utf-8")
    paths.stat.write_text("\n".join(str(path) for path in changed_files) + "\n", encoding="utf-8")
    return paths


def failed_work_manifest(
    proposal: Proposal,
    *,
    reason: str,
    transport: str,
) -> dict[str, Any]:
    """Build the standard failed-work manifest payload."""

    return {
        "created_at": utc_now(),
        "artifact_kind": "failed_ephemeral_workspace",
        "reason": reason,
        "target_task": proposal.target_task,
        "summary": proposal.summary,
        "impact": proposal.impact,
        "files": [item.get("path", "") for item in proposal.files],
        "changed_files": proposal.changed_files,
        "errors": [compact_message(error) for error in proposal.errors],
        "transport": transport,
        "validation_results": [result.compact() for result in proposal.validation_results],
    }


def accepted_work_manifest(
    proposal: Proposal,
    *,
    transport: str,
) -> dict[str, Any]:
    """Build the standard accepted-work sidecar manifest payload."""

    return {
        "created_at": utc_now(),
        "artifact_kind": "accepted_ephemeral_workspace",
        "target_task": proposal.target_task,
        "summary": proposal.summary,
        "impact": proposal.impact,
        "changed_files": proposal.changed_files,
        "transport": transport,
        "promotion_verified": proposal.promotion_verified,
        "validation_results": [result.compact() for result in proposal.validation_results],
    }


def failed_work_workspace_payload(proposal: Proposal, *, reason: str, transport: str) -> dict[str, Any]:
    """Build the standard failed-work workspace payload."""

    return workspace_artifact_payload(
        proposal,
        transport=transport,
        promoted=False,
        reason=reason,
    )


def accepted_work_workspace_payload(proposal: Proposal, *, transport: str) -> dict[str, Any]:
    """Build the standard accepted-work workspace payload."""

    return workspace_artifact_payload(
        proposal,
        transport=transport,
        promoted=True,
    )


def as_repo_path(path: Path, repo_root: Path) -> str:
    """Return ``path`` relative to ``repo_root`` when possible."""

    resolved_root = repo_root.resolve()
    resolved_path = path.resolve()
    try:
        return resolved_path.relative_to(resolved_root).as_posix()
    except ValueError:
        return path.as_posix()


def compact_validation_result(result: dict[str, Any]) -> dict[str, Any]:
    """Return the compact validation result stored in accepted-work ledgers."""

    command = result.get("command", [])
    if not isinstance(command, list):
        command = []
    returncode = result.get("returncode", 0)
    try:
        returncode = int(returncode)
    except (TypeError, ValueError):
        returncode = 1
    return {
        "command": [str(part) for part in command],
        "returncode": returncode,
    }


def build_accepted_work_ledger_entry(
    *,
    repo_root: Path,
    target_task: str,
    summary: str,
    impact: str,
    changed_files: Iterable[str],
    transport: str,
    artifacts: Optional[WorkSidecarPaths],
    validation_results: Iterable[dict[str, Any]],
    diff_text: str = "",
    promotion_verified: bool = False,
    promotion_errors: Optional[Iterable[str]] = None,
    ledger_path: Optional[Path] = None,
    created_at: str | None = None,
    ledger_filename: str = DEFAULT_ACCEPTED_WORK_LEDGER_FILENAME,
) -> dict[str, Any]:
    """Build a stable accepted-work ledger entry."""

    compact_results = [compact_validation_result(result) for result in validation_results]
    if artifacts is None:
        artifact_payload = {
            "mode": "ledger_only",
            "ledger": as_repo_path(
                ledger_path or repo_root / ".daemon" / "accepted-work" / ledger_filename,
                repo_root,
            ),
        }
    else:
        artifact_payload = {
            "mode": "sidecars",
            "manifest": as_repo_path(artifacts.manifest, repo_root),
            "workspace": as_repo_path(artifacts.workspace, repo_root),
            "diff": as_repo_path(artifacts.diff, repo_root),
            "stat": as_repo_path(artifacts.stat, repo_root),
        }
    return {
        "schema_version": ACCEPTED_WORK_LEDGER_SCHEMA_VERSION,
        "created_at": created_at or utc_now(),
        "target_task": str(target_task),
        "summary": str(summary),
        "impact": str(impact),
        "changed_files": sorted(str(path) for path in changed_files),
        "transport": str(transport),
        "artifacts": artifact_payload,
        "diff": {
            "sha256": hashlib.sha256(diff_text.encode("utf-8")).hexdigest(),
            "line_count": len(diff_text.splitlines()),
        },
        "promotion": {
            "verified": bool(promotion_verified),
            "errors": [str(error) for error in (promotion_errors or [])],
        },
        "validation_results": compact_results,
        "validation_passed": bool(compact_results) and all(result["returncode"] == 0 for result in compact_results),
    }


def append_jsonl_ledger(directory: Path, entry: dict[str, Any], *, filename: str) -> Path:
    """Append one JSON object to a daemon artifact ledger."""

    directory.mkdir(parents=True, exist_ok=True)
    ledger_path = directory / filename
    with ledger_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry, sort_keys=True) + "\n")
    return ledger_path
