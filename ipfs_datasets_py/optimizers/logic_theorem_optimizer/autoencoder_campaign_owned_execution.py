"""Owned execution of the original sealed v8 campaign jobs.

The public entry uses supervised, isolated native workers. The private test seam
always records injected execution. Registry completion still uses the existing
coordinator and campaign replay verifier; this module supplies neither a second
optimizer nor a second definition of successful training or formalization.
"""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
import time

from . import autoencoder_campaign_owned_training as preparation
from . import autoencoder_campaign_plan as plans
from . import autoencoder_campaign_training_request as codec
from . import autoencoder_training_coordinator as coordinator
from .autoencoder_daemon_operation_journal import DurableDaemonOperationJournal, MAX_JOURNAL_BYTES
from .autoencoder_daemon_resources import DaemonResourceReservation, _inventory, _safe_path

STATUS_SCHEMA = "autoencoder-campaign-owned-execution-status-v1"
RECORD_SCHEMA = "autoencoder-campaign-owned-execution-record-v1"
MAX_RECORD_BYTES = 65_536
_FALSE = ("admitted", "formalized", "promotion_performed", "publication_performed",
          "source_authority_authenticated", "global_holdout_verified")
_require = preparation._require
_same = preparation._same


def _key(kind, run_id):
    return kind + "-" + hashlib.sha256(run_id.encode()).hexdigest()


def _sources():
    result = preparation._sources()
    for name in (__file__, Path(__file__).with_name("autoencoder_campaign_process.py"),
                 Path(__file__).with_name("autoencoder_campaign_process_worker.py"),
                 Path(__file__).with_name("autoencoder_daemon_resources.py")):
        path = _safe_path(name)
        raw = coordinator._read_bounded(path, 4 * 1024 * 1024)
        result[str(path)] = {"sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw)}
    return result


def _check_sources(before):
    _require(_same(before, _sources()), "owned execution source changed")


def _record(registry, journal, request_ref, spec, kind):
    descriptor = journal.get_metadata(_key(kind, spec.run_id))
    if descriptor is None:
        return None
    raw = preparation._read(registry, descriptor, MAX_RECORD_BYTES)
    value = coordinator._read_json(raw)
    _require(type(value) is dict and set(value) == {
        "schema_version", "request_artifact", "run_id", "job_spec_sha256", "kind", "prior", "record"},
        "invalid owned execution record")
    _require(value["schema_version"] == RECORD_SCHEMA and value["kind"] == kind
             and value["run_id"] == spec.run_id and value["job_spec_sha256"] == spec.canonical_sha256
             and _same(value["request_artifact"], request_ref), "owned execution record binding differs")
    _require(type(value["record"]) is dict and coordinator._bytes(value) == raw,
             "owned execution record is not canonical")
    if value["prior"] is not None:
        plans._ref(value["prior"])
    record = value["record"]
    if kind in ("resource", "replay_resource"):
        _require(set(record) == {"reservation_id", "attempt_directory", "purpose", "status"}
                 and type(record["reservation_id"]) is str and bool(record["reservation_id"])
                 and type(record["attempt_directory"]) is str
                 and record["purpose"] == ("replay" if kind == "replay_resource" else "training")
                 and record["status"] in ("active", "release_pending"), "invalid resource record")
    return value["record"]


class _OwnerResources:
    """One independently admitted reservation for each worker or replay.

    Worker output paths stay unchanged. Their observed high-water size is
    conservatively charged outside the small control attempt. CAS copies and
    compaction scratch are charged before coordinator staging. These checks
    are cooperative observations, not a filesystem or kernel quota.
    """

    def __init__(self, registry, request, request_ref, journal, factory, deadline):
        self.registry, self.request, self.request_ref = registry, request, request_ref
        self.journal, self.factory, self.deadline = journal, factory, deadline
        self.entries = {}
        self.history = []

    def time_left(self):
        remaining = self.deadline - time.monotonic()
        _require(remaining > 0, "owned invocation deadline exceeded")
        return remaining

    def save(self, entry, kind, value):
        self.time_left()
        spec = entry["spec"]
        key = _key(kind, spec.run_id)
        body = {"schema_version": RECORD_SCHEMA, "request_artifact": self.request_ref,
                "run_id": spec.run_id, "job_spec_sha256": spec.canonical_sha256,
                "kind": kind, "prior": self.journal.get_metadata(key), "record": value}
        raw = coordinator._bytes(body)
        _require(len(raw) <= MAX_RECORD_BYTES, "owned execution record exceeds bound")
        entry["charge_number"] += 1
        entry["reservation"].account_external_bytes(
            "control-record-" + str(entry["charge_number"]), 2 * len(raw))
        descriptor = preparation._stage(self.registry, raw)
        self.journal.set_metadata(key, descriptor)
        _require(_same(_record(self.registry, self.journal, self.request_ref, spec, kind), value),
                 "owned record changed after publication")

    def admit(self, spec, *, replay=False):
        self.time_left()
        _require(spec.run_id not in self.entries, "job already has an active reservation")
        kind = "replay_resource" if replay else "resource"
        previous = _record(self.registry, self.journal, self.request_ref, spec, kind)
        _require(previous is None or (replay and _released(self.journal, previous, kind, spec.run_id)),
                 "existing resource claim requires explicit recovery")
        policy = self.request["resource_policy"]
        reservation = self.factory(policy["ledger_path"], roots=policy["roots"],
            storage_bytes=policy["storage_bytes"], memory_mb=policy["memory_mb"],
            cpu_slots=policy["cpu_slots"], timeout_seconds=0, ledger_lock_timeout_seconds=5)
        token = str(reservation.reservation_id)
        _require(token and len(token) <= 128 and all(c.isalnum() or c in "_-" for c in token),
                 "invalid resource reservation identity")
        control = Path(self.request["output_root"])
        attempt = control.parent / (".campaign-" + self.request_ref["sha256"][:16] + "-" + token)
        _safe_path(attempt, directory=True, missing=True)
        _require(not os.path.lexists(attempt), "owned control attempt already exists")
        _require(any(attempt == Path(root) or Path(root) in attempt.parents for root in policy["roots"]),
                 "owned control attempt is outside resource roots")
        protected = [control, Path(self.request["owner"]["database_path"]),
                     Path(self.request["owner"]["artifact_root"]),
                     *(Path(row["output_directory"]) for row in self.request["batches"])]
        _require(all(attempt != path and attempt not in path.parents and path not in attempt.parents
                     for path in protected), "owned attempt overlaps protected storage")
        output = Path(spec.output_directory)
        parent = _safe_path(output.parent, directory=True).stat()
        entry = {"spec": spec, "reservation": reservation, "attempt": attempt,
                 "kind": kind, "output_parent": (parent.st_dev, parent.st_ino),
                 "output_identity": None, "output_high_water": 0, "output_charge_number": 0,
                 "charge_number": 0, "released": False, "closed": False}
        self.history.append(entry)
        try:
            reservation.__enter__()
        except BaseException:
            # Admission may retain a ledger row if host scheduling failed.
            # Keep that evidence in the report even though no run was claimed.
            entry["closed"] = True
            raise
        self.entries[spec.run_id] = entry
        try:
            attempt.mkdir(mode=0o700)
            # The journal is outside every worker attempt. Include replacement
            # scratch plus the complete bounded journal before any mutation.
            reservation.account_external_bytes("owner-journal", 2 * MAX_JOURNAL_BYTES)
            self.save(entry, kind, {"reservation_id": token, "attempt_directory": str(attempt),
                "purpose": "replay" if replay else "training", "status": "active"})
            self.check(entry)
            return entry
        except BaseException:
            reservation.__exit__(*__import__("sys").exc_info())
            entry["closed"] = True
            raise

    def observe_output(self, entry):
        self.time_left()
        output = Path(entry["spec"].output_directory)
        parent = _safe_path(output.parent, directory=True).stat()
        _require((parent.st_dev, parent.st_ino) == entry["output_parent"], "worker output parent changed")
        if not os.path.lexists(output):
            _require(entry["output_identity"] is None, "worker output disappeared")
            return
        info = _safe_path(output, directory=True).stat()
        identity = (info.st_dev, info.st_ino)
        _require(entry["output_identity"] in (None, identity), "worker output directory changed")
        entry["output_identity"] = identity
        size = _inventory([output], strict=True)["apparent_bytes"]
        if size > entry["output_high_water"]:
            # Geometric allowances avoid one ledger update for every small
            # accepted patch. Charges are conservative capacity, not byte
            # measurements; the strict inventory remains the observed size.
            allowance = max(65_536, entry["output_high_water"])
            while allowance < size:
                allowance *= 2
            entry["output_charge_number"] += 1
            entry["reservation"].account_external_bytes(
                "worker-output-" + str(entry["output_charge_number"]), allowance - entry["output_high_water"])
            entry["output_high_water"] = allowance

    def check(self, entry):
        self.observe_output(entry)
        return entry["reservation"].check_usage(entry["attempt"])

    def before_prepare(self, spec, receipt):
        entry = self.entries[spec.run_id]
        self.check(entry)
        _require(type(receipt) is dict, "worker returned no receipt object")
        def size(value):
            _require(type(value) is dict and type(value.get("bytes")) is int
                     and 0 < value["bytes"] <= self.request["resource_policy"]["storage_bytes"],
                     "worker artifact exceeds declared storage")
            return value["bytes"]
        charge = len(coordinator._bytes(receipt)) + size(receipt.get("candidate"))
        segments = receipt.get("sparse_patch_segments")
        _require(type(segments) is list and len(segments) <= spec.training_config.epochs,
                 "invalid sparse segment inventory")
        charge += sum(size(segment) for segment in segments)
        if spec.candidate_storage == "sparse":
            charge += 2 * size(receipt.get("candidate_materialized_checkpoint"))
        # The values are conservative reservation inputs only. The original
        # coordinator independently verifies every byte and state identity.
        entry["reservation"].account_external_bytes("owner-completion", charge)

    def release(self, entry):
        self.check(entry)
        for directory in (entry["attempt"], Path(entry["spec"].output_directory)):
            if directory.exists():
                descriptor = os.open(directory, os.O_RDONLY | os.O_DIRECTORY)
                try:
                    os.fsync(descriptor)
                finally:
                    os.close(descriptor)
        # Persist a release intent while the reservation still covers its CAS
        # and journal bytes. An interrupted release remains explicit recovery.
        previous = _record(self.registry, self.journal, self.request_ref, entry["spec"], entry["kind"])
        self.save(entry, entry["kind"], {**previous, "status": "release_pending"})
        result = entry["reservation"].release(artifacts_durable=True)
        _require(result.get("status") == "released", "reservation release was not confirmed")
        entry["released"] = True
        # The already reserved journal allowance covers this bounded final
        # status write; no model or worker artifact is written after release.
        key = _key(entry["kind"], entry["spec"].run_id)
        entry["release_receipt"] = result
        self.journal.set_metadata(key + "-released", {
            "status": "released",
            "reservation_id": entry["reservation"].reservation_id,
            "resource_record": self.journal.get_metadata(key)})
        self.entries.pop(entry["spec"].run_id)

    def close(self):
        failures = []
        for entry in self.history:
            if not entry["closed"]:
                try:
                    entry["reservation"].__exit__(None, None, None)
                    entry["closed"] = True
                except BaseException as exc:
                    failures.append(exc)
        if failures:
            raise preparation.CampaignOwnedTrainingError("one or more resource claims require recovery") from failures[0]

    def report(self):
        return [{"run_id": entry["spec"].run_id, "purpose": entry["kind"],
                 "reservation": entry["reservation"].to_dict(), "released": entry["released"]}
                for entry in self.history]


def _released(journal, record, kind, run_id):
    if record is None:
        return False
    marker = journal.get_metadata(_key(kind, run_id) + "-released")
    return (record.get("status") == "release_pending" and type(marker) is dict
            and set(marker) == {"status", "reservation_id", "resource_record"}
            and marker.get("status") == "released"
            and marker.get("reservation_id") == record.get("reservation_id")
            and _same(marker.get("resource_record"), journal.get_metadata(_key(kind, run_id))))


def _operation_membership(journal, selected):
    """History observations cannot reach another request's registered jobs."""
    run_ids = {item["spec"].run_id for _, item in selected}
    kinds = {"ClaimRun": "claim", "RenewLease": "renew", "CompleteRun": "complete", "FailRun": "fail"}
    for slot, operation in journal.operations().items():
        payload = operation["payload"]
        run_id = payload.get("run_id", payload.get("lease", {}).get("run_id"))
        kind = kinds.get(operation["command"])
        _require(run_id in run_ids and kind is not None, "journal operation is outside prepared jobs")
        ordinal = None
        if kind == "renew":
            suffix = slot.rsplit("-", 1)[-1]
            _require(suffix.isascii() and suffix.isdecimal(), "invalid journal renewal ordinal")
            ordinal = int(suffix)
        _require(slot == coordinator._owned_operation_slot(run_id, kind, ordinal),
                 "journal operation slot differs from prepared job")


def _load(registry, request_artifact):
    owner = preparation._owner(registry)
    request_ref = preparation._copy_input(request_artifact)
    plans._ref(request_ref)
    preparation._pin()
    request = codec.decode_campaign_training_request(preparation._read(registry, request_ref, codec.MAX_REQUEST_BYTES))
    _require(_same(request["owner"], owner), "request belongs to another owner")
    plan, resolved, artifacts, identities = preparation._capture(registry, request["plan_artifact"])
    selected = preparation._selection(plan, resolved, [row["batch_id"] for row in request["batches"]])
    _require(_same(request["batches"], [preparation._batch(batch, item) for batch, item in selected]),
             "prepared jobs differ from current plan")
    for field in ("variant_id", "variant_manifest_sha256", "source_campaign_binding", "parent_policy"):
        _require(_same(request[field], plan[field]), "prepared campaign binding differs")
    preparation._namespace(request, resolved)
    preparation._path_state(request, require_pristine=False, selected=selected)
    registration = preparation._history(registry, request, request_ref, required=True)
    journal_path, _ = preparation._journal_paths(request, existing=True)
    return request, request_ref, plan, resolved, selected, artifacts, identities, registration, journal_path


def execute_prepared_campaign_training(registry, request_artifact, *, max_new_batches=1, max_workers=1):
    """Execute an explicit bounded slice of original jobs under their owner.

    Native qualification is separate from this callable implementation. No
    branch head, legal admission, corpus status or publication is promoted.
    Uncertain prior starts require explicit recovery; they never restart here.
    """
    return _execute_prepared_campaign_training(registry, request_artifact,
        max_new_batches=max_new_batches, max_workers=max_workers)


def _execute_prepared_campaign_training(registry, request_artifact, *, max_new_batches=1, max_workers=1,
        executor_factory=None, worker_function=coordinator.execute_training_job,
        reservation_factory=DaemonResourceReservation):
    """Private injected test path; injection cannot establish native identity."""
    _require(type(max_new_batches) is int and 1 <= max_new_batches <= codec.MAX_BATCHES,
             "invalid owned dispatch batch bound")
    _require(type(max_workers) is int and 1 <= max_workers <= codec.MAX_WORKERS,
             "invalid owned worker bound")
    native = (executor_factory is None and worker_function is coordinator.execute_training_job
              and reservation_factory is DaemonResourceReservation)
    _require(native or (executor_factory is not None and worker_function is not coordinator.execute_training_job),
             "injected execution requires an explicit test executor and test worker")
    started, sources = time.monotonic(), _sources()
    request, request_ref, plan, resolved, selected, artifacts, identities, registration, journal_path = _load(
        registry, request_artifact)
    policy = request["execution_policy"]
    _require(max_workers <= policy["max_workers"], "worker count exceeds sealed execution policy")
    _require(native or not (policy["defer_target_hydration_gc"] or policy["reduce_native_targets"]),
             "native runtime flags cannot be exercised by injected execution")
    deadline = started + policy["timeout_seconds"]
    with DurableDaemonOperationJournal(journal_path, preparation._journal_binding(request, request_ref), create=False) as journal:
        _require(_same(journal.get_metadata("prepared"),
            {"request_artifact": request_ref, "journal_path": str(journal_path)}), "prepared journal differs")
        saved = journal.get_metadata("registration")
        _require(saved is None or _same(saved, registration), "journal registration differs")
        _operation_membership(journal, selected)
        # Resolve existing receipts only. No pending intent may become a new
        # claim or computation during this recovery observation.
        unresolved = []
        for slot in journal.pending():
            try:
                if journal.resolve(registry, slot) is None:
                    unresolved.append(slot)
            except Exception:
                unresolved.append(slot)
        manager = _OwnerResources(registry, request, request_ref, journal, reservation_factory, deadline)
        supervisor = None
        dispatched, rows, dispatch = [], [], None
        try:
            def guard():
                manager.time_left()
                preparation._guard_artifacts(artifacts, identities)
                _check_sources(sources)
                preparation._history(registry, request, request_ref, required=True)

            for batch, item in selected:
                spec, run = item["spec"], item["run"]
                row = {"batch_id": batch["batch_id"], "run_id": spec.run_id,
                       "job_id": spec.job_id, "registry_status": run["status"], "completion_verified": False,
                       "supervised_native_execution_verified": False}
                resource = _record(registry, journal, request_ref, spec, "resource")
                prior_start = _record(registry, journal, request_ref, spec, "start")
                if run["status"] == "completed" and not unresolved:
                    entry = manager.admit(spec, replay=True)
                    version = plans._completed(registry, item)
                    manager.check(entry)
                    row.update(status="completed", completion_verified=True,
                               candidate_version_id=version["version_id"], candidate=version["artifact"],
                               execution_mode=run["result"]["execution_mode"])
                    guard()
                    manager.release(entry)
                    if resource is not None and not _released(journal, resource, "resource", spec.run_id):
                        row["status"] = "recovery_required"
                        row["reason"] = "prior_resource_release_unresolved"
                    elif resource is not None and prior_start is not None:
                        row["supervised_native_execution_verified"] = bool(
                            prior_start.get("state") == "observed" and prior_start.get("child")
                            and prior_start.get("execution_mode") == row["execution_mode"] == "native_training")
                elif preparation._pristine(run, spec.output_directory) and resource is None and prior_start is None:
                    own_slots = [slot for slot, operation in journal.operations().items()
                        if operation["payload"].get("run_id", operation["payload"].get("lease", {}).get("run_id")) == spec.run_id]
                    row["status"] = "queued" if not own_slots else "recovery_required"
                else:
                    row.update(status="recovery_required", reason="existing_attempt_requires_explicit_recovery")
                rows.append(row)
            ready = [] if unresolved or any(row["status"] == "recovery_required" for row in rows) else [
                item["spec"] for row, (_, item) in zip(rows, selected, strict=True) if row["status"] == "queued"][:max_new_batches]
            preparation._guard_artifacts(artifacts, identities)
            _check_sources(sources)
            if ready:
                coordinator._owned_journal_capacity(journal, run_count=len(ready), max_workers=max_workers,
                    lease_seconds=policy["lease_seconds"], poll_seconds=policy["poll_seconds"],
                    timeout_seconds=manager.time_left())

                def record_start(spec, lease, job_artifact):
                    _require(_record(registry, journal, request_ref, spec, "start") is None,
                             "prior start intent cannot be repeated")
                    manager.save(manager.entries[spec.run_id], "start", {
                        "state": "intent", "lease": lease, "job_artifact": job_artifact,
                        "execution_mode": "native_training" if native else "injected_test"})

                def record_child(spec, lease, job_artifact, identity):
                    prior = _record(registry, journal, request_ref, spec, "start")
                    _require(prior is not None and prior["state"] == "intent"
                             and _same(prior["lease"], lease) and _same(prior["job_artifact"], job_artifact),
                             "child identity does not match start intent")
                    manager.save(manager.entries[spec.run_id], "start", {**prior, "state": "observed", "child": identity})

                if native:
                    from .autoencoder_campaign_process import _CampaignProcessExecutor
                    supervisor = _CampaignProcessExecutor(record_start=record_start, record_child=record_child,
                        timeout_seconds=manager.time_left(), max_workers=max_workers,
                        defer_target_hydration_gc=policy["defer_target_hydration_gc"],
                        reduce_native_targets=policy["reduce_native_targets"])

                def before_claim(spec):
                    preparation._guard_artifacts(artifacts, identities)
                    _check_sources(sources)
                    _require(preparation._pristine(registry.get_run(spec.run_id), spec.output_directory),
                             "selected job is no longer pristine")
                    entry = manager.admit(spec)
                    ref = registry.get_run(spec.run_id)["spec"]["job_spec_artifact"]
                    descriptor = {**ref, "path": str(registry.artifact_path(ref))}
                    if supervisor is not None:
                        supervisor.register(spec, reservation=entry["reservation"],
                            attempt_directory=entry["attempt"], job_artifact=descriptor,
                            usage_check=lambda: manager.observe_output(entry))

                def after_terminal(spec, terminal_report):
                    row, item = next((row, item) for row, (_, item) in zip(rows, selected, strict=True)
                                     if row["run_id"] == spec.run_id)
                    item["run"] = registry.get_run(spec.run_id)
                    row["registry_status"] = item["run"]["status"]
                    if item["run"]["status"] != "completed" or journal.pending():
                        row.update(status="recovery_required", reason="dispatch_or_completion_requires_recovery")
                        if not journal.pending():
                            if supervisor is not None:
                                supervisor.retire(spec)
                            entry = manager.entries[spec.run_id]
                            entry["reservation"].__exit__(None, None, None)
                            entry["closed"] = True
                        return
                    entry = manager.entries[spec.run_id]
                    manager.check(entry)
                    version = plans._completed(registry, item)
                    guard()
                    if supervisor is not None:
                        supervisor.retire(spec)
                    manager.release(entry)
                    row.update(status="completed", completion_verified=True,
                        candidate_version_id=version["version_id"], candidate=version["artifact"],
                        execution_mode=item["run"]["result"]["execution_mode"],
                        supervised_native_execution_verified=native)

                def before_prepare(spec, receipt):
                    # The public coordinator deliberately labels all injected
                    # executors as tests. Reject a conflicting producer label
                    # here, before it can become an inconsistent completed row.
                    expected_mode = "native_training" if native else "injected_test"
                    _require(type(receipt) is dict and receipt.get("execution_mode") == expected_mode,
                             "owned worker receipt execution mode differs")
                    manager.before_prepare(spec, receipt)

                dispatch = coordinator._run_owned_training_jobs(registry, ready,
                    operation_journal=journal, supervisor=supervisor, before_claim=before_claim,
                    before_prepare=before_prepare, worker_id=request["worker_id"],
                    before_submit=None if native else record_start, after_terminal=after_terminal,
                    timeout_seconds=manager.time_left(), max_workers=max_workers,
                    lease_seconds=policy["lease_seconds"], poll_seconds=policy["poll_seconds"],
                    executor_factory=executor_factory, worker_function=worker_function,
                    defer_target_hydration_gc=policy["defer_target_hydration_gc"],
                    reduce_native_targets=policy["reduce_native_targets"],
                    sparse_checkpoint_policy=coordinator.SparseCheckpointPolicy(**policy["sparse_checkpoint_policy"]))
                dispatched = [spec.run_id for spec in ready if journal.receipt(coordinator._owned_operation_slot(spec.run_id, "claim"))]
                for row, (_, item) in zip(rows, selected, strict=True):
                    spec = item["spec"]
                    if spec.run_id not in manager.entries:
                        continue
                    item["run"] = registry.get_run(spec.run_id)
                    row["registry_status"] = item["run"]["status"]
                    row.update(status="recovery_required", reason="dispatch_or_completion_requires_recovery")
            guard()
            pending = list(journal.pending())
            recovery = bool(unresolved or pending or (dispatch and dispatch.get("recovery_required"))
                            or any(row["status"] == "recovery_required" for row in rows))
            complete = all(row["status"] == "completed" and row["completion_verified"] for row in rows)
            if supervisor is not None:
                supervisor.close()
            manager.close()
            return {"schema_version": STATUS_SCHEMA, "request_artifact": request_ref,
                "status": "recovery_required" if recovery else "complete" if complete else "ready",
                "batch_count": len(rows), "batches": rows, "dispatch": dispatch,
                "dispatched_run_ids": dispatched,
                "completed_run_ids": [row["run_id"] for row in rows if row["completion_verified"]],
                "deferred_run_ids": [row["run_id"] for row in rows if row["status"] == "queued"],
                "pending_operation_slots": pending, "unresolved_operation_slots": unresolved,
                "resources": manager.report(), "execution_mode": "native_training" if native else "injected_test",
                "native_execution_verified": native and complete and not recovery and all(
                    row["supervised_native_execution_verified"] for row in rows),
                "training_dispatched": bool(dispatched), "elapsed_seconds": time.monotonic() - started,
                **{name: False for name in _FALSE}}
        finally:
            try:
                if supervisor is not None:
                    supervisor.close()
            finally:
                manager.close()


__all__ = ["execute_prepared_campaign_training"]


F18_STATUS_SCHEMA = "autoencoder-campaign-owned-f18-status/v1"


def _f18_output_inventory(spec, *, complete=False):
    output = Path(spec.output_directory)
    if not os.path.lexists(output):
        _require(not complete, "F18 output is missing")
        return None, 0
    output = _safe_path(output, directory=True)
    info = output.stat()
    if complete:
        entries = list(output.iterdir())
        _require(len(entries) == 3 and {p.name for p in entries} == {
            "checkpoint.json", "report.json", "receipt.json"}, "fixed F18 output inventory differs")
        for path in entries:
            _safe_path(path)
    return (info.st_dev, info.st_ino), _inventory([output], strict=True)["apparent_bytes"]


def _f18_verify_artifacts(spec, receipt, job_artifact):
    owner = preparation._f18_owner()
    receipt = owner.validate_receipt(spec, receipt, job_file_sha256=job_artifact["sha256"])
    _f18_output_inventory(spec, complete=True)
    for key, maximum in (("checkpoint", owner.MAX_CHECKPOINT_BYTES), ("report", owner.MAX_REPORT_BYTES)):
        owner._read_descriptor(receipt[key], maximum, retain=False)
    path = _safe_path(Path(spec.output_directory) / "receipt.json")
    raw = coordinator._read_bounded(path, owner.MAX_RECEIPT_BYTES)
    _require(raw == owner._canonical(receipt), "persisted F18 receipt differs from worker result")
    descriptor = {"path": str(path), "bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}
    preparation._read_bound(path, {key: descriptor[key] for key in ("bytes", "sha256")})
    return receipt, descriptor


def execute_prepared_f18_conditions_training(request, *, expected_request_sha256):
    """Fixed original-owner path; source/purpose admission belongs to the caller.

    A request/preparation is not a resource grant. Prior output or journal is
    explicit recovery, never an automatic resume or a fresh consumed start.
    """
    return _execute_f18_conditions_training(request, expected_request_sha256=expected_request_sha256)


def _execute_prepared_f18_conditions_training_for_test(request, *, expected_request_sha256,
                                                      reservation_factory, executor_factory, input_check):
    """Fixture-only adapters never establish payload integrity or native credit.

    input_check must return None. It can inject a lifecycle failure, but cannot
    present cached metadata as a native resource grant or verified input bytes.
    """
    _require(all(callable(value) for value in (reservation_factory, executor_factory, input_check)),
             "explicit test adapters required")
    return _execute_f18_conditions_training(request, expected_request_sha256=expected_request_sha256,
                                           _test_adapters=(reservation_factory, executor_factory, input_check))


def _execute_f18_conditions_training(request, *, expected_request_sha256, _test_adapters=None):
    _require(type(expected_request_sha256) is str and len(expected_request_sha256) == 64
             and all(char in "0123456789abcdef" for char in expected_request_sha256),
             "independent F18 request SHA-256 required")
    started = time.monotonic()
    request, digest, spec = preparation._f18_request(request, expected_sha256=expected_request_sha256)
    owner, sources = preparation._f18_owner(), preparation._f18_sources()
    policy, resource = request["execution_policy"], request["resource_policy"]
    output, journal_path = Path(request["output_root"]), Path(request["journal_path"])
    _require(not os.path.lexists(output) and not os.path.lexists(journal_path),
             "existing F18 output/journal requires explicit recovery")
    _require(resource["storage_bytes"] >= 2 * MAX_JOURNAL_BYTES, "F18 journal allowance exceeds storage")
    deadline = started + policy["timeout_seconds"]
    native = _test_adapters is None
    if native:
        from .autoencoder_campaign_process import _CampaignProcessExecutor
        factory, executor_factory = DaemonResourceReservation, _CampaignProcessExecutor
    else:
        _require(type(_test_adapters) is tuple and len(_test_adapters) == 3
                 and all(callable(x) for x in _test_adapters), "explicit test adapters required")
        factory, executor_factory, input_check = _test_adapters
    reservation = factory(resource["ledger_path"], roots=resource["roots"], storage_bytes=resource["storage_bytes"],
        memory_mb=resource["memory_mb"], cpu_slots=resource["cpu_slots"], child_process_slots=1,
        require_existing_ledger=True, scheduler_state_path=resource["scheduler_state_path"],
        expected_scheduler_policy_sha256=resource["expected_scheduler_policy_sha256"],
        timeout_seconds=0, ledger_lock_timeout_seconds=5)
    if native:
        _require(type(reservation) is DaemonResourceReservation
                 and all(name not in reservation.__dict__ for name in ("_usage_inventory", "heartbeat", "cancelled")),
                 "literal original F18 reservation/default monitor and lease methods required")
    token = str(reservation.reservation_id)
    _require(0 < len(token) <= 128 and all(x.isalnum() or x in "_-" for x in token), "invalid F18 reservation identity")
    attempt = output.parent / (".f18-attempt-" + digest[:16] + "-" + token)
    _safe_path(attempt, directory=True, missing=True)
    _require(not os.path.lexists(attempt) and any(Path(root) in attempt.parents for root in resource["roots"]),
             "F18 attempt must be exclusive and inside charged roots")
    info = output.parent.stat()
    parent_identity = (info.st_dev, info.st_ino)
    executor, output_identity = None, None
    high_water, charges = 0, 0
    last_heartbeat = None
    binding = {"schema_version": preparation.F18_REQUEST_SCHEMA, "request_sha256": digest,
               "run_id": spec.run_id, "job_spec_sha256": spec.canonical_sha256}

    def time_left():
        remaining = deadline - time.monotonic()
        _require(remaining > 0, "owned F18 wall deadline exhausted")
        return remaining

    def renew(*, force=False):
        nonlocal last_heartbeat
        # Cancellation is checked even when renewal is throttled. A successful
        # renewal does not establish that the original grant was not cancelled.
        _require(reservation.cancelled() is False, "F18 resource cancellation state is not clear")
        now = time.monotonic()
        if force or last_heartbeat is None or now - last_heartbeat >= 5:
            _require(reservation.heartbeat() is True, "F18 resource heartbeat was not confirmed")
            last_heartbeat = time.monotonic()
        _require(reservation.cancelled() is False, "F18 resource cancellation state is not clear")

    def guard(*, payload=False, force_heartbeat=False):
        time_left()
        renew(force=force_heartbeat)
        _require(_same(sources, preparation._f18_sources()), "fixed F18 controller sources changed")
        current = preparation._f18_job_artifact(request["job_artifact"])
        _require(current.canonical_sha256 == spec.canonical_sha256, "F18 job metadata changed")
        parent = output.parent.stat()
        _require(parent_identity == (parent.st_dev, parent.st_ino), "F18 output parent changed")
        if payload:
            if native:
                verified = owner.validate_job_inputs(spec)
                _require(verified["job_spec_sha256"] == spec.canonical_sha256 and verified["input_bytes_verified"] is True
                         and verified["runtime_grant"] is False, "F18 input integrity boundary differs")
            else:
                _require(input_check(spec) is None, "test input check cannot grant input integrity")
        # Input/source reads may take time; never dispatch on an aged renewal.
        time_left()
        renew()

    def observe_output():
        nonlocal output_identity, high_water, charges
        guard()
        identity, size = _f18_output_inventory(spec)
        if identity is not None:
            _require(output_identity is None or output_identity == identity, "F18 output identity changed")
            output_identity = identity
        if size > high_water:
            charges += 1
            reservation.account_external_bytes(f"f18-output-{charges:06d}", size - high_water)
            high_water = size

    with reservation:
        try:
            guard(payload=True, force_heartbeat=True)
            attempt.mkdir(mode=0o700)
            reservation.account_external_bytes("f18-owner-journal", 2 * MAX_JOURNAL_BYTES)
            reservation.check_usage(attempt)
            _require(not os.path.lexists(journal_path), "existing F18 journal requires explicit recovery")
            with DurableDaemonOperationJournal(journal_path, binding, create=True) as journal:
                _require(not journal.operations() and journal.get_metadata("f18-start") is None
                         and journal.get_metadata("f18-prepared") is None, "F18 journal is not pristine")
                journal.set_metadata("f18-prepared", {"request_sha256": digest, "job_artifact": request["job_artifact"],
                    "execution_mode": "native_training" if native else "injected_test"})
                journal.set_metadata("f18-resource", {"reservation_id": token, "attempt_directory": str(attempt)})

                def record_start(current, lease, artifact):
                    guard(payload=True, force_heartbeat=True)
                    _require(current.canonical_sha256 == spec.canonical_sha256
                             and _same(lease, {"run_id": spec.run_id, "request_sha256": digest})
                             and _same(artifact, request["job_artifact"])
                             and journal.get_metadata("f18-start") is None, "F18 consumed start cannot repeat")
                    journal.set_metadata("f18-start", {"state": "intent", "lease": lease, "job_artifact": artifact,
                        "execution_mode": "native_training" if native else "injected_test"})

                def record_child(current, lease, artifact, identity):
                    guard(payload=True, force_heartbeat=True)
                    prior = journal.get_metadata("f18-start")
                    _require(prior is not None and prior["state"] == "intent" and _same(prior["lease"], lease)
                             and _same(prior["job_artifact"], artifact), "F18 child/start binding differs")
                    journal.set_metadata("f18-start", {**prior, "state": "observed", "child": identity})

                executor = executor_factory(record_start=record_start, record_child=record_child,
                    timeout_seconds=time_left(), max_workers=1, defer_target_hydration_gc=False, reduce_native_targets=False)
                executor.register_f18(spec, reservation=reservation, attempt_directory=attempt,
                                      job_artifact=request["job_artifact"], usage_check=observe_output)
                future = executor.submit(spec, lease={"run_id": spec.run_id, "request_sha256": digest},
                                         job_artifact=request["job_artifact"])
                while not future.done():
                    guard()
                    executor.poll()
                    reservation.check_usage(attempt)
                    if not future.done():
                        time.sleep(min(policy["poll_seconds"], time_left()))
                guard(force_heartbeat=True)
                receipt, receipt_artifact = _f18_verify_artifacts(spec, future.result(), request["job_artifact"])
                guard(payload=True, force_heartbeat=True)
                observe_output()
                reservation.check_usage(attempt)
                observed = journal.get_metadata("f18-start")
                _require(observed is not None and observed["state"] == "observed", "F18 child was never observed")
                executor.retire(spec)
                executor.close()
                executor = None
                journal.set_metadata("f18-terminal", {"status": receipt["status"], "receipt_artifact": receipt_artifact,
                    "requested_steps": receipt["requested_steps"], "completed_steps": receipt["completed_steps"]})
                for directory in (attempt, output, journal_path.parent):
                    fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY)
                    try:
                        os.fsync(fd)
                    finally:
                        os.close(fd)
                guard(payload=True, force_heartbeat=True)
                reservation.check_usage(attempt)
                _f18_verify_artifacts(spec, receipt, request["job_artifact"])
                journal.set_metadata("f18-release-intent", {"reservation_id": token})
                guard(force_heartbeat=True)
                released = reservation.finalize(attempt, artifacts_durable=True)
                _require(released.get("status") == "released", "F18 release was not confirmed")
                if not native:
                    released = {**released, "injected_test": True, "input_bytes_verified": False,
                        "native_execution_verified": False, "native_purpose_admitted": False,
                        **{key: False for key in owner.FALSE_FIELDS}}
                journal.set_metadata("f18-released", {"reservation_id": token, "status": "released"})
                result = {"schema_version": F18_STATUS_SCHEMA, "request_sha256": digest, "run_id": spec.run_id,
                    "job_spec_sha256": spec.canonical_sha256, "status": receipt["status"],
                    "requested_steps": receipt["requested_steps"], "completed_steps": receipt["completed_steps"],
                    "initial_progress": receipt["initial_progress"], "final_progress": receipt["final_progress"],
                    "all_requested_steps_completed": receipt["all_requested_steps_completed"],
                    "receipt": receipt, "receipt_artifact": receipt_artifact, "resource": released,
                    "journal_path": str(journal_path), "attempt_directory": str(attempt),
                    "execution_mode": "native_training" if native else "injected_test",
                    "injected_test": not native, "input_bytes_verified": native,
                    "native_execution_verified": native, "native_purpose_admitted": False,
                    "controller_elapsed_seconds": time.monotonic() - started,
                    **{key: False for key in owner.FALSE_FIELDS}}
            return result
        finally:
            if executor is not None:
                executor.close()
