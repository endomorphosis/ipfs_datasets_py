"""Declare train and compiler/decompiler edit work on autoformal loop todos.

The accelerate supervisor owns claims and completion. This adapter stamps
work_kind, sealed repair packets, and frozen v6 training contracts onto the
goal tree so a later native pass can dispatch. Completing a training job is
not promoting a model. A sealed edit is not an admit or a compiler import.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Mapping, Sequence

from .supervisor_queue import (
    EDIT_SCOPES,
    NAMESPACE as REPAIR_NAMESPACE,
    SCHEMA as REPAIR_SCHEMA,
    RepairQueueError,
    approved_edit_scope,
    persist_packet,
    repair_outputs,
    repair_packets,
)


WORK_KIND_EDIT = "compiler_decompiler_edit"
WORK_KIND_TRAIN = "autoencoder_training"
WORK_KIND_REVIEW = "preserve_replace_review"
TRAIN_FAILURES = frozenset({"inference_still_failing", "capture_not_in_decompilation"})
TRAINING_SCHEMA = "uscode-autoformal-training-job/v1"
TRAINING_NAMESPACE = "uscode-autoformal-training-v1"
TRAINING_ENTRYPOINT = "scripts/ops/legal_ir/run_autoformal_training_cycle.py"
TRAINING_JOB_SCHEMA = "autoencoder-training-job-v6"
EDIT_CONFLICT = "serialize overlapping compiler/decompiler edits"
REVIEW_CONFLICT = "do not write compiler or decompiler patches from this task"
LOOP_VALIDATION = ["python3", "-m", "pytest", "tests/unit/logic/test_supervisor_loop.py", "-q"]
UNBOUND_MODEL = "sha256:loop-census-unbound"


class SupervisorDispatchError(ValueError):
    """Train or edit work cannot be declared without inventing authority."""


def classify_work(reason: str) -> tuple[str, ...]:
    """Map a census failure onto train, compiler/decompiler edit, or both."""

    key = str(reason or "").split(":", 1)[0]
    kinds: list[str] = []
    try:
        approved_edit_scope(reason)
        kinds.append(WORK_KIND_EDIT)
    except RepairQueueError:
        pass
    if key in TRAIN_FAILURES:
        kinds.append(WORK_KIND_TRAIN)
    return tuple(kinds)


def bind_job_template(path: str | Path) -> dict[str, str]:
    """Accept only the frozen v6 training job. Do not start training here."""

    destination = Path(path)
    try:
        raw = destination.read_bytes()
    except OSError as exc:
        raise SupervisorDispatchError(f"training job template is unreadable: {destination}") from exc
    if len(raw) > 64 * 1024 * 1024:
        raise SupervisorDispatchError("training job template exceeds bounded input size")
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise SupervisorDispatchError("training job template must be JSON") from exc
    if not isinstance(payload, Mapping) or payload.get("schema_version") != TRAINING_JOB_SCHEMA:
        raise SupervisorDispatchError("training todos require autoencoder-training-job-v6")
    return {
        "path": str(destination.resolve()),
        "schema_version": TRAINING_JOB_SCHEMA,
        "sha256": hashlib.sha256(raw).hexdigest(),
    }


def _cid(kind: str, *parts: Any) -> str:
    payload = json.dumps(parts, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return f"{kind}:" + hashlib.sha256(payload.encode("utf-8")).hexdigest()[:32]


def _failure(task: Mapping[str, Any]) -> str:
    return str(task.get("failure_mode") or task.get("reason") or "")


def _row_from_task(task: Mapping[str, Any], agreement: Mapping[str, Any] | None) -> dict[str, Any]:
    span = str(task.get("source_span_id") or task.get("id") or "")
    for row in (agreement or {}).get("rows") or []:
        if not isinstance(row, Mapping):
            continue
        if str(row.get("source_span_id") or row.get("id") or "") == span:
            return dict(row)
    return {
        "agrees": False,
        "canonical_citation": str(task.get("canonical_citation") or ""),
        "capture": dict(task.get("capture") or {}),
        "decompiled": str(task.get("decompiled") or ""),
        "dropped": list(task.get("dropped") or []),
        "entry_cid": str(task.get("entry_cid") or ""),
        "id": span,
        "legal_id": str(task.get("legal_id") or ""),
        "reason": _failure(task),
        "skipped": False,
        "source_span_id": span,
        "text": str(task.get("source_text") or task.get("text") or ""),
    }


def _preserved_rows(agreement: Mapping[str, Any] | None) -> list[dict[str, Any]]:
    rows = []
    for row in (agreement or {}).get("rows") or []:
        if isinstance(row, Mapping) and row.get("agrees") and not row.get("skipped"):
            rows.append(dict(row))
    return rows


def _stamp_edit_scope(task: dict[str, Any]) -> None:
    failure = approved_edit_scope(_failure(task))
    paths = list(EDIT_SCOPES[failure])
    task["allowed_edit_paths"] = paths
    task["predicted_files"] = paths
    task["edit_scope"] = failure
    task["work_kind"] = WORK_KIND_EDIT
    task["track"] = "autoformal-compiler-edit"
    task["conflict_policy"] = EDIT_CONFLICT
    task["admitted"] = False
    task["formalized"] = False
    task["wrote_compiler"] = False
    task["match_is_not_admit"] = True


def _seal_edit(
    task: dict[str, Any],
    *,
    agreement: Mapping[str, Any] | None,
    packet_directory: Path | None,
    code_identity: str,
    model_identity: str,
    release_id: str,
    query: str,
) -> None:
    _stamp_edit_scope(task)
    task["dispatch_status"] = "awaiting_sealed_packet"
    task["review_only"] = True
    if packet_directory is None or not str(code_identity or "").strip() or not str(model_identity or "").strip():
        return
    row = _row_from_task(task, agreement)
    if not str(row.get("text") or "").strip():
        return
    try:
        items = repair_packets(
            {"rows": [row, *_preserved_rows(agreement)], "agrees": False, "admitted": False, "formalized": False},
            release_id=release_id or str(task.get("release_id") or "loop-v1"),
            code_identity=code_identity,
            model_identity=model_identity,
            query=query or str(task.get("query") or ""),
        )
    except RepairQueueError:
        return
    if not items:
        return
    item = items[0]
    packet, digest = item["packet"], item["sha256"]
    path = persist_packet(Path(packet_directory), packet, digest)
    from ipfs_accelerate_py.agent_supervisor.task_sources.control_plane_contracts import content_identity

    command = [
        "python3",
        "scripts/ops/legal_ir/validate_autoformal_repair.py",
        "--packet",
        str(path),
        "--sha256",
        digest,
    ]
    acceptance = (
        "Repair the allowed Python compiler/decompiler/parser paths in an isolated worktree. "
        "Preserve the named working behavior and add a regression test. "
        "Pass exact-source replay and the frozen regression suite; task packaging is not a repair. "
        "Do not change validators, source evidence, trust policy or benchmark scores. "
        "Do not mark the law formalized or admitted."
    )
    task.update(
        {
            "acceptance": acceptance,
            "acceptance_criteria": [acceptance],
            "board_namespace": REPAIR_NAMESPACE,
            "conflict_policy": EDIT_CONFLICT,
            "description": acceptance + "\nFull immutable evidence: " + str(path),
            "dispatch_status": "sealed_edit",
            "is_schedulable": True,
            "outputs": [{"path": value} for value in repair_outputs(packet, digest)],
            "packet_path": str(path),
            "packet_sha256": digest,
            "review_only": False,
            "task_cid": content_identity({"schema": REPAIR_SCHEMA, "packet_sha256": digest}),
            "task_id": "AFTD-" + digest[:20],
            "validation_commands": [{"argv": command}],
        }
    )


def _bind_train(
    task: dict[str, Any],
    *,
    job: Mapping[str, str] | None,
    accelerate_root: str | Path | None,
    database: str | Path | None,
    runtime_root: str | Path | None,
) -> None:
    bound = job is not None and accelerate_root is not None and database is not None and runtime_root is not None
    acceptance = (
        "Run the frozen v6 autoencoder training cycle on this failure family. "
        "Completing training is not promoting a model, importing a compiler, or admitting law."
    )
    template = str((job or {}).get("path") or "")
    spec = {
        "admitted": False,
        "bound": bound,
        "entrypoint": TRAINING_ENTRYPOINT,
        "formalized": False,
        "job_schema": TRAINING_JOB_SCHEMA,
        "job_template": template,
        "job_template_sha256": str((job or {}).get("sha256") or ""),
        "production_promotion": False,
        "review_only": not bound,
        "schema": TRAINING_SCHEMA,
    }
    task.update(
        {
            "acceptance": acceptance,
            "acceptance_criteria": [acceptance],
            "allowed_edit_paths": [],
            "board_namespace": TRAINING_NAMESPACE,
            "conflict_policy": REVIEW_CONFLICT,
            "dispatch_status": "bound_training_job" if bound else "awaiting_job_template",
            "predicted_files": [],
            "production_promotion": False,
            "review_only": not bound,
            "track": "autoencoder-training",
            "training_job": spec,
            "work_kind": WORK_KIND_TRAIN,
            "wrote_compiler": False,
        }
    )
    if bound:
        runtime = Path(runtime_root)
        argv = [
            "python3",
            TRAINING_ENTRYPOINT,
            "--job-template",
            template,
            "--accelerate-root",
            str(Path(accelerate_root)),
            "--database",
            str(Path(database)),
            "--runtime-root",
            str(runtime),
        ]
        task["validation_commands"] = [{"argv": argv}]
        task["outputs"] = [{"path": "workspace/autoformal-training/cycle-receipt.json"}]
        task["training_job"] = {
            **spec,
            "accelerate_root": str(Path(accelerate_root)),
            "database": str(Path(database)),
            "runtime_root": str(runtime),
        }
        task["is_schedulable"] = True


def attach_dispatch(
    tree: dict[str, Any],
    *,
    agreement: Mapping[str, Any] | None = None,
    packet_directory: str | Path | None = None,
    code_identity: str = "",
    model_identity: str = "",
    job_template: str | Path | None = None,
    accelerate_root: str | Path | None = None,
    database: str | Path | None = None,
    runtime_root: str | Path | None = None,
    release_id: str = "",
    query: str = "",
) -> dict[str, Any]:
    """Stamp train and edit contracts onto spawned loop todos. Does not claim."""

    job = bind_job_template(job_template) if job_template else None
    packets = Path(packet_directory) if packet_directory is not None else None
    expanded: list[dict[str, Any]] = []
    id_map: dict[str, list[str]] = {}
    for original in tree.get("tasks") or []:
        task = dict(original)
        old_id = str(task.get("task_id") or "")
        kinds = classify_work(_failure(task))
        if not kinds:
            task["work_kind"] = WORK_KIND_REVIEW
            task["dispatch_status"] = "review_only"
            task["review_only"] = True
            task["conflict_policy"] = REVIEW_CONFLICT
            task["wrote_compiler"] = False
            expanded.append(task)
            id_map[old_id] = [old_id]
            continue
        siblings: list[dict[str, Any]] = []
        for kind in kinds:
            item = dict(task)
            if kind == WORK_KIND_EDIT:
                _seal_edit(
                    item,
                    agreement=agreement,
                    packet_directory=packets,
                    code_identity=code_identity,
                    model_identity=model_identity or UNBOUND_MODEL,
                    release_id=release_id or str(item.get("release_id") or ""),
                    query=query or str(item.get("query") or ""),
                )
            else:
                _bind_train(
                    item,
                    job=job,
                    accelerate_root=accelerate_root,
                    database=database,
                    runtime_root=runtime_root,
                )
                if len(kinds) > 1:
                    item["task_id"] = old_id + "-train"
                    item["depends_on"] = list(item.get("depends_on") or [])
            if not item.get("task_cid") or kind == WORK_KIND_TRAIN or item.get("dispatch_status") != "sealed_edit":
                item["task_cid"] = _cid("task", item.get("task_id"), item.get("source_span_id"), kind)
            item["admitted"] = False
            item["formalized"] = False
            item["proof_authoritative"] = False
            item["wrote_compiler"] = False
            siblings.append(item)
        expanded.extend(siblings)
        id_map[old_id] = [item["task_id"] for item in siblings]
    for goal in tree.get("goals") or []:
        resolves: list[str] = []
        for task_id in goal.get("resolves") or []:
            mapped = id_map.get(str(task_id), [str(task_id)])
            for item in mapped:
                if item not in resolves:
                    resolves.append(item)
        goal["resolves"] = resolves
    for index, task in enumerate(expanded, start=1):
        task["ordinal"] = index
    tree["tasks"] = expanded
    return tree


def dispatch_counts(tasks: Sequence[Mapping[str, Any]]) -> dict[str, int]:
    counts = {"edit": 0, "train": 0, "review": 0, "sealed_packets": 0, "bound_training": 0}
    for task in tasks:
        kind = str(task.get("work_kind") or "")
        if kind == WORK_KIND_EDIT:
            counts["edit"] += 1
        elif kind == WORK_KIND_TRAIN:
            counts["train"] += 1
        else:
            counts["review"] += 1
        if task.get("dispatch_status") == "sealed_edit" and task.get("packet_sha256"):
            counts["sealed_packets"] += 1
        if task.get("dispatch_status") == "bound_training_job":
            counts["bound_training"] += 1
    return counts
