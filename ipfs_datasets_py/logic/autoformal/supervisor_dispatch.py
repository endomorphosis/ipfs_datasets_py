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


WORK_KIND_REVIEWED_EVALUATION = "reviewed_source_evaluation"
REVIEWED_EVALUATION_ENTRYPOINT = "scripts/ops/legal_ir/run_incremental_autoencoders.py"
REVIEWED_EVALUATION_BINDING_SCHEMA = "supervisor-reviewed-source-evaluation/v1"


def bind_reviewed_evaluation_task(task: Mapping[str, Any], request_artifact: Mapping[str, Any]) -> dict[str, Any]:
    """Bind explicit evaluation DATA without changing the native task lifecycle."""
    if (not isinstance(task, Mapping) or task.get("work_kind") != WORK_KIND_REVIEWED_EVALUATION
            or type(task.get("task_id")) is not str or not task["task_id"].strip()):
        raise SupervisorDispatchError("explicit reviewed evaluation work kind and existing task ID required")
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_inference import _read_reviewed_evaluation_request
    reference, _raw, request = _read_reviewed_evaluation_request(request_artifact)
    if request["request_id"] != task["task_id"]:
        raise SupervisorDispatchError("reviewed request must bind the existing native task ID")
    binding = {
        "schema": REVIEWED_EVALUATION_BINDING_SCHEMA,
        "entrypoint": REVIEWED_EVALUATION_ENTRYPOINT,
        "request_artifact": {"path": reference.path, "sha256": reference.sha256, "bytes": reference.bytes},
        "request_schema": request["schema"],
        "operation": request["operation"],
        "requires_live_parent_runtime": True,
    }
    if "reviewed_evaluation" in task and task["reviewed_evaluation"] != binding:
        raise SupervisorDispatchError("existing reviewed task binding differs; no implicit rebind or retry")
    result = dict(task)
    result["reviewed_evaluation"] = binding
    return result



def _reviewed_parent_schema(runtime):
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_inference as inference
    inference._validate_parent_typed_structure_profile(runtime.typed_structure_profile)
    inference._validate_parent_candidate_syntax_profile(runtime.candidate_syntax_profile)
    return ('reviewed-source-evaluation-parent/v3' if runtime.candidate_syntax_profile is not None else
            'reviewed-source-evaluation-parent/v2' if runtime.typed_structure_profile is not None else
            'reviewed-source-evaluation-parent/v1')


def _validate_reviewed_parent_audits(parent, child, request, request_sha256, child_ref, runtime):
    """Validate opt-in audit DATA, without inferring an execution or grant."""
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_inference as inference
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_training_worker as worker
    if parent.get('schema') != _reviewed_parent_schema(runtime):
        raise SupervisorDispatchError('parent audit schema differs from trusted runtime selection')
    cycle_ref = child_ref if type(child_ref) is worker.CheckpointArtifact else worker.CheckpointArtifact.from_dict(child_ref)
    contracts = (
        ('typed_structure', runtime.typed_structure_profile, 'typed_structure_profile',
         'typed_structure_audit_artifact', 'typed-structure-audit.json',
         ('parent_typed_structure_audit_after_wait', 'parent_current_admission_rechecked_after_audit'),
         inference._parent_typed_structure_source_pins, inference._build_parent_typed_structure_audit),
        ('candidate_syntax', runtime.candidate_syntax_profile, 'candidate_syntax_profile',
         'candidate_syntax_audit_artifact', 'candidate-syntax-audit.json',
         ('parent_candidate_syntax_audit_after_wait', 'parent_current_admission_rechecked_after_candidate_audit'),
         inference._parent_candidate_syntax_source_pins, inference._build_parent_candidate_syntax_audit),
    )
    state = dict(artifacts={}, source_pins={})
    for kind, profile, profile_field, artifact_field, filename, flags, pins_owner, build in contracts:
        fields = (profile_field, artifact_field, *flags)
        if profile is None:
            if any(field in parent for field in fields):
                raise SupervisorDispatchError('unrequested parent audit fields cannot select a trusted profile')
            continue
        if parent.get(profile_field) != profile or any(parent.get(flag) is not True for flag in flags):
            raise SupervisorDispatchError('parent audit profile or original-parent checks differ')
        descriptor = parent.get(artifact_field)
        reference = worker.CheckpointArtifact.from_dict(descriptor)
        if reference.path != str(Path(request['output_directory']) / filename):
            raise SupervisorDispatchError('parent audit artifact path differs from fixed output')
        raw = worker._reviewed_decoder_artifact(reference, limit=inference.REVIEWED_EVALUATION_OUTPUT_LIMIT)
        audit = worker._parse_json(raw)
        pins = pins_owner()
        args = (child, request, cycle_ref, request_sha256, pins)
        expected = build(*args, profile) if kind == 'candidate_syntax' else build(*args)
        if worker._json_bytes(audit) != worker._json_bytes(expected):
            raise SupervisorDispatchError('parent audit differs from recomputed original artifact joins')
        state['artifacts'][kind] = dict(path=reference.path, sha256=reference.sha256, bytes=reference.bytes)
        state['source_pins'][kind] = pins
    return state


def _reauthenticate_reviewed_parent_audits(state, request, reference, runtime):
    """Recheck observed inputs, code and sidecars after the last callback."""
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_inference as inference
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_training_worker as worker
    if state['artifacts']:
        inference._check_parent_audit_inputs(request, reference,
            candidate=runtime.candidate_syntax_profile is not None)
    else:
        worker._reviewed_decoder_artifact(reference, limit=4 * 1024**2, load=False)
    owners = {'typed_structure': inference._parent_typed_structure_source_pins,
              'candidate_syntax': inference._parent_candidate_syntax_source_pins}
    if set(state['source_pins']) != set(state['artifacts']):
        raise SupervisorDispatchError('parent audit source/artifact population differs')
    for kind, pins in state['source_pins'].items():
        if kind not in owners or owners[kind]() != pins:
            raise SupervisorDispatchError('parent audit implementation changed after final callback')
    for descriptor in state['artifacts'].values():
        worker._reviewed_decoder_artifact(worker.CheckpointArtifact.from_dict(descriptor),
            limit=inference.REVIEWED_EVALUATION_OUTPUT_LIMIT, load=False)

def execute_reviewed_evaluation_task(task: Mapping[str, Any], *, reviewed_parent_runtime=None) -> dict[str, Any]:
    """Use the normal fixed CLI under the caller's original admitted parent.

    Accelerate retains claims, task revisions, completion and resource release.
    No callable, permission or runtime is reconstructed from serialized task data.
    """
    if reviewed_parent_runtime is None:
        raise SupervisorDispatchError("configured original reviewed parent runtime required")
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_inference as inference
    if type(reviewed_parent_runtime) is not inference.ReviewedInferenceParentRuntime:
        raise SupervisorDispatchError("exact configured reviewed parent runtime required")
    runtime = reviewed_parent_runtime
    # Freeze ordinary native task DATA before invoking caller-owned callbacks.
    frozen_task = json.dumps(dict(task), sort_keys=True, separators=(",", ":"), allow_nan=False)
    original_task = task
    task = json.loads(frozen_task)
    runtime.source_guard()
    if not isinstance(task, Mapping) or not isinstance(task.get("reviewed_evaluation"), Mapping):
        raise SupervisorDispatchError("explicit bound reviewed evaluation task required")
    binding = task["reviewed_evaluation"]
    rebound = bind_reviewed_evaluation_task(task, binding.get("request_artifact"))
    if rebound["reviewed_evaluation"] != binding:
        raise SupervisorDispatchError("reviewed task binding changed")
    reference, _raw, request = inference._read_reviewed_evaluation_request(binding["request_artifact"])
    # The importer is fixed in this canonical owner; task data cannot select code.
    root = Path(__file__).resolve().parents[3]
    cli_path = root / REVIEWED_EVALUATION_ENTRYPOINT
    expected = request["lifecycle_source_sha256"][str(cli_path)]
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_daemon_invocation_contracts as artifacts
    raw = artifacts.read_bytes(cli_path, 1024 * 1024)
    if len(raw) > 1024 * 1024 or hashlib.sha256(raw).hexdigest() != expected:
        raise SupervisorDispatchError("fixed reviewed CLI source changed")
    import types
    module = types.ModuleType("_autoformal_reviewed_cli_" + expected)
    module.__file__ = str(cli_path)
    runtime.source_guard()
    exec(compile(raw, str(cli_path), "exec", dont_inherit=True), module.__dict__)
    runtime.source_guard()
    if hashlib.sha256(artifacts.read_bytes(cli_path, 1024 * 1024)).hexdigest() != expected:
        raise SupervisorDispatchError("fixed reviewed CLI source changed during import")
    code = module.main([
        "--execution-mode", "inference", "--state-directory", request["attempt_directory"],
        "--reviewed-evaluation-request", reference.path,
        "--reviewed-evaluation-sha256", reference.sha256,
    ], reviewed_parent_runtime=runtime)
    if code != 0:
        raise SupervisorDispatchError("normal reviewed evaluation CLI did not finish")
    runtime.source_guard()
    parent_path = Path(request["output_directory"]) / "parent-cycle.json"
    child_path = Path(request["output_directory"]) / "cycle.json"
    # These receipts record execution; they cannot grant task-completion authority.
    def receipt(path):
        raw = artifacts.read_bytes(path, 1024 * 1024)
        value = artifacts.parse_json(raw)
        if type(value) is not dict:
            raise SupervisorDispatchError("reviewed cycle receipt must be an object")
        return value, {"path": str(path), "sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw)}
    parent, parent_ref = receipt(parent_path)
    child, child_ref = receipt(child_path)
    if parent.get("child_cycle_artifact") != child_ref:
        raise SupervisorDispatchError("parent receipt does not bind the exact child cycle bytes")
    false_claims = ("training_executed", "admitted", "model_quality_qualified", "legal_meaning_verified",
                    "proof_authority", "convergence_proved", "corpus_admitted")
    if (parent.get("schema") != _reviewed_parent_schema(runtime)
            or child.get("schema") != "reviewed-source-evaluation-cycle/v1"
            or any(value.get("request_sha256") != reference.sha256 or value.get("completed") is not True
                   or value.get("execution_path") != "inference" for value in (parent, child))
            or parent.get("parent_receipt") != str(parent_path) or parent.get("receipt") != str(child_path)
            or type(parent.get("parent_callbacks")) is not dict
            or (parent.get("parent_callbacks") or {}).get("child_identity") != parent.get("original_child_identity")
            or any(value.get(name) is not False for name in false_claims for value in (parent, child))
            or parent.get("original_child_waited") is not True
            or parent.get("parent_FINISH_acknowledged") is not True
            or parent.get("parent_current_admission_rechecked_after_wait") is not True
            or parent.get("parent_output_artifacts_rechecked_after_wait") is not True
            or parent.get("resource_release_performed") is not False
            or parent.get("original_owner_reservation_id") != runtime.owner.reservation_id
            or (parent.get("parent_callbacks") or {}).get("finished") is not True
            or (parent.get("parent_callbacks") or {}).get("closed") is not True):
        raise SupervisorDispatchError("original parent execution closeout is incomplete or mismatched")
    audit_state = _validate_reviewed_parent_audits(parent, child, request, reference.sha256, child_ref, runtime)
    runtime.source_guard()
    if json.dumps(dict(original_task), sort_keys=True, separators=(",", ":"), allow_nan=False) != frozen_task:
        raise SupervisorDispatchError("native task DATA changed during reviewed execution")
    # The final original Source callback can change files after receipt reads.
    # Recheck all child outputs and both exact receipts after that callback.
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_training_worker as worker
    for value in (parent, child):
        inference._check_reviewed_evaluation_outputs(value, request)
    if parent["output_artifacts"] != child["output_artifacts"]:
        raise SupervisorDispatchError("parent receipt does not bind the exact child output descriptors")
    for descriptor in (child_ref, parent_ref):
        worker._reviewed_decoder_artifact(worker.CheckpointArtifact.from_dict(descriptor),
                                         limit=1024 * 1024, load=False)
    _reauthenticate_reviewed_parent_audits(audit_state, request, reference, runtime)
    result = {
        "schema": "supervisor-reviewed-source-evaluation-result/v1",
        "task_id": task["task_id"], "request_sha256": reference.sha256,
        "parent_receipt": parent_ref, "cycle_receipt": child_ref,
        "output_artifacts": child["output_artifacts"],
        "original_child_waited": True, "training_executed": False,
        "task_status_changed": False, "task_completion_authority": False,
        "resource_release_performed": False, "admitted": False,
    }
    if audit_state['artifacts']:
        result.update(schema='supervisor-reviewed-source-evaluation-result/v2',
            parent_schema=parent['schema'], audit_artifacts=audit_state['artifacts'],
            parent_audits_recomputed=True, audit_scope='source_bound_syntax_DATA_only',
            native_proof_verified=False, legal_meaning_verified=False)
    return result
