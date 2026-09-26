"""Explicit, durable control of owner-prepared daemon invocations.

Submission records an intent in the existing registry operation log. It does
not acquire a lease or run a child. Only the owner calls ``execute_pending``;
that call delegates execution and independent verification to the existing
coordinator. Wire clients never provide paths, arguments, leases or results.

The caller must close this controller before closing its registry. Closing
while execution is active is refused. A gateway may submit/read concurrently,
but must never call the blocking owner execution method from its request pump.
Importing this module starts no listener, worker or network connection.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import os
from pathlib import Path
import threading
from typing import Any, Mapping
import uuid

from .autoencoder_registry import AutoencoderRegistry, SCHEMA as REGISTRY_SCHEMA, _artifact, _token
from .contracts import canonical_json_bytes
from ..optimizers.logic_theorem_optimizer.autoencoder_daemon_invocation import run_owned_daemon_invocation
from ..optimizers.logic_theorem_optimizer.autoencoder_daemon_invocation_contracts import (
    REQUEST_SCHEMA, SHADOW_REQUEST_SCHEMA, WEIGHT_REQUEST_SCHEMA, MAX_REQUEST_BYTES,
    parse_json, safe_path, validate_request, verify,
)
from ..optimizers.logic_theorem_optimizer.autoencoder_daemon_operation_journal import DurableDaemonOperationJournal

SCHEMA = "autoencoder-owned-invocation-control-v1"
MAX_ASSIGNMENTS = 64
MAX_WORKERS = 4
MAX_REPLY_BYTES = 128 * 1024
_SUBMIT = "SubmitOwnedInvocation"
_BIND = "BindOwnedInvocation"
_START = "StartOwnedInvocation"
_FINISH = "FinishOwnedInvocation"
_REQUEST_SCHEMAS = {REQUEST_SCHEMA, SHADOW_REQUEST_SCHEMA, WEIGHT_REQUEST_SCHEMA}


class OwnedInvocationControlError(ValueError):
    """A scoped control request or its durable history cannot be verified."""


def _copy(value):
    return json.loads(canonical_json_bytes(value))


def _same(left, right):
    return canonical_json_bytes(left) == canonical_json_bytes(right)


def _reply(value):
    raw = canonical_json_bytes(value)
    if len(raw) > MAX_REPLY_BYTES:
        raise OwnedInvocationControlError("control reply exceeds bound")
    return json.loads(raw)


def _identifier(value, name):
    if type(value) is not str:
        raise OwnedInvocationControlError(name + " must be an exact string")
    _token(value, name)
    return value


def _content(value):
    if (type(value) is not dict or set(value) != {"sha256", "bytes"}
            or type(value["sha256"]) is not str or type(value["bytes"]) is not int):
        raise OwnedInvocationControlError("request_artifact must be an ordinary descriptor")
    result = _artifact(value)
    if result["bytes"] > MAX_REQUEST_BYTES:
        raise OwnedInvocationControlError("request artifact exceeds bound")
    return result


def _phase_id(control_id, phase):
    return "owned-control-" + phase + ":" + hashlib.sha256(control_id.encode()).hexdigest()


class OwnedInvocationControl:
    """One immutable owner-issued assignment set; no automatic execution.

    ``submit`` and ``resolve`` expose the immutable submission receipt.
    ``read`` exposes current bounded progress. A durable start without a known
    coordinator outcome is ``recovery_required`` after restart, never a reason
    to launch again. Explicit execution can reconcile an already committed
    coordinator operation using its existing journal, without invoking a child.
    Historical completion is not a claim of current artifact availability.
    """

    def __init__(self, registry: AutoencoderRegistry, *, worker_id: str,
                 prepared_invocations: Mapping[str, Mapping[str, Any]]) -> None:
        if type(registry) is not AutoencoderRegistry:
            raise OwnedInvocationControlError("control requires the actual registry owner")
        registry._ensure_owner()
        self._registry = registry
        self._worker_id = _identifier(worker_id, "worker_id")
        if not isinstance(prepared_invocations, Mapping) or not 1 <= len(prepared_invocations) <= MAX_ASSIGNMENTS:
            raise OwnedInvocationControlError("control requires one to 64 prepared assignments")
        self._owner = {"database_path": str(registry.database_path), "artifact_root": str(registry.artifact_root)}
        self._prepared = {}
        for run_id, supplied in prepared_invocations.items():
            _identifier(run_id, "run_id")
            if type(supplied) is not dict or set(supplied) != {"request", "journal_path", "binding"}:
                raise OwnedInvocationControlError("invalid prepared invocation handle")
            handle = _copy(supplied)
            ref, binding = handle["request"], handle["binding"]
            if type(ref) is not dict or set(ref) != {"path", "sha256", "bytes"}:
                raise OwnedInvocationControlError("invalid prepared request reference")
            content = _content({key: ref[key] for key in ("sha256", "bytes")})
            if type(ref["path"]) is not str or ref["path"] != str(registry.artifact_path(content)):
                raise OwnedInvocationControlError("prepared request is not bound to this owner's CAS")
            if (type(binding) is not dict or set(binding) != {"schema", "run_id", "variant_id", "base_version_id"}
                    or type(binding["schema"]) is not str or binding["schema"] not in _REQUEST_SCHEMAS
                    or binding["run_id"] != run_id):
                raise OwnedInvocationControlError("prepared binding differs from assigned run")
            for name in ("variant_id", "base_version_id"):
                _identifier(binding[name], name)
            path = handle["journal_path"]
            if type(path) is not str or not Path(path).is_absolute() or ".." in Path(path).parts:
                raise OwnedInvocationControlError("prepared journal requires an absolute owner path")
            self._prepared[run_id] = handle
        self._run_ids = frozenset(self._prepared)
        self._pid = os.getpid()
        self._lock = threading.RLock()
        self._running = set()
        self._draining = False
        self._closed = False

    @property
    def registry(self):
        return self._registry

    @property
    def worker_id(self):
        return self._worker_id

    @property
    def run_ids(self):
        return self._run_ids

    def _ensure_open(self):
        if self._closed or os.getpid() != self._pid:
            raise OwnedInvocationControlError("controller is closed or inherited by another process")
        self.registry._ensure_owner()
        if self._owner != {"database_path": str(self.registry.database_path), "artifact_root": str(self.registry.artifact_root)}:
            raise OwnedInvocationControlError("registry owner binding changed")

    def _assignment(self, run_id, request_artifact):
        self._ensure_open()
        _identifier(run_id, "run_id")
        if run_id not in self.run_ids:
            raise OwnedInvocationControlError("run is outside the assigned scope")
        ref = _content(request_artifact)
        handle = self._prepared[run_id]
        if not _same(ref, {key: handle["request"][key] for key in ("sha256", "bytes")}):
            raise OwnedInvocationControlError("request differs from assigned immutable invocation")
        return handle, ref

    def _submission(self, operation_id, run_id, request_artifact):
        handle, ref = self._assignment(run_id, request_artifact)
        _identifier(operation_id, "operation_id")
        control_id = "owned-control:" + hashlib.sha256(canonical_json_bytes({
            "owner": self._owner, "worker_id": self.worker_id, "wire_operation_id": operation_id,
        })).hexdigest()
        payload = {"control_schema": SCHEMA, "owner": self._owner, "worker_id": self.worker_id,
                   "wire_operation_id": operation_id, "run_id": run_id, "request_artifact": ref,
                   "prepared_sha256": hashlib.sha256(canonical_json_bytes(handle)).hexdigest()}
        return control_id, payload

    def _get_operation(self, operation_id):
        with self.registry._transaction() as connection:
            row = connection.execute("SELECT payload_digest, receipt FROM autoencoder_control.operations WHERE operation_id=?", [operation_id]).fetchone()
        return None if row is None else {"payload_digest": row[0], "receipt": json.loads(row[1])}

    def _binding_id(self, run_id):
        return "owned-control-run:" + hashlib.sha256(canonical_json_bytes({
            "owner": self._owner, "run_id": run_id,
        })).hexdigest()

    def _mutate(self, operation_id, command, payload, apply):
        try:
            return self.registry._mutate(operation_id, command, payload, apply)
        except Exception:
            # Response loss never chooses another operation ID or dispatches a
            # different command. An unavailable lookup preserves the primary.
            try:
                resolved = self.registry.resolve_operation(operation_id, command, payload)
            except Exception:
                resolved = None
            if resolved is not None:
                return resolved
            raise

    def _accepted(self, receipt, control_id, payload):
        expected = {"schema": REGISTRY_SCHEMA, "operation_id": control_id, "command": _SUBMIT,
                    "admitted": False, **payload, "status": "accepted"}
        if not _same(receipt, expected):
            raise OwnedInvocationControlError("durable submission receipt differs")
        return _reply({"schema": SCHEMA, "status": "accepted", "run_id": payload["run_id"],
            "request_artifact": payload["request_artifact"], "wire_operation_id": payload["wire_operation_id"],
            "control_operation_id": control_id, "admitted": False, "promoted": False})

    def _find_submission(self, run_id, ref):
        binding_id = self._binding_id(run_id)
        binding = self._get_operation(binding_id)
        if binding is None:
            return None
        receipt = binding["receipt"]
        fields = {"schema", "operation_id", "command", "admitted", "owner", "run_id",
                  "control_operation_id", "submission_payload"}
        if set(receipt) != fields or type(receipt["submission_payload"]) is not dict:
            raise OwnedInvocationControlError("invalid durable run binding")
        control_id, payload = self._submission(receipt["submission_payload"]["wire_operation_id"], run_id, ref)
        expected = {"owner": self._owner, "run_id": run_id,
                    "control_operation_id": control_id, "submission_payload": payload}
        if not _same(receipt, {"schema": REGISTRY_SCHEMA, "operation_id": binding_id,
                              "command": _BIND, "admitted": False, **expected}):
            raise OwnedInvocationControlError("run submission belongs to another owner-issued scope")
        if not _same(self.registry.resolve_operation(binding_id, _BIND, expected), receipt):
            raise OwnedInvocationControlError("durable run binding differs")
        resolved = self.registry.resolve_operation(control_id, _SUBMIT, payload)
        return self._accepted(resolved, control_id, payload)

    def _check_prepared(self, run_id):
        handle = self._prepared[run_id]
        request = validate_request(parse_json(verify(handle["request"], MAX_REQUEST_BYTES)))
        if not _same({name: request[name] for name in handle["binding"]}, handle["binding"]):
            raise OwnedInvocationControlError("prepared request binding differs")
        if handle["journal_path"] != str(Path(request["output_directory"]) / "owner-operations.json"):
            raise OwnedInvocationControlError("prepared journal does not belong to request output")
        safe_path(handle["journal_path"])
        with DurableDaemonOperationJournal(handle["journal_path"], handle["binding"]) as journal:
            if not _same(journal.get_metadata("prepared"), handle):
                raise OwnedInvocationControlError("prepared handle differs from coordinator journal")
        return request

    def submit(self, operation_id: str, run_id: str, request_artifact: Mapping[str, Any]) -> dict:
        control_id, payload = self._submission(operation_id, run_id, request_artifact)
        old = self.registry.resolve_operation(control_id, _SUBMIT, payload)
        if old is not None:
            return self._accepted(old, control_id, payload)
        self._check_prepared(run_id)

        def apply(connection):
            binding_id = self._binding_id(run_id)
            if connection.execute("SELECT 1 FROM autoencoder_control.operations WHERE operation_id=?", [binding_id]).fetchone():
                raise OwnedInvocationControlError("run already has a selected submission")
            run = self.registry._run(connection, run_id)
            binding = self._prepared[run_id]["binding"]
            if (run["variant_id"] != binding["variant_id"] or run["base_version_id"] != binding["base_version_id"]
                    or not _same(run["spec"], {"schema": binding["schema"], "request_artifact": payload["request_artifact"]})):
                raise OwnedInvocationControlError("prepared invocation differs from registered execution run")
            if run["status"] != "queued" or run["attempt"] != 0:
                raise OwnedInvocationControlError("new submission requires the untouched prepared execution run")
            binding_payload = {"owner": self._owner, "run_id": run_id,
                               "control_operation_id": control_id, "submission_payload": payload}
            binding_receipt = {"schema": REGISTRY_SCHEMA, "operation_id": binding_id,
                               "command": _BIND, "admitted": False, **binding_payload}
            # The primary-key binding and the outer submission commit together.
            # Status polling never scans unrelated historical operation rows.
            connection.execute("INSERT INTO autoencoder_control.operations VALUES (?, ?, ?)",
                [binding_id, self.registry._command_digest(binding_id, _BIND, binding_payload),
                 canonical_json_bytes(binding_receipt).decode()])
            return {**payload, "status": "accepted"}

        receipt = self._mutate(control_id, _SUBMIT, payload, apply)
        return self._accepted(receipt, control_id, payload)

    def resolve(self, operation_id: str, run_id: str, request_artifact: Mapping[str, Any]) -> dict:
        control_id, payload = self._submission(operation_id, run_id, request_artifact)
        old = self.registry.resolve_operation(control_id, _SUBMIT, payload)
        receipt = None if old is None else self._accepted(old, control_id, payload)
        return _reply({"schema": SCHEMA, "wire_operation_id": operation_id,
            "control_operation_id": control_id, "resolution": "missing" if old is None else "committed",
            "receipt": receipt, "admitted": False})

    def _phase(self, accepted, phase):
        control_id = accepted["control_operation_id"]
        operation_id = _phase_id(control_id, phase)
        operation = self._get_operation(operation_id)
        if operation is None:
            return None
        receipt = operation["receipt"]
        names = {"control_operation_id", "execution_id"} if phase == "start" else {"control_operation_id", "status", "coordinator_operation"}
        if set(receipt) != names | {"schema", "operation_id", "command", "admitted"}:
            raise OwnedInvocationControlError("invalid durable control phase")
        payload = {name: receipt[name] for name in names}
        command = _START if phase == "start" else _FINISH
        if (receipt["schema"] != REGISTRY_SCHEMA or receipt["operation_id"] != operation_id
                or receipt["command"] != command or receipt["admitted"] is not False
                or receipt["control_operation_id"] != control_id
                or not _same(self.registry.resolve_operation(operation_id, command, payload), receipt)):
            raise OwnedInvocationControlError("durable control phase binding differs")
        return receipt

    def _verify_outcome(self, outcome, run_id):
        if type(outcome) is not dict or set(outcome) != {"operation_id", "payload_digest", "receipt"}:
            raise OwnedInvocationControlError("invalid coordinator operation reference")
        operation = self._get_operation(outcome["operation_id"])
        if operation is None or not _same(operation, {key: outcome[key] for key in ("payload_digest", "receipt")}):
            raise OwnedInvocationControlError("coordinator receipt is absent or changed")
        receipt = operation["receipt"]
        if (receipt.get("schema") != REGISTRY_SCHEMA or receipt.get("operation_id") != outcome["operation_id"]
                or receipt.get("run_id") != run_id or receipt.get("admitted") is not False
                or receipt.get("command") not in {"CompleteRun", "FailRun"}):
            raise OwnedInvocationControlError("coordinator operation belongs to another run")
        status = "completed" if receipt["command"] == "CompleteRun" else "failed"
        if receipt.get("status") != status or (status == "completed" and receipt.get("promoted") is not False):
            raise OwnedInvocationControlError("coordinator outcome differs")
        return status

    def read(self, run_id: str, request_artifact: Mapping[str, Any]) -> dict:
        _, ref = self._assignment(run_id, request_artifact)
        accepted = self._find_submission(run_id, ref)
        value = {"schema": SCHEMA, "status": "not_submitted", "run_id": run_id, "request_artifact": ref,
            "wire_operation_id": None, "control_operation_id": None, "coordinator_operation_id": None,
            "completion": None, "admitted": False, "promoted": False,
            "current_artifact_availability_checked": False}
        if accepted is None:
            return _reply(value)
        value.update({name: accepted[name] for name in ("status", "wire_operation_id", "control_operation_id")})
        finish = self._phase(accepted, "finish")
        if finish is not None:
            outcome = finish["coordinator_operation"]
            status = self._verify_outcome(outcome, run_id)
            if finish["status"] != status:
                raise OwnedInvocationControlError("finished control status differs from coordinator")
            value.update(status=status, coordinator_operation_id=outcome["operation_id"], completion=outcome["receipt"])
        elif self._phase(accepted, "start") is not None:
            with self._lock:
                value["status"] = "running" if run_id in self._running else "recovery_required"
        return _reply(value)

    def _coordinator_outcome(self, run_id):
        """Resolve an existing terminal slot, without retrying its mutation."""
        handle = self._prepared[run_id]
        safe_path(handle["journal_path"])
        with DurableDaemonOperationJournal(handle["journal_path"], handle["binding"]) as journal:
            if not _same(journal.get_metadata("prepared"), handle):
                raise OwnedInvocationControlError("coordinator recovery handle differs")
            operations = journal.operations()
            operation = operations.get("complete") or operations.get("fail")
            if operation is None:
                return None
            expected = "CompleteRun" if "complete" in operations else "FailRun"
            payload = operation["payload"]
            if (operation["command"] != expected or payload["lease"]["run_id"] != run_id
                    or payload["lease"]["worker_id"] != "native-daemon-owner"):
                raise OwnedInvocationControlError("coordinator terminal operation binding differs")
            if expected == "CompleteRun" and (payload["result"].get("schema") != "autoencoder-daemon-owned-completion-v1"
                    or not _same(payload["result"].get("request_artifact"), {key: handle["request"][key] for key in ("sha256", "bytes")})):
                raise OwnedInvocationControlError("coordinator completion is not bound to this request")
            receipt = self.registry.resolve_operation(operation["operation_id"], expected, payload)
            if receipt is None:
                return None
            outcome = {"operation_id": operation["operation_id"],
                "payload_digest": self.registry._command_digest(operation["operation_id"], expected, payload), "receipt": receipt}
            self._verify_outcome(outcome, run_id)
            return outcome

    def _finish(self, accepted, outcome):
        status = self._verify_outcome(outcome, accepted["run_id"])
        control_id = accepted["control_operation_id"]
        payload = {"control_operation_id": control_id, "status": status, "coordinator_operation": outcome}
        self._mutate(_phase_id(control_id, "finish"), _FINISH, payload, lambda connection: payload)

    def _execute_one(self, accepted):
        run_id, ref = accepted["run_id"], accepted["request_artifact"]
        if self._phase(accepted, "finish") is not None:
            return self.read(run_id, ref)
        if self._phase(accepted, "start") is not None:
            # No resume of computation. A stopped owner may have committed its
            # terminal operation before recording this control-layer outcome.
            try:
                outcome = self._coordinator_outcome(run_id)
                if outcome is not None:
                    self._finish(accepted, outcome)
            except (OSError, ValueError):
                pass
            return self.read(run_id, ref)
        control_id = accepted["control_operation_id"]
        payload = {"control_operation_id": control_id, "execution_id": uuid.uuid4().hex}
        try:
            self._mutate(_phase_id(control_id, "start"), _START, payload, lambda connection: payload)
        except Exception:
            # A competing owner call can win the unique start operation, but
            # its different nonce can never authorize a second invocation.
            if self._phase(accepted, "start") is not None:
                return self.read(run_id, ref)
            raise
        with self._lock:
            self._running.add(run_id)
        try:
            returned = run_owned_daemon_invocation(self.registry, _copy(self._prepared[run_id]))
            outcome = self._coordinator_outcome(run_id)
            if (outcome is None or outcome["receipt"]["command"] != "CompleteRun"
                    or type(returned) is not dict or not _same(returned.get("completion"), outcome["receipt"])):
                raise OwnedInvocationControlError("coordinator return lacks exact committed completion")
            self._finish(accepted, outcome)
        except Exception:
            # A genuine recorded failure is terminal; any ambiguous operation
            # remains recovery_required. Never issue FailRun here or reexecute.
            try:
                outcome = self._coordinator_outcome(run_id)
                if outcome is not None:
                    self._finish(accepted, outcome)
            except (OSError, ValueError):
                pass
        finally:
            with self._lock:
                self._running.discard(run_id)
        return self.read(run_id, ref)

    def execute_pending(self, *, max_workers: int = 1) -> dict:
        """Owner-only blocking drain; never called by the transport pump.

        The existing coordinator owns all resource/lease/child cleanup. The
        number of simultaneous invocations is capped at four, and each still
        requires its existing shared resource reservation. No implicit retry of
        a started computation occurs, including after controller/owner restart.
        """
        self._ensure_open()
        if type(max_workers) is not int or not 1 <= max_workers <= MAX_WORKERS:
            raise OwnedInvocationControlError("max_workers must be within one to four")
        with self._lock:
            self._ensure_open()
            if self._draining:
                raise OwnedInvocationControlError("owner execution is already active")
            self._draining = True
        try:
            selected = []
            for run_id in sorted(self.run_ids):
                ref = {key: self._prepared[run_id]["request"][key] for key in ("sha256", "bytes")}
                accepted = self._find_submission(run_id, ref)
                if accepted is not None:
                    selected.append(accepted)
            with ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="owned-invocation-control") as pool:
                results = list(pool.map(self._execute_safely, selected))
            return _reply({"schema": SCHEMA, "results": results, "admitted": False})
        finally:
            with self._lock:
                self._draining = False

    def _execute_safely(self, accepted):
        try:
            return self._execute_one(accepted)
        except Exception as error:
            # Preserve other assigned outcomes if one run's storage/history is
            # unavailable. This is an unresolved control error, not FailRun.
            try:
                result = self.read(accepted["run_id"], accepted["request_artifact"])
            except Exception:
                result = {**accepted, "status": "recovery_required", "coordinator_operation_id": None,
                    "completion": None, "current_artifact_availability_checked": False}
            result["control_error"] = type(error).__name__[:128]
            return _reply(result)

    def close(self) -> None:
        if os.getpid() != self._pid:
            raise OwnedInvocationControlError("forked process cannot close owner control")
        with self._lock:
            if self._draining or self._running:
                raise OwnedInvocationControlError("cannot close control while owner execution is active")
            self._closed = True

    def __enter__(self):
        self._ensure_open()
        return self

    def __exit__(self, *exc):
        self.close()


__all__ = ["OwnedInvocationControl", "OwnedInvocationControlError", "SCHEMA"]
