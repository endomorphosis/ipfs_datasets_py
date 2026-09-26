"""Upload autoformal discrepancy todos to Hugging Face.

Parquet plus a supervisor markdown board are the release artifacts. JSONL is
not written. Dry-run planning never contacts a write endpoint.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Mapping, Sequence

from ipfs_datasets_py.huggingface.publication_profile import (
    HuggingFacePublicationProfile,
    autoformal_todo_publication_profile,
)
from ipfs_datasets_py.logic.autoformal.supervisor_todo import (
    BOARD_NAMESPACE,
    huggingface_todo_locator,
    render_supervisor_board,
    time_management,
    validate_supervisor_board,
)


PACKAGE_SCHEMA = "uscode-autoformal-todo-package/v1"
POINTER_SCHEMA = "ipfs_datasets_py/autoformal-todo-release-pointer/v1"
TODOS_NAME = "todos.parquet"
BOARD_NAME = "board.md"
LOCATOR_NAME = "locator.json"
MANIFEST_NAME = "release-manifest.json"
POINTER_NAME = "pointer.json"


class AutoformalTodoError(ValueError):
    """Unsafe or incomplete autoformal Hugging Face todo package."""


def _json(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode("utf-8") + b"\n"


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _descriptor(path: Path, relative: str) -> dict[str, Any]:
    payload = path.read_bytes()
    return {
        "path": relative,
        "relative_path": relative,
        "sha256": _sha(payload),
        "size_bytes": len(payload),
    }


def _parquet_rows(tasks: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    rows = []
    for task in tasks:
        rows.append(
            {
                "acceptance": str(task.get("acceptance") or ""),
                "board_namespace": str(task.get("board_namespace") or BOARD_NAMESPACE),
                "canonical_citation": str(task.get("canonical_citation") or ""),
                "decompiled": str(task.get("decompiled") or ""),
                "dropped": json.dumps(list(task.get("dropped") or []), ensure_ascii=True, sort_keys=True),
                "entry_cid": str(task.get("entry_cid") or ""),
                "estimated_tokens": int(task.get("estimated_tokens") or 0),
                "estimated_validation_seconds": int(task.get("estimated_validation_seconds") or 0),
                "failure_mode": str(task.get("failure_mode") or ""),
                "goal_id": str(task.get("goal_id") or ""),
                "legal_id": str(task.get("legal_id") or ""),
                "preserve": json.dumps(list(task.get("preserve") or []), ensure_ascii=True, sort_keys=True),
                "priority": str(task.get("priority") or "P2"),
                "replace": json.dumps(list(task.get("replace") or []), ensure_ascii=True, sort_keys=True),
                "resource_class": str(task.get("resource_class") or ""),
                "source_span_id": str(task.get("source_span_id") or ""),
                "source_text": str(task.get("source_text") or ""),
                "status": str(task.get("status") or "todo"),
                "task_id": str(task.get("task_id") or ""),
                "title": str(task.get("title") or ""),
                "token_class": str(task.get("token_class") or ""),
                "track": str(task.get("track") or ""),
                "work_kind": str(task.get("work_kind") or ""),
                "dispatch_status": str(task.get("dispatch_status") or ""),
                "allowed_edit_paths": json.dumps(
                    list(task.get("allowed_edit_paths") or []), ensure_ascii=True, sort_keys=True
                ),
                "packet_sha256": str(task.get("packet_sha256") or ""),
                "training_job_template": str(
                    ((task.get("training_job") or {}) if isinstance(task.get("training_job"), Mapping) else {}).get(
                        "job_template"
                    )
                    or ""
                ),
            }
        )
    return rows


def _assert_board_matches_parquet(
    board: str,
    parquet_path: Path,
    tasks: Sequence[Mapping[str, Any]],
) -> None:
    """Board headers, parquet rows, and task records must name the same todos."""

    import re

    import pyarrow.parquet as pq

    board_ids = re.findall(r"^## (AFTD-\S+)\s+", board, re.MULTILINE)
    record_ids = [str(task.get("task_id") or "") for task in tasks]
    table_ids = [str(value) for value in pq.read_table(parquet_path).column("task_id").to_pylist()]
    if not board_ids or board_ids != record_ids or board_ids != table_ids:
        raise AutoformalTodoError("board task ids must match the parquet table")
    if ".jsonl" in board.casefold():
        raise AutoformalTodoError("todo package must not reference jsonl")


def write_todos_parquet(path: Path, tasks: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Authoritative todo table. JSONL is not a substitute."""

    try:
        import pyarrow as pa
        import pyarrow.parquet as pq
    except ImportError as exc:
        raise AutoformalTodoError("pyarrow is required to write the Hugging Face todo table") from exc
    rows = _parquet_rows(tasks)
    if not rows:
        raise AutoformalTodoError("todo table requires at least one discrepancy")
    table = pa.Table.from_pylist(rows)
    path.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(table, path)
    return _descriptor(path, TODOS_NAME)


def build_autoformal_todo_package(
    tasks: Sequence[Mapping[str, Any]],
    destination: str | Path,
    *,
    repository_id: str | None = None,
    release_id: str | None = None,
    profile: HuggingFacePublicationProfile | None = None,
) -> dict[str, Any]:
    """Write parquet, markdown board, locator, and a dry-run publication manifest."""

    resolved_profile = profile or autoformal_todo_publication_profile()
    if repository_id:
        resolved_profile = resolved_profile.with_repository(repository_id)
    root = Path(destination)
    if root.exists():
        raise AutoformalTodoError("todo package destination already exists")
    root.mkdir(parents=True, exist_ok=False)
    task_list = list(tasks)
    parquet_info = write_todos_parquet(root / TODOS_NAME, task_list)
    board = render_supervisor_board(task_list)
    validate_supervisor_board(board)
    _assert_board_matches_parquet(board, root / TODOS_NAME, task_list)
    (root / BOARD_NAME).write_text(board, encoding="utf-8")
    board_info = _descriptor(root / BOARD_NAME, BOARD_NAME)
    digest_source = _json(
        {
            "board": board_info,
            "schema": PACKAGE_SCHEMA,
            "tasks": [task.get("task_id") for task in task_list],
            "todos": parquet_info,
        }
    )
    resolved_release = release_id or f"sha256-{_sha(digest_source)}"
    locator = huggingface_todo_locator(
        repository_id=resolved_profile.repository_id,
        release_id=resolved_release,
        board_path=f"{resolved_profile.release_prefix_for(resolved_release)}/{BOARD_NAME}",
        todos_path=f"{resolved_profile.release_prefix_for(resolved_release)}/{TODOS_NAME}",
        tasks=task_list,
    )
    (root / LOCATOR_NAME).write_bytes(_json(locator))
    locator_info = _descriptor(root / LOCATOR_NAME, LOCATOR_NAME)
    files = [board_info, locator_info, parquet_info]
    files.sort(key=lambda item: item["relative_path"])
    manifest = {
        "board_namespace": BOARD_NAMESPACE,
        "files": files,
        "jsonl_written": False,
        "profile_id": resolved_profile.profile_id,
        "program_id": resolved_profile.program_id,
        "release_id": resolved_release,
        "repository_id": resolved_profile.repository_id,
        "schema_version": resolved_profile.canonical_release_schema,
        "time_management": time_management(task_list),
        "wrote_compiler": False,
        "wrote_decompiler": False,
    }
    manifest["release_sha256"] = _sha(_json({key: value for key, value in manifest.items() if key != "release_sha256"}))
    (root / MANIFEST_NAME).write_bytes(_json(manifest))
    package = {
        "admitted": False,
        "formalized": False,
        "jsonl_written": False,
        "local_root": str(root),
        "locator": locator,
        "manifest": manifest,
        "package_root": str(root),
        "profile": resolved_profile.to_dict(),
        "task_count": len(task_list),
        "wrote_compiler": False,
        "wrote_decompiler": False,
    }
    package["pointer"] = write_autoformal_todo_pointer(package)
    return package


def write_autoformal_todo_pointer(
    package: Mapping[str, Any],
    *,
    pointer_path: str | Path | None = None,
) -> dict[str, Any]:
    """Local latest-release pointer the accelerate supervisor can load."""

    root = Path(package["package_root"])
    locator = dict(package.get("locator") or {})
    payload = {
        "board_path": str(root / BOARD_NAME),
        "dataset_repo_id": locator.get("dataset_repo_id") or "",
        "dry_run": bool(package.get("dry_run", True)),
        "jsonl_written": False,
        "locator_path": str(root / LOCATOR_NAME),
        "package_root": str(root),
        "release_id": locator.get("release_id") or package["manifest"]["release_id"],
        "revision": locator.get("revision") or "main",
        "schema": POINTER_SCHEMA,
        "time_management": dict((package.get("manifest") or {}).get("time_management") or locator.get("time_management") or {}),
        "todos_path": str(root / TODOS_NAME),
        "uploaded": bool(package.get("uploaded", False)),
        "wrote_compiler": False,
    }
    (root / POINTER_NAME).write_bytes(_json(payload))
    if pointer_path is not None:
        destination = Path(pointer_path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(_json(payload))
        payload = {**payload, "pointer_path": str(destination)}
    return payload


def upload_autoformal_todos(
    tasks: Sequence[Mapping[str, Any]],
    destination: str | Path,
    *,
    repository_id: str | None = None,
    release_id: str | None = None,
    dry_run: bool = True,
    publisher: Any | None = None,
    approval: Any | None = None,
    pointer_path: str | Path | None = None,
    existing_remote_paths: Sequence[str] = (),
    existing_remote_digests: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """Package todos and plan (or publish) the Hugging Face release.

    Default is dry-run. Live writes require an injected publisher, an explicit
    ``PublicationApproval``, and ``dry_run=False``. JSONL is never the uploaded
    authority.
    """

    package = build_autoformal_todo_package(
        tasks,
        destination,
        repository_id=repository_id,
        release_id=release_id,
    )
    profile = autoformal_todo_publication_profile(
        repository_id=package["manifest"]["repository_id"]
    )
    if publisher is None:
        from ipfs_datasets_py.huggingface.publisher import HuggingFaceReleasePublisher

        publisher = HuggingFaceReleasePublisher(profile=profile)
    plan = publisher.plan_dry_run(
        package["manifest"],
        local_root=package["local_root"],
        existing_remote_paths=existing_remote_paths,
        existing_remote_digests=existing_remote_digests,
    )
    receipt = {
        **package,
        "dry_run": True,
        "plan_digest": getattr(plan, "plan_digest", ""),
        "remote_write_contacted": False,
        "uploaded": False,
    }
    if dry_run:
        receipt["pointer"] = write_autoformal_todo_pointer(receipt, pointer_path=pointer_path)
        return receipt
    if approval is None:
        raise AutoformalTodoError(
            "live Hugging Face todo publication requires an explicit approved publish path"
        )
    publish = getattr(publisher, "publish_append_only", None)
    if not callable(publish):
        raise AutoformalTodoError(
            "live Hugging Face todo publication requires publisher.publish_append_only"
        )
    commit = publish(plan, approval=approval, local_root=package["local_root"])
    commit_sha = str(getattr(commit, "commit_sha", "") or (commit.get("commit_sha") if isinstance(commit, Mapping) else "") or "")
    locator = dict(receipt["locator"])
    if commit_sha:
        locator["revision"] = commit_sha
    receipt.update(
        {
            "commit": commit.to_dict() if hasattr(commit, "to_dict") else commit,
            "commit_sha": commit_sha,
            "dry_run": False,
            "locator": locator,
            "remote_write_contacted": True,
            "uploaded": True,
        }
    )
    receipt["pointer"] = write_autoformal_todo_pointer(receipt, pointer_path=pointer_path)
    return receipt


def publish_discrepancy_todos(
    agreement: Mapping[str, Any],
    destination: str | Path,
    *,
    board_path: str | Path | None = None,
    pointer_path: str | Path | None = None,
    query: str = "",
    release_id: str = "",
    dry_run: bool = True,
    publisher: Any | None = None,
    approval: Any | None = None,
    repository_id: str | None = None,
) -> dict[str, Any]:
    """Board + Hugging Face package for one agreement. Does not write JSONL."""

    from ipfs_datasets_py.logic.autoformal.supervisor_todo import submit_discrepancies

    def upload(tasks):
        return upload_autoformal_todos(
            tasks,
            destination,
            repository_id=repository_id,
            dry_run=dry_run,
            publisher=publisher,
            approval=approval,
            pointer_path=pointer_path,
        )

    return submit_discrepancies(
        agreement,
        board_path=board_path,
        query=query,
        release_id=release_id,
        upload=None if agreement.get("agrees") else upload,
    )


def publish_repair_item_todos(
    items: Sequence[Mapping[str, Any]],
    destination: str | Path,
    **kwargs: Any,
) -> dict[str, Any]:
    """Publish sealed repair-packet rows as Hugging Face supervisor todos."""

    rows: list[dict[str, Any]] = []
    for item in items:
        packet = item.get("packet") if isinstance(item, Mapping) else None
        row = dict((packet or {}).get("row") or {})
        if not row:
            continue
        row.setdefault("agrees", False)
        row.setdefault("skipped", False)
        rows.append(row)
    return publish_discrepancy_todos(
        {
            "admitted": False,
            "agrees": False,
            "formalized": False,
            "reason": "compiler_disagreement",
            "rows": rows,
        },
        destination,
        **kwargs,
    )


def publish_observation_todos(
    observations: Sequence[Mapping[str, Any]],
    destination: str | Path,
    **kwargs: Any,
) -> dict[str, Any]:
    """Flatten cycle observation batches into one Hugging Face todo release."""

    rows: list[dict[str, Any]] = []
    for observation in observations:
        for row in observation.get("rows") or []:
            if isinstance(row, Mapping) and not row.get("skipped"):
                rows.append(dict(row))
    agreement = {
        "admitted": False,
        "agrees": bool(rows) and all(row.get("agrees") for row in rows),
        "formalized": False,
        "rows": rows,
        "reason": "" if rows and all(row.get("agrees") for row in rows) else "compiler_disagreement",
    }
    return publish_discrepancy_todos(agreement, destination, **kwargs)
