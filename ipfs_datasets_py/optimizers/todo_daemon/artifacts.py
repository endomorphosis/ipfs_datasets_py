"""Reusable artifact persistence helpers for todo daemons."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Optional

from .core import write_json
from .engine import (
    Proposal,
    append_jsonl,
    compact_message,
    normalize_string_items,
    run_command,
    utc_now,
    workspace_artifact_payload,
)


DEFAULT_ACCEPTED_WORK_LEDGER_FILENAME = "accepted-work.jsonl"
ACCEPTED_WORK_LEDGER_SCHEMA_VERSION = 2
DEFAULT_ACCEPTED_WORK_LOG_TITLE = "Todo Daemon Accepted Work"
DEFAULT_ACCEPTED_WORK_LOG_DESCRIPTION = (
    "This file is append-only daemon evidence for validated work that changed daemon-owned files."
)


@dataclass(frozen=True)
class WorkSidecarPaths:
    """Sidecar files written for one accepted or failed daemon work item."""

    manifest: Path
    workspace: Path
    diff: Path
    stat: Path


@dataclass(frozen=True)
class AcceptedWorkEvidencePaths:
    """Legacy accepted-work evidence files written for one accepted daemon result."""

    manifest: Path
    diff: Path
    stat: Path


@dataclass(frozen=True)
class AcceptedWorkPersistenceResult:
    """Artifacts and ledger row written for one accepted daemon work item."""

    artifacts: Optional[WorkSidecarPaths]
    ledger_entry: dict[str, Any]
    ledger_path: Path


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


def artifact_string_items(values: Iterable[Any]) -> list[str]:
    """Return non-empty string/Path artifact list items."""

    return [
        item
        for item in normalize_string_items(list(values), accepted_scalar_types=(str, Path))
        if item
    ]


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

    payload = workspace_artifact_payload(
        proposal,
        transport=transport,
        promoted=False,
        reason=reason,
    )
    payload["promoted"] = False
    return payload


def accepted_work_workspace_payload(proposal: Proposal, *, transport: str) -> dict[str, Any]:
    """Build the standard accepted-work workspace payload."""

    payload = workspace_artifact_payload(
        proposal,
        transport=transport,
        promoted=True,
    )
    payload["promoted"] = True
    return payload


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


def compact_validation_results(validation_results: Iterable[Any]) -> list[dict[str, Any]]:
    """Return compact validation-result payloads from mappings or result objects."""

    compacted: list[dict[str, Any]] = []
    for result in validation_results:
        payload: Any
        compact = getattr(result, "compact", None)
        if callable(compact):
            payload = compact()
        else:
            payload = result
        if isinstance(payload, Mapping):
            compacted.append(compact_validation_result(dict(payload)))
    return compacted


def validation_command_summaries(validation_results: Iterable[Any]) -> list[str]:
    """Return human-readable validation command summaries for markdown evidence."""

    summaries: list[str] = []
    for item in compact_validation_results(validation_results):
        command = item.get("command", [])
        parts = [str(part) for part in command if str(part)]
        if not parts:
            continue
        summaries.append(f"`{' '.join(parts)}` -> `{item.get('returncode')}`")
    return summaries


def accepted_work_markdown_header(
    *,
    title: str = DEFAULT_ACCEPTED_WORK_LOG_TITLE,
    description: str = DEFAULT_ACCEPTED_WORK_LOG_DESCRIPTION,
) -> str:
    """Return the standard header for append-only accepted-work markdown logs."""

    normalized_title = str(title or DEFAULT_ACCEPTED_WORK_LOG_TITLE).strip().lstrip("#").strip()
    normalized_description = str(description or DEFAULT_ACCEPTED_WORK_LOG_DESCRIPTION).strip()
    return f"# {normalized_title}\n\n{normalized_description}\n\n"


def accepted_work_markdown_entry(
    *,
    timestamp: str,
    target_task: str,
    summary: str,
    impact: str = "",
    changed_files: Iterable[str],
    evidence_paths: Iterable[str] = (),
    validation_results: Iterable[Any] = (),
) -> str:
    """Return one append-only accepted-work markdown entry."""

    changed_file_list = artifact_string_items(changed_files)
    evidence_path_list = artifact_string_items(evidence_paths)
    validation_commands = validation_command_summaries(validation_results)
    entry = [
        f"## {timestamp}",
        "",
        f"- Target: `{target_task or 'unknown'}`",
        f"- Summary: {summary or 'No summary'}",
    ]
    if impact:
        entry.append(f"- Impact: {impact}")
    entry.append(f"- Changed files: {', '.join(f'`{file}`' for file in changed_file_list)}")
    if evidence_path_list:
        entry.append(f"- Evidence: {', '.join(f'`{item}`' for item in evidence_path_list)}")
    if validation_commands:
        entry.append(f"- Validation: {', '.join(validation_commands)}")
    entry.append("")
    return "\n".join(entry) + "\n"


def append_accepted_work_markdown_log(
    path: Path,
    entry: str,
    *,
    title: str = DEFAULT_ACCEPTED_WORK_LOG_TITLE,
    description: str = DEFAULT_ACCEPTED_WORK_LOG_DESCRIPTION,
) -> None:
    """Append one entry to an accepted-work markdown log, creating the header if needed."""

    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.write_text(
            accepted_work_markdown_header(title=title, description=description),
            encoding="utf-8",
        )
    with path.open("a", encoding="utf-8") as handle:
        handle.write(entry.rstrip())
        handle.write("\n\n")


def accepted_work_evidence_manifest(
    *,
    timestamp: str,
    target_task: str,
    summary: str,
    impact: str,
    changed_files: Iterable[str],
    validation_results: Iterable[Any],
    diff_stat: str = "",
    diff_available: bool = False,
) -> dict[str, Any]:
    """Build the compact manifest for accepted-work evidence sidecars."""

    validation = compact_validation_results(validation_results)
    return {
        "timestamp": timestamp,
        "target_task": target_task,
        "summary": summary,
        "impact": impact,
        "changed_files": artifact_string_items(changed_files),
        "validation": validation,
        "diff_stat": diff_stat,
        "diff_available": bool(diff_available),
    }


def write_accepted_work_evidence_artifacts(
    *,
    root: Path,
    repo_root: Path,
    artifact: Mapping[str, Any],
    changed_files: Iterable[str],
    run_command_fn: Callable[..., Any] = run_command,
    command_timeout_seconds: int = 120,
    now: Any = None,
) -> list[str]:
    """Write manifest, diff, and stat evidence for accepted daemon work."""

    changed_file_list = artifact_string_items(changed_files)
    if not changed_file_list:
        return []
    root.mkdir(parents=True, exist_ok=True)
    base = timestamped_artifact_base(
        root,
        summary=str(artifact.get("summary") or artifact.get("target_task") or "accepted-work"),
        fallback="accepted-work",
        now=now,
    )
    timestamp = base.name.split("-", 1)[0]
    diff = run_command_fn(
        ("git", "diff", "--", *changed_file_list),
        cwd=repo_root,
        timeout_seconds=command_timeout_seconds,
    )
    diff_stat = run_command_fn(
        ("git", "diff", "--stat", "--", *changed_file_list),
        cwd=repo_root,
        timeout_seconds=command_timeout_seconds,
    )
    manifest = accepted_work_evidence_manifest(
        timestamp=timestamp,
        target_task=str(artifact.get("target_task") or ""),
        summary=str(artifact.get("summary") or ""),
        impact=str(artifact.get("impact") or ""),
        changed_files=changed_file_list,
        validation_results=artifact.get("validation_results", []),
        diff_stat=diff_stat.stdout if diff_stat.ok else "",
        diff_available=bool(diff.ok and diff.stdout.strip()),
    )

    paths = AcceptedWorkEvidencePaths(
        manifest=Path(str(base) + ".json"),
        diff=Path(str(base) + ".diff"),
        stat=Path(str(base) + ".stat.txt"),
    )
    write_json(paths.manifest, manifest)
    paths.diff.write_text(diff.stdout if diff.ok else "", encoding="utf-8")
    paths.stat.write_text(diff_stat.stdout if diff_stat.ok else "", encoding="utf-8")
    return [
        as_repo_path(paths.manifest, repo_root),
        as_repo_path(paths.diff, repo_root),
        as_repo_path(paths.stat, repo_root),
    ]


def build_accepted_work_ledger_entry(
    *,
    repo_root: Path,
    target_task: str,
    summary: str,
    impact: str,
    changed_files: Iterable[str],
    transport: str,
    artifacts: Optional[WorkSidecarPaths],
    validation_results: Iterable[Any],
    diff_text: str = "",
    promotion_verified: bool = False,
    promotion_errors: Optional[Iterable[str]] = None,
    ledger_path: Optional[Path] = None,
    created_at: str | None = None,
    ledger_filename: str = DEFAULT_ACCEPTED_WORK_LEDGER_FILENAME,
) -> dict[str, Any]:
    """Build a stable accepted-work ledger entry."""

    compact_results = compact_validation_results(validation_results)
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


def build_scoped_accepted_work_ledger_entry(
    *,
    repo_root: Path,
    accepted_dir: Path,
    target_task: str,
    summary: str,
    impact: str,
    changed_files: Iterable[str],
    transport: str,
    artifacts: Optional[WorkSidecarPaths],
    validation_results: Iterable[Any],
    diff_text: str = "",
    promotion_verified: bool = False,
    promotion_errors: Optional[Iterable[str]] = None,
    created_at: str | None = None,
    ledger_filename: str = DEFAULT_ACCEPTED_WORK_LEDGER_FILENAME,
) -> dict[str, Any]:
    """Build an accepted-work ledger entry scoped to a daemon artifact directory."""

    resolved_accepted_dir = accepted_dir if accepted_dir.is_absolute() else repo_root / accepted_dir
    return build_accepted_work_ledger_entry(
        repo_root=repo_root,
        target_task=target_task,
        summary=summary,
        impact=impact,
        changed_files=changed_files,
        transport=transport,
        artifacts=artifacts,
        validation_results=validation_results,
        diff_text=diff_text,
        promotion_verified=promotion_verified,
        promotion_errors=promotion_errors,
        ledger_path=resolved_accepted_dir / ledger_filename,
        created_at=created_at,
        ledger_filename=ledger_filename,
    )


def build_proposal_accepted_work_ledger_entry(
    *,
    repo_root: Path,
    accepted_dir: Path,
    proposal: Proposal,
    transport: str,
    artifacts: Optional[WorkSidecarPaths],
    diff_text: str = "",
    ledger_filename: str = DEFAULT_ACCEPTED_WORK_LEDGER_FILENAME,
    created_at: str | None = None,
) -> dict[str, Any]:
    """Build a scoped accepted-work ledger entry from a daemon proposal."""

    return build_scoped_accepted_work_ledger_entry(
        repo_root=repo_root,
        accepted_dir=accepted_dir,
        target_task=proposal.target_task,
        summary=proposal.summary,
        impact=proposal.impact,
        changed_files=proposal.changed_files,
        transport=transport,
        artifacts=artifacts,
        validation_results=proposal.validation_results,
        diff_text=diff_text,
        promotion_verified=proposal.promotion_verified,
        promotion_errors=proposal.promotion_errors,
        created_at=created_at,
        ledger_filename=ledger_filename,
    )


def append_accepted_work_ledger(
    accepted_dir: Path,
    entry: dict[str, Any],
    *,
    filename: str = DEFAULT_ACCEPTED_WORK_LEDGER_FILENAME,
) -> Path:
    """Append one JSON object to a daemon accepted-work ledger."""

    return append_jsonl_ledger(accepted_dir, entry, filename=filename)


def append_jsonl_ledger(directory: Path, entry: dict[str, Any], *, filename: str) -> Path:
    """Append one JSON object to a daemon artifact ledger."""

    ledger_path = directory / filename
    append_jsonl(ledger_path, entry)
    return ledger_path


def resolve_artifact_directory(directory: Path, *, repo_root: Optional[Path] = None) -> Path:
    """Resolve a daemon artifact directory against ``repo_root`` when it is relative."""

    path = Path(directory)
    if path.is_absolute() or repo_root is None:
        return path
    return Path(repo_root) / path


def persist_proposal_accepted_work(
    *,
    repo_root: Path,
    accepted_dir: Path,
    proposal: Proposal,
    diff_text: str,
    transport: str = "direct",
    write_sidecars_enabled: bool = False,
    ledger_filename: str = DEFAULT_ACCEPTED_WORK_LEDGER_FILENAME,
) -> AcceptedWorkPersistenceResult:
    """Persist accepted proposal evidence and append the accepted-work ledger."""

    accepted_dir = resolve_artifact_directory(accepted_dir, repo_root=repo_root)
    accepted_dir.mkdir(parents=True, exist_ok=True)
    artifacts: Optional[WorkSidecarPaths] = None
    if write_sidecars_enabled:
        base = timestamped_artifact_base(
            accepted_dir,
            summary=proposal.summary,
            fallback="accepted-work",
        )
        artifacts = write_work_sidecars(
            base=base,
            manifest=accepted_work_manifest(proposal, transport=transport),
            workspace=accepted_work_workspace_payload(proposal, transport=transport),
            diff_text=diff_text,
            changed_files=proposal.changed_files,
        )
    entry = build_proposal_accepted_work_ledger_entry(
        repo_root=repo_root,
        accepted_dir=accepted_dir,
        proposal=proposal,
        transport=transport,
        artifacts=artifacts,
        diff_text=diff_text,
        ledger_filename=ledger_filename,
    )
    ledger_path = append_accepted_work_ledger(accepted_dir, entry, filename=ledger_filename)
    return AcceptedWorkPersistenceResult(
        artifacts=artifacts,
        ledger_entry=entry,
        ledger_path=ledger_path,
    )


def persist_proposal_failed_work(
    *,
    failed_dir: Path,
    proposal: Proposal,
    diff_text: str,
    reason: str,
    transport: str = "direct",
    repo_root: Optional[Path] = None,
) -> WorkSidecarPaths:
    """Persist failed proposal sidecars for one daemon work item."""

    failed_dir = resolve_artifact_directory(failed_dir, repo_root=repo_root)
    failed_dir.mkdir(parents=True, exist_ok=True)
    base = timestamped_artifact_base(
        failed_dir,
        summary=proposal.summary or reason,
        fallback="failed-work",
        reason=reason,
    )
    return write_work_sidecars(
        base=base,
        manifest=failed_work_manifest(proposal, reason=reason, transport=transport),
        workspace=failed_work_workspace_payload(proposal, reason=reason, transport=transport),
        diff_text=diff_text,
        changed_files=proposal.changed_files,
    )
