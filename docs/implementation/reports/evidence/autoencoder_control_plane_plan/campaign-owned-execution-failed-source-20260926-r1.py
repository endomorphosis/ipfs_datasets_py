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

                dispatch = coordinator._run_owned_training_jobs(registry, ready,
                    operation_journal=journal, supervisor=supervisor, before_claim=before_claim,
                    before_prepare=manager.before_prepare, worker_id=request["worker_id"],
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
