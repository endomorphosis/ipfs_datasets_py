"""Prepare exact registered campaign jobs for the separate owned worker executor.

Preparation adds immutable control artifacts and operation bindings only. It
does not claim runs, hydrate targets, load weights, reserve runtime capacity or
launch workers. Original job bytes, settings and completion rules are retained.
The request is not accepted by the daemon's owned-control profile. Callers must
admit preparation's own filesystem work separately from its declared future
per-worker resource policy. The explicit execution entry lazily delegates to
the owned executor; preparation and inspection remain metadata-only.
Importing this module starts no service.
"""
from __future__ import annotations

from dataclasses import fields
import hashlib
import json
import os
from pathlib import Path
import tempfile

from ...duckdb_control.autoencoder_registry import AutoencoderRegistry, SCHEMA as REGISTRY_SCHEMA
from ...duckdb_control.contracts import canonical_json_bytes
from . import autoencoder_campaign_plan as plans
from . import autoencoder_campaign_training_request as codec
from . import autoencoder_training_coordinator as coordinator
from .autoencoder_campaign_job_inputs import _CampaignRootScope
from .autoencoder_daemon_corpus_inputs import _read_bound
from .autoencoder_daemon_operation_journal import DurableDaemonOperationJournal
from .autoencoder_daemon_resources import DaemonResourceReservation, _safe_path
from .autoencoder_training_worker import CheckpointArtifact

STATUS_SCHEMA = "autoencoder-campaign-training-preparation-status-v1"
PREPARE_COMMAND = "PrepareCampaignTraining"
BIND_COMMAND = "BindCampaignTrainingRun"
_JOURNAL = "owner-operations.json"


class CampaignOwnedTrainingError(ValueError):
    """An owner, request, preparation history or current input is inconsistent."""


def _require(value, message):
    if not value:
        raise CampaignOwnedTrainingError(message)


def _same(left, right):
    return canonical_json_bytes(left) == canonical_json_bytes(right)


def _digest(value):
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _copy_input(value):
    codec._ordinary(value)
    chunks, count = [], 0
    encoder = json.JSONEncoder(ensure_ascii=True, sort_keys=True, separators=(",", ":"), allow_nan=False)
    for chunk in encoder.iterencode(value):
        count += len(chunk)
        _require(count <= codec.MAX_REQUEST_BYTES, "preparation input exceeds control byte bound")
        chunks.append(chunk)
    return json.loads("".join(chunks))


def _bare(ref):
    return {"sha256": ref.sha256, "bytes": ref.bytes}


def _owner(registry):
    _require(type(registry) is AutoencoderRegistry, "preparation requires the actual registry owner")
    registry._ensure_owner()
    _safe_path(registry.database_path)
    _safe_path(registry.artifact_root, directory=True)
    return {"database_path": str(registry.database_path), "artifact_root": str(registry.artifact_root)}


def _sources():
    # Boundary drift detection, not whole-package runtime attestation. A
    # qualification capture must retain its independent full producer guard.
    result = {}
    root = Path(__file__).resolve().parents[3]
    for module_path in (__file__, codec.__file__, plans.__file__, coordinator.__file__,
                        Path(__file__).with_name("autoencoder_campaign_job_inputs.py"),
                        Path(__file__).with_name("autoencoder_daemon_operation_journal.py")):
        path = _safe_path(module_path)
        _require(root in path.parents, "preparation helper loaded from another checkout")
        info = path.stat()
        _require(info.st_size <= 4 * 1024 * 1024, "preparation source exceeds bound")
        raw = coordinator._read_bounded(path, 4 * 1024 * 1024)
        ref = {"sha256": hashlib.sha256(raw).hexdigest(), "bytes": info.st_size}
        _read_bound(path, ref)
        result[str(path)] = ref
    return result


def _check_sources(before):
    _require(_same(before, _sources()), "preparation source changed")


def _pin():
    from ...logic.autoformal import tree_pin
    root = Path(__file__).resolve().parents[3]
    _require(root in Path(tree_pin.__file__).resolve().parents and tree_pin.workspace_root() == root,
             "logic-tree guard loaded from another checkout")
    tree_pin.require_workspace_logic_tree()


def _read(registry, ref, maximum):
    plans._ref(ref)
    _require(ref["bytes"] <= maximum, "control artifact exceeds read bound")
    _, raw = _read_bound(registry.artifact_path(ref), ref, retain=True)
    return raw


def _add_artifact(registry, artifacts, ref):
    bare = _bare(ref)
    path = str(registry.artifact_path(bare))
    _require(ref.path == path, "job dependency is not in this owner's CAS")
    previous = artifacts.setdefault(path, bare)
    _require(_same(previous, bare), "conflicting artifact sizes")


def _capture(registry, plan_artifact):
    raw = _read(registry, plan_artifact, plans.MAX_PLAN_BYTES)
    plan = plans.decode_campaign_plan(raw)
    _require(plan["artifact_root"] == str(registry.artifact_root), "plan belongs to another owner CAS")
    # Check declared sizes before the older registry reader, which hashes a
    # whole file. Aggregate job bounds come from the strict plan decoder.
    for batch in plan["batches"]:
        _read_bound(registry.artifact_path(batch["job_spec_artifact"]), batch["job_spec_artifact"])
    # Reuse the existing lexical root cache within this capture only. Every
    # job still authorizes both roles and checks its selected current bytes.
    with _CampaignRootScope(registry) as root_scope:
        current, resolved = plans._capture(registry, [row["run_id"] for row in plan["batches"]],
                                           plan["parent_policy"], root_scope=root_scope)
    _require(plans.encode_campaign_plan(current) == raw, "plan differs from current registered jobs")
    artifacts = {str(registry.artifact_path(plan_artifact)): dict(plan_artifact)}
    for item in resolved:
        item["base_version"] = registry.get_version(item["spec"].base_version_id)
        _require(_same(item["base_version"]["artifact"], _bare(item["spec"].base_checkpoint))
                 and item["base_version"]["variant_id"] == plan["variant_id"], "registered base changed")
        descriptor = item["job_spec_artifact"]
        artifacts[str(registry.artifact_path(descriptor))] = dict(descriptor)
        for field in fields(item["spec"]):
            value = getattr(item["spec"], field.name)
            if isinstance(value, CheckpointArtifact):
                _add_artifact(registry, artifacts, value)
            elif isinstance(value, (tuple, list)):
                for child in value:
                    if isinstance(child, CheckpointArtifact):
                        _add_artifact(registry, artifacts, child)
    identities = {path: _read_bound(Path(path), ref)[0] for path, ref in artifacts.items()}
    return plan, resolved, artifacts, identities


def _guard_artifacts(artifacts, identities):
    for path, ref in artifacts.items():
        _require(_read_bound(Path(path), ref)[0] == identities[path], "artifact identity changed during preparation")


def _batch(batch, item):
    names = codec.BATCH_FIELDS - {"plan_ordinal", "output_directory"}
    return {**{name: batch[name] for name in names}, "plan_ordinal": batch["ordinal"],
            "output_directory": item["spec"].output_directory}


def _selection(plan, resolved, selected_batch_ids):
    _require(type(selected_batch_ids) is list and 1 <= len(selected_batch_ids) <= codec.MAX_BATCHES
             and all(type(value) is str for value in selected_batch_ids)
             and len(set(selected_batch_ids)) == len(selected_batch_ids), "invalid selected batch IDs")
    selected = [(batch, item) for batch, item in zip(plan["batches"], resolved, strict=True)
                if batch["batch_id"] in selected_batch_ids]
    _require([batch["batch_id"] for batch, _ in selected] == selected_batch_ids,
             "selection must use existing batches in plan order")
    return selected


def _pristine(run, output):
    return (run["status"] == "queued" and type(run["attempt"]) is int and run["attempt"] == 0
            and type(run["fence"]) is int and run["fence"] == 0
            and run["lease"] is None and run["result"] is None and not os.path.lexists(output))


def _namespace(request, resolved):
    control = Path(request["output_root"])
    ledger = Path(request["resource_policy"]["ledger_path"])
    ledger_paths = (ledger, ledger.with_name(ledger.name + ".lock"))
    protected = [control, Path(request["owner"]["artifact_root"])]
    for item in resolved:
        output = Path(item["spec"].output_directory)
        _require(output.is_absolute() and output.resolve() == output and ".." not in output.parts,
                 "original worker output has a path alias")
        _require(control != output and control not in output.parents and output not in control.parents,
                 "control output overlaps an original worker output")
        protected.append(output)
    database = Path(request["owner"]["database_path"])
    database_files = {database, database.with_name(database.name + ".wal"),
                      database.with_name(database.name + ".owner.lock")}
    for path in ledger_paths:
        _require(path not in database_files and all(path != root and root not in path.parents
                                                  for root in protected),
                 "resource ledger overlaps protected owner or job storage")


def _path_state(request, *, require_pristine, selected):
    policy = request["resource_policy"]
    reservation = DaemonResourceReservation(policy["ledger_path"], roots=policy["roots"],
        storage_bytes=policy["storage_bytes"], memory_mb=policy["memory_mb"], cpu_slots=policy["cpu_slots"],
        timeout_seconds=0, ledger_lock_timeout_seconds=5)
    # Construct only. Entering this reservation would admit runtime work.
    output_root = _safe_path(request["output_root"], directory=True)
    owner = request["owner"]
    protected = [Path(owner["database_path"]), Path(owner["artifact_root"])]
    _require(all(output_root != path and output_root not in path.parents and path not in output_root.parents
                 for path in protected), "control output overlaps owner storage")
    paths = [output_root, *protected]
    worker_outputs = []
    worker_path_states = []
    for _, item in selected:
        spec, run = item["spec"], item["run"]
        output = Path(spec.output_directory)
        _require(output.is_absolute() and str(output) == spec.output_directory and ".." not in output.parts,
                 "worker output must be normalized and absolute")
        _safe_path(output.parent, directory=True)
        if os.path.lexists(output):
            _safe_path(output, directory=True)
        _require(output_root != output and output_root not in output.parents and output not in output_root.parents,
                 "control output overlaps a worker output")
        _require(all(output != other and output not in other.parents and other not in output.parents
                     for other in worker_outputs), "worker outputs overlap")
        _require(all(output != path and output not in path.parents and path not in output.parents
                     for path in protected), "worker output overlaps owner storage")
        worker_outputs.append(output)
        parent_info = output.parent.stat()
        info = output.lstat() if os.path.lexists(output) else None
        worker_path_states.append({"path": str(output), "parent": (parent_info.st_dev, parent_info.st_ino),
            "output": None if info is None else (info.st_dev, info.st_ino, info.st_mode)})
        paths.append(output)
        if require_pristine:
            _require(_pristine(run, output), "preparation requires pristine queued jobs")
        config, execution = spec.training_config, request["execution_policy"]
        _require(config.max_seconds <= execution["lease_seconds"]
                 and config.max_seconds <= execution["timeout_seconds"], "job budget exceeds sealed execution limit")
        _require(config.legal_ir_parallel_workers <= policy["cpu_slots"], "bridge workers exceed per-worker CPU policy")
    for path in paths:
        _require(any(path == root or root in path.parents for root in reservation.roots),
                 "owner or output path is outside declared resource roots")
    return {"roots": reservation.root_identities,
            "output": (output_root.stat().st_dev, output_root.stat().st_ino),
            "worker_paths": worker_path_states,
            "owner_paths": [(str(path), path.stat().st_dev, path.stat().st_ino) for path in protected]}


def _prepare_id(request_ref):
    return "campaign-training-prepare:" + request_ref["sha256"]


def _binding_id(owner, run_id):
    return "campaign-training-run:" + _digest({"owner": owner, "run_id": run_id})


def _prepare_payload(request, request_ref):
    return {"request_artifact": request_ref, "owner": request["owner"], "worker_id": request["worker_id"]}


def _bind_payload(request, request_ref, batch):
    return {**_prepare_payload(request, request_ref), "run_id": batch["run_id"],
            "job_spec_sha256": batch["job_spec_sha256"], "preparation_operation_id": _prepare_id(request_ref)}


def _receipt(operation_id, command, payload):
    return {"schema": REGISTRY_SCHEMA, "operation_id": operation_id, "command": command,
            "admitted": False, **payload, "status": "prepared"}


def _history(registry, request, request_ref, *, required):
    operation_id = _prepare_id(request_ref)
    payload = _prepare_payload(request, request_ref)
    expected = _receipt(operation_id, PREPARE_COMMAND, payload)
    receipt = registry.resolve_operation(operation_id, PREPARE_COMMAND, payload)
    _require(receipt is None or _same(receipt, expected), "preparation receipt differs")
    for batch in request["batches"]:
        binding_id = _binding_id(request["owner"], batch["run_id"])
        bound_payload = _bind_payload(request, request_ref, batch)
        bound = registry.resolve_operation(binding_id, BIND_COMMAND, bound_payload)
        _require((bound is None) == (receipt is None), "partial preparation history")
        if bound is not None:
            _require(_same(bound, _receipt(binding_id, BIND_COMMAND, bound_payload)), "run binding receipt differs")
    _require(not required or receipt is not None, "request is not registered for owned preparation")
    return receipt


def _journal_binding(request, request_ref):
    return {"schema": codec.SCHEMA, "owner": request["owner"], "request_artifact": request_ref}


def _journal_paths(request, *, existing):
    output = _safe_path(request["output_root"], directory=True)
    journal, lock = output / _JOURNAL, output / ("." + _JOURNAL + ".lock")
    names = set()
    with os.scandir(output) as entries:
        for entry in entries:
            names.add(entry.name)
            _require(len(names) <= 2, "control directory contains unrelated artifacts")
    _require(names <= {journal.name, lock.name}, "control directory contains unrelated artifacts")
    if existing or names:
        _require(names == {journal.name, lock.name}, "prepared journal is missing or incomplete")
        for path in (journal, lock):
            path = _safe_path(path)
            _require(path.stat().st_nlink == 1, "prepared journal has aliases")
    return journal, not names


def _stage(registry, raw):
    descriptor, path = tempfile.mkstemp(prefix=".campaign-training-request-", dir=registry.artifact_root)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        ref = {"sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw)}
        _require(_same(registry.stage_artifact(path, expected_sha256=ref["sha256"]), ref), "staged request differs")
        return ref
    finally:
        Path(path).unlink(missing_ok=True)


def _recheck_rows(registry, request, resolved):
    _require(_same(_owner(registry), request["owner"]), "owner changed")
    _namespace(request, resolved)
    for item in resolved:
        _require(_same(registry.get_run(item["run"]["run_id"]), item["run"]), "run changed during preparation")
        _require(_same(registry.get_version(item["spec"].base_version_id), item["base_version"]),
                 "base version changed during preparation")
    _require(_same(registry.get_variant(request["variant_id"])["manifest"], resolved[0]["variant"]),
             "variant changed during preparation")


def _register(registry, request, request_ref, resolved):
    payload, operation_id = _prepare_payload(request, request_ref), _prepare_id(request_ref)
    selected = {batch["run_id"] for batch in request["batches"]}

    def apply(connection):
        # Database checks only: no hashing, filesystem calls or model work
        # while this short transaction serializes the single owner.
        for item in resolved:
            run = registry._run(connection, item["run"]["run_id"])
            _require(_same(run, item["run"]), "run changed before assignment commit")
            _require(_same(registry._version(connection, item["spec"].base_version_id), item["base_version"]),
                     "base version changed before commit")
            if run["run_id"] in selected:
                _require(run["status"] == "queued" and run["attempt"] == run["fence"] == 0
                         and run["lease"] is None and run["result"] is None, "selected run is no longer pristine")
        variant = connection.execute("SELECT manifest FROM autoencoder_control.variants WHERE variant_id=?",
                                     [request["variant_id"]]).fetchone()
        _require(variant is not None and _same(json.loads(variant[0]), resolved[0]["variant"]), "variant changed before commit")
        for batch in request["batches"]:
            binding_id = _binding_id(request["owner"], batch["run_id"])
            _require(connection.execute("SELECT 1 FROM autoencoder_control.operations WHERE operation_id=?",
                                        [binding_id]).fetchone() is None, "run already has a prepared assignment")
            bound_payload = _bind_payload(request, request_ref, batch)
            bound = _receipt(binding_id, BIND_COMMAND, bound_payload)
            connection.execute("INSERT INTO autoencoder_control.operations VALUES (?, ?, ?)",
                [binding_id, registry._command_digest(binding_id, BIND_COMMAND, bound_payload),
                 canonical_json_bytes(bound).decode()])
        return {**payload, "status": "prepared"}

    try:
        result = registry._mutate(operation_id, PREPARE_COMMAND, payload, apply)
    except Exception:
        # A lost response can follow a committed transaction. Only this exact
        # operation is resolved; never allocate a replacement or start a job.
        try:
            result = registry.resolve_operation(operation_id, PREPARE_COMMAND, payload)
        except Exception:
            result = None
        if result is None:
            raise
    _require(_same(result, _receipt(operation_id, PREPARE_COMMAND, payload)), "registration receipt differs")
    return result


def prepare_campaign_training(registry, plan_artifact, *, selected_batch_ids, worker_id,
                              output_root, resource_policy, execution_policy):
    """Seal and atomically bind a pristine v8 selection without execution.

    Identical preparation can be repeated while the jobs remain pristine. A
    missing journal cannot be recreated for an already bound assignment.
    Failures may retain a staged request/journal, and post-commit guard failure
    does not roll back the historical binding. No original run is modified.
    """
    owner, source = _owner(registry), _sources()
    plan_artifact = _copy_input(plan_artifact)
    plans._ref(plan_artifact)
    selected_batch_ids = _copy_input(selected_batch_ids)
    resource_policy, execution_policy = _copy_input(resource_policy), _copy_input(execution_policy)
    codec._resource_policy(resource_policy)
    codec._execution_policy(execution_policy)
    _pin()
    plan, resolved, artifacts, identities = _capture(registry, plan_artifact)
    selected = _selection(plan, resolved, selected_batch_ids)
    request = {"schema_version": codec.SCHEMA, "owner": owner, "plan_artifact": dict(plan_artifact),
        "worker_id": worker_id, "output_root": str(output_root), "variant_id": plan["variant_id"],
        "variant_manifest_sha256": plan["variant_manifest_sha256"], "source_campaign_binding": plan["source_campaign_binding"],
        "parent_policy": plan["parent_policy"], "batches": [_batch(batch, item) for batch, item in selected],
        "resource_policy": resource_policy, "execution_policy": execution_policy,
        **{field: False for field in codec.FALSE_FIELDS}}
    raw = codec.encode_campaign_training_request(request)
    request = codec.decode_campaign_training_request(raw)
    request_ref = {"sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw)}
    _namespace(request, resolved)
    path_state = _path_state(request, require_pristine=True, selected=selected)
    old = _history(registry, request, request_ref, required=False)
    journal_path, create_journal = _journal_paths(request, existing=old is not None)
    _check_sources(source)
    _guard_artifacts(artifacts, identities)
    _stage(registry, raw)
    _guard_artifacts(artifacts, identities)
    _recheck_rows(registry, request, resolved)
    _require(path_state == _path_state(request, require_pristine=True, selected=selected), "resource paths changed")
    _check_sources(source)
    with DurableDaemonOperationJournal(journal_path, _journal_binding(request, request_ref), create=create_journal) as journal:
        saved = journal.get_metadata("prepared")
        expected = {"request_artifact": request_ref, "journal_path": str(journal_path)}
        _require(saved is None or _same(saved, expected), "journal prepared request differs")
        _require(old is None or saved is not None, "registered request has no prepared journal record")
        saved_registration = journal.get_metadata("registration")
        _require(saved_registration is None or (old is not None and _same(saved_registration, old)),
                 "journal registration differs from durable history")
        _require(not journal.operations(), "preparation cannot reuse an execution journal")
        if saved is None:
            journal.set_metadata("prepared", expected)
        _guard_artifacts(artifacts, identities)
        _require(path_state == _path_state(request, require_pristine=True, selected=selected), "resource paths changed")
        _check_sources(source)
        result = _register(registry, request, request_ref, resolved)
        journal.set_metadata("registration", result)
        _guard_artifacts(artifacts, identities)
        _read(registry, request_ref, codec.MAX_REQUEST_BYTES)
        _recheck_rows(registry, request, resolved)
        _require(path_state == _path_state(request, require_pristine=True, selected=selected), "resource paths changed")
        _check_sources(source)
        _history(registry, request, request_ref, required=True)
        _require(_same(journal.get_metadata("prepared"), expected), "prepared journal changed")
        _require(_same(journal.get_metadata("registration"), result), "journal registration changed")
    return {"request_artifact": request_ref, "journal_path": str(journal_path), "registration": result}


def inspect_campaign_training(registry, request_artifact):
    """Read current inputs and durable assignment; never qualify completion.

    Registry status and pristine eligibility are observations. A completed row
    remains unverified here because candidate replay belongs to execution's
    independent verifier. Missing journals reject without creating new ones.
    """
    owner, source = _owner(registry), _sources()
    request_artifact = _copy_input(request_artifact)
    plans._ref(request_artifact)
    _pin()
    request = codec.decode_campaign_training_request(_read(registry, request_artifact, codec.MAX_REQUEST_BYTES))
    _require(_same(request["owner"], owner), "request belongs to another owner")
    plan, resolved, artifacts, identities = _capture(registry, request["plan_artifact"])
    selected = _selection(plan, resolved, [batch["batch_id"] for batch in request["batches"]])
    _require(_same(request["batches"], [_batch(batch, item) for batch, item in selected]), "request jobs differ from plan")
    for key in ("variant_id", "variant_manifest_sha256", "source_campaign_binding", "parent_policy"):
        _require(_same(request[key], plan[key]), "request campaign binding differs")
    _namespace(request, resolved)
    path_state = _path_state(request, require_pristine=False, selected=selected)
    registration = _history(registry, request, request_artifact, required=True)
    journal_path, _ = _journal_paths(request, existing=True)
    with DurableDaemonOperationJournal(journal_path, _journal_binding(request, request_artifact), create=False) as journal:
        _require(_same(journal.get_metadata("prepared"),
                      {"request_artifact": request_artifact, "journal_path": str(journal_path)}), "prepared journal differs")
        local = journal.get_metadata("registration")
        _require(local is None or _same(local, registration), "journal registration differs")
        execution_history_present = bool(journal.operations())
        rows = [{"batch_id": batch["batch_id"], "run_id": item["run"]["run_id"], "job_id": item["spec"].job_id,
                 "registry_status": item["run"]["status"], "attempt": item["run"]["attempt"], "fence": item["run"]["fence"],
                 "pristine_queued": _pristine(item["run"], item["spec"].output_directory), "completion_verified": False}
                for batch, item in selected]
        _guard_artifacts(artifacts, identities)
        _read(registry, request_artifact, codec.MAX_REQUEST_BYTES)
        _recheck_rows(registry, request, resolved)
        _require(path_state == _path_state(request, require_pristine=False, selected=selected), "resource paths changed")
        _check_sources(source)
        _history(registry, request, request_artifact, required=True)
        _require(_same(journal.get_metadata("registration"), local), "journal registration changed")
    count = sum(row["pristine_queued"] for row in rows)
    return {"schema_version": STATUS_SCHEMA, "request_artifact": dict(request_artifact), "registration": registration,
        "batch_count": len(rows), "batches": rows, "pristine_queued_count": count,
        "status": "prepared" if count == len(rows) and not execution_history_present else "recovery_required",
        "execution_history_present": execution_history_present, "execution_available": False,
        "capacity_admitted": False, **{field: False for field in codec.FALSE_FIELDS}}


def execute_prepared_campaign_training(registry, request_artifact, *, max_new_batches=1, max_workers=1):
    """Execute a bounded slice of the original prepared jobs under their owner."""
    from .autoencoder_campaign_owned_execution import execute_prepared_campaign_training as execute
    return execute(registry, request_artifact, max_new_batches=max_new_batches, max_workers=max_workers)


__all__ = ["CampaignOwnedTrainingError", "prepare_campaign_training", "inspect_campaign_training",
           "execute_prepared_campaign_training"]
